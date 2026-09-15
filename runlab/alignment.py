from __future__ import annotations

"""Run-to-run alignment helpers for telemetry overlays.

The display layer stores a simple time offset per compare session.  This module
estimates that offset from common, physically meaningful channels without
modifying source telemetry.  The algorithm is intentionally conservative:
launch detection provides the initial zero, then a bounded correlation search
looks for the small residual offset that best aligns transient structure.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from .models import TelemetryRun
from .telemetry import detect_drag_pass_window


@dataclass
class AlignmentResult:
    offset_s: float
    score: float
    canonical: str
    method: str
    samples: int


_PRIORITY = (
    "longitudinal_g",
    "driveshaft_rpm",
    "engine_rpm",
    "speed_mph",
    "throttle_pct",
)


def _canonical_series(run: TelemetryRun, canonical: str) -> Tuple[np.ndarray, np.ndarray]:
    tc = run.channel_map.get("time_s")
    yc = run.channel_map.get(canonical)
    if not tc or not yc or tc not in run.data.columns or yc not in run.data.columns:
        return np.array([], dtype=float), np.array([], dtype=float)
    t = pd.to_numeric(run.data[tc], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(run.data[yc], errors="coerce").to_numpy(dtype=float)
    good = np.isfinite(t) & np.isfinite(y)
    if good.sum() < 8:
        return np.array([], dtype=float), np.array([], dtype=float)
    t, y = t[good], y[good]
    order = np.argsort(t)
    t, y = t[order], y[order]
    # Duplicate timestamps are troublesome for interpolation.  Keep first.
    unique = np.r_[True, np.diff(t) > 0]
    return t[unique], y[unique]


def _launch_time(run: TelemetryRun, t: np.ndarray) -> float:
    try:
        return float(detect_drag_pass_window(run).launch_time_s)
    except Exception:
        return float(t[0]) if len(t) else 0.0


def _feature(y: np.ndarray, canonical: str) -> np.ndarray:
    """Create a scale-insensitive alignment feature.

    Monotonic speed/RPM traces correlate too well across a broad range of lags,
    so their first derivative is blended with the standardized raw trace.  G and
    throttle already contain useful transient structure and are used directly.
    """
    y = np.asarray(y, dtype=float)
    if len(y) < 3:
        return y
    med = float(np.nanmedian(y))
    mad = float(np.nanmedian(np.abs(y - med)))
    scale = mad * 1.4826
    if not np.isfinite(scale) or scale < 1e-12:
        scale = float(np.nanstd(y))
    if not np.isfinite(scale) or scale < 1e-12:
        scale = 1.0
    z = (y - med) / scale
    if canonical in ("engine_rpm", "driveshaft_rpm", "speed_mph"):
        dz = np.gradient(z)
        dscale = float(np.nanstd(dz))
        if np.isfinite(dscale) and dscale > 1e-12:
            dz = dz / dscale
            z = 0.35 * z + 0.65 * dz
    # Limit isolated spikes so one bad pulse cannot dominate the alignment.
    return np.clip(z, -8.0, 8.0)


def _score_pair(a: np.ndarray, b: np.ndarray) -> float:
    good = np.isfinite(a) & np.isfinite(b)
    if good.sum() < 20:
        return -np.inf
    aa, bb = a[good], b[good]
    aa = aa - np.mean(aa); bb = bb - np.mean(bb)
    sa = float(np.linalg.norm(aa)); sb = float(np.linalg.norm(bb))
    if sa < 1e-12 or sb < 1e-12:
        return -np.inf
    return float(np.dot(aa, bb) / (sa * sb))


def estimate_time_alignment(
    main: TelemetryRun,
    compare: TelemetryRun,
    *,
    max_offset_s: float = 1.0,
    search_step_s: Optional[float] = None,
    window_s: float = 8.0,
) -> AlignmentResult:
    """Estimate display offset for ``compare`` relative to ``main``.

    The returned offset follows the desktop convention: compare X coordinates
    are displayed as ``time_from_launch + offset_s``.  Positive values move the
    compare trace to the right.
    """
    best_common = None
    for canonical in _PRIORITY:
        ta, ya = _canonical_series(main, canonical)
        tb, yb = _canonical_series(compare, canonical)
        if len(ta) >= 20 and len(tb) >= 20:
            best_common = (canonical, ta, ya, tb, yb)
            break
    if best_common is None:
        raise ValueError("No common mapped channel is suitable for automatic alignment.")

    canonical, ta, ya, tb, yb = best_common
    ta = ta - _launch_time(main, ta)
    tb = tb - _launch_time(compare, tb)

    # Determine a resampling interval that respects the slower source and keeps
    # the search lightweight.  Never claim sub-millisecond precision from a
    # 20/50/100 Hz logger channel.
    def dt_of(t):
        d = np.diff(t)
        d = d[np.isfinite(d) & (d > 0)]
        return float(np.median(d)) if len(d) else 0.01
    dt = max(dt_of(ta), dt_of(tb), 0.001)
    if search_step_s is None:
        search_step_s = max(0.001, min(dt / 2.0, 0.02))

    lo = max(float(np.nanmin(ta)), float(np.nanmin(tb)) - max_offset_s, -0.25)
    hi = min(float(np.nanmax(ta)), float(np.nanmax(tb)) + max_offset_s, window_s)
    if hi - lo < max(0.5, 20 * dt):
        raise ValueError("The common pass window is too short for automatic alignment.")
    grid = np.arange(lo, hi + dt * 0.25, dt)
    if len(grid) < 20:
        raise ValueError("Too few common samples for automatic alignment.")

    # Main trace is fixed. For candidate display offset o, compare's raw
    # launch-relative signal is sampled at grid-o because it is drawn at t+o.
    main_i = np.interp(grid, ta, ya, left=np.nan, right=np.nan)
    main_f = _feature(main_i, canonical)
    offsets = np.arange(-abs(max_offset_s), abs(max_offset_s) + search_step_s * 0.25, search_step_s)
    best_score = -np.inf
    best_offset = 0.0
    best_n = 0
    for off in offsets:
        comp_i = np.interp(grid - off, tb, yb, left=np.nan, right=np.nan)
        comp_f = _feature(comp_i, canonical)
        score = _score_pair(main_f, comp_f)
        if score > best_score:
            best_score = score
            best_offset = float(off)
            best_n = int(np.sum(np.isfinite(main_f) & np.isfinite(comp_f)))

    if not np.isfinite(best_score):
        raise ValueError("Automatic alignment could not find a stable correlation peak.")
    return AlignmentResult(
        offset_s=best_offset,
        score=best_score,
        canonical=canonical,
        method="bounded launch-relative correlation",
        samples=best_n,
    )
