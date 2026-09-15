from __future__ import annotations

"""Native MoTeC i2 ``.ld`` reader.

The binary layout implemented here is based on independently documented,
MIT-licensed community format work (not MoTeC proprietary source code).  It is
kept deliberately small, bounds-checked, and fail-closed so an unfamiliar file
variant cannot silently generate nonsense engineering values.

The parser preserves every channel on its native sample timebase and also
creates a rectangular DataFrame resampled to the fastest channel for backwards
compatibility with the current inverse/physics pipeline.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Tuple
import mmap
import struct
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from .models import TelemetryRun, ChannelSeries
from .importers import auto_map_channels, _normalize_canonical
from .units import normalize_unit


class MoTeCLDError(ValueError):
    pass


class MoTeCUnsupportedChannel(MoTeCLDError):
    """A structurally valid channel whose sample encoding is not decoded yet."""

    def __init__(self, meta: "_ChannelMeta") -> None:
        self.meta = meta
        super().__init__(
            f"{meta.name}: unsupported LD data type class=0x{meta.elem_type:02x}, size={meta.elem_size}"
        )


def _u16(buf: memoryview, off: int) -> int:
    if off < 0 or off + 2 > len(buf):
        raise MoTeCLDError(f"LD offset {off} is outside file")
    return struct.unpack_from('<H', buf, off)[0]


def _u32(buf: memoryview, off: int) -> int:
    if off < 0 or off + 4 > len(buf):
        raise MoTeCLDError(f"LD offset {off} is outside file")
    return struct.unpack_from('<I', buf, off)[0]


def _str(buf: memoryview, off: int, n: int) -> str:
    if off < 0 or off + n > len(buf):
        return ""
    raw = bytes(buf[off:off+n])
    raw = raw.split(b'\0', 1)[0]
    return raw.decode('latin-1', errors='replace').strip()


def _put(meta: Dict[str, Any], key: str, value: Any) -> None:
    if value not in (None, "", 0):
        meta[key] = value


@dataclass
class _ChannelMeta:
    name: str
    short_name: str
    unit: str
    data_addr: int
    count: int
    elem_type: int
    elem_size: int
    rate_hz: float
    shift: float
    mul: float
    scale: float
    dec_pts: int
    next_addr: int


def _decode_channel(buf: memoryview, addr: int) -> Tuple[_ChannelMeta, np.ndarray]:
    """Decode one MoTeC LD channel record.

    Known LD files use a 120-byte base record and may append 92 bytes of
    extended metadata.  The scale fields are signed int16 values; treating
    shift/mul/scale as unsigned is a subtle but serious source of bad values.
    """
    if addr <= 0 or addr + 120 > len(buf):
        raise MoTeCLDError(f"Invalid channel metadata address 0x{addr:x}")
    next_addr = _u32(buf, addr + 4)
    try:
        (data_addr, data_count, elem_type, elem_size, sample_rate,
         shift, mul, scale, dec_pts) = struct.unpack_from('<II2xHHHhhhh', buf, addr + 8)
    except struct.error as exc:
        raise MoTeCLDError(f"Could not decode channel metadata at 0x{addr:x}") from exc

    raw_name = bytes(buf[addr + 32:addr + 64])
    name = raw_name.split(b'\0', 1)[0].decode('latin-1', errors='replace').strip()
    short_name = _str(buf, addr + 64, 8)
    unit_raw = _str(buf, addr + 72, 12)

    # M1 logs frequently leave the 12-byte unit field blank and store the unit
    # in short_name.  If the 32-byte name is completely full, a 1–2 character
    # short_name can instead be a truncated-name continuation.
    name_was_full = b'\0' not in raw_name
    if not name:
        name = f"Channel_0x{addr:x}"
    if name_was_full and short_name and len(short_name) <= 2 and name[-1:].isalnum():
        name = name + short_name
        short_name_for_unit = ""
    else:
        short_name_for_unit = short_name
    effective_unit = unit_raw or short_name_for_unit
    unit = normalize_unit(effective_unit) or effective_unit

    if data_count == 0:
        meta = _ChannelMeta(
            name=name, short_name=short_name, unit=unit, data_addr=int(data_addr),
            count=0, elem_type=int(elem_type), elem_size=int(elem_size),
            rate_hz=float(sample_rate), shift=float(shift), mul=float(mul),
            scale=float(scale), dec_pts=int(dec_pts), next_addr=int(next_addr),
        )
        return meta, np.array([], dtype=np.float64)
    if not sample_rate:
        raise MoTeCLDError(f"{name}: sample rate is zero")
    if data_count > 100_000_000:
        raise MoTeCLDError(f"{name}: implausible sample count {data_count}")

    meta = _ChannelMeta(
        name=name, short_name=short_name, unit=unit, data_addr=int(data_addr),
        count=int(data_count), elem_type=int(elem_type), elem_size=int(elem_size),
        rate_hz=float(sample_rate), shift=float(shift), mul=float(mul),
        scale=float(scale), dec_pts=int(dec_pts), next_addr=int(next_addr),
    )

    # Supported sample encodings observed in MoTeC LD logs.  Some M1 files
    # contain isolated diagnostic/state encodings (notably class 0x06/size 4)
    # among otherwise ordinary channels.  Treat those as unsupported channels
    # rather than rejecting the entire run.
    if elem_type in (0x00, 0x03, 0x05):
        dtype = {2: '<i2', 4: '<i4'}.get(elem_size)
    elif elem_type == 0x07:
        dtype = {2: '<f2', 4: '<f4'}.get(elem_size)
    elif elem_type == 0x08 and elem_size == 8:
        dtype = '<f8'
    else:
        dtype = None
    if dtype is None:
        raise MoTeCUnsupportedChannel(meta)

    nbytes = int(elem_size) * int(data_count)
    if data_addr <= 0 or data_addr + nbytes > len(buf):
        raise MoTeCLDError(
            f"{name}: sample buffer 0x{data_addr:x}+{nbytes} exceeds file size {len(buf)}"
        )
    raw = buf[data_addr:data_addr+nbytes]
    arr = np.frombuffer(raw, dtype=dtype).astype(np.float64, copy=True)

    # Verified MoTeC engineering conversion:
    # converted = (raw / scale) * 10**(-dec_places) * mul + shift
    # A zero scale is an observed edge case; in that case skip the division.
    divisor = float(scale) if int(scale) != 0 else 1.0
    values = (arr / divisor) * (10.0 ** (-int(dec_pts))) * float(mul) + float(shift)

    return meta, values


def _parse_ldx(path: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not path.exists():
        return out
    try:
        root = ET.parse(path).getroot()
        out['ldx_file'] = path.name
        # Preserve simple metadata and common lap/beacon attributes without
        # assuming one firmware-specific XML schema.
        attrs = {}
        for elem in root.iter():
            for k, v in elem.attrib.items():
                if len(attrs) < 100:
                    attrs[f"{elem.tag}.{k}"] = v
        if attrs:
            out['ldx_attributes'] = attrs
    except Exception as exc:
        out['ldx_warning'] = f"Could not parse sidecar {path.name}: {exc}"
    return out


def _metadata(buf: memoryview) -> Tuple[int, int, Dict[str, Any]]:
    if len(buf) < 1700:
        raise MoTeCLDError("File is too small to be a supported MoTeC LD log")
    marker = _u32(buf, 0)
    if marker != 64:
        raise MoTeCLDError(
            f"Unsupported MoTeC LD header marker {marker}; expected 64 for the validated LD family"
        )
    channel_meta_addr = _u32(buf, 8)
    event_addr = _u32(buf, 36)
    # M1 LDs store the advisory channel count as a 16-bit value at 0x56.
    # The following uint16 is commonly a duplicate; reading four bytes here
    # turns e.g. 0x00b5/0x00b5 into the bogus count 11,862,197.
    num_channels = _u16(buf, 86)
    if not channel_meta_addr or num_channels > 10000:
        raise MoTeCLDError(
            f"Invalid LD channel table: first=0x{channel_meta_addr:x}, count={num_channels}"
        )

    meta: Dict[str, Any] = {
        'format': 'MoTeC LD',
        'device_serial': _u32(buf, 70),
        'device_type': _str(buf, 74, 8),
        'device_version': f"{_u16(buf, 82) / 100:.2f}",
        'channel_count': int(num_channels),
        'log_date': _str(buf, 94, 16),
        'log_time': _str(buf, 126, 16),
        'driver': _str(buf, 158, 64),
        'vehicle': _str(buf, 222, 64),
        'venue': _str(buf, 350, 64),
        'short_comment': _str(buf, 1572, 64),
    }
    # Remove empty strings/zeros from display metadata.
    meta = {k: v for k, v in meta.items() if v not in (None, "", 0)}

    if event_addr and event_addr + 1156 <= len(buf):
        _put(meta, 'event_name', _str(buf, event_addr, 64))
        _put(meta, 'event_session', _str(buf, event_addr + 64, 64))
        _put(meta, 'long_comment', _str(buf, event_addr + 128, 1024))
        venue_addr = _u32(buf, event_addr + 1152)
        if venue_addr and venue_addr + 1102 <= len(buf):
            _put(meta, 'venue_name', _str(buf, venue_addr, 64))
            vehicle_addr = _u32(buf, venue_addr + 1098)
            if vehicle_addr and vehicle_addr + 260 <= len(buf):
                _put(meta, 'vehicle_id', _str(buf, vehicle_addr, 64))
                _put(meta, 'vehicle_weight', _u32(buf, vehicle_addr + 192))
                _put(meta, 'vehicle_type', _str(buf, vehicle_addr + 196, 32))
                _put(meta, 'vehicle_comment', _str(buf, vehicle_addr + 228, 32))

    return channel_meta_addr, int(num_channels), meta


def _is_discrete(name: str, unit: str) -> bool:
    n = name.lower()
    return (
        unit in ("", "s")
        or any(k in n for k in ("gear", "beacon", "event", "status", "switch", "flag", "lap"))
    )


def _to_wide(native: Dict[str, ChannelSeries]) -> pd.DataFrame:
    if not native:
        return pd.DataFrame()
    max_rate = max(float(ch.sample_rate_hz or 0) for ch in native.values())
    if max_rate <= 0:
        max_rate = 10.0
    # Keep compatibility grid bounded. Native-rate arrays remain available to the
    # desktop viewer and are the preferred display source.
    max_rate = min(max_rate, 2000.0)
    end = max(float(ch.time_s[-1]) for ch in native.values() if len(ch.time_s))
    step = 1.0 / max_rate
    count = int(np.floor(end / step)) + 1
    if count > 10_000_000:
        raise MoTeCLDError(
            f"Log would require {count:,} points on the compatibility grid; use native channel access instead"
        )
    t = np.arange(count, dtype=np.float64) * step
    out: Dict[str, np.ndarray] = {'Time': t}
    for name, ch in native.items():
        if len(ch.time_s) == 0:
            continue
        x = np.asarray(ch.time_s, dtype=float)
        y = np.asarray(ch.values, dtype=float)
        finite = np.isfinite(x) & np.isfinite(y)
        if finite.sum() < 1:
            out[name] = np.full_like(t, np.nan)
            continue
        x, y = x[finite], y[finite]
        if ch.interpolate and len(x) >= 2:
            vals = np.interp(t, x, y, left=np.nan, right=np.nan)
        else:
            idx = np.searchsorted(x, t, side='right') - 1
            vals = np.full_like(t, np.nan)
            ok = (idx >= 0) & (idx < len(y))
            vals[ok] = y[idx[ok]]
        out[name] = vals
    return pd.DataFrame(out)


def parse_motec_ld(path: str | Path) -> TelemetryRun:
    path = Path(path)
    native: Dict[str, ChannelSeries] = {}
    units: Dict[str, str] = {'Time': 's'}
    unit_provenance: Dict[str, str] = {'Time': 'generated from native MoTeC sample clocks'}
    unsupported_channels: List[Dict[str, Any]] = []

    with path.open('rb') as fh:
        with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            buf = memoryview(mm)
            try:
                first_addr, count, meta = _metadata(buf)
                addr = first_addr
                visited = set()
                linked_records = 0
                loaded = 0
                # Header count is advisory.  The metadata linked list is the
                # authoritative source of channel records.
                while addr:
                    if addr in visited:
                        raise MoTeCLDError(f"Channel metadata linked list loops at 0x{addr:x}")
                    if linked_records >= 10000:
                        raise MoTeCLDError("MoTeC LD channel list exceeds safety limit")
                    visited.add(addr)
                    linked_records += 1
                    try:
                        cm, values = _decode_channel(buf, addr)
                    except MoTeCUnsupportedChannel as exc:
                        cm = exc.meta
                        unsupported_channels.append({
                            'name': cm.name,
                            'element_type': cm.elem_type,
                            'element_size': cm.elem_size,
                            'sample_rate_hz': cm.rate_hz,
                            'sample_count': cm.count,
                            'metadata_offset': addr,
                        })
                        addr = cm.next_addr
                        continue
                    # A zero-length final record is a normal terminator in some LDs.
                    if cm.count == 0:
                        break
                    time_s = np.arange(cm.count, dtype=np.float64) / cm.rate_hz
                    # Duplicate names occur in some systems; preserve all data.
                    name = cm.name
                    if name in native:
                        base = name
                        n = 2
                        while f"{base} ({n})" in native:
                            n += 1
                        name = f"{base} ({n})"
                    unit = normalize_unit(cm.unit) or cm.unit
                    native[name] = ChannelSeries(
                        name=name,
                        time_s=time_s,
                        values=values,
                        unit=unit,
                        sample_rate_hz=cm.rate_hz,
                        decimals=max(cm.dec_pts, 0),
                        interpolate=not _is_discrete(name, unit),
                        metadata={
                            'ld_element_type': cm.elem_type,
                            'ld_element_size': cm.elem_size,
                            'ld_shift': cm.shift,
                            'ld_multiplier': cm.mul,
                            'ld_scale': cm.scale,
                            'ld_decimal_places': cm.dec_pts,
                            'ld_short_name': cm.short_name,
                        },
                    )
                    units[name] = unit
                    unit_provenance[name] = 'native MoTeC LD channel metadata'
                    loaded += 1
                    addr = cm.next_addr

                meta['header_channel_count'] = int(count)
                meta['linked_channel_records'] = int(linked_records)
                meta['parsed_channel_count'] = int(loaded)
                if unsupported_channels:
                    meta['unsupported_channels'] = unsupported_channels
                    names = ', '.join(x['name'] for x in unsupported_channels[:4])
                    more = '' if len(unsupported_channels) <= 4 else f" (+{len(unsupported_channels)-4} more)"
                    meta.setdefault('data_warnings', []).append(
                        f"Skipped {len(unsupported_channels)} structurally valid MoTeC channel(s) with unsupported encodings: {names}{more}."
                    )
                if loaded == 0:
                    raise MoTeCLDError("No decodable channels were found in the MoTeC LD linked list")
                # Because unsupported diagnostic channels may be skipped, compare
                # the header against linked records, not only loaded channels.
                if int(count) not in (linked_records, linked_records - 1):
                    meta.setdefault('data_warnings', []).append(
                        f"MoTeC header declares {count} channels; linked list contains {linked_records} records. Linked-list count used."
                    )
            finally:
                # Always release the exported view, including on decode errors,
                # before mmap.__exit__ attempts to close the mapping.
                buf.release()

    df = _to_wide(native)
    cmap = auto_map_channels([c for c in df.columns if c != 'Time'], units=units)
    cmap['time_s'] = 'Time'
    meta.update(_parse_ldx(path.with_suffix('.ldx')))
    meta.update({
        'source_file': path.name,
        'source_path': str(path),
        'native_rate_channels': True,
        'unit_provenance': unit_provenance,
        'original_channel_map': dict(cmap),
        'parser': 'NHRA Velocity native MoTeC LD reader',
    })
    run = TelemetryRun(
        name=path.stem,
        data=df,
        channel_map=cmap,
        units=units,
        vendor='MoTeC',
        metadata=meta,
        native_channels=native,
    )
    return _normalize_canonical(run)
