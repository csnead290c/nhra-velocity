from __future__ import annotations

"""Native reader for RacePak/DataLink ``.rpk`` run files.

Two DataLink serialization families are supported: the older ``ScaledBuffer``
layout and the current ``CAN_Device`` layout found in NHRA race data.  Both are
self-describing binary object streams with float32 sample buffers, but current
files use extended length-prefixed strings and duplicate their used-sample
count in the buffer header.

The reader is intentionally conservative.  Structural relationships (object
definitions, sample timers, buffer counts and bounds) are validated before a
channel is exposed so an unfamiliar file variant fails loudly instead of
silently producing mislabeled engineering data.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
import math
import re
import struct

import numpy as np
import pandas as pd

from .models import TelemetryRun, TimingData, Environment
from .units import normalize_unit


_SCALED_MARKER = b"ScaledBuffer"
_CAN_DEVICE_CLASS = b"CAN_Device"


@dataclass
class RpkChannelDef:
    offset: int
    storage_type: str
    name: str
    description: str
    default: str
    timer: str
    sample_rate_hz: Optional[float]
    scale: Optional[Tuple[float, float, float, float]]
    unit: str


@dataclass
class RpkObjectDef:
    offset: int
    storage_type: str
    name: str
    description: str
    expression: str


@dataclass
class RpkBuffer:
    offset: int
    capacity: int
    used: int
    flag: int
    values: np.ndarray


def _read_lp_string(data: bytes, pos: int, max_len: int = 20_000) -> Tuple[str, int]:
    """Read a DataLink length-prefixed Latin-1 string.

    Older files use a one-byte length.  Current DataLink uses 0xff followed by
    a little-endian uint16 for long strings; support a uint32 continuation as a
    defensive extension for very large descriptions.
    """
    if pos >= len(data):
        raise ValueError("Unexpected end of RPK object")
    n = int(data[pos])
    pos += 1
    if n == 0xFF:
        if pos + 2 > len(data):
            raise ValueError("Truncated extended RPK string length")
        n = int(struct.unpack_from("<H", data, pos)[0])
        pos += 2
        if n == 0xFFFF:
            if pos + 4 > len(data):
                raise ValueError("Truncated long RPK string length")
            n = int(struct.unpack_from("<I", data, pos)[0])
            pos += 4
    if n > max_len or pos + n > len(data):
        raise ValueError("Invalid RPK length-prefixed string")
    raw = data[pos : pos + n]
    return raw.decode("latin1", errors="replace"), pos + n


def _parse_object_entries(data: bytes) -> List[Tuple[int, str, str, str, str, str]]:
    """Find DataLink object definitions with the common five-string payload."""
    recognized = ("ScaledBuffer", "CAN_Device:", "Calculation:", "FileLookup:", "Integrator:")
    entries: List[Tuple[int, str, str, str, str, str]] = []
    i = 0
    n = len(data)
    while i < n - 10:
        # Object tags differ by DataLink generation/type, while bytes +2/+3
        # remain 02 00 in all validated legacy and current files.
        if data[i + 2 : i + 4] != b"\x02\x00":
            i += 1
            continue
        try:
            pos = i + 4
            storage_type, pos = _read_lp_string(data, pos, 128)
            name, pos = _read_lp_string(data, pos, 256)
            description, pos = _read_lp_string(data, pos, 50_000)
            fourth, pos = _read_lp_string(data, pos, 20_000)
            fifth, pos = _read_lp_string(data, pos, 20_000)
        except Exception:
            i += 1
            continue
        if (
            storage_type
            and name
            and any(token in description for token in recognized)
            and all((31 < ord(ch) < 127) or ch in "\t\r\n" for ch in name)
        ):
            entries.append((i, storage_type, name.strip(), description, fourth, fifth))
            i = max(i + 1, pos)
        else:
            i += 1
    return entries


def _sample_rate(timer: str) -> Optional[float]:
    m = re.search(r"Timer[_ ]*([0-9]+(?:\.[0-9]+)?)\s*sps", str(timer), re.I)
    if not m:
        return None
    hz = float(m.group(1))
    return hz if hz > 0 else None


def _scale_from_description(description: str) -> Optional[Tuple[float, float, float, float]]:
    # DataLink stores linear sensor calibration as (raw0=>eng0,raw1=>eng1).
    pat = re.compile(
        r"\(\s*([-+0-9.eE]+)\s*=>\s*([-+0-9.eE]+)\s*,\s*"
        r"([-+0-9.eE]+)\s*=>\s*([-+0-9.eE]+)\s*\)"
    )
    m = pat.search(description)
    if not m:
        return None
    try:
        return tuple(float(m.group(i)) for i in range(1, 5))  # type: ignore[return-value]
    except Exception:
        return None


def _attribute(description: str, key: str) -> Optional[str]:
    m = re.search(re.escape(key) + r'=\"([^\"]*)\"', description)
    return m.group(1).strip() if m else None


def _modern_hw_scale(description: str) -> Optional[Tuple[float, float, float, float]]:
    """Return the full linear CAN_Device raw→engineering calibration.

    Current DataLink files can describe two consecutive linear transforms:
    logger counts → sensor voltage via ``_HW_A/_HW_B``, then sensor voltage →
    engineering units via ``_X_MIN/_X_MAX/_Y_MIN/_Y_MAX``.  Because both are
    linear, collapse them into one two-point map consumed by the common scaling
    path.  When the sensor map is absent, retain only hardware gain/offset.
    """
    if "CAN_Device:" not in description:
        return None

    def _float_attr(key: str) -> Optional[float]:
        raw = _attribute(description, key)
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except Exception:
            return None

    gain = _float_attr("_HW_A")
    offset = _float_attr("_HW_B")
    if gain is None:
        gain = 1.0
    if offset is None:
        offset = 0.0

    x0 = _float_attr("_X_MIN")
    x1 = _float_attr("_X_MAX")
    y0 = _float_attr("_Y_MIN")
    y1 = _float_attr("_Y_MAX")
    if None not in (x0, x1, y0, y1) and abs(float(x1) - float(x0)) > 1e-12:
        # raw -> hw = raw*gain + offset; choose raw points that land exactly
        # on the X-domain endpoints, then map those to engineering Y endpoints.
        if abs(gain) > 1e-15:
            raw0 = (float(x0) - offset) / gain
            raw1 = (float(x1) - offset) / gain
            return (raw0, float(y0), raw1, float(y1))
        return None

    # No sensor map: direct hardware calibration only.
    if gain != 1.0 or offset != 0.0:
        return (0.0, offset, 1.0, offset + gain)
    return None


def _unit_from_description(description: str, storage_type: str) -> str:
    # Current CAN_Device objects carry an explicit _UNIT attribute.
    modern = _attribute(description, "_UNIT")
    if modern is not None:
        modern = modern.replace("\xb0", "deg").strip()
        if modern:
            return normalize_unit(modern) or modern.lower()

    # Legacy display spec normally ends: [(min,max),%-5.2lf,UNIT]
    matches = re.findall(r",\s*([^,\]\[]*)\]", description)
    unit = matches[-1].strip() if matches else ""
    unit = unit.replace("\xb0", "deg").strip()
    if unit:
        return normalize_unit(unit) or unit.lower()
    st = storage_type.lower()
    if st == "rpm" or st.endswith("_rpm") or "tach" in st:
        return "rpm"
    if "gm_" in st or "g-meter" in st or "g_meter" in st:
        return "g"
    return ""


def parse_channel_definitions(data: bytes) -> List[RpkChannelDef]:
    defs: List[RpkChannelDef] = []
    for off, st, name, desc, fourth, fifth in _parse_object_entries(data):
        if "ScaledBuffer" not in desc and "CAN_Device:" not in desc:
            continue
        defs.append(
            RpkChannelDef(
                offset=off,
                storage_type=st,
                name=name,
                description=desc,
                default=fourth,
                timer=fifth,
                sample_rate_hz=_sample_rate(fifth),
                scale=_scale_from_description(desc) or _modern_hw_scale(desc),
                unit=_unit_from_description(desc, st),
            )
        )
    return defs


def parse_calculated_definitions(data: bytes) -> List[RpkObjectDef]:
    out: List[RpkObjectDef] = []
    for off, st, name, desc, fourth, fifth in _parse_object_entries(data):
        if "Calculation:" in desc:
            # In validated files the fourth string is the expression; the fifth
            # is empty.  Keep a fallback because old/new DataLink builds differ.
            expr = fourth or fifth
            out.append(RpkObjectDef(off, st, name, desc, expr))
    return out


def _find_legacy_buffers(data: bytes) -> List[RpkBuffer]:
    buffers: List[RpkBuffer] = []
    start = 0
    while True:
        off = data.find(_SCALED_MARKER, start)
        if off < 0:
            break
        start = off + 1
        if off == 0 or data[off - 1] != len(_SCALED_MARKER):
            continue
        if off + 28 > len(data):
            continue
        try:
            capacity, reserved, used, flag = struct.unpack_from("<4I", data, off + 12)
        except struct.error:
            continue
        if reserved != 0 or used > capacity or capacity > 5_000_000 or flag > 32:
            continue
        value_off = off + 28
        end = value_off + int(capacity) * 4
        if end > len(data):
            continue
        values = (
            np.frombuffer(data, dtype="<f4", count=int(capacity), offset=value_off).copy()
            if capacity else np.empty(0, dtype=float)
        )
        buffers.append(RpkBuffer(off, int(capacity), int(used), int(flag), values))
    return buffers


def _find_modern_buffers(data: bytes) -> List[RpkBuffer]:
    """Find current DataLink CAN_Device float buffers in serialization order.

    The object is an LP string ``CAN_Device`` followed by four uint32 values:
    capacity, used-count A, used-count B, and a small flag.  In validated files
    the two used counts agree.  Float32 samples immediately follow the header.
    """
    buffers: List[RpkBuffer] = []
    marker = bytes([len(_CAN_DEVICE_CLASS)]) + _CAN_DEVICE_CLASS
    start = 0
    while True:
        off = data.find(marker, start)
        if off < 0:
            break
        start = off + 1
        header_off = off + len(marker)
        if header_off + 16 > len(data):
            continue
        try:
            capacity, used_a, used_b, flag = struct.unpack_from("<4I", data, header_off)
        except struct.error:
            continue
        if capacity > 5_000_000 or used_a > capacity or used_b > capacity or flag > 32:
            continue
        # Current files duplicate the used count.  Permit one zero for a nearby
        # DataLink revision, but reject conflicting nonzero counts.
        if used_a and used_b and used_a != used_b:
            continue
        used = int(used_a or used_b)
        value_off = header_off + 16
        end = value_off + int(capacity) * 4
        if end > len(data):
            continue
        values = (
            np.frombuffer(data, dtype="<f4", count=int(capacity), offset=value_off).copy()
            if capacity else np.empty(0, dtype=float)
        )
        buffers.append(RpkBuffer(off, int(capacity), used, int(flag), values))
    return buffers


def _find_buffers(data: bytes) -> Tuple[str, List[RpkBuffer]]:
    modern = _find_modern_buffers(data)
    if modern:
        return "CAN_Device", modern
    legacy = _find_legacy_buffers(data)
    if legacy:
        return "ScaledBuffer", legacy
    return "", []


def _match_modern_channels(
    defs: Sequence[RpkChannelDef], buffers: Sequence[RpkBuffer]
) -> Tuple[List[Tuple[RpkChannelDef, RpkBuffer]], Optional[float]]:
    modern_defs = [d for d in defs if "CAN_Device:" in d.description]
    if not modern_defs or not buffers:
        return [], None
    if len(modern_defs) != len(buffers):
        # Do not label samples by guesswork when object counts do not preserve the
        # one-to-one serialization relationship. Fall back to timed alignment.
        return _match_recorded_channels(modern_defs, buffers)

    pairs: List[Tuple[RpkChannelDef, RpkBuffer]] = []
    durations: List[float] = []
    for cfg, buf in zip(modern_defs, buffers):
        if buf.capacity <= 0:
            continue
        sr = float(cfg.sample_rate_hz or 0.0)
        if sr <= 0:
            raise ValueError(
                f"RPK populated CAN_Device buffer for {cfg.name!r} has no DataLink sample timer"
            )
        count = int(buf.used or buf.capacity)
        if count <= 0:
            continue
        pairs.append((cfg, buf))
        durations.append(count / sr)

    if not pairs:
        return [], None
    nominal = float(np.median(np.asarray(durations, dtype=float)))
    # Used-count duration is exact in validated current files.  A little slop is
    # allowed for logger start/stop boundaries but gross mismatches are structural.
    for (cfg, buf), duration in zip(pairs, durations):
        if nominal > 0 and abs(duration / nominal - 1.0) > 0.08:
            raise ValueError(
                f"RPK CAN_Device buffer duration for {cfg.name!r} differs from the common recording window"
            )
    return pairs, nominal


def _match_recorded_channels(
    defs: Sequence[RpkChannelDef], buffers: Sequence[RpkBuffer]
) -> Tuple[List[Tuple[RpkChannelDef, RpkBuffer]], Optional[float]]:
    """Monotonically align configured channels to non-empty serialized buffers.

    Some DataLink files contain configured/timed channels with no recorded data.
    Buffer capacities scale with the timer rate, so we identify the common record
    window and allow channel definitions to be skipped without reordering data.
    """
    configs = [d for d in defs if d.sample_rate_hz and d.sample_rate_hz > 0]
    bufs = [x for x in buffers if x.capacity > 0]
    if not configs or not bufs:
        return [], None
    if len(bufs) > len(configs):
        raise ValueError(
            f"RPK has {len(bufs)} populated buffers but only {len(configs)} timed channel definitions"
        )

    candidate_durations = sorted(
        {
            round((buf.used if buf.used > 0 else buf.capacity) / float(cfg.sample_rate_hz), 9)
            for buf in bufs
            for cfg in configs
            if cfg.sample_rate_hz
        }
    )
    n, m = len(configs), len(bufs)
    best_total = float("inf")
    best_path: Optional[List[Tuple[int, int]]] = None
    best_duration: Optional[float] = None

    # A mismatch by a factor of two costs much more than skipping one configured
    # channel, which lets a 100 Hz buffer bypass a missing 50 Hz channel cleanly.
    skip_cfg_cost = 0.65
    match_weight = 8.0

    for duration in candidate_durations:
        if duration <= 0:
            continue
        dp = np.full((n + 1, m + 1), np.inf, dtype=float)
        prev: List[List[Optional[Tuple[int, int, str]]]] = [[None] * (m + 1) for _ in range(n + 1)]
        dp[0, 0] = 0.0
        for i in range(n):
            for j in range(m + 1):
                cur = float(dp[i, j])
                if not np.isfinite(cur):
                    continue
                # Skip a configured channel that has no serialized data.
                if cur + skip_cfg_cost < dp[i + 1, j]:
                    dp[i + 1, j] = cur + skip_cfg_cost
                    prev[i + 1][j] = (i, j, "skip")
                if j < m:
                    sr = float(configs[i].sample_rate_hz or 0)
                    observed_duration = (bufs[j].used if bufs[j].used > 0 else bufs[j].capacity) / sr if sr > 0 else float("inf")
                    if observed_duration > 0 and np.isfinite(observed_duration):
                        rel = abs(math.log(observed_duration / duration))
                        cost = cur + match_weight * rel
                        if cost < dp[i + 1, j + 1]:
                            dp[i + 1, j + 1] = cost
                            prev[i + 1][j + 1] = (i, j, "match")
        total = float(dp[n, m])
        if total < best_total:
            path: List[Tuple[int, int]] = []
            i, j = n, m
            while i > 0 or j > 0:
                p = prev[i][j]
                if p is None:
                    path = []
                    break
                pi, pj, action = p
                if action == "match":
                    path.append((pi, pj))
                i, j = pi, pj
            if path or m == 0:
                best_total = total
                best_path = list(reversed(path))
                best_duration = duration

    if best_path is None:
        raise ValueError("Could not align RPK channel definitions with recorded buffers")

    matched = [(configs[i], bufs[j]) for i, j in best_path]
    # Reject a structurally implausible file rather than silently mislabeling data.
    if best_duration:
        for cfg, buf in matched:
            obs = (buf.used if buf.used > 0 else buf.capacity) / float(cfg.sample_rate_hz or 1)
            if abs(obs / best_duration - 1.0) > 0.08:
                raise ValueError("RPK timed-buffer layout differs from the validated DataLink format")
    return matched, best_duration


def _apply_linear_scale(values: np.ndarray, scale: Optional[Tuple[float, float, float, float]]) -> np.ndarray:
    arr = values.astype(float, copy=True)
    if not scale:
        return arr
    x0, y0, x1, y1 = scale
    if abs(x1 - x0) < 1e-12:
        return arr
    return y0 + (arr - x0) * (y1 - y0) / (x1 - x0)


def _simple_calculation(expr: str, channels: Dict[str, np.ndarray]) -> Optional[np.ndarray]:
    """Evaluate the safe subset used for direct scaled-channel calculations.

    Supported: 'CHANNEL' followed by multiplication/division by numeric constants,
    e.g. ``'DRIVE SHAFT'*.021`` or ``'FW RPM'*.0135*5``.
    """
    text = str(expr or "").strip()
    m = re.fullmatch(r"'([^']+)'\s*((?:[*/]\s*[-+0-9.eE]+\s*)+)", text)
    if not m:
        return None
    source = m.group(1).strip()
    if source not in channels:
        return None
    result = np.asarray(channels[source], dtype=float).copy()
    for op, token in re.findall(r"([*/])\s*([-+0-9.eE]+)", m.group(2)):
        value = float(token)
        if op == "*":
            result *= value
        elif abs(value) > 1e-15:
            result /= value
        else:
            return None
    return result


def _calculation_unit(description: str, name: str) -> str:
    unit = _unit_from_description(description, "")
    if unit:
        return unit
    n = name.strip().lower()
    if n == "mph" or "speed" in n:
        return "mph"
    return ""


def _extract_basic_metadata(data: bytes) -> Dict[str, str]:
    """Read the initial DataLink key/value dictionary when present."""
    out: Dict[str, str] = {}
    # Legacy demo files place a short binary header before the dictionary.  Find
    # the first known key rather than binding to one exact header length.
    key = b"AirTemperature"
    loc = data.find(key, 0, min(len(data), 4096))
    if loc < 1:
        return out
    pos = loc - 1
    for _ in range(80):
        try:
            k, pos2 = _read_lp_string(data, pos, 80)
            v, pos3 = _read_lp_string(data, pos2, 200)
        except Exception:
            break
        if not k or any(ord(ch) < 32 for ch in k):
            break
        # Stop when the stream moves from the run dictionary into other objects.
        if len(k) > 70 or "<" in k or "\\" in k:
            break
        if all((31 < ord(ch) < 127) for ch in v) or v == "":
            out[k] = v
        pos = pos3
    return out


def parse_racepak_rpk(path: str | Path) -> TelemetryRun:
    """Parse a validated legacy RacePak/DataLink native ``.rpk`` run file."""
    path = Path(path)
    data = path.read_bytes()
    if len(data) < 128:
        raise ValueError(f"{path.name}: not a recognized DataLink RPK file")

    channel_defs = parse_channel_definitions(data)
    buffer_family, buffers = _find_buffers(data)
    if not channel_defs or not buffers:
        raise ValueError(f"{path.name}: not a recognized DataLink RPK file")
    if buffer_family == "CAN_Device":
        matched, nominal_window_s = _match_modern_channels(channel_defs, buffers)
    else:
        matched, nominal_window_s = _match_recorded_channels(channel_defs, buffers)
    if not matched:
        raise ValueError(f"{path.name}: no validated recorded DataLink channels found")

    # Reconstruct each channel in engineering units at its native sample rate.
    channel_native: Dict[str, Tuple[np.ndarray, np.ndarray, float, str]] = {}
    sample_rates: Dict[str, float] = {}
    channel_calibrations: Dict[str, Dict[str, object]] = {}
    for cfg, buf in matched:
        sr = float(cfg.sample_rate_hz or 0.0)
        count = min(buf.used if buf.used > 0 else buf.capacity, buf.capacity)
        if sr <= 0 or count <= 0:
            continue
        raw = np.asarray(buf.values[:count], dtype=float)
        eng = _apply_linear_scale(raw, cfg.scale)
        t = np.arange(count, dtype=float) / sr
        channel_native[cfg.name] = (t, eng, sr, cfg.unit)
        sample_rates[cfg.name] = sr
        channel_calibrations[cfg.name] = {
            "storage_type": cfg.storage_type,
            "description": cfg.description,
            "timer": cfg.timer,
            "scale": cfg.scale,
            "unit": cfg.unit,
            "buffer_capacity": buf.capacity,
            "used_samples": count,
            "buffer_offset": buf.offset,
        }

    if not channel_native:
        raise ValueError(f"{path.name}: no populated RPK channels after alignment")

    # Use the fastest logged channel as the common analysis grid.  This keeps
    # native 100 Hz channels intact while linearly interpolating 20/50 Hz analogs.
    target_rate = max(v[2] for v in channel_native.values())
    duration = max(float(v[0][-1]) if len(v[0]) else 0.0 for v in channel_native.values())
    if duration <= 0:
        raise ValueError(f"{path.name}: RPK channels contain no time span")
    n_target = int(math.floor(duration * target_rate + 1e-9)) + 1
    common_t = np.arange(n_target, dtype=float) / target_rate

    cols: Dict[str, np.ndarray] = {"Time (s)": common_t}
    units: Dict[str, str] = {"Time (s)": "s"}
    resampled_for_calcs: Dict[str, np.ndarray] = {}
    for name, (t, values, _sr, unit) in channel_native.items():
        finite = np.isfinite(t) & np.isfinite(values)
        if finite.sum() < 2:
            arr = np.full_like(common_t, np.nan, dtype=float)
            if finite.sum() == 1:
                arr[np.argmin(abs(common_t - t[finite][0]))] = float(values[finite][0])
        else:
            tv = t[finite]
            vv = values[finite]
            arr = np.interp(common_t, tv, vv, left=np.nan, right=np.nan)
        cols[name] = arr
        resampled_for_calcs[name] = arr
        if unit:
            units[name] = unit

    # Materialize simple DataLink calculated channels that are direct scale
    # transforms of a recorded channel (e.g. DS RPM -> MPH).  More complicated
    # DataLink expressions remain visible in metadata and are not guessed.
    calculated_loaded: List[str] = []
    calculated_skipped: List[str] = []
    for obj in parse_calculated_definitions(data):
        arr = _simple_calculation(obj.expression, resampled_for_calcs)
        if arr is None:
            calculated_skipped.append(obj.name)
            continue
        cols[obj.name] = arr
        resampled_for_calcs[obj.name] = arr
        u = _calculation_unit(obj.description, obj.name)
        if u:
            units[obj.name] = u
        calculated_loaded.append(obj.name)

    frame = pd.DataFrame(cols)
    # Import lazily to avoid a module cycle (importers imports this parser).
    from .importers import auto_map_channels, _normalize_canonical

    channel_map = auto_map_channels(frame.columns, units=units)
    rpk_meta = _extract_basic_metadata(data)

    def _num(key: str):
        value = rpk_meta.get(key, "")
        try:
            return float(str(value).strip()) if str(value).strip() else None
        except Exception:
            return None

    timing_hint = {
        "sixty_ft_s": _num("Time60ft"),
        "three_thirty_ft_s": _num("Time330ft"),
        "eighth_mile_s": _num("Time660ft"),
        "eighth_mile_mph": _num("MPH660ft"),
        "thousand_ft_s": _num("Time1000ft"),
        "quarter_mile_s": _num("ElapsedTime"),
        "quarter_mile_mph": _num("MPH"),
    }
    timing_hint = {k: v for k, v in timing_hint.items() if v is not None}
    environment_hint = {
        "temperature_f": _num("AirTemperature"),
        "elevation_ft": _num("Altitude"),
        "barometer_inhg": _num("Barometer"),
        "humidity_pct": _num("Humidity"),
        "track_temperature_f": _num("TrackTemperature"),
    }
    environment_hint = {k: v for k, v in environment_hint.items() if v is not None}

    metadata = {
        "source_file": path.name,
        "source_format": f"RacePak/DataLink native RPK ({buffer_family})",
        "rpk_buffer_family": buffer_family,
        "rpk_metadata": rpk_meta,
        "timing_hint": timing_hint,
        "environment_hint": environment_hint,
        "rpk_recorded_channels": list(channel_native.keys()),
        "rpk_calculated_channels_loaded": calculated_loaded,
        "rpk_calculated_channels_skipped": calculated_skipped,
        "rpk_sample_rates_hz": sample_rates,
        "rpk_channel_calibrations": channel_calibrations,
        "rpk_nominal_buffer_window_s": nominal_window_s,
        "rpk_common_rate_hz": target_rate,
        "original_channel_map": dict(channel_map),
    }
    run = TelemetryRun(
        name=path.stem,
        data=frame,
        channel_map=channel_map,
        units=units,
        vendor="RacePak",
        metadata=metadata,
        environment=Environment.from_dict(environment_hint),
        timing=TimingData.from_dict(timing_hint),
    )
    run.metadata["timing_provenance"] = {k: "native RacePak file metadata" for k in timing_hint}
    run.metadata["environment_provenance"] = {k: "native RacePak file metadata" for k in environment_hint}
    return _normalize_canonical(run)
