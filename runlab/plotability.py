from __future__ import annotations

"""Plotability checks and smart default channel selection.

This module deliberately has no Qt dependency.  Importers and tests can prove
that a decoded telemetry run has channels the desktop viewer can actually draw
before the UI reports the file as successfully opened.
"""

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .models import TelemetryRun


DEFAULT_CANONICAL_ORDER = (
    "engine_rpm",
    "driveshaft_rpm",
    "clutch_rpm",
    "speed_mph",
    "longitudinal_g",
    "throttle_pct",
    "gear",
    "power_hp",
    "torque_lbft",
    "boost_psi",
    "lambda",
)


@dataclass
class PlotabilityReport:
    plotable: bool
    numeric_channels: List[str]
    default_channels: List[str]
    timebase: str
    time_channel: Optional[str]
    warnings: List[str]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _finite_count(values) -> int:
    arr = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(float)
    return int(np.isfinite(arr).sum())


def _source_for_accepted_canonical(run: TelemetryRun, canonical: str) -> Optional[str]:
    """Return the human/source channel behind an accepted canonical mapping."""
    if canonical not in run.channel_map:
        return None
    mapped = run.channel_map.get(canonical)
    originals = run.metadata.get("original_channel_map", {}) or {}
    source = originals.get(canonical)
    if source and (source in run.native_channels or source in run.data.columns):
        return str(source)
    if mapped and not str(mapped).startswith("__") and (mapped in run.native_channels or mapped in run.data.columns):
        return str(mapped)
    # Canonical private channels are valid plot sources as a last resort, but
    # the viewer normally prefers the original logger name.
    if mapped and mapped in run.data.columns:
        return str(mapped)
    return None


def numeric_plot_channels(run: TelemetryRun) -> List[str]:
    names: List[str] = []
    # Time/index channels belong on the X axis, not in smart default Y traces.
    # Keep them visible in the parameter browser, but do not let a generic
    # numeric fallback waste a default waveform slot on them.
    excluded=set()
    originals=run.metadata.get("original_channel_map", {}) or {}
    if originals.get("time_s"): excluded.add(str(originals.get("time_s")))
    mapped_time=run.channel_map.get("time_s")
    if mapped_time and not str(mapped_time).startswith("__"): excluded.add(str(mapped_time))
    for name, ch in run.native_channels.items():
        if str(name) in excluded:
            continue
        try:
            if min(len(ch.time_s), len(ch.values)) >= 2 and _finite_count(ch.values) >= 2:
                names.append(str(name))
        except Exception:
            continue
    for name in run.data.columns:
        name = str(name)
        if name.startswith("__") or name in excluded:
            continue
        if name in names:
            continue
        try:
            if _finite_count(run.data[name]) >= 2:
                names.append(name)
        except Exception:
            continue
    return names


def choose_default_plot_channels(run: TelemetryRun, limit: int = 5) -> List[str]:
    available = set(numeric_plot_channels(run))
    chosen: List[str] = []
    for canonical in DEFAULT_CANONICAL_ORDER:
        src = _source_for_accepted_canonical(run, canonical)
        if src and src in available and src not in chosen:
            chosen.append(src)
            if len(chosen) >= limit:
                return chosen
    # Fall back to source channels in file order so *every* valid telemetry file
    # can immediately show something, even before canonical mapping is curated.
    for name in numeric_plot_channels(run):
        if name not in chosen:
            chosen.append(name)
            if len(chosen) >= limit:
                break
    return chosen


def assess_plotability(run: TelemetryRun) -> PlotabilityReport:
    numeric = numeric_plot_channels(run)
    warnings: List[str] = []
    time_channel: Optional[str] = None
    timebase = "sample_index"

    tc = run.channel_map.get("time_s")
    if tc and tc in run.data.columns:
        t = pd.to_numeric(run.data[tc], errors="coerce").to_numpy(float)
        finite = t[np.isfinite(t)]
        if len(finite) >= 2:
            dt = np.diff(finite)
            positive = dt[np.isfinite(dt) & (dt > 0)]
            if len(positive):
                time_channel = str(tc)
                timebase = "validated_time_channel"
            else:
                warnings.append("Mapped time channel is not increasing; viewer will fall back to sample index for rectangular channels.")

    if run.native_channels:
        native_ok = any(
            len(ch.time_s) >= 2 and np.isfinite(np.asarray(ch.time_s, dtype=float)).sum() >= 2
            for ch in run.native_channels.values()
        )
        if native_ok:
            timebase = "native_channel_time"

    defaults = choose_default_plot_channels(run)
    plotable = bool(numeric and defaults)
    if not numeric:
        warnings.append("No numeric telemetry channels with at least two finite samples were found.")
    if numeric and not defaults:
        warnings.append("Numeric channels were decoded but none could be selected for a default waveform.")
    return PlotabilityReport(plotable, numeric, defaults, timebase, time_channel, warnings)


def require_plotable(run: TelemetryRun) -> PlotabilityReport:
    report = assess_plotability(run)
    run.metadata["plotability"] = report.to_dict()
    if not report.plotable:
        details = "; ".join(report.warnings) or "no plotable telemetry channels"
        raise ValueError(f"Telemetry decoded, but the run is not plotable: {details}")
    return report
