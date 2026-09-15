from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .models import TelemetryRun


@dataclass
class PassWindow:
    launch_index: int
    start_index: int
    end_index: int
    launch_time_s: float
    start_time_s: float
    end_time_s: float
    peak_index: int
    peak_time_s: float
    peak_speed_mph: Optional[float]
    method: str
    confidence: str


def _finite_series(run: TelemetryRun, canonical: str) -> Optional[np.ndarray]:
    col = run.channel_map.get(canonical)
    if not col or col not in run.data.columns:
        return None
    return pd.to_numeric(run.data[col], errors="coerce").to_numpy(float)


def _segments(mask: np.ndarray, max_gap: int = 0):
    mask = np.asarray(mask, dtype=bool).copy()
    if max_gap > 0 and mask.any():
        # Close short False gaps inside a True excursion.
        false = ~mask
        starts = np.flatnonzero(false & np.r_[True, mask[:-1]])
        ends = np.flatnonzero(false & np.r_[mask[1:], True])
        for s, e in zip(starts, ends):
            if s > 0 and e + 1 < len(mask) and (e - s + 1) <= max_gap:
                mask[s : e + 1] = True
    x = np.r_[False, mask, False].astype(int)
    d = np.diff(x)
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1) - 1
    return list(zip(starts.tolist(), ends.tolist()))


def detect_drag_pass_window(
    run: TelemetryRun,
    *,
    movement_mph: float = 3.0,
    pre_roll_s: float = 0.50,
    post_peak_s: float = 2.0,
) -> PassWindow:
    """Find the most likely drag-racing pass inside a longer logger recording.

    Primary signal is vehicle speed.  The algorithm deliberately chooses the
    excursion that reaches the highest speed instead of the first threshold
    crossing, then backtracks to the last near-stationary sample.  Driveshaft
    speed and throttle are conservative fallbacks for logs with no speed channel.
    """
    t = _finite_series(run, "time_s")
    if t is None or len(t) == 0 or not np.isfinite(t).any():
        t = np.arange(len(run.data), dtype=float)
    n = len(t)
    if n == 0:
        return PassWindow(0, 0, 0, 0.0, 0.0, 0.0, 0, 0.0, None, "empty", "Low")

    # Estimate sample period for gap closing / pre-roll.
    good_t = t[np.isfinite(t)]
    dt = float(np.nanmedian(np.diff(good_t))) if len(good_t) > 2 else 0.05
    if not np.isfinite(dt) or dt <= 0:
        dt = 0.05
    gap_samples = max(1, int(round(0.25 / dt)))
    pre_samples = max(0, int(round(pre_roll_s / dt)))
    post_samples = max(1, int(round(post_peak_s / dt)))

    speed = _finite_series(run, "speed_mph")
    if speed is not None and np.isfinite(speed).sum() >= 5:
        # A modest rolling/staging artifact should not beat a real pass.  Choose
        # the segment with the greatest peak speed, with duration as a tie-breaker.
        mask = np.isfinite(speed) & (speed > movement_mph)
        segs = _segments(mask, max_gap=gap_samples)
        if segs:
            scored = []
            for s, e in segs:
                vals = speed[s : e + 1]
                peak = float(np.nanmax(vals)) if np.isfinite(vals).any() else -np.inf
                scored.append((peak, e - s + 1, s, e))
            _, _, s, e = max(scored)
            peak_rel = int(np.nanargmax(speed[s : e + 1]))
            peak_idx = s + peak_rel

            # Backtrack from the movement threshold to the last truly stationary
            # sample.  Limit the search so an old unrelated stop does not steal zero.
            search_back = max(pre_samples, int(round(3.0 / dt)))
            lo = max(0, s - search_back)
            near_zero = np.flatnonzero(np.isfinite(speed[lo : s + 1]) & (speed[lo : s + 1] <= 1.0))
            launch = lo + int(near_zero[-1]) if len(near_zero) else s
            launch = min(launch, s)
            start = max(0, launch - pre_samples)
            end = min(n - 1, max(e, peak_idx + post_samples))
            peak_speed = float(speed[peak_idx]) if np.isfinite(speed[peak_idx]) else None
            confidence = "High" if (peak_speed or 0) >= 50 else "Medium"
            return PassWindow(
                launch, start, end,
                float(t[launch]), float(t[start]), float(t[end]),
                peak_idx, float(t[peak_idx]), peak_speed,
                "vehicle speed excursion", confidence,
            )

    # Driveshaft fallback.  Select the excursion with the largest RPM peak.
    ds = _finite_series(run, "driveshaft_rpm")
    if ds is not None and np.isfinite(ds).sum() >= 5:
        mask = np.isfinite(ds) & (np.abs(ds) > 150.0)
        segs = _segments(mask, max_gap=gap_samples)
        if segs:
            scored = [(float(np.nanmax(np.abs(ds[s : e + 1]))), e - s + 1, s, e) for s, e in segs]
            _, _, s, e = max(scored)
            peak_idx = s + int(np.nanargmax(np.abs(ds[s : e + 1])))
            search_back = max(pre_samples, int(round(3.0 / dt)))
            lo = max(0, s - search_back)
            stationary = np.flatnonzero(np.isfinite(ds[lo : s + 1]) & (np.abs(ds[lo : s + 1]) <= 50.0))
            launch = lo + int(stationary[-1]) if len(stationary) else s
            start = max(0, launch - pre_samples)
            end = min(n - 1, max(e, peak_idx + post_samples))
            return PassWindow(
                launch, start, end,
                float(t[launch]), float(t[start]), float(t[end]),
                peak_idx, float(t[peak_idx]), None,
                "driveshaft RPM excursion", "Medium",
            )

    throttle = _finite_series(run, "throttle_pct")
    if throttle is not None and np.isfinite(throttle).sum() >= 5:
        mask = np.isfinite(throttle) & (throttle > 85.0)
        segs = _segments(mask, max_gap=gap_samples)
        if segs:
            s, e = max(segs, key=lambda p: p[1] - p[0])
            launch = s
            start = max(0, launch - pre_samples)
            peak_idx = e
            end = min(n - 1, e + post_samples)
            return PassWindow(
                launch, start, end,
                float(t[launch]), float(t[start]), float(t[end]),
                peak_idx, float(t[peak_idx]), None,
                "wide-open-throttle excursion", "Low",
            )

    first = int(np.flatnonzero(np.isfinite(t))[0]) if np.isfinite(t).any() else 0
    last = int(np.flatnonzero(np.isfinite(t))[-1]) if np.isfinite(t).any() else n - 1
    return PassWindow(
        first, first, last,
        float(t[first]), float(t[first]), float(t[last]),
        first, float(t[first]), None,
        "full recording fallback", "Low",
    )
