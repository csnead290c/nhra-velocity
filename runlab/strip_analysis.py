from __future__ import annotations

"""Drag-strip spatial analysis and measured-vs-model residuals."""

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from .display_data import channel_xy
from .models import SimulationResult, TelemetryRun

OFFICIAL_BEAMS: tuple[tuple[str, float, str, Optional[str]], ...] = (
    ("60 ft", 60.0, "sixty_ft_s", None),
    ("330 ft", 330.0, "three_thirty_ft_s", None),
    ("660 ft", 660.0, "eighth_mile_s", "eighth_mile_mph"),
    ("1000 ft", 1000.0, "thousand_ft_s", None),
    ("1320 ft", 1320.0, "quarter_mile_s", "quarter_mile_mph"),
)

@dataclass(frozen=True)
class StripEvent:
    label: str
    distance_ft: float
    source: str = "derived"
    severity: str = ""
    time_s: Optional[float] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass
class StripAnalysisResult:
    distance_ft: np.ndarray
    observed: dict[str, np.ndarray]
    modeled: dict[str, np.ndarray]
    residuals: dict[str, np.ndarray]
    timing_residuals: pd.DataFrame
    events: list[StripEvent]
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _finite_unique_xy(x: Sequence[float], y: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    xx=np.asarray(x,dtype=float); yy=np.asarray(y,dtype=float)
    n=min(len(xx),len(yy)); xx=xx[:n]; yy=yy[:n]
    good=np.isfinite(xx)&np.isfinite(yy)
    xx=xx[good]; yy=yy[good]
    if len(xx)<2:return np.array([],float),np.array([],float)
    order=np.argsort(xx,kind="stable"); xx=xx[order]; yy=yy[order]
    keep=np.r_[True,np.diff(xx)>0]
    return xx[keep],yy[keep]


def _interp_on_grid(x: Sequence[float], y: Sequence[float], grid: np.ndarray) -> np.ndarray:
    xx,yy=_finite_unique_xy(x,y)
    if len(xx)<2:return np.full(len(grid),np.nan,float)
    out=np.full(len(grid),np.nan,float)
    inside=(grid>=xx[0])&(grid<=xx[-1])
    if inside.any():out[inside]=np.interp(grid[inside],xx,yy)
    return out


def source_for_role(run: TelemetryRun, role: str) -> Optional[str]:
    direct=run.channel_map.get(role)
    if direct and (direct in run.data.columns or direct in run.native_channels):return direct
    original=run.metadata.get("original_channel_map",{})
    if isinstance(original,dict):
        c=original.get(role)
        if c and (c in run.data.columns or c in run.native_channels):return str(c)
    return None


def measured_distance_series(run: TelemetryRun, role: str) -> tuple[np.ndarray,np.ndarray]:
    # Distance views are only physically meaningful when speed is available.
    # channel_xy intentionally falls back to time/sample index for ordinary
    # display resilience; strip analysis must fail soft rather than mislabel that
    # fallback coordinate as feet.
    if not source_for_role(run,"speed_mph"):
        return np.array([],float),np.array([],float)
    channel=source_for_role(run,role)
    if not channel:return np.array([],float),np.array([],float)
    x,y=channel_xy(run,channel,"Distance from Launch")
    return _finite_unique_xy(x,y)


def simulation_distance_series(result: SimulationResult, column: str) -> tuple[np.ndarray,np.ndarray]:
    trace=result.trace
    if trace is None or column not in trace.columns:return np.array([],float),np.array([],float)
    distance_col="timing_distance_ft" if "timing_distance_ft" in trace.columns else "axle_distance_ft"
    if distance_col not in trace.columns:return np.array([],float),np.array([],float)
    x=pd.to_numeric(trace[distance_col],errors="coerce").to_numpy(float)
    y=pd.to_numeric(trace[column],errors="coerce").to_numpy(float)
    return _finite_unique_xy(x,y)


def timing_residual_table(run: TelemetryRun, model: SimulationResult) -> pd.DataFrame:
    rows=[]
    for label,distance,et_attr,mph_attr in OFFICIAL_BEAMS:
        observed_et=getattr(run.timing,et_attr,None); modeled_et=getattr(model.timing,et_attr,None)
        observed_mph=getattr(run.timing,mph_attr,None) if mph_attr else None
        modeled_mph=getattr(model.timing,mph_attr,None) if mph_attr else None
        rows.append({
            "point":label,"distance_ft":distance,
            "observed_et_s":observed_et,"modeled_et_s":modeled_et,
            "et_residual_s":np.nan if observed_et is None or modeled_et is None else float(modeled_et-observed_et),
            "observed_mph":observed_mph,"modeled_mph":modeled_mph,
            "mph_residual":np.nan if observed_mph is None or modeled_mph is None else float(modeled_mph-observed_mph),
        })
    return pd.DataFrame(rows)



def section_residual_table(run: TelemetryRun, model: SimulationResult) -> pd.DataFrame:
    points=[("Launch",0.0,0.0,0.0)]
    for label,distance,et_attr,_mph_attr in OFFICIAL_BEAMS:
        obs=getattr(run.timing,et_attr,None); pred=getattr(model.timing,et_attr,None)
        if obs is not None and pred is not None:
            points.append((label,distance,float(obs),float(pred)))
    rows=[]
    for (a,da,oa,pa),(b,db,ob,pb) in zip(points[:-1],points[1:]):
        observed=ob-oa; modeled=pb-pa
        rows.append({"section":f"{a} → {b}","start_ft":da,"end_ft":db,"observed_s":observed,"modeled_s":modeled,"residual_s":modeled-observed})
    if len(points)>1:
        a,da,oa,pa=points[0];b,db,ob,pb=points[-1]
        rows.insert(0,{"section":f"{a} → {b}","start_ft":da,"end_ft":db,"observed_s":ob-oa,"modeled_s":pb-pa,"residual_s":(pb-pa)-(ob-oa)})
    return pd.DataFrame(rows)

def time_to_distance(run: TelemetryRun, time_from_launch_s: float) -> float:
    sc=source_for_role(run,"speed_mph")
    if not sc:return float("nan")
    xdist,_=channel_xy(run,sc,"Distance from Launch")
    t,_=channel_xy(run,sc,"Time from Launch")
    tt,dd=_finite_unique_xy(t,xdist)
    if len(tt)<2 or time_from_launch_s<tt[0] or time_from_launch_s>tt[-1]:return float("nan")
    return float(np.interp(float(time_from_launch_s),tt,dd))


def official_events(run: TelemetryRun) -> list[StripEvent]:
    out=[StripEvent("Launch",0.0,"official",time_s=0.0)]
    for label,distance,et_attr,_ in OFFICIAL_BEAMS:
        t=getattr(run.timing,et_attr,None)
        if t is not None:out.append(StripEvent(label,distance,"official",time_s=float(t)))
    return out


def rule_events_to_strip(run: TelemetryRun, event_rows: Optional[pd.DataFrame]) -> list[StripEvent]:
    if event_rows is None or event_rows.empty:return []
    out=[]
    for _,rec in event_rows.iterrows():
        start=float(rec.get("start_s",np.nan)); d=time_to_distance(run,start)
        if not np.isfinite(d):continue
        out.append(StripEvent(str(rec.get("rule") or rec.get("event_type") or "Rule event"),float(d),"rule",str(rec.get("severity") or ""),start,{"event_type":str(rec.get("event_type") or ""),"trigger":str(rec.get("trigger") or "")}))
    return out


def analyze_strip(run: TelemetryRun, model: Optional[SimulationResult]=None, *, distance_step_ft: float=5.0, max_distance_ft: float=1320.0, observed_roles: Sequence[str]=( "speed_mph", "engine_rpm", "driveshaft_rpm", "longitudinal_g" ), rule_events: Optional[pd.DataFrame]=None) -> StripAnalysisResult:
    step=max(0.1,float(distance_step_ft)); maxd=max(step,float(max_distance_ft)); grid=np.arange(0.0,maxd+step*0.5,step,float)
    observed={}; modeled={}; residuals={}
    for role in observed_roles:
        x,y=measured_distance_series(run,role); observed[role]=_interp_on_grid(x,y,grid)
    if model is not None:
        mapping={"speed_mph":"speed_mph","engine_rpm":"engine_rpm","driveshaft_rpm":"driveshaft_rpm","longitudinal_g":"accel_g"}
        for role,col in mapping.items():
            x,y=simulation_distance_series(model,col); modeled[role]=_interp_on_grid(x,y,grid)
            if role in observed:residuals[role]=modeled[role]-observed[role]
        timing=timing_residual_table(run,model)
    else:
        timing=pd.DataFrame(columns=["point","distance_ft","observed_et_s","modeled_et_s","et_residual_s","observed_mph","modeled_mph","mph_residual"])
    events=official_events(run)+rule_events_to_strip(run,rule_events); events.sort(key=lambda e:(e.distance_ft,e.label))
    diagnostics={"distance_step_ft":step,"max_distance_ft":maxd,"observed_roles":[k for k,v in observed.items() if np.isfinite(v).any()],"modeled_roles":[k for k,v in modeled.items() if np.isfinite(v).any()],"event_count":len(events)}
    return StripAnalysisResult(grid,observed,modeled,residuals,timing,events,diagnostics)


def strip_table(result: StripAnalysisResult) -> pd.DataFrame:
    data={"distance_ft":result.distance_ft}
    for name,values in result.observed.items():data[f"observed.{name}"]=values
    for name,values in result.modeled.items():data[f"modeled.{name}"]=values
    for name,values in result.residuals.items():data[f"residual.{name}"]=values
    return pd.DataFrame(data)
