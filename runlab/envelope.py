from __future__ import annotations

"""Aligned multi-run envelope/statistics helpers."""

from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np

from .models import TelemetryRun
from .display_data import channel_xy, prepare_plot_series
from .compare import matching_reference_channel
from .units import normalize_unit, compatible, convert_value


@dataclass
class EnvelopeResult:
    x: np.ndarray
    minimum: np.ndarray
    maximum: np.ndarray
    mean: np.ndarray
    std: np.ndarray
    count: np.ndarray
    unit: str
    main_channel: str
    run_count: int
    overlap: tuple[float,float]


def multi_run_envelope(
    sessions: Sequence[Tuple[TelemetryRun, float]],
    main_channel: str,
    *,
    x_mode: str='Time from Launch',
    grid_points: int=2000,
) -> EnvelopeResult:
    """Calculate aligned min/max/mean/std across main + compare sessions.

    ``sessions`` is ordered with Main first and each tuple carries the display
    alignment offset in seconds. Matching channels in compare runs are selected
    by exact source name or canonical engineering role. The common overlap only
    is used so no trace is extrapolated beyond recorded data.
    """
    if len(sessions)<2:
        raise ValueError('Multi-run envelope requires at least two sessions.')
    main=sessions[0][0]
    target_unit=normalize_unit(main.units.get(main_channel,''))
    series=[]
    for idx,(run,alignment) in enumerate(sessions):
        channel=main_channel if idx==0 else matching_reference_channel(main,run,main_channel)
        if not channel:
            continue
        x,y=channel_xy(run,channel,x_mode,float(alignment))
        p=prepare_plot_series(x,y,max_points=100000)
        if p.output_points<2:
            continue
        src_unit=normalize_unit(run.units.get(channel,''))
        yy=np.asarray(p.y,float)
        if idx and target_unit and src_unit and src_unit!=target_unit:
            if not compatible(target_unit,src_unit):
                continue
            yy=np.asarray(convert_value(yy,src_unit,target_unit),float)
        elif not target_unit:
            target_unit=src_unit
        series.append((p.x,yy))
    if len(series)<2:
        raise ValueError('Fewer than two sessions contain a compatible matching channel.')
    lo=max(float(x[0]) for x,_ in series); hi=min(float(x[-1]) for x,_ in series)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi<=lo:
        raise ValueError('The selected runs have no common overlap on this X axis.')
    grid_points=max(32,min(int(grid_points),20000))
    grid=np.linspace(lo,hi,grid_points)
    matrix=np.vstack([np.interp(grid,x,y) for x,y in series])
    return EnvelopeResult(
        x=grid,
        minimum=np.nanmin(matrix,axis=0),
        maximum=np.nanmax(matrix,axis=0),
        mean=np.nanmean(matrix,axis=0),
        std=np.nanstd(matrix,axis=0),
        count=np.sum(np.isfinite(matrix),axis=0).astype(int),
        unit=target_unit,
        main_channel=str(main_channel),
        run_count=len(series),
        overlap=(lo,hi),
    )
