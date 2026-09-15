from __future__ import annotations

"""Region-based telemetry statistics for workstation displays and reports."""

from typing import Iterable, List, Dict
import numpy as np

from .models import TelemetryRun
from .display_data import channel_xy, prepare_plot_series


def region_statistics(
    run: TelemetryRun,
    channels: Iterable[str],
    x1: float,
    x2: float,
    *,
    x_mode: str="Time from Launch",
    alignment_s: float=0.0,
) -> List[Dict[str, float | str | int]]:
    lo,hi=sorted((float(x1),float(x2)))
    rows=[]
    for channel in channels:
        x,y=channel_xy(run,str(channel),x_mode,alignment_s)
        p=prepare_plot_series(x,y,max_points=None)
        if p.output_points<1:
            continue
        tol=max(1e-12,abs(hi-lo)*1e-10)
        keep=(p.x>=lo-tol)&(p.x<=hi+tol)
        xx=p.x[keep]; yy=p.y[keep]
        if not len(yy):
            continue
        finite=yy[np.isfinite(yy)]
        if not len(finite):
            continue
        start=float(yy[0]); end=float(yy[-1])
        rows.append({
            'channel':str(channel),'count':int(len(finite)),
            'start':start,'end':end,'delta':end-start,
            'min':float(np.min(finite)),'max':float(np.max(finite)),
            'mean':float(np.mean(finite)),'median':float(np.median(finite)),
            'std':float(np.std(finite)),'rms':float(np.sqrt(np.mean(finite**2))),
            'x1':lo,'x2':hi,
        })
    return rows
