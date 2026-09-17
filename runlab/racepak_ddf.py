from __future__ import annotations

"""Direct reader for raw RacePak/DataLink ``.DDF`` logger recordings.

Validated NHRA RacePak DDF files use a compact, deterministic layout:

* bytes 12..13 contain the descriptor count (little-endian uint16)
* descriptors begin at byte 14 and are 22 bytes each
* descriptor byte 0 is 0x33 in the qualified families
* bytes 2..5 are the DataLink ``_CONNECT4_COMMAND`` channel identifier
* bytes 6..9 are the logger sample rate in Hz
* bytes 10..13 are a logger/config field; zero means the descriptor has no
  samples in the payload in the qualified families
* descriptor byte 1 encodes the fixed-point decimal divisor
* the payload is int16 samples, arranged in one-second frames. Within each
  frame, active channels appear in descriptor order and contribute exactly
  ``sample_rate_hz`` samples.

The payload can therefore be decoded without DataLink. A matching RCG/RPK
configuration is optional and is used only to recover channel names/units and
to validate channel identity; raw DDF values are already engineering values.

The implementation is intentionally fail-closed. Unknown descriptor markers,
fixed-point flags, impossible rates, or malformed payloads are rejected rather
than guessed.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

from .models import ChannelSeries, TelemetryRun
from .racepak import RpkChannelDef, _attribute, parse_channel_definitions
from .units import normalize_unit


_HEADER_SIZE = 14
_DESCRIPTOR_SIZE = 22
_DESCRIPTOR_MARKER = 0x33
_VALID_SCALE_FLAGS = {0x00, 0xFC, 0xFD, 0xFE, 0xFF}


@dataclass(frozen=True)
class DdfDescriptor:
    index: int
    flags: int
    channel_id: int
    sample_rate_hz: int
    config_rate: int
    raw_record: bytes

    @property
    def recorded(self) -> bool:
        """Whether this descriptor contributes samples to the DDF payload."""
        return self.config_rate > 0

    @property
    def decimal_exponent(self) -> int:
        """Return the fixed-point decimal exponent encoded by ``flags``.

        Qualified files use 0x00 for integer engineering values and 0xFF,
        0xFE, 0xFD, 0xFC for 1, 2, 3, 4 decimal places respectively.
        """
        if self.flags == 0x00:
            return 0
        if self.flags in {0xFC, 0xFD, 0xFE, 0xFF}:
            return 0x100 - self.flags
        raise ValueError(f"Unsupported RacePak DDF fixed-point flag 0x{self.flags:02X}")

    @property
    def divisor(self) -> float:
        return float(10 ** self.decimal_exponent)


@dataclass(frozen=True)
class DdfStructure:
    header: bytes
    descriptors: tuple[DdfDescriptor, ...]
    payload_offset: int
    payload_nbytes: int
    frame_words: int
    full_frames: int
    partial_frame_words: int
    descriptor_signature: str

    @property
    def recorded_descriptors(self) -> tuple[DdfDescriptor, ...]:
        return tuple(d for d in self.descriptors if d.recorded)

    @property
    def duration_s_estimate(self) -> float:
        if self.frame_words <= 0:
            return 0.0
        return self.full_frames + self.partial_frame_words / self.frame_words


@dataclass(frozen=True)
class DdfConfigBinding:
    by_channel_id: Dict[int, RpkChannelDef]
    unmatched_ddf_ids: tuple[int, ...]
    duplicate_config_ids: tuple[int, ...]
    rate_mismatches: tuple[str, ...]


def _config_sample_rate(defn: RpkChannelDef) -> Optional[float]:
    if defn.sample_rate_hz and defn.sample_rate_hz > 0:
        return float(defn.sample_rate_hz)
    for key in ("Logger_Sample_Rate", "LOGGER_SAMPLE_RATE", "Logger Sample Rate"):
        raw = _attribute(defn.description, key)
        if raw not in (None, ""):
            try:
                hz = float(raw)
            except Exception:
                continue
            if hz > 0:
                return hz
    return None


def parse_ddf_structure(path_or_bytes: str | Path | bytes | bytearray | memoryview) -> DdfStructure:
    if isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
        data = bytes(path_or_bytes)
        label = "DDF bytes"
    else:
        path = Path(path_or_bytes)
        data = path.read_bytes()
        label = path.name

    if len(data) < _HEADER_SIZE:
        raise ValueError(f"{label}: file is too small to be a RacePak DDF")

    count = int.from_bytes(data[12:14], "little", signed=False)
    if not (1 <= count <= 2048):
        raise ValueError(f"{label}: invalid RacePak DDF descriptor count {count}")

    payload_offset = _HEADER_SIZE + count * _DESCRIPTOR_SIZE
    if payload_offset > len(data):
        raise ValueError(f"{label}: truncated RacePak DDF descriptor table")

    descriptors: list[DdfDescriptor] = []
    seen_ids: set[int] = set()
    for i in range(count):
        start = _HEADER_SIZE + i * _DESCRIPTOR_SIZE
        rec = data[start : start + _DESCRIPTOR_SIZE]
        if len(rec) != _DESCRIPTOR_SIZE:
            raise ValueError(f"{label}: truncated descriptor {i}")
        if rec[0] != _DESCRIPTOR_MARKER:
            raise ValueError(
                f"{label}: descriptor {i} has unsupported marker 0x{rec[0]:02X}; "
                "this DDF family is not qualified"
            )
        flags = int(rec[1])
        if flags not in _VALID_SCALE_FLAGS:
            raise ValueError(
                f"{label}: descriptor {i} has unsupported fixed-point flag 0x{flags:02X}"
            )
        channel_id = int.from_bytes(rec[2:6], "little", signed=False)
        rate = int.from_bytes(rec[6:10], "little", signed=False)
        config_rate = int.from_bytes(rec[10:14], "little", signed=False)
        if channel_id in seen_ids:
            raise ValueError(f"{label}: duplicate DDF channel id {channel_id}")
        seen_ids.add(channel_id)
        if not (1 <= rate <= 20_000):
            raise ValueError(f"{label}: implausible sample rate {rate} Hz for channel id {channel_id}")
        # Qualified descriptor tails are reserved/zero. Treat nonzero bytes as a
        # new family instead of pretending we understand their meaning.
        if any(rec[14:22]):
            raise ValueError(
                f"{label}: descriptor {i} contains unsupported nonzero reserved bytes"
            )
        descriptors.append(DdfDescriptor(i, flags, channel_id, rate, config_rate, bytes(rec)))

    payload_nbytes = len(data) - payload_offset
    if payload_nbytes < 0 or payload_nbytes % 2:
        raise ValueError(f"{label}: DDF payload is not an even number of int16 bytes")

    active = [d for d in descriptors if d.recorded]
    if not active:
        raise ValueError(f"{label}: DDF has no recorded channel descriptors")
    frame_words = sum(int(d.sample_rate_hz) for d in active)
    if frame_words <= 0:
        raise ValueError(f"{label}: DDF has an invalid zero-size sample frame")

    payload_words = payload_nbytes // 2
    full_frames, partial = divmod(payload_words, frame_words)
    signature_bytes = b"".join(d.raw_record for d in descriptors)
    signature = sha256(signature_bytes).hexdigest()
    return DdfStructure(
        header=bytes(data[:_HEADER_SIZE]),
        descriptors=tuple(descriptors),
        payload_offset=payload_offset,
        payload_nbytes=payload_nbytes,
        frame_words=frame_words,
        full_frames=int(full_frames),
        partial_frame_words=int(partial),
        descriptor_signature=signature,
    )


def bind_ddf_config(structure: DdfStructure, config_bytes: bytes) -> DdfConfigBinding:
    defs = parse_channel_definitions(config_bytes)
    by_id: Dict[int, RpkChannelDef] = {}
    duplicates: set[int] = set()
    for defn in defs:
        raw = _attribute(defn.description, "_CONNECT4_COMMAND")
        if raw in (None, ""):
            continue
        try:
            channel_id = int(str(raw), 0)
        except Exception:
            continue
        if channel_id in by_id:
            duplicates.add(channel_id)
            continue
        by_id[channel_id] = defn

    if duplicates:
        for channel_id in duplicates:
            by_id.pop(channel_id, None)

    mismatches: list[str] = []
    for desc in structure.recorded_descriptors:
        defn = by_id.get(desc.channel_id)
        if defn is None:
            continue
        cfg_rate = _config_sample_rate(defn)
        if cfg_rate is not None and abs(cfg_rate - desc.sample_rate_hz) > 1e-6:
            mismatches.append(
                f"channel {desc.channel_id} ({defn.name}): DDF {desc.sample_rate_hz} Hz vs config {cfg_rate:g} Hz"
            )

    unmatched = tuple(d.channel_id for d in structure.recorded_descriptors if d.channel_id not in by_id)
    return DdfConfigBinding(
        by_channel_id=by_id,
        unmatched_ddf_ids=unmatched,
        duplicate_config_ids=tuple(sorted(duplicates)),
        rate_mismatches=tuple(mismatches),
    )


def _decode_payload(
    data: bytes,
    structure: DdfStructure,
) -> Dict[int, np.ndarray]:
    words = np.frombuffer(data, dtype="<i2", count=structure.payload_nbytes // 2, offset=structure.payload_offset)
    active = structure.recorded_descriptors
    out_parts: Dict[int, list[np.ndarray]] = {d.channel_id: [] for d in active}

    cursor = 0
    # Each complete DDF frame represents one second. Within a frame, channels
    # occur in descriptor order and contribute sample_rate_hz int16 words.
    for _ in range(structure.full_frames):
        for desc in active:
            n = int(desc.sample_rate_hz)
            out_parts[desc.channel_id].append(words[cursor : cursor + n])
            cursor += n

    # A recording may stop part-way through the final one-second frame. Consume
    # that tail in the same descriptor order without inventing missing samples.
    remain = int(structure.partial_frame_words)
    if remain:
        for desc in active:
            if remain <= 0:
                break
            n = min(int(desc.sample_rate_hz), remain)
            out_parts[desc.channel_id].append(words[cursor : cursor + n])
            cursor += n
            remain -= n

    if cursor != len(words):
        raise ValueError(
            f"RacePak DDF payload accounting mismatch: consumed {cursor} words from {len(words)}"
        )

    decoded: Dict[int, np.ndarray] = {}
    for desc in active:
        chunks = out_parts[desc.channel_id]
        raw = np.concatenate(chunks).astype(float, copy=False) if chunks else np.empty(0, dtype=float)
        decoded[desc.channel_id] = raw / desc.divisor
    return decoded


def _discover_sibling_config(path: Path) -> Optional[Path]:
    candidates = sorted({*path.parent.glob("*.rcg"), *path.parent.glob("*.RCG")})
    if len(candidates) == 1:
        return candidates[0]
    return None


def parse_racepak_ddf(
    path: str | Path,
    config_path: str | Path | None = None,
) -> TelemetryRun:
    """Decode a raw RacePak DDF recording directly.

    ``config_path`` may be a matching ``.rcg`` configuration or an ``.rpk``
    run containing the same DataLink channel definitions. It is optional: a DDF
    without a configuration still opens using stable channel-id labels, but no
    canonical engineering role is guessed from the numeric id alone.
    """
    from .importers import _normalize_canonical, auto_map_channels

    path = Path(path)
    data = path.read_bytes()
    structure = parse_ddf_structure(data)

    selected_config: Optional[Path] = Path(config_path) if config_path else _discover_sibling_config(path)
    binding: Optional[DdfConfigBinding] = None
    if selected_config is not None:
        if not selected_config.exists():
            raise FileNotFoundError(selected_config)
        binding = bind_ddf_config(structure, selected_config.read_bytes())
        if binding.duplicate_config_ids:
            raise ValueError(
                f"{selected_config.name}: duplicate _CONNECT4_COMMAND ids prevent safe DDF binding: "
                + ", ".join(map(str, binding.duplicate_config_ids[:12]))
            )
        if binding.rate_mismatches:
            raise ValueError(
                f"{selected_config.name}: configuration does not match this DDF sample-rate signature: "
                + "; ".join(binding.rate_mismatches[:8])
            )

    decoded = _decode_payload(data, structure)
    native_channels: Dict[str, ChannelSeries] = {}
    units: Dict[str, str] = {}
    name_for_id: Dict[int, str] = {}
    used_names: Dict[str, int] = {}

    for desc in structure.recorded_descriptors:
        defn = binding.by_channel_id.get(desc.channel_id) if binding else None
        base_name = (defn.name.strip() if defn and defn.name.strip() else f"RacePak Channel {desc.channel_id}")
        if base_name in used_names:
            used_names[base_name] += 1
            name = f"{base_name} [{desc.channel_id}]"
        else:
            used_names[base_name] = 1
            name = base_name
        name_for_id[desc.channel_id] = name
        unit = normalize_unit(defn.unit) if defn and defn.unit else ""
        values = decoded[desc.channel_id]
        t = np.arange(len(values), dtype=float) / float(desc.sample_rate_hz)
        native_channels[name] = ChannelSeries(
            name=name,
            time_s=t,
            values=values,
            unit=unit,
            sample_rate_hz=float(desc.sample_rate_hz),
            decimals=desc.decimal_exponent,
            metadata={
                "racepak_connect4_command": desc.channel_id,
                "ddf_flags": desc.flags,
                "ddf_decimal_exponent": desc.decimal_exponent,
                "ddf_config_rate": desc.config_rate,
            },
        )
        if unit:
            units[name] = unit

    if not native_channels:
        raise ValueError(f"{path.name}: DDF decoded no channels")

    # Preserve native sample rates for the waveform viewer, while retaining the
    # established rectangular DataFrame contract for analysis/report code.
    target_rate = max(float(ch.sample_rate_hz or 0.0) for ch in native_channels.values())
    duration = max(float(ch.time_s[-1]) if len(ch.time_s) else 0.0 for ch in native_channels.values())
    if target_rate <= 0 or duration <= 0:
        raise ValueError(f"{path.name}: DDF channels contain no usable time span")
    common_t = np.arange(int(np.floor(duration * target_rate + 1e-9)) + 1, dtype=float) / target_rate
    cols: Dict[str, np.ndarray] = {"Time (s)": common_t}
    units["Time (s)"] = "s"
    for name, ch in native_channels.items():
        t = np.asarray(ch.time_s, dtype=float)
        values = np.asarray(ch.values, dtype=float)
        if len(t) == 0:
            cols[name] = np.full_like(common_t, np.nan)
        elif len(t) == 1:
            arr = np.full_like(common_t, np.nan)
            arr[np.argmin(np.abs(common_t - t[0]))] = values[0]
            cols[name] = arr
        else:
            cols[name] = np.interp(common_t, t, values, left=np.nan, right=np.nan)

    df = pd.DataFrame(cols)
    channel_map = auto_map_channels(df.columns, units) if binding else {"time_s": "Time (s)"}
    metadata = {
        "source_file": path.name,
        "source_format": "RacePak raw DDF",
        "ddf_descriptor_count": len(structure.descriptors),
        "ddf_recorded_channel_count": len(structure.recorded_descriptors),
        "ddf_descriptor_signature_sha256": structure.descriptor_signature,
        "ddf_frame_words": structure.frame_words,
        "ddf_full_frames": structure.full_frames,
        "ddf_partial_frame_words": structure.partial_frame_words,
        "ddf_estimated_duration_s": structure.duration_s_estimate,
        "ddf_channel_ids": [d.channel_id for d in structure.recorded_descriptors],
        "ddf_sample_rates_hz": {name_for_id[d.channel_id]: d.sample_rate_hz for d in structure.recorded_descriptors},
        "ddf_scaling": "signed int16 / 10^(256-flags) for flags FC-FF; integer for flag 00",
        "ddf_config_file": selected_config.name if selected_config else None,
        "ddf_config_path": str(selected_config.resolve()) if selected_config else None,
        "ddf_config_sha256": sha256(selected_config.read_bytes()).hexdigest() if selected_config else None,
        "ddf_config_bound_channels": len(binding.by_channel_id) if binding else 0,
        "ddf_unmatched_channel_ids": list(binding.unmatched_ddf_ids) if binding else [d.channel_id for d in structure.recorded_descriptors],
        "original_channel_map": dict(channel_map),
    }
    if not binding:
        metadata["data_warnings"] = [
            "Raw RacePak DDF samples were decoded directly, but no matching RCG/RPK configuration was supplied. "
            "Channels are identified by stable RacePak channel id; NHRA Velocity did not guess channel names or canonical roles."
        ]
    elif binding.unmatched_ddf_ids:
        metadata["data_warnings"] = [
            "The selected RacePak configuration did not define every recorded DDF channel id. "
            "Matched channels use the configuration names/units; unmatched channels retain stable RacePak channel-id labels: "
            + ", ".join(map(str, binding.unmatched_ddf_ids[:20]))
        ]

    run = TelemetryRun(
        name=path.stem,
        data=df,
        channel_map=channel_map,
        units=units,
        vendor="RacePak",
        metadata=metadata,
        native_channels=native_channels,
    )
    return _normalize_canonical(run)
