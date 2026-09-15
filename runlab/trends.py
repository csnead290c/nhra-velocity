from __future__ import annotations

"""Historical engineering trend helpers.

These routines intentionally report descriptive changes in stored engineering
observations. They do not claim causal or parity-corrected vehicle improvement;
that higher-level conclusion belongs to the future model-quality/comparability
layer.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import math
import numpy as np
import pandas as pd

from .catalog import LocalCatalog


@dataclass(frozen=True)
class SeasonTrendComparison:
    key: str
    unit: str
    season_a: int
    season_b: int
    count_a: int
    count_b: int
    mean_a: float
    mean_b: float
    median_a: float
    median_b: float
    std_a: float
    std_b: float
    percent_change_mean: float
    percent_change_median: float

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def engineering_trend_frame(catalog: LocalCatalog, key: str, *, driver_id: str | None = None, vehicle_id: str | None = None) -> pd.DataFrame:
    rows=catalog.engineering_history(key,driver_id=driver_id,vehicle_id=vehicle_id,limit=100000)
    out=[]
    for row in rows:
        value=row.get('value')
        try:value=float(value)
        except Exception:continue
        if not math.isfinite(value):continue
        out.append({
            'run_id':row.get('run_id'),'date':row.get('run_datetime'),'season':row.get('season'),
            'event':row.get('event_name'),'driver':row.get('driver_name'),'vehicle':row.get('vehicle_name'),
            'category':row.get('category'),'car_number':row.get('car_number'),'value':value,
            'unit':str(row.get('unit') or ''),'provenance':row.get('provenance'),'confidence':row.get('confidence'),
            'model_snapshot_id':row.get('model_snapshot_id'),'method':row.get('method'),
        })
    return pd.DataFrame(out)


def compare_seasons(catalog: LocalCatalog, key: str, season_a: int, season_b: int, *, driver_id: str | None = None, vehicle_id: str | None = None) -> SeasonTrendComparison:
    df=engineering_trend_frame(catalog,key,driver_id=driver_id,vehicle_id=vehicle_id)
    if df.empty:raise ValueError(f'No finite engineering observations found for {key}')
    units=[u for u in df['unit'].dropna().astype(str).unique() if u]
    if len(units)>1:raise ValueError(f'Engineering history mixes incompatible units: {units}')
    a=df[df['season']==int(season_a)]['value'].to_numpy(dtype=float)
    b=df[df['season']==int(season_b)]['value'].to_numpy(dtype=float)
    if len(a)==0 or len(b)==0:raise ValueError(f'Both seasons need observations; got {season_a}: {len(a)}, {season_b}: {len(b)}')
    mean_a=float(np.mean(a));mean_b=float(np.mean(b));med_a=float(np.median(a));med_b=float(np.median(b))
    pct_mean=float((mean_b/mean_a-1.0)*100.0) if abs(mean_a)>1e-12 else float('nan')
    pct_med=float((med_b/med_a-1.0)*100.0) if abs(med_a)>1e-12 else float('nan')
    return SeasonTrendComparison(
        key=key,unit=units[0] if units else '',season_a=int(season_a),season_b=int(season_b),
        count_a=len(a),count_b=len(b),mean_a=mean_a,mean_b=mean_b,median_a=med_a,median_b=med_b,
        std_a=float(np.std(a,ddof=1)) if len(a)>1 else 0.0,std_b=float(np.std(b,ddof=1)) if len(b)>1 else 0.0,
        percent_change_mean=pct_mean,percent_change_median=pct_med,
    )
