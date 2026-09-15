from __future__ import annotations

"""Format-neutral waveform data extraction.

Qt widgets should be rendering clients, not the authority on telemetry clocks.
Keeping X/Y extraction here lets the import and plotting contract be tested in
headless CI using the same code the desktop waveform calls.
"""

from typing import Tuple

import numpy as np
import pandas as pd

from .models import TelemetryRun
from .telemetry import detect_drag_pass_window


from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class PreparedSeries:
    x: np.ndarray
    y: np.ndarray
    input_points: int
    finite_points: int
    output_points: int
    monotonic_repair: bool = False
    decimated: bool = False
    warning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_points": self.input_points,
            "finite_points": self.finite_points,
            "output_points": self.output_points,
            "monotonic_repair": self.monotonic_repair,
            "decimated": self.decimated,
            "warning": self.warning,
        }


def _longest_strictly_increasing_segment(x: np.ndarray, y: np.ndarray):
    """Return the longest contiguous segment with strictly increasing X.

    pyqtgraph's clipping/downsampling logic assumes ordered X values. Vendor
    logs occasionally contain duplicate timestamps or a clock reset. Rather
    than letting one bad sample make the entire trace disappear, retain the
    longest physically ordered segment and report that repair to diagnostics.
    """
    if len(x) < 2:
        return x, y, False
    good_step = np.diff(x) > 0
    if bool(np.all(good_step)):
        return x, y, False
    # boundaries are indexes where a new segment starts
    starts=[0]
    for i, ok in enumerate(good_step, start=1):
        if not ok:
            starts.append(i)
    starts.append(len(x))
    best=(0,0)
    for a,b in zip(starts[:-1],starts[1:]):
        if b-a > best[1]-best[0]:
            best=(a,b)
    a,b=best
    return x[a:b], y[a:b], True


def _minmax_decimate(x: np.ndarray, y: np.ndarray, max_points: int):
    """Peak-preserving index-bucket decimation for waveform rendering.

    Keeping min/max samples per bucket preserves narrow spikes much better
    than taking every Nth point, which matters for ignition, shift, pressure
    and acceleration events.
    """
    n=len(x)
    max_points=max(16,int(max_points))
    if n <= max_points:
        return x,y,False
    buckets=max(1,max_points//2)
    edges=np.linspace(0,n,buckets+1,dtype=int)
    idx=[]
    for a,b in zip(edges[:-1],edges[1:]):
        if b<=a:
            continue
        seg=y[a:b]
        if not len(seg):
            continue
        imin=a+int(np.nanargmin(seg)); imax=a+int(np.nanargmax(seg))
        if imin<=imax:
            idx.extend([imin,imax] if imin!=imax else [imin])
        else:
            idx.extend([imax,imin])
    if not idx:
        return x[:max_points],y[:max_points],True
    ii=np.asarray(sorted(set(idx)),dtype=int)
    if len(ii)>max_points:
        ii=ii[:max_points]
    return x[ii],y[ii],True


def prepare_plot_series(x, y, max_points: Optional[int] = 50000) -> PreparedSeries:
    """Sanitize X/Y for a time/distance waveform without mutating raw data."""
    xx=np.asarray(x,dtype=float).reshape(-1)
    yy=np.asarray(y,dtype=float).reshape(-1)
    n=min(len(xx),len(yy)); xx=xx[:n]; yy=yy[:n]
    mask=np.isfinite(xx)&np.isfinite(yy)
    xx=xx[mask]; yy=yy[mask]
    finite=len(xx)
    warning=""
    if finite<2:
        return PreparedSeries(xx,yy,n,finite,finite,warning="fewer than two finite X/Y samples")
    xx,yy,repaired=_longest_strictly_increasing_segment(xx,yy)
    if repaired:
        warning="non-monotonic or duplicate X values; longest increasing segment retained for display"
    dec=False
    if max_points is not None and len(xx)>int(max_points):
        xx,yy,dec=_minmax_decimate(xx,yy,int(max_points))
    return PreparedSeries(xx,yy,n,finite,len(xx),repaired,dec,warning)


def _rectangular_time(run: TelemetryRun, n: int) -> Tuple[np.ndarray, bool]:
    tc = run.channel_map.get("time_s")
    if tc and tc in run.data.columns:
        t = pd.to_numeric(run.data[tc], errors="coerce").to_numpy(float)
        if len(t) == n and np.isfinite(t).sum() >= 2:
            finite = t[np.isfinite(t)]
            if len(finite) >= 2 and np.any(np.diff(finite) > 0):
                return t, True
    return np.arange(n, dtype=float), False


def channel_xy(
    run: TelemetryRun,
    channel: str,
    x_mode: str = "Time from Launch",
    alignment_s: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return plot-ready x/y arrays for one source channel.

    A channel remains viewable even if semantic time mapping failed: rectangular
    data falls back to sample index, while native-rate channels always retain
    their logger clock.  Physics can still refuse missing/unsafe time separately.
    """
    native = channel in run.native_channels
    if native:
        ch = run.native_channels[channel]
        t = np.asarray(ch.time_s, dtype=float)
        y = np.asarray(ch.values, dtype=float)
        n = min(len(t), len(y))
        t, y = t[:n], y[:n]
        valid_time = np.isfinite(t).sum() >= 2
    elif channel in run.data.columns:
        y = pd.to_numeric(run.data[channel], errors="coerce").to_numpy(float)
        t, valid_time = _rectangular_time(run, len(y))
    else:
        return np.array([], dtype=float), np.array([], dtype=float)

    mode = str(x_mode or "Time from Launch").strip().lower()
    if mode.startswith("sample"):
        return np.arange(len(y), dtype=float), y
    if mode.startswith("logger"):
        return t, y
    if not valid_time:
        return np.arange(len(y), dtype=float), y

    try:
        launch = float(detect_drag_pass_window(run).launch_time_s)
    except Exception:
        finite = t[np.isfinite(t)]
        launch = float(finite[0]) if len(finite) else 0.0

    if mode.startswith("time"):
        return t - launch + float(alignment_s), y

    if mode.startswith("normalized"):
        # Display-only normalization.  Physical Run time remains untouched.
        finish = run.timing.quarter_mile_s
        if finish is None or not np.isfinite(float(finish)) or float(finish) <= 0:
            try:
                window = detect_drag_pass_window(run)
                finish = float(window.end_time_s - window.launch_time_s)
            except Exception:
                finish = None
        if finish is None or float(finish) <= 0:
            return t - launch + float(alignment_s), y
        return ((t - launch) / float(finish)) * 100.0 + float(alignment_s), y

    if mode.startswith("distance"):
        tc = run.channel_map.get("time_s")
        sc = run.channel_map.get("speed_mph")
        if not tc or not sc or tc not in run.data.columns or sc not in run.data.columns:
            return t - launch + float(alignment_s), y
        bt = pd.to_numeric(run.data[tc], errors="coerce").to_numpy(float)
        sp = pd.to_numeric(run.data[sc], errors="coerce").to_numpy(float)
        good = np.isfinite(bt) & np.isfinite(sp)
        if good.sum() < 3:
            return t - launch + float(alignment_s), y
        bt, sp = bt[good], sp[good]
        order = np.argsort(bt); bt, sp = bt[order], sp[order]
        keep = np.r_[True, np.diff(bt) > 0]
        bt, sp = bt[keep], sp[keep]
        if len(bt) < 3:
            return t - launch + float(alignment_s), y
        dt = np.diff(bt, prepend=bt[0]); dt[0] = 0.0
        dist = np.cumsum(np.maximum(sp, 0.0) * 1.4666666666667 * np.maximum(dt, 0.0))
        launch_dist = float(np.interp(launch, bt, dist))
        x = np.interp(t, bt, dist, left=np.nan, right=np.nan) - launch_dist
        return x, y

    return t - launch + float(alignment_s), y


def validate_default_waveform(run: TelemetryRun, channels) -> dict:
    """Headless contract used by CI: default traces must yield drawable X/Y pairs."""
    results = {}
    for channel in channels:
        x, y = channel_xy(run, channel, "Time from Launch")
        prepared = prepare_plot_series(x, y, max_points=50000)
        results[str(channel)] = int(prepared.output_points)
    return results
