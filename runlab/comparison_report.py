from __future__ import annotations

"""Structured run-to-run comparison summary."""

import numpy as np
import pandas as pd

from .models import TelemetryRun
from .compare import source_for_canonical
from .display_data import channel_xy, prepare_plot_series
from .units import normalize_unit, compatible, convert_value

_TIMING=[
    ('60 ft ET','sixty_ft_s','s'),('330 ft ET','three_thirty_ft_s','s'),('660 ft ET','eighth_mile_s','s'),
    ('660 ft MPH','eighth_mile_mph','mph'),('1000 ft ET','thousand_ft_s','s'),('1320 ft ET','quarter_mile_s','s'),('1320 ft MPH','quarter_mile_mph','mph')
]
_EVENT_TIMES=[('60 ft','sixty_ft_s'),('330 ft','three_thirty_ft_s'),('660 ft','eighth_mile_s'),('1000 ft','thousand_ft_s'),('1320 ft','quarter_mile_s')]
_CANONICAL=[('Engine RPM','engine_rpm'),('Driveshaft RPM','driveshaft_rpm'),('Vehicle Speed','speed_mph'),('Longitudinal G','longitudinal_g'),('Engine Power','power_hp'),('Engine Torque','torque_lbft')]


def _sample(run:TelemetryRun,channel:str,x:float,alignment:float=0.0):
    xx,yy=channel_xy(run,channel,'Time from Launch',alignment)
    p=prepare_plot_series(xx,yy,max_points=100000)
    if p.output_points<2 or x<p.x[0] or x>p.x[-1]:return np.nan
    return float(np.interp(x,p.x,p.y))


def comparison_summary(main:TelemetryRun, reference:TelemetryRun, *, main_alignment_s:float=0.0, reference_alignment_s:float=0.0) -> pd.DataFrame:
    rows=[]
    mt=main.timing.to_dict(); rt=reference.timing.to_dict()
    for label,key,unit in _TIMING:
        a=mt.get(key);b=rt.get(key)
        if a is None and b is None:continue
        av=np.nan if a is None else float(a);bv=np.nan if b is None else float(b)
        rows.append({'section':'Timing','location':'Timeslip','metric':label,'unit':unit,'main':av,'reference':bv,'delta':bv-av if np.isfinite(av) and np.isfinite(bv) else np.nan})
    # Use Main official timing locations as a repeatable set of sampling events.
    for event,key in _EVENT_TIMES:
        tx=mt.get(key)
        if tx is None:continue
        x=float(tx)
        for label,canonical in _CANONICAL:
            mc=source_for_canonical(main,canonical);rc=source_for_canonical(reference,canonical)
            if not mc or not rc:continue
            av=_sample(main,mc,x,main_alignment_s);bv=_sample(reference,rc,x,reference_alignment_s)
            mu=normalize_unit(main.units.get(mc,''));ru=normalize_unit(reference.units.get(rc,''))
            if np.isfinite(bv) and mu and ru and mu!=ru:
                if not compatible(mu,ru):continue
                bv=float(convert_value(bv,ru,mu))
            unit=mu or ru
            rows.append({'section':'Telemetry','location':event,'metric':label,'unit':unit,'main':av,'reference':bv,'delta':bv-av if np.isfinite(av) and np.isfinite(bv) else np.nan})
    return pd.DataFrame(rows,columns=['section','location','metric','unit','main','reference','delta'])
