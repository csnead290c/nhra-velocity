from __future__ import annotations

"""Run-to-run comparison helpers used by the desktop workstation.

These functions deliberately have no Qt dependency so compare math can be
regression-tested independently of the renderer.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from .display_data import channel_xy, prepare_plot_series
from .models import TelemetryRun
from .units import normalize_unit, compatible, convert_value, dimension


@dataclass
class DeltaSeries:
    x: np.ndarray
    delta: np.ndarray
    main: np.ndarray
    reference: np.ndarray
    unit: str
    main_channel: str
    reference_channel: str
    overlap: Optional[Tuple[float, float]]


def source_for_canonical(run: TelemetryRun, canonical: str) -> Optional[str]:
    if canonical not in run.channel_map:
        return None
    originals = run.metadata.get("original_channel_map", {}) or {}
    source = originals.get(canonical)
    if source and (source in run.native_channels or source in run.data.columns):
        return str(source)
    mapped = run.channel_map.get(canonical)
    if mapped and not str(mapped).startswith("__") and (mapped in run.native_channels or mapped in run.data.columns):
        return str(mapped)
    return None


def canonical_for_source(run: TelemetryRun, source: str) -> Optional[str]:
    originals = run.metadata.get("original_channel_map", {}) or {}
    for canonical, name in originals.items():
        if str(name) == str(source) and canonical in run.channel_map:
            return str(canonical)
    for canonical, mapped in run.channel_map.items():
        if str(mapped) == str(source):
            return str(canonical)
    return None


def matching_reference_channel(main: TelemetryRun, reference: TelemetryRun, main_channel: str) -> Optional[str]:
    if main_channel in reference.native_channels or main_channel in reference.data.columns:
        return main_channel
    canonical = canonical_for_source(main, main_channel)
    if canonical:
        return source_for_canonical(reference, canonical)
    return None


def reference_delta_series(
    main: TelemetryRun,
    reference: TelemetryRun,
    main_channel: str,
    reference_channel: Optional[str] = None,
    *,
    x_mode: str = "Time from Launch",
    main_alignment_s: float = 0.0,
    reference_alignment_s: float = 0.0,
    sign: str = "reference-main",
    max_points: int = 50000,
) -> DeltaSeries:
    """Return an aligned reference-vs-main delta trace.

    Reference is interpolated onto the main trace X grid over only the common
    range. Units are converted when they are dimensionally compatible.
    """
    ref_channel = reference_channel or matching_reference_channel(main, reference, main_channel)
    if not ref_channel:
        raise ValueError(f"No matching reference channel for {main_channel!r}.")

    mx, my = channel_xy(main, main_channel, x_mode, main_alignment_s)
    rx, ry = channel_xy(reference, ref_channel, x_mode, reference_alignment_s)
    mp = prepare_plot_series(mx, my, max_points=max_points)
    rp = prepare_plot_series(rx, ry, max_points=max_points)
    if mp.output_points < 2 or rp.output_points < 2:
        raise ValueError("Main/reference channel does not contain enough drawable samples.")

    main_unit = normalize_unit(main.units.get(main_channel, ""))
    ref_unit = normalize_unit(reference.units.get(ref_channel, ""))
    if main_unit and ref_unit and main_unit != ref_unit:
        if not compatible(main_unit, ref_unit):
            raise ValueError(
                f"Cannot compare {main_channel} [{main_unit}] with {ref_channel} [{ref_unit}]: incompatible dimensions."
            )
        ry2 = np.asarray(convert_value(rp.y, ref_unit, main_unit), dtype=float)
    else:
        ry2 = rp.y
    unit = main_unit or ref_unit

    lo = max(float(mp.x[0]), float(rp.x[0]))
    hi = min(float(mp.x[-1]), float(rp.x[-1]))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        raise ValueError("Main and reference traces do not overlap on the selected X axis.")
    keep = (mp.x >= lo) & (mp.x <= hi)
    x = mp.x[keep]
    main_y = mp.y[keep]
    if len(x) < 2:
        raise ValueError("Main/reference overlap contains fewer than two samples.")
    ref_y = np.interp(x, rp.x, ry2)
    key = str(sign).strip().lower()
    if key in {"main-reference", "main-ref", "main_minus_reference", "main-reference"}:
        delta = main_y - ref_y
    else:
        delta = ref_y - main_y
    return DeltaSeries(x, delta, main_y, ref_y, unit, str(main_channel), str(ref_channel), (lo, hi))


def delta_statistics(series: DeltaSeries) -> dict:
    d=np.asarray(series.delta,dtype=float)
    good=d[np.isfinite(d)]
    if not len(good):
        return {"count":0,"mean":np.nan,"median":np.nan,"min":np.nan,"max":np.nan,"rms":np.nan,"max_abs":np.nan}
    return {
        "count":int(len(good)),
        "mean":float(np.mean(good)),
        "median":float(np.median(good)),
        "min":float(np.min(good)),
        "max":float(np.max(good)),
        "rms":float(np.sqrt(np.mean(good**2))),
        "max_abs":float(np.max(np.abs(good))),
    }
