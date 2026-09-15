from __future__ import annotations

"""Conservative Holley EFI V6 DL/DLZ telemetry reader.

This module intentionally implements only the structure that has been qualified
against a real NHRA Pro Stock V6 recording.  Older/newer Holley families remain
fail-closed until representative files are checked.

The source file is never modified.  DLZ expansion happens in memory, raw V6
parameter slots are retained, and only a very small set of semantic channel
names is asserted where the position has independent format/range evidence.
"""

from pathlib import Path
from typing import Dict, Tuple
import struct

import numpy as np
import pandas as pd

from .models import TelemetryRun


HOLLEY_MAGIC_V5_V6 = 0x0085F41F
HOLLEY_MAGIC_V3 = 0x0095365F
HOLLEY_V6_VERSION = 6
HOLLEY_V5_VERSION = 5
HOLLEY_V6_DATA_START = 16_456
HOLLEY_V6_FLOATS_PER_ROW = 1_030
HOLLEY_V6_BYTES_PER_ROW = HOLLEY_V6_FLOATS_PER_ROW * 4
HOLLEY_V6_PARAMETER_SLOTS = 516


class HolleyDecodeError(ValueError):
    pass


def _swap_four_byte_words(data: bytes) -> bytes:
    """Reverse byte order within each complete four-byte word."""
    n = (len(data) // 4) * 4
    if not n:
        return data
    arr = np.frombuffer(data[:n], dtype=np.uint8).reshape(-1, 4)
    swapped = arr[:, ::-1].copy().reshape(-1).tobytes()
    return swapped + data[n:]


def _rle_expand(data: bytes) -> bytes:
    """Expand the byte-run encoding used by qualified Holley DLZ files.

    0xFF COUNT VALUE emits VALUE COUNT times.  COUNT=0 is an escape for a
    literal 0xFF.  A truncated marker is rejected rather than guessed.
    """
    out = bytearray()
    i = 0
    size = len(data)
    while i < size:
        value = data[i]
        i += 1
        if value != 0xFF:
            out.append(value)
            continue
        if i + 1 >= size:
            raise HolleyDecodeError("truncated DLZ RLE marker")
        count = data[i]
        repeated = data[i + 1]
        i += 2
        if count == 0:
            out.append(0xFF)
        else:
            out.extend(bytes((repeated,)) * count)
    return bytes(out)


def decompress_dlz_bytes(data: bytes) -> bytes:
    """Expand a qualified Holley DLZ stream into its DL representation."""
    if len(data) < 32:
        raise HolleyDecodeError("DLZ file is too small")
    # The qualified family uses the same four-byte magic before expansion.
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic not in {HOLLEY_MAGIC_V5_V6, HOLLEY_MAGIC_V3}:
        raise HolleyDecodeError(f"unrecognized Holley DLZ magic 0x{magic:08X}")
    return _swap_four_byte_words(_rle_expand(_swap_four_byte_words(data)))


def _validated_v6_layout(data: bytes) -> Tuple[int, int, int, int, float]:
    """Return rows, remainder, first tick, last tick and median tick step."""
    if len(data) < HOLLEY_V6_DATA_START + HOLLEY_V6_BYTES_PER_ROW:
        raise HolleyDecodeError("Holley DL file is too small for a V6 data row")
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic == HOLLEY_MAGIC_V3:
        raise HolleyDecodeError(
            "Holley V3/Terminator-family DL was recognized, but direct V3 decoding is not yet NHRA-qualified."
        )
    if magic != HOLLEY_MAGIC_V5_V6:
        raise HolleyDecodeError(f"unrecognized Holley DL magic 0x{magic:08X}")
    version = struct.unpack_from("<I", data, 8)[0]
    if version == HOLLEY_V5_VERSION:
        raise HolleyDecodeError(
            "Holley V5 sparse DL format was recognized. Convert/open-save it with Holley software to V6 before import; "
            "NHRA Tech Data will not guess the V5 sparse layout."
        )
    if version != HOLLEY_V6_VERSION:
        raise HolleyDecodeError(
            f"Holley DL version field {version} is not the qualified V6 family (version 6)."
        )

    payload = len(data) - HOLLEY_V6_DATA_START
    rows, remainder = divmod(payload, HOLLEY_V6_BYTES_PER_ROW)
    if rows < 2:
        raise HolleyDecodeError("Holley V6 file contains fewer than two complete data rows")
    # Real V6 examples can carry a tiny trailer; anything sizeable means the
    # assumed row contract does not fit the file and must fail closed.
    if remainder > 64:
        raise HolleyDecodeError(
            f"Holley V6 row structure mismatch: {remainder} trailing bytes after {rows} rows"
        )

    words = np.frombuffer(
        data,
        dtype="<u4",
        count=rows * HOLLEY_V6_FLOATS_PER_ROW,
        offset=HOLLEY_V6_DATA_START,
    ).reshape(rows, HOLLEY_V6_FLOATS_PER_ROW)
    # Qualified V6 stores the RTC as a 64-bit integer spanning the two u32
    # words that occupy parameter slot 1.  It is not a float channel.
    ticks = (words[:, 3].astype(np.uint64) << np.uint64(32)) | words[:, 2].astype(np.uint64)
    signed = ticks.astype(np.int64)
    dt = np.diff(signed)
    positive = dt[dt > 0]
    if len(positive) < max(2, int(0.95 * len(dt))):
        raise HolleyDecodeError("Holley V6 RTC is not sufficiently monotonic")
    median_step = float(np.median(positive))
    # NHRA qualification demonstrated millisecond ticks. Keep the accepted
    # envelope broad enough for lower logging rates without accepting nonsense.
    if not (1.0 <= median_step <= 10_000.0):
        raise HolleyDecodeError(f"Holley V6 RTC step {median_step:g} is implausible for millisecond ticks")
    return rows, remainder, int(ticks[0]), int(ticks[-1]), median_step


def parse_holley(path: str | Path) -> TelemetryRun:
    """Parse a qualified Holley V6 .dl or .dlz file.

    Semantic mapping is intentionally limited. Engine RPM and the logger clock
    are qualified. A few standard early parameter slots receive descriptive
    source names, while every other raw slot remains visible as ``Holley Param
    NNN`` so no unverified signal identity is invented.
    """
    path = Path(path)
    source = path.read_bytes()
    compressed = path.suffix.lower() == ".dlz"
    data = decompress_dlz_bytes(source) if compressed else source

    rows, remainder, first_tick, last_tick, median_tick_ms = _validated_v6_layout(data)
    words = np.frombuffer(
        data,
        dtype="<u4",
        count=rows * HOLLEY_V6_FLOATS_PER_ROW,
        offset=HOLLEY_V6_DATA_START,
    ).reshape(rows, HOLLEY_V6_FLOATS_PER_ROW)
    floats = words.view("<f4")
    values = floats[:, ::2][:, :HOLLEY_V6_PARAMETER_SLOTS]
    ticks = (words[:, 3].astype(np.uint64) << np.uint64(32)) | words[:, 2].astype(np.uint64)
    time_s = (ticks - ticks[0]).astype(np.float64) / 1000.0

    known_names: Dict[int, str] = {
        0: "Holley Point Number",
        2: "Engine RPM",
        # These early fields follow the standard Holley V6 parameter ordering
        # and are retained as source labels. Only Engine RPM/time are promoted
        # to canonical roles by this qualified reader.
        3: "Injector PW",
        4: "Injector Duty Cycle",
        6: "Target AFR",
    }
    columns: Dict[str, object] = {
        "Time (s)": time_s,
        "Holley RTC Ticks": ticks,
    }
    parameter_index: Dict[str, int] = {}
    for idx in range(HOLLEY_V6_PARAMETER_SLOTS):
        if idx == 1:
            # Parameter slot 1 is the 64-bit RTC represented separately above.
            continue
        name = known_names.get(idx, f"Holley Param {idx:03d}")
        columns[name] = values[:, idx]
        parameter_index[name] = idx

    df = pd.DataFrame(columns)
    units = {
        "Time (s)": "s",
        "Holley RTC Ticks": "ms_tick",
        "Engine RPM": "rpm",
        "Injector PW": "ms",
        "Injector Duty Cycle": "pct",
    }
    channel_map = {
        "time_s": "Time (s)",
        "engine_rpm": "Engine RPM",
    }
    sample_rate_hz = 1000.0 / median_tick_ms
    warnings = [
        "Holley V6 direct import currently has limited semantic channel mapping. "
        "Unqualified parameter slots remain visible by numeric Holley parameter index rather than being guessed."
    ]
    metadata = {
        "source_file": path.name,
        "source_format": "Holley DLZ V6" if compressed else "Holley DL V6",
        "holley_version": 6,
        "holley_data_start": HOLLEY_V6_DATA_START,
        "holley_floats_per_row": HOLLEY_V6_FLOATS_PER_ROW,
        "holley_parameter_slots": HOLLEY_V6_PARAMETER_SLOTS,
        "holley_parameter_index": parameter_index,
        "holley_rtc_first_tick": first_tick,
        "holley_rtc_last_tick": last_tick,
        "holley_rtc_median_step_ms": median_tick_ms,
        "holley_sample_rate_hz": sample_rate_hz,
        "holley_trailing_bytes": remainder,
        "holley_semantic_mapping": {
            "time_s": {"source": "Holley RTC Ticks", "confidence": "qualified", "scale": "milliseconds"},
            "engine_rpm": {"source": "parameter_002", "confidence": "qualified"},
        },
        "original_channel_map": dict(channel_map),
        "data_warnings": warnings,
    }
    return TelemetryRun(
        name=path.stem,
        data=df,
        channel_map=channel_map,
        units=units,
        vendor="Holley",
        metadata=metadata,
    )
