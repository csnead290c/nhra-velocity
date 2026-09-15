from __future__ import annotations

"""Telemetry sensor-quality heuristics.

These checks do not decide whether a race-car system is healthy; they identify
recording/channel problems that deserve review: missing samples, flat-lines,
clock resets, extreme step outliers, and implausibly low sample counts.
"""

from dataclasses import dataclass
from typing import List
import numpy as np
import pandas as pd

from .models import TelemetryRun


@dataclass
class SensorHealthRow:
    channel: str
    unit: str
    samples: int
    finite_pct: float
    sample_rate_hz: float | None
    clock_violations: int
    flatline_pct: float
    step_outliers: int
    minimum: float | None
    maximum: float | None
    std: float | None
    status: str
    note: str


def _channel_arrays(run: TelemetryRun, name: str):
    if name in run.native_channels:
        ch=run.native_channels[name]
        return np.asarray(ch.time_s,float),np.asarray(ch.values,float),ch.sample_rate_hz
    y=pd.to_numeric(run.data[name],errors='coerce').to_numpy(float)
    tc=run.channel_map.get('time_s')
    if tc and tc in run.data:
        t=pd.to_numeric(run.data[tc],errors='coerce').to_numpy(float)
    else:
        t=np.arange(len(y),dtype=float)
    return t,y,None


def sensor_health(run: TelemetryRun) -> pd.DataFrame:
    names=[]
    for n in run.native_channels:
        if n not in names:names.append(n)
    for n in run.data.columns:
        if str(n).startswith('__'):continue
        try:
            if pd.api.types.is_numeric_dtype(run.data[n]) and n not in names:names.append(str(n))
        except Exception:pass
    rows:List[SensorHealthRow]=[]
    for name in names:
        t,y,reported_rate=_channel_arrays(run,name)
        n=min(len(t),len(y));t=t[:n];y=y[:n]
        finite=np.isfinite(y); finite_count=int(finite.sum()); finite_pct=100.0*finite_count/max(n,1)
        sample_rate=None; clock_viol=0
        tf=np.asarray(t[np.isfinite(t)],float)
        if len(tf)>=2:
            dt=np.diff(tf);clock_viol=int(np.sum(dt<=0));pos=dt[dt>0]
            if len(pos):sample_rate=float(1.0/np.median(pos))
        if reported_rate and np.isfinite(reported_rate):sample_rate=float(reported_rate)
        flat=0.0;outliers=0;minimum=maximum=std=None
        if finite_count:
            vals=y[finite];minimum=float(np.min(vals));maximum=float(np.max(vals));std=float(np.std(vals))
            if len(vals)>=2:
                d=np.diff(vals);scale=max(float(np.nanmax(vals)-np.nanmin(vals)),abs(float(np.nanmedian(vals))),1.0)
                eps=max(scale*1e-9,1e-12);flat=100.0*float(np.mean(np.abs(d)<=eps))
                med=float(np.median(d));mad=float(np.median(np.abs(d-med)))
                if mad>1e-15:
                    z=np.abs(d-med)/(1.4826*mad);outliers=int(np.sum(z>12.0))
        status='OK';notes=[]
        if n<3 or finite_count<2:
            status='ERROR';notes.append('insufficient numeric samples')
        elif finite_pct<80:
            status='ERROR';notes.append(f'{100-finite_pct:.1f}% missing/non-finite')
        elif finite_pct<98:
            status='WARN';notes.append(f'{100-finite_pct:.1f}% missing/non-finite')
        if clock_viol:
            status='ERROR' if clock_viol>max(3,int(0.01*max(n-1,1))) else ('WARN' if status=='OK' else status);notes.append(f'{clock_viol} duplicate/reset time steps')
        if n>=25 and flat>99.5:
            status='WARN' if status=='OK' else status;notes.append('nearly flat-lined')
        if n>=25 and outliers>max(2,int(0.02*(n-1))):
            status='WARN' if status=='OK' else status;notes.append(f'{outliers} extreme step outliers')
        if sample_rate is not None and (sample_rate<=0 or sample_rate>200000):
            status='WARN' if status=='OK' else status;notes.append(f'unusual sample rate {sample_rate:.3g} Hz')
        rows.append(SensorHealthRow(name,run.units.get(name,''),n,finite_pct,sample_rate,clock_viol,flat,outliers,minimum,maximum,std,status,'; '.join(notes) or 'no obvious recording-quality issue'))
    order={'ERROR':0,'WARN':1,'OK':2}
    return pd.DataFrame([r.__dict__ for r in rows]).sort_values('status',key=lambda s:s.map(order)).reset_index(drop=True) if rows else pd.DataFrame(columns=list(SensorHealthRow.__annotations__))
