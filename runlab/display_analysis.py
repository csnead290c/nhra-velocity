from __future__ import annotations

"""Headless analysis primitives for rich workstation displays.

The desktop widgets are clients of these functions.  Keeping paired-channel
alignment, regressions, distributions and cursor sampling outside Qt lets the
same behavior support reports, automation and future live telemetry.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .display_data import channel_xy, prepare_plot_series
from .models import TelemetryRun
from .workstation import evaluate_gate, resolve_channel


@dataclass(frozen=True)
class PairedChannelData:
    time_s: np.ndarray
    x: np.ndarray
    y: np.ndarray
    z: Optional[np.ndarray] = None
    points: int = 0
    aligned: bool = False
    gate_expression: str = ""


@dataclass(frozen=True)
class RegressionResult:
    slope: float
    intercept: float
    r_squared: float
    correlation: float
    count: int
    x_min: float
    x_max: float

    def predict(self, x):
        xx = np.asarray(x, dtype=float)
        return self.slope * xx + self.intercept


@dataclass(frozen=True)
class DistributionResult:
    centers: np.ndarray
    values: np.ndarray
    edges: np.ndarray
    counts: np.ndarray
    source_points: int
    used_points: int
    mode: str
    cumulative: bool
    total_time_s: float


@dataclass(frozen=True)
class ChannelSnapshot:
    channel: str
    x: float
    value: float
    unit: str
    in_range: bool


def _logger_series(run: TelemetryRun, channel: str):
    actual = resolve_channel(run, channel) or channel
    t, y = channel_xy(run, actual, "Logger Time", 0.0)
    prepared = prepare_plot_series(t, y, max_points=None)
    return actual, np.asarray(prepared.x, float), np.asarray(prepared.y, float)


def _rectangular_gate_pair(run: TelemetryRun, channels: list[str], gate_expression: str):
    actual = [resolve_channel(run, ch) or ch for ch in channels]
    if not all(ch in run.data.columns for ch in actual):
        raise ValueError("A gated multi-channel display requires channels on the rectangular analysis table; native mixed-rate channels must be explicitly normalized first.")
    tc = run.channel_map.get("time_s")
    if not tc or tc not in run.data.columns:
        raise ValueError("A gated multi-channel display requires a validated rectangular time channel.")
    gate = evaluate_gate(run, gate_expression)
    arrays = [pd.to_numeric(run.data[ch], errors="coerce").to_numpy(float) for ch in actual]
    t = pd.to_numeric(run.data[tc], errors="coerce").to_numpy(float)
    n = min([len(t), len(gate), *map(len, arrays)])
    t = t[:n]; gate = gate[:n]; arrays = [a[:n] for a in arrays]
    finite = np.isfinite(t) & gate
    for arr in arrays:
        finite &= np.isfinite(arr)
    return actual, t[finite], [a[finite] for a in arrays]


def paired_channel_data(
    run: TelemetryRun,
    x_channel: str,
    y_channel: str,
    z_channel: str | None = None,
    *,
    gate_expression: str = "",
    max_points: int = 50_000,
) -> PairedChannelData:
    """Return time-aligned X/Y[/Z] values without creating fake precision.

    With no gate, source channels retain their own logger clocks and are aligned
    on the lowest-rate source's timestamps over the overlapping interval.  With
    a gate, all channels must already live on the rectangular analysis grid so
    the boolean condition cannot silently interpolate unrelated clocks.
    """
    requested = [x_channel, y_channel] + ([z_channel] if z_channel else [])
    if gate_expression.strip():
        _actual, t, arrays = _rectangular_gate_pair(run, requested, gate_expression)
        if len(t) > max_points:
            idx = np.linspace(0, len(t) - 1, max_points, dtype=int)
            t = t[idx]; arrays = [a[idx] for a in arrays]
        return PairedChannelData(t, arrays[0], arrays[1], arrays[2] if len(arrays) > 2 else None, len(t), False, gate_expression)

    series = []
    for ch in requested:
        _name, t, y = _logger_series(run, ch)
        if len(t) < 2:
            raise ValueError(f"Channel {ch!r} does not have enough finite samples.")
        series.append((t, y))
    lo = max(float(s[0][0]) for s in series)
    hi = min(float(s[0][-1]) for s in series)
    if not np.isfinite(lo + hi) or hi <= lo:
        raise ValueError("Selected channels do not overlap in logger time.")
    # Use the sparsest source clock as the grid, matching the workstation's
    # existing comparison behavior and avoiding upsampled visual precision.
    base_t = min((s[0] for s in series), key=len)
    grid = base_t[(base_t >= lo) & (base_t <= hi)]
    if len(grid) > max_points:
        idx = np.linspace(0, len(grid) - 1, max_points, dtype=int)
        grid = grid[idx]
    arrays = [np.interp(grid, t, y) for t, y in series]
    finite = np.isfinite(grid)
    for arr in arrays:
        finite &= np.isfinite(arr)
    grid = grid[finite]; arrays = [a[finite] for a in arrays]
    if len(grid) < 2:
        raise ValueError("Selected channels have fewer than two overlapping finite samples.")
    return PairedChannelData(grid, arrays[0], arrays[1], arrays[2] if len(arrays) > 2 else None, len(grid), True, "")


def linear_regression(x, y) -> RegressionResult:
    xx = np.asarray(x, dtype=float).reshape(-1)
    yy = np.asarray(y, dtype=float).reshape(-1)
    n = min(len(xx), len(yy)); xx = xx[:n]; yy = yy[:n]
    good = np.isfinite(xx) & np.isfinite(yy)
    xx = xx[good]; yy = yy[good]
    if len(xx) < 2 or float(np.ptp(xx)) <= 0:
        raise ValueError("Linear regression requires at least two finite points with nonzero X range.")
    slope, intercept = np.polyfit(xx, yy, 1)
    pred = slope * xx + intercept
    ss_res = float(np.sum((yy - pred) ** 2))
    ss_tot = float(np.sum((yy - np.mean(yy)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    corr = float(np.corrcoef(xx, yy)[0, 1]) if len(xx) > 1 and np.std(yy) > 0 else float("nan")
    return RegressionResult(float(slope), float(intercept), float(r2), corr, len(xx), float(np.min(xx)), float(np.max(xx)))


def channel_distribution(
    run: TelemetryRun,
    channel: str,
    *,
    bins: int = 60,
    mode: str = "samples",
    cumulative: bool = False,
    gate_expression: str = "",
) -> DistributionResult:
    """Histogram/distribution with sample- or dwell-time weighting.

    Modes: samples, percent_samples, time, percent_time.
    """
    if bins < 2:
        raise ValueError("Histogram bins must be at least 2.")
    actual = resolve_channel(run, channel) or channel
    m = str(mode or "samples").strip().lower().replace(" ", "_")
    allowed = {"samples", "percent_samples", "time", "percent_time"}
    if m not in allowed:
        raise ValueError(f"Unknown distribution mode {mode!r}.")

    if gate_expression.strip():
        _actual, t, arrays = _rectangular_gate_pair(run, [actual], gate_expression)
        y = arrays[0]
    else:
        _actual, t, y = _logger_series(run, actual)
        good = np.isfinite(t) & np.isfinite(y)
        t = t[good]; y = y[good]
    source_points = len(y)
    if source_points < 2:
        raise ValueError("Distribution requires at least two finite samples.")

    weights = None
    total_time = 0.0
    if m in {"time", "percent_time"}:
        order = np.argsort(t, kind="stable"); t = t[order]; y = y[order]
        keep = np.r_[True, np.diff(t) > 0]; t = t[keep]; y = y[keep]
        if len(t) < 2:
            raise ValueError("Time-weighted distribution requires an increasing timebase.")
        dt = np.diff(t)
        # Each sample owns the interval until the next sample. The final sample
        # has no following dwell interval, so it contributes zero time rather
        # than an invented median interval beyond the recording.
        weights = np.r_[dt, 0.0]
        weights = np.maximum(weights, 0.0)
        total_time = float(t[-1] - t[0])

    counts, edges = np.histogram(y, bins=int(bins))
    if weights is None:
        values = counts.astype(float)
        if m == "percent_samples":
            denom = max(float(np.sum(values)), 1.0)
            values = values / denom * 100.0
    else:
        values, _ = np.histogram(y, bins=edges, weights=weights)
        values = values.astype(float)
        if m == "percent_time":
            denom = max(float(np.sum(values)), 1e-30)
            values = values / denom * 100.0
    if cumulative:
        values = np.cumsum(values)
    centers = (edges[:-1] + edges[1:]) / 2.0
    return DistributionResult(centers, values, edges, counts.astype(float), source_points, len(y), m, bool(cumulative), total_time)


def sample_channel_at(
    run: TelemetryRun,
    channel: str,
    x: float,
    *,
    x_mode: str = "Time from Launch",
    alignment_s: float = 0.0,
) -> ChannelSnapshot:
    actual = resolve_channel(run, channel) or channel
    xx, yy = channel_xy(run, actual, x_mode, alignment_s)
    p = prepare_plot_series(xx, yy, max_points=None)
    if p.output_points < 1:
        return ChannelSnapshot(actual, float(x), float("nan"), str(run.units.get(actual, "")), False)
    lo, hi = float(p.x[0]), float(p.x[-1])
    target = float(x)
    in_range = lo <= target <= hi
    value = float(np.interp(target, p.x, p.y)) if in_range else float("nan")
    return ChannelSnapshot(actual, target, value, str(run.units.get(actual, "")), in_range)
