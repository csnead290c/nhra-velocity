from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .importers import load_telemetry
from .telemetry import detect_drag_pass_window


def numeric_channels(run) -> List[str]:
    out: List[str] = []
    for c in run.data.columns:
        s = pd.to_numeric(run.data[c], errors="coerce")
        if s.notna().sum() >= max(5, int(0.25 * len(run.data))):
            out.append(str(c))
    return out


def _smooth(series: pd.Series, samples: int) -> pd.Series:
    if samples <= 1:
        return series
    return series.rolling(samples, center=True, min_periods=1).mean()


def analysis_frame(run, pass_only: bool = False) -> pd.DataFrame:
    df = run.data.copy()
    cmap = run.channel_map
    time_col = cmap.get("time_s")
    if time_col is None or time_col not in df.columns:
        raise ValueError("A usable time channel is required for the viewer.")
    t = pd.to_numeric(df[time_col], errors="coerce")
    launch = detect_drag_pass_window(run).launch_time_s
    df["__time_from_launch_s"] = t - launch

    # Speed canonical copy and derived distance.
    speed_col = cmap.get("speed_mph")
    if speed_col and speed_col in df.columns:
        speed = pd.to_numeric(df[speed_col], errors="coerce").interpolate(limit_direction="both")
        df["__speed_mph"] = speed
        sec = pd.to_numeric(df["__time_from_launch_s"], errors="coerce")
        vfts = speed * 5280.0 / 3600.0
        dt = sec.diff().clip(lower=0).fillna(0)
        avg_v = (vfts + vfts.shift(1).fillna(vfts)) * 0.5
        dist = (avg_v * dt).cumsum()
        # Keep pre-launch at negative/zero distance for context.
        dist = dist - float(dist.loc[sec.ge(0).idxmax()]) if sec.ge(0).any() else dist
        df["__distance_ft"] = dist
        if "longitudinal_g" not in cmap:
            v = speed * 1.4666666667
            accel = v.diff() / sec.diff().replace(0, np.nan) / 32.174
            df["__derived_accel_g"] = accel

    if pass_only:
        window = detect_drag_pass_window(run)
        t_abs = pd.to_numeric(df[time_col], errors="coerce")
        # Include a little staging and shutdown context.
        lo = window.launch_time_s - 0.75
        hi = window.end_time_s + 0.75
        df = df[(t_abs >= lo) & (t_abs <= hi)].copy()
    return df.reset_index(drop=True)


def channel_catalog(run) -> pd.DataFrame:
    rows = []
    inverse = {v: k for k, v in run.channel_map.items()}
    for c in numeric_channels(run):
        s = pd.to_numeric(run.data[c], errors="coerce")
        rows.append({
            "Channel": c,
            "Canonical role": inverse.get(c, ""),
            "Unit": run.units.get(c, ""),
            "Samples": int(s.notna().sum()),
            "Min": float(s.min()) if s.notna().any() else np.nan,
            "Max": float(s.max()) if s.notna().any() else np.nan,
            "Mean": float(s.mean()) if s.notna().any() else np.nan,
            "Hz (approx)": _sample_rate(run, c),
        })
    # Derived viewer channels are intentionally explicit.
    if run.channel_map.get("speed_mph"):
        rows += [
            {"Channel": "__time_from_launch_s", "Canonical role": "viewer", "Unit": "s", "Samples": len(run.data), "Min": np.nan, "Max": np.nan, "Mean": np.nan, "Hz (approx)": np.nan},
            {"Channel": "__distance_ft", "Canonical role": "viewer", "Unit": "ft", "Samples": len(run.data), "Min": np.nan, "Max": np.nan, "Mean": np.nan, "Hz (approx)": np.nan},
        ]
    return pd.DataFrame(rows)


def _sample_rate(run, channel: str) -> float:
    tcol = run.channel_map.get("time_s")
    if not tcol or tcol not in run.data.columns:
        return np.nan
    t = pd.to_numeric(run.data[tcol], errors="coerce")
    y = pd.to_numeric(run.data[channel], errors="coerce") if channel in run.data.columns else pd.Series(dtype=float)
    mask = t.notna() & y.notna()
    if mask.sum() < 4:
        return np.nan
    dt = t[mask].diff().dropna()
    med = float(dt[dt > 0].median()) if (dt > 0).any() else np.nan
    return round(1.0 / med, 2) if med and np.isfinite(med) else np.nan


def plot_channels(
    run,
    channels: Sequence[str],
    x_mode: str = "Time from launch",
    pass_only: bool = True,
    smoothing_ms: float = 0.0,
    normalize: bool = False,
    separate_axes: bool = True,
) -> Tuple[go.Figure, pd.DataFrame, pd.DataFrame]:
    df = analysis_frame(run, pass_only=pass_only)
    channels = [c for c in channels if c in df.columns]
    if not channels:
        # Useful defaults.
        for canonical in ["engine_rpm", "driveshaft_rpm", "speed_mph", "longitudinal_g", "throttle_pct"]:
            c = run.channel_map.get(canonical)
            if c and c in df.columns and c not in channels:
                channels.append(c)
        channels = channels[:5]
    if not channels:
        raise ValueError("No numeric channels are available to plot.")

    if x_mode.startswith("Distance"):
        if "__distance_ft" not in df.columns:
            raise ValueError("Distance axis requires a speed channel.")
        x = pd.to_numeric(df["__distance_ft"], errors="coerce")
        x_title = "Distance from launch (ft)"
    elif x_mode.startswith("Logger"):
        x = pd.to_numeric(df[run.channel_map["time_s"]], errors="coerce")
        x_title = "Logger time (s)"
    else:
        x = pd.to_numeric(df["__time_from_launch_s"], errors="coerce")
        x_title = "Time from launch (s)"

    # Determine smoothing samples from median time step.
    t = pd.to_numeric(df[run.channel_map["time_s"]], errors="coerce")
    dt = t.diff().dropna()
    med_dt = float(dt[dt > 0].median()) if (dt > 0).any() else 0.02
    smooth_n = max(1, int(round((float(smoothing_ms) / 1000.0) / max(med_dt, 1e-6))))

    fig = go.Figure()
    stats = []
    sample = pd.DataFrame({"X": x})
    for idx, c in enumerate(channels):
        y = pd.to_numeric(df[c], errors="coerce")
        y = _smooth(y, smooth_n)
        unit = run.units.get(c, "")
        if normalize:
            lo, hi = float(y.min()), float(y.max())
            y_plot = (y - lo) / (hi - lo) if np.isfinite(hi-lo) and abs(hi-lo) > 1e-12 else y * 0
            trace_name = f"{c} (normalized)"
        else:
            y_plot = y
            trace_name = c + (f" [{unit}]" if unit else "")
        axis = "y" if (not separate_axes or normalize or idx == 0) else f"y{idx+1}"
        fig.add_trace(go.Scattergl(x=x, y=y_plot, mode="lines", name=trace_name, yaxis=axis, connectgaps=False))
        if separate_axes and not normalize and idx > 0:
            side = "right" if idx % 2 else "left"
            position = max(0.03, min(0.97, 1.0 - 0.045 * ((idx+1)//2))) if side == "right" else min(0.97, 0.045 * (idx//2))
            fig.update_layout(**{f"yaxis{idx+1}": dict(title=trace_name, overlaying="y", side=side, position=position, showgrid=False)})
        stats.append({
            "Channel": c, "Unit": unit, "Min": float(y.min()), "Max": float(y.max()),
            "Mean": float(y.mean()), "Std Dev": float(y.std()), "Range": float(y.max()-y.min()),
        })
        sample[c] = y

    fig.update_layout(
        height=650,
        hovermode="x unified",
        title=f"{Path(run.name).name} — synchronized channel view",
        xaxis=dict(title=x_title, rangeslider=dict(visible=True, thickness=0.06)),
        yaxis=dict(title=" / ".join(channels[:1]) if not normalize else "Normalized value"),
        legend=dict(orientation="h", y=1.08),
        margin=dict(l=70, r=90, t=90, b=80),
    )
    sample = sample.iloc[np.linspace(0, len(sample)-1, min(250, len(sample))).astype(int)] if len(sample) else sample
    return fig, pd.DataFrame(stats), sample.reset_index(drop=True)


def overlay_channel(
    runs: Sequence[Any],
    canonical: str,
    x_mode: str = "Time from launch",
    pass_only: bool = True,
) -> go.Figure:
    fig = go.Figure()
    for run in runs:
        c = run.channel_map.get(canonical)
        if not c or c not in run.data.columns:
            continue
        df = analysis_frame(run, pass_only=pass_only)
        if x_mode.startswith("Distance") and "__distance_ft" in df.columns:
            x = df["__distance_ft"]
            x_title = "Distance from launch (ft)"
        else:
            x = df["__time_from_launch_s"]
            x_title = "Time from launch (s)"
        fig.add_trace(go.Scattergl(x=x, y=pd.to_numeric(df[c], errors="coerce"), mode="lines", name=Path(run.name).name))
    fig.update_layout(height=580, title=f"Run overlay — {canonical}", xaxis_title=x_title, hovermode="x unified", legend=dict(orientation="h"))
    return fig


def add_math_channel(df: pd.DataFrame, name: str, expression: str) -> Tuple[pd.DataFrame, Optional[str]]:
    """Add a temporary math channel using pandas expression syntax.

    Existing column names containing spaces may be wrapped in backticks, e.g.
    `ENGINE RPM` - `DRIVE SHAFT` * 4.86.
    """
    if not expression or not str(expression).strip():
        return df, None
    out = df.copy()
    cname = (name or "Math Channel").strip()
    try:
        out[cname] = out.eval(str(expression), engine="python")
    except Exception as exc:
        raise ValueError(f"Math expression failed: {exc}") from exc
    return out, cname


def ab_delta_table(
    run,
    channels: Sequence[str],
    x_mode: str,
    x_a: float,
    x_b: float,
    pass_only: bool = True,
) -> pd.DataFrame:
    df = analysis_frame(run, pass_only=pass_only)
    if x_mode.startswith("Distance"):
        if "__distance_ft" not in df.columns:
            raise ValueError("Distance cursor mode requires a speed channel.")
        x = pd.to_numeric(df["__distance_ft"], errors="coerce")
    elif x_mode.startswith("Logger"):
        x = pd.to_numeric(df[run.channel_map["time_s"]], errors="coerce")
    else:
        x = pd.to_numeric(df["__time_from_launch_s"], errors="coerce")
    order = np.argsort(x.to_numpy(dtype=float))
    xv = x.to_numpy(dtype=float)[order]
    rows = []
    for c in channels:
        if c not in df.columns:
            continue
        y = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)[order]
        mask = np.isfinite(xv) & np.isfinite(y)
        if mask.sum() < 2:
            continue
        xa, xb = float(x_a), float(x_b)
        ya = float(np.interp(xa, xv[mask], y[mask]))
        yb = float(np.interp(xb, xv[mask], y[mask]))
        dx = xb - xa
        rows.append({
            "Channel": c,
            "Unit": run.units.get(c, ""),
            "A": ya,
            "B": yb,
            "Δ": yb - ya,
            "ΔX": dx,
            "Δ/ΔX": (yb - ya) / dx if abs(dx) > 1e-12 else np.nan,
        })
    return pd.DataFrame(rows)


def xy_plot(run, x_channel: str, y_channels: Sequence[str], pass_only: bool = True, color_by_time: bool = True) -> go.Figure:
    df = analysis_frame(run, pass_only=pass_only)
    if x_channel not in df.columns:
        raise ValueError("Choose a valid X channel.")
    x = pd.to_numeric(df[x_channel], errors="coerce")
    t = pd.to_numeric(df["__time_from_launch_s"], errors="coerce")
    fig = go.Figure()
    for c in y_channels:
        if c not in df.columns:
            continue
        y = pd.to_numeric(df[c], errors="coerce")
        mask = x.notna() & y.notna()
        marker = dict(size=5, opacity=0.65)
        if color_by_time:
            marker.update(color=t[mask], colorscale="Viridis", showscale=(len(fig.data)==0), colorbar=dict(title="Time s"))
        fig.add_trace(go.Scattergl(x=x[mask], y=y[mask], mode="markers", name=c, marker=marker))
    fig.update_layout(height=580, title="XY / correlation view", xaxis_title=x_channel, yaxis_title="Selected Y channels", hovermode="closest", legend=dict(orientation="h"))
    return fig
