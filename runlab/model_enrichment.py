from __future__ import annotations

"""RSA model-derived virtual channels for ordinary telemetry analysis.

The model channels deliberately retain the simulation's own Run-time grid.
They are not silently resampled onto logger clocks. Residual channels use an
explicit interpolation of measured canonical channels onto that model grid and
are labeled model-minus-measured.
"""

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from .branding import PRODUCT_VERSION
from .display_data import channel_xy
from .models import ChannelSeries, Environment, SimulationResult, TelemetryRun, VehicleConfig
from .workstation import resolve_channel


@dataclass(frozen=True)
class ModelChannelSpec:
    trace_column: str
    name: str
    unit: str
    canonical_role: str


MODEL_CHANNEL_SPECS: tuple[ModelChannelSpec, ...] = (
    ModelChannelSpec("timing_distance_ft", "Model.Distance", "ft", "model_distance_ft"),
    ModelChannelSpec("speed_mph", "Model.Speed", "mph", "model_speed_mph"),
    ModelChannelSpec("accel_g", "Model.Longitudinal G", "g", "model_longitudinal_g"),
    ModelChannelSpec("engine_rpm", "Model.Engine RPM", "rpm", "model_engine_rpm"),
    ModelChannelSpec("engine_hp_weather", "Model.Engine Power", "hp", "model_power_hp"),
    ModelChannelSpec("engine_torque_lbft", "Model.Engine Torque", "lbft", "model_torque_lbft"),
    ModelChannelSpec("driveshaft_rpm", "Model.Driveshaft RPM", "rpm", "model_driveshaft_rpm"),
    ModelChannelSpec("wheel_rpm", "Model.Wheel RPM", "rpm", "model_wheel_rpm"),
    ModelChannelSpec("gear", "Model.Gear", "ratio", "model_gear"),
    ModelChannelSpec("tire_slip_ratio", "Model.Tire Slip Ratio", "ratio", "model_tire_slip_ratio"),
    ModelChannelSpec("traction_limited", "Model.Traction Limited", "ratio", "model_traction_limited"),
    ModelChannelSpec("drive_force_lb", "Model.Drive Force", "lb", "model_drive_force_lb"),
    ModelChannelSpec("drag_force_lb", "Model.Aero Drag", "lb", "model_drag_force_lb"),
    ModelChannelSpec("traction_force_lb", "Model.Traction Force", "lb", "model_traction_force_lb"),
    ModelChannelSpec("dynamic_rear_weight_lb", "Model.Dynamic Rear Weight", "lb", "model_dynamic_rear_weight_lb"),
    ModelChannelSpec("engine_inertia_hp", "Model.Engine Inertia Power", "hp", "model_engine_inertia_hp"),
    ModelChannelSpec("chassis_inertia_hp", "Model.Chassis Inertia Power", "hp", "model_chassis_inertia_hp"),
)

RESIDUAL_ROLES: tuple[tuple[str, str, str, str], ...] = (
    ("speed_mph", "Model.Speed", "Residual.Speed", "residual_speed_mph"),
    ("engine_rpm", "Model.Engine RPM", "Residual.Engine RPM", "residual_engine_rpm"),
    ("driveshaft_rpm", "Model.Driveshaft RPM", "Residual.Driveshaft RPM", "residual_driveshaft_rpm"),
    ("longitudinal_g", "Model.Longitudinal G", "Residual.Longitudinal G", "residual_longitudinal_g"),
)


def _model_time(trace: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    # Match the workstation's drag-pass launch convention: the last near-zero
    # sample before the >3 mph pass excursion is Run Time zero.  This remains
    # separate from the NHRA ET clock, which begins at beam release after rollout.
    if "physical_time_s" not in trace.columns:
        raise ValueError("RSA simulation trace has no physical time")
    t_abs = pd.to_numeric(trace["physical_time_s"], errors="coerce").to_numpy(float)
    launch_time = 0.0
    if "speed_mph" in trace.columns:
        speed=pd.to_numeric(trace["speed_mph"],errors="coerce").to_numpy(float)
        moving=np.flatnonzero(np.isfinite(speed)&(speed>3.0))
        if len(moving):
            s=int(moving[0]); stationary=np.flatnonzero(np.isfinite(speed[:s+1])&(speed[:s+1]<=1.0))
            launch_idx=int(stationary[-1]) if len(stationary) else s
            if np.isfinite(t_abs[launch_idx]): launch_time=float(t_abs[launch_idx])
    t=t_abs-launch_time
    good = np.isfinite(t) & (t >= -1e-12)
    idx = np.flatnonzero(good)
    if len(idx) < 2:
        raise ValueError("RSA simulation trace has fewer than two post-launch time samples")
    tt = t[idx]
    keep = np.r_[True, np.diff(tt) > 0]
    idx = idx[keep]
    tt = t[idx]
    if len(tt) < 2:
        raise ValueError("RSA simulation Run-time grid is not strictly increasing")
    return tt, idx


def _sample_rate(time_s: np.ndarray) -> Optional[float]:
    if len(time_s) < 3:
        return None
    dt = np.diff(time_s)
    dt = dt[np.isfinite(dt) & (dt > 0)]
    if not len(dt):
        return None
    return float(1.0 / np.median(dt))


def _finite_unique_xy(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = min(len(x), len(y)); x=np.asarray(x[:n],float); y=np.asarray(y[:n],float)
    good=np.isfinite(x)&np.isfinite(y); x=x[good]; y=y[good]
    if len(x)<2:return np.array([],float),np.array([],float)
    order=np.argsort(x,kind="stable");x=x[order];y=y[order]
    keep=np.r_[True,np.diff(x)>0]
    return x[keep],y[keep]


def _fingerprint(vehicle: VehicleConfig | None, environment: Environment | None, engine: str, model_snapshot_id: str) -> str:
    payload={"engine":engine,"model_snapshot_id":model_snapshot_id,"vehicle":vehicle.to_dict() if vehicle else None,"environment":environment.to_dict() if environment else None,"software_version":PRODUCT_VERSION}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")).hexdigest()


def clear_model_enrichment(run: TelemetryRun) -> None:
    names=set(run.metadata.get("model_virtual_channels",{})) | set(run.metadata.get("model_residual_channels",{}))
    for name in names:
        run.native_channels.pop(str(name),None)
        run.units.pop(str(name),None)
    run.metadata.pop("model_virtual_channels",None)
    run.metadata.pop("model_residual_channels",None)
    run.metadata.pop("model_enrichment",None)


def attach_model_enrichment(
    run: TelemetryRun,
    result: SimulationResult,
    *,
    vehicle: VehicleConfig | None = None,
    environment: Environment | None = None,
    engine: str = "reference",
    model_snapshot_id: str = "",
    include_residuals: bool = True,
    replace: bool = True,
) -> dict[str, Any]:
    """Attach RSA model and explicit residual channels to an in-memory Run.

    Raw logger columns and authoritative timing are not changed.  All model
    channels use the post-launch RSA ET-clock grid.  Residuals are
    model-minus-measured after explicitly interpolating the measured canonical
    channel onto that model grid.
    """
    if replace:
        clear_model_enrichment(run)
    trace=result.trace
    if trace is None or not isinstance(trace,pd.DataFrame) or trace.empty:
        raise ValueError("RSA simulation result has no trace")
    model_t, idx=_model_time(trace)
    sr=_sample_rate(model_t)
    virtual_roles: dict[str,str]={}
    residual_roles: dict[str,str]={}
    attached=[]
    for spec in MODEL_CHANNEL_SPECS:
        if spec.trace_column not in trace.columns:
            continue
        values=pd.to_numeric(trace[spec.trace_column],errors="coerce").to_numpy(float)[idx]
        run.native_channels[spec.name]=ChannelSeries(spec.name,model_t.copy(),values,spec.unit,sr,3,True,{"source_kind":"rsa_model","model_engine":engine,"software_version":PRODUCT_VERSION})
        run.units[spec.name]=spec.unit
        virtual_roles[spec.name]=spec.canonical_role
        attached.append(spec.name)

    if include_residuals:
        model_by_name={name:run.native_channels[name] for name in attached}
        for measured_role, model_name, residual_name, residual_role in RESIDUAL_ROLES:
            source=resolve_channel(run,measured_role)
            model_series=model_by_name.get(model_name)
            if not source or model_series is None:
                continue
            mx,my=channel_xy(run,source,"Time from Launch")
            mx,my=_finite_unique_xy(mx,my)
            if len(mx)<2:
                continue
            observed=np.full(len(model_t),np.nan,float)
            inside=(model_t>=mx[0])&(model_t<=mx[-1])
            if inside.any(): observed[inside]=np.interp(model_t[inside],mx,my)
            residual=np.asarray(model_series.values,float)-observed
            unit=model_series.unit
            run.native_channels[residual_name]=ChannelSeries(residual_name,model_t.copy(),residual,unit,sr,3,True,{"source_kind":"rsa_residual","residual_sign":"model-minus-measured","measured_channel":source,"model_channel":model_name,"software_version":PRODUCT_VERSION})
            run.units[residual_name]=unit
            residual_roles[residual_name]=residual_role
            attached.append(residual_name)

    fingerprint=_fingerprint(vehicle,environment or run.environment,engine,model_snapshot_id)
    run.metadata["model_virtual_channels"]=virtual_roles
    run.metadata["model_residual_channels"]=residual_roles
    run.metadata["model_enrichment"]={
        "engine":engine,
        "software_version":PRODUCT_VERSION,
        "model_snapshot_id":model_snapshot_id,
        "fingerprint_sha256":fingerprint,
        "time_domain":"Run time / workstation launch convention (last <=1 mph before pass)",
        "residual_sign":"model-minus-measured",
        "channel_count":len(attached),
    }
    return {"channels":attached,"model_channels":list(virtual_roles),"residual_channels":list(residual_roles),"fingerprint_sha256":fingerprint,"sample_rate_hz":sr}


def model_enrichment_frame(run: TelemetryRun) -> pd.DataFrame:
    names=list(run.metadata.get("model_virtual_channels",{}))+list(run.metadata.get("model_residual_channels",{}))
    names=[n for n in names if n in run.native_channels]
    if not names:
        return pd.DataFrame()
    base=run.native_channels[names[0]]
    t=np.asarray(base.time_s,float)
    out={"run_time_s":t}
    for name in names:
        ch=run.native_channels[name]
        ct=np.asarray(ch.time_s,float);cv=np.asarray(ch.values,float)
        if len(ct)==len(t) and np.allclose(ct,t,equal_nan=True):
            out[name]=cv
        else:
            x,y=_finite_unique_xy(ct,cv);vals=np.full(len(t),np.nan,float)
            if len(x)>=2:
                inside=(t>=x[0])&(t<=x[-1]);vals[inside]=np.interp(t[inside],x,y)
            out[name]=vals
    return pd.DataFrame(out)


def run_rsa_model_enrichment(
    run: TelemetryRun,
    vehicle: VehicleConfig,
    *,
    environment: Environment | None = None,
    engine: str = "reference",
    dt_s: float = 0.0025,
    model_snapshot_id: str = "",
    include_residuals: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    env=environment or run.environment
    if engine == "reference":
        from .legacy_reference import simulate_legacy_reference
        result=simulate_legacy_reference(vehicle,env)
    elif engine == "smooth":
        from .physics import simulate, SolverOptions
        result=simulate(vehicle,env,options=SolverOptions(dt_s=float(dt_s)))
    else:
        raise ValueError("engine must be 'reference' or 'smooth'")
    info=attach_model_enrichment(run,result,vehicle=vehicle,environment=env,engine=engine,model_snapshot_id=model_snapshot_id,include_residuals=include_residuals)
    if persist:
        derived=run.metadata.setdefault("derived_analyses",{})
        if not isinstance(derived,dict):
            derived={};run.metadata["derived_analyses"]=derived
        derived["rsa_model_enrichment"]={"enabled":True,"engine":engine,"dt_s":float(dt_s),"include_residuals":bool(include_residuals),"model_snapshot_id":model_snapshot_id,"fingerprint_sha256":info["fingerprint_sha256"]}
    return info


def rebuild_rsa_model_enrichment(run: TelemetryRun, vehicle: VehicleConfig) -> dict[str, Any] | None:
    derived=run.metadata.get("derived_analyses",{})
    cfg=derived.get("rsa_model_enrichment",{}) if isinstance(derived,dict) else {}
    if not isinstance(cfg,dict) or not cfg.get("enabled"):
        return None
    return run_rsa_model_enrichment(run,vehicle,environment=run.environment,engine=str(cfg.get("engine") or "reference"),dt_s=float(cfg.get("dt_s") or 0.0025),model_snapshot_id=str(cfg.get("model_snapshot_id") or ""),include_residuals=bool(cfg.get("include_residuals",True)),persist=True)
