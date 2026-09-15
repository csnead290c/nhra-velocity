from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from .models import Environment, TelemetryRun, TimingData, VehicleConfig
from .physics import SolverOptions, simulate
from .legacy_reference import simulate_legacy_reference
from .telemetry import detect_drag_pass_window
from .strip_analysis import analyze_strip


@dataclass(frozen=True)
class FitDistanceWindow:
    name: str
    start_ft: float
    end_ft: float
    weight: float = 1.0

    def __post_init__(self):
        if float(self.end_ft) <= float(self.start_ft):
            raise ValueError("Fit distance window end must exceed start")
        if float(self.weight) < 0:
            raise ValueError("Fit distance window weight cannot be negative")

    def to_dict(self) -> Dict[str, Any]:
        return {"name":self.name,"start_ft":float(self.start_ft),"end_ft":float(self.end_ft),"weight":float(self.weight)}

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "FitDistanceWindow":
        return cls(str(value.get("name") or "Window"),float(value.get("start_ft",0.0)),float(value.get("end_ft",1320.0)),float(value.get("weight",1.0)))


@dataclass
class FitEvidencePolicy:
    """Explicit observation-selection/weighting policy for one measured Run.

    telemetry_domain='time' preserves the historical inverse behavior.  Setting
    it to 'distance' evaluates measured-vs-model residuals on physical downtrack
    distance and can restrict them to selected windows.  Weights multiply the
    normalized residual after the engineering uncertainty scale is applied.
    """
    telemetry_domain: str = "time"  # time | distance
    timing_weights: Dict[str, float] = field(default_factory=dict)
    telemetry_weights: Dict[str, float] = field(default_factory=dict)
    telemetry_scales: Dict[str, float] = field(default_factory=dict)
    distance_windows: List[FitDistanceWindow] = field(default_factory=list)
    max_points: int = 90
    distance_step_ft: float = 5.0

    def __post_init__(self):
        if self.telemetry_domain not in {"time", "distance"}:
            raise ValueError("telemetry_domain must be 'time' or 'distance'")
        if int(self.max_points) < 1:
            raise ValueError("max_points must be positive")
        if float(self.distance_step_ft) <= 0:
            raise ValueError("distance_step_ft must be positive")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "telemetry_domain":self.telemetry_domain,
            "timing_weights":dict(self.timing_weights),
            "telemetry_weights":dict(self.telemetry_weights),
            "telemetry_scales":dict(self.telemetry_scales),
            "distance_windows":[w.to_dict() for w in self.distance_windows],
            "max_points":int(self.max_points),
            "distance_step_ft":float(self.distance_step_ft),
        }

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "FitEvidencePolicy":
        return cls(
            telemetry_domain=str(value.get("telemetry_domain") or "time"),
            timing_weights={str(k):float(v) for k,v in (value.get("timing_weights") or {}).items()},
            telemetry_weights={str(k):float(v) for k,v in (value.get("telemetry_weights") or {}).items()},
            telemetry_scales={str(k):float(v) for k,v in (value.get("telemetry_scales") or {}).items()},
            distance_windows=[FitDistanceWindow.from_dict(x) for x in (value.get("distance_windows") or [])],
            max_points=int(value.get("max_points") or 90),
            distance_step_ft=float(value.get("distance_step_ft") or 5.0),
        )


@dataclass
class FitRun:
    name: str
    environment: Environment
    timing: TimingData = field(default_factory=TimingData)
    telemetry: Optional[TelemetryRun] = None
    telemetry_weight: float = 1.0
    timing_weight: float = 1.0
    evidence: Optional[FitEvidencePolicy] = None
    nuisance_terms: Optional[List[str]] = None
    source_run_id: str = ""
    role: str = "measurement"


@dataclass
class ParameterSpec:
    name: str
    initial: float
    lower: float
    upper: float
    description: str = ""


@dataclass
class FitResult:
    success: bool
    message: str
    estimates: pd.DataFrame
    correlation: pd.DataFrame
    residuals: pd.DataFrame
    optimized_vehicle: VehicleConfig
    optimizer_result: Any
    predicted_runs: Dict[str, Any]
    reference_predictions: Dict[str, Any]
    reference_residuals: pd.DataFrame
    identifiability_notes: List[str]


def _default_spec(name: str, vehicle: VehicleConfig) -> ParameterSpec:
    if name == "power_scale":
        return ParameterSpec(name, 1.0, 0.50, 1.60, "Global multiplier on the dyno curve")
    if name == "cda_ft2":
        return ParameterSpec(name, vehicle.cda_ft2, max(0.2, vehicle.cda_ft2 * 0.35), max(1.0, vehicle.cda_ft2 * 2.5), "Aerodynamic CdA; Cd and area are not separated without extra information")
    if name == "cla_ft2":
        base = float(vehicle.lift_coefficient) * float(vehicle.frontal_area_ft2)
        return ParameterSpec(name, base, -10.0, max(60.0, abs(base) * 4.0 + 5.0), "Combined downforce coefficient × area (positive adds vertical load in the Quarter Pro convention)")
    if name == "traction_index":
        return ParameterSpec(name, vehicle.traction_index, 1.0, 10.0, "Quarter Pro traction index")
    if name == "stall_rpm":
        return ParameterSpec(name, vehicle.stall_rpm, max(500.0, vehicle.dyno.rpm[0] * 0.55), vehicle.dyno.rpm[-1] * 1.10, "Converter stall / clutch slip floor")
    if name == "slippage":
        return ParameterSpec(name, vehicle.slippage, 1.000, 1.15, "Driveline/converter slippage ratio")
    if name == "torque_multiplication":
        return ParameterSpec(name, vehicle.torque_multiplication, 1.0, 3.0, "Converter torque multiplication")
    if name == "final_drive_ratio":
        return ParameterSpec(name, vehicle.final_drive_ratio, max(1.0, vehicle.final_drive_ratio * 0.65), vehicle.final_drive_ratio * 1.45, "Final drive ratio")
    if name == "final_drive_efficiency":
        return ParameterSpec(name, vehicle.final_drive_efficiency, 0.82, 1.00, "Final-drive mechanical efficiency")
    if name == "tire_diameter_in":
        return ParameterSpec(name, vehicle.tire_diameter_in, max(12.0, vehicle.tire_diameter_in * 0.75), vehicle.tire_diameter_in * 1.25, "Static tire diameter")
    if name == "tire_growth_scale":
        return ParameterSpec(name, vehicle.tire_growth_scale, 0.0, 2.5, "Multiplier on Quarter Pro tire-growth model")
    if name == "weight_lb":
        return ParameterSpec(name, vehicle.weight_lb, max(100.0, vehicle.weight_lb * 0.70), vehicle.weight_lb * 1.30, "Race weight")
    if name == "cg_height_in":
        initial = vehicle.cg_height_in if vehicle.cg_height_in is not None else vehicle.tire_diameter_in / 2.0 + 3.75
        return ParameterSpec(name, float(initial), 5.0, max(60.0, vehicle.wheelbase_in * 0.60), "Center-of-gravity height used by the longitudinal load-transfer model")
    if name == "static_front_weight_lb":
        initial = vehicle.static_front_weight_lb if vehicle.static_front_weight_lb is not None else vehicle.weight_lb * 0.50
        return ParameterSpec(name, float(initial), max(1.0, vehicle.weight_lb * 0.05), vehicle.weight_lb * 0.90, "Static front-axle load; best measured on scales rather than inferred")
    if name == "efficiency_scale":
        return ParameterSpec(name, 1.0, 0.85, 1.05, "Multiplier on gear efficiencies")
    if name == "shift_rpm_offset":
        return ParameterSpec(name, 0.0, -2500.0, 2500.0, "Common offset applied to shift RPM targets")
    if name == "front_overhang_in":
        return ParameterSpec(name, vehicle.front_overhang_in, max(0.0, vehicle.front_overhang_in - 20), vehicle.front_overhang_in + 20, "Front overhang used in timing-beam geometry")
    if name == "rollout_in":
        return ParameterSpec(name, vehicle.rollout_in, 0.0, max(24.0, vehicle.rollout_in * 2.0 + 4.0), "Staging rollout")
    if name.startswith("gear_ratio_"):
        idx = int(name.rsplit("_", 1)[1]) - 1
        if idx < 0 or idx >= vehicle.n_gears:
            raise KeyError(f"{name} is not available for a {vehicle.n_gears}-gear vehicle")
        base = float(vehicle.gear_ratios[idx])
        return ParameterSpec(name, base, max(0.25, base * 0.55), base * 1.60, f"Transmission ratio for gear {idx + 1}")
    if name.startswith("shift_rpm_"):
        idx = int(name.rsplit("_", 1)[1]) - 1
        if idx < 0 or idx >= max(0, vehicle.n_gears - 1):
            raise KeyError(f"{name} is not an active shift for a {vehicle.n_gears}-gear vehicle")
        base = float(vehicle.shift_rpms[idx]) if vehicle.shift_rpms[idx] > 0 else float(vehicle.dyno.rpm[-1])
        return ParameterSpec(name, base, max(500.0, vehicle.dyno.rpm[0] * 0.65), vehicle.dyno.rpm[-1] * 1.20, f"Engine RPM target for the {idx + 1}→{idx + 2} shift")
    if name.startswith("curve_node_"):
        return ParameterSpec(name, 1.0, 0.60, 1.45, "Local dyno-curve multiplier")
    raise KeyError(f"Unsupported fit parameter: {name}")


def make_parameter_specs(names: Sequence[str], vehicle: VehicleConfig) -> List[ParameterSpec]:
    return [_default_spec(n, vehicle) for n in names]


def make_run_nuisance_specs(runs: Sequence[FitRun], terms: Sequence[str]) -> List[ParameterSpec]:
    specs: List[ParameterSpec] = []
    for i, run in enumerate(runs):
        allowed = set(terms if run.nuisance_terms is None else run.nuisance_terms)
        for term in terms:
            if term not in allowed:
                continue
            if term == "power_scale":
                specs.append(ParameterSpec(f"run__{i}__power_scale", 1.0, 0.85, 1.15, f"{run.name}: bounded run-specific power correction; regularized toward 1.0"))
            elif term == "traction_delta":
                specs.append(ParameterSpec(f"run__{i}__traction_delta", 0.0, -2.0, 2.0, f"{run.name}: run-specific traction-index delta; regularized toward 0"))
            elif term == "rollout_delta_in":
                specs.append(ParameterSpec(f"run__{i}__rollout_delta_in", 0.0, -2.0, 2.0, f"{run.name}: run-specific staging-rollout delta [in]; regularized toward 0"))
            else:
                raise KeyError(f"Unsupported nuisance term: {term}")
    return specs


def _run_nuisance_value(knobs: Dict[str, Any], run_idx: int, term: str, default: float) -> float:
    return float(knobs.get("run_nuisance", {}).get(f"run__{run_idx}__{term}", default))


def _apply_parameters(
    base: VehicleConfig,
    specs: Sequence[ParameterSpec],
    x: Sequence[float],
) -> Tuple[VehicleConfig, Dict[str, Any]]:
    v = copy.deepcopy(base)
    knobs: Dict[str, Any] = {
        "power_scale": 1.0,
        "efficiency_scale": 1.0,
        "shift_rpm_offset": 0.0,
        "curve_multipliers": None,
        "run_nuisance": {},
    }
    curve_nodes: Dict[int, float] = {}
    for spec, value in zip(specs, x):
        name = spec.name
        value = float(value)
        if name == "power_scale":
            knobs["power_scale"] = value
        elif name == "cda_ft2":
            v.drag_coefficient = value / max(v.frontal_area_ft2, 1e-9)
        elif name == "cla_ft2":
            v.lift_coefficient = value / max(v.frontal_area_ft2, 1e-9)
        elif name == "traction_index":
            v.traction_index = value
        elif name == "stall_rpm":
            v.stall_rpm = value
        elif name == "slippage":
            v.slippage = value
        elif name == "torque_multiplication":
            v.torque_multiplication = value
        elif name == "final_drive_ratio":
            v.final_drive_ratio = value
        elif name == "final_drive_efficiency":
            v.final_drive_efficiency = value
        elif name == "tire_diameter_in":
            v.tire_diameter_in = value
        elif name == "tire_growth_scale":
            v.tire_growth_scale = value
        elif name == "weight_lb":
            v.weight_lb = value
        elif name == "cg_height_in":
            v.cg_height_in = value
        elif name == "static_front_weight_lb":
            v.static_front_weight_lb = value
        elif name == "efficiency_scale":
            knobs["efficiency_scale"] = value
        elif name == "shift_rpm_offset":
            knobs["shift_rpm_offset"] = value
        elif name == "front_overhang_in":
            v.front_overhang_in = value
        elif name == "rollout_in":
            v.rollout_in = value
        elif name.startswith("gear_ratio_"):
            idx = int(name.rsplit("_", 1)[1]) - 1
            v.gear_ratios[idx] = value
        elif name.startswith("shift_rpm_"):
            idx = int(name.rsplit("_", 1)[1]) - 1
            v.shift_rpms[idx] = value
        elif name.startswith("curve_node_"):
            idx = int(name.split("_")[-1])
            curve_nodes[idx] = value
        elif name.startswith("run__"):
            knobs["run_nuisance"][name] = value
        else:
            raise KeyError(name)

    if curve_nodes:
        n = max(curve_nodes) + 1
        mult = [1.0] * n
        for i, val in curve_nodes.items():
            mult[i] = val
        knobs["curve_multipliers"] = mult
    return v, knobs




def _materialize_vehicle(v: VehicleConfig, knobs: Dict[str, Any]) -> VehicleConfig:
    """Bake optimizer-only modifiers into a portable VehicleConfig."""
    out = copy.deepcopy(v)
    power_scale = float(knobs.get("power_scale", 1.0))
    curve = knobs.get("curve_multipliers")
    rpm = np.asarray(out.dyno.rpm, dtype=float)
    hp = np.asarray(out.dyno.hp, dtype=float) * power_scale
    if curve is not None and len(curve):
        curve = np.asarray(curve, dtype=float)
        node_x = np.linspace(rpm[0], rpm[-1], len(curve))
        hp = hp * np.interp(rpm, node_x, curve)
    out.dyno.hp = [float(x) for x in hp]
    eff_scale = float(knobs.get("efficiency_scale", 1.0))
    out.gear_efficiencies = [max(0.5, min(1.0, float(x) * eff_scale)) for x in out.gear_efficiencies]
    shift_offset = float(knobs.get("shift_rpm_offset", 0.0))
    out.shift_rpms = [float(x + shift_offset) if x > 0 else float(x) for x in out.shift_rpms]
    return out.normalized()

def _launch_zero(run: TelemetryRun) -> float:
    """Estimate launch time from the dominant drag-pass excursion."""
    return float(detect_drag_pass_window(run).launch_time_s)


def _telemetry_residuals(run: TelemetryRun, sim_trace: pd.DataFrame, max_points: int = 90, *, channel_weights: Optional[Dict[str,float]] = None, channel_scales: Optional[Dict[str,float]] = None) -> Tuple[List[float], List[Dict[str, Any]]]:
    df = run.data
    m = run.channel_map
    if "time_s" not in m:
        return [], []
    t = pd.to_numeric(df[m["time_s"]], errors="coerce").to_numpy(float)
    t0 = _launch_zero(run)
    t = t - t0
    sim_t = sim_trace["physical_time_s"].to_numpy(float)
    if len(sim_t) < 2:
        return [], []

    residuals: List[float] = []
    detail: List[Dict[str, Any]] = []

    default_scales = {"speed_mph":1.5,"engine_rpm":125.0,"driveshaft_rpm":80.0,"longitudinal_g":0.05}
    sim_columns = {"speed_mph":"speed_mph","engine_rpm":"engine_rpm","driveshaft_rpm":"driveshaft_rpm","longitudinal_g":"accel_g"}
    for canonical, sim_col in sim_columns.items():
        weight=float((channel_weights or {}).get(canonical,1.0))
        if weight <= 0: continue
        scale=float((channel_scales or {}).get(canonical,default_scales[canonical]))
        if scale <= 0: raise ValueError(f"Telemetry scale for {canonical} must be positive")
        if canonical not in m:
            continue
        y = pd.to_numeric(df[m[canonical]], errors="coerce").to_numpy(float)
        mask = np.isfinite(t) & np.isfinite(y) & (t >= 0.0) & (t <= sim_t[-1])
        idx = np.flatnonzero(mask)
        if len(idx) < 3:
            continue
        if len(idx) > max_points:
            idx = idx[np.linspace(0, len(idx) - 1, max_points).astype(int)]
        pred = np.interp(t[idx], sim_t, sim_trace[sim_col].to_numpy(float))
        for j, p in zip(idx, pred):
            r = ((float(p) - float(y[j])) / scale) * weight
            residuals.append(r)
            detail.append({
                "source": f"telemetry:{canonical}",
                "x": float(t[j]),
                "observed": float(y[j]),
                "predicted": float(p),
                "normalized_residual": float(r),
            })
    return residuals, detail



def _telemetry_distance_residuals(run: TelemetryRun, sim, policy: FitEvidencePolicy) -> Tuple[List[float], List[Dict[str, Any]]]:
    result=analyze_strip(run,sim,distance_step_ft=float(policy.distance_step_ft))
    default_scales={"speed_mph":1.5,"engine_rpm":125.0,"driveshaft_rpm":80.0,"longitudinal_g":0.05}
    windows=policy.distance_windows or [FitDistanceWindow("Full strip",0.0,1320.0,1.0)]
    residuals: List[float]=[]; detail: List[Dict[str,Any]]=[]
    for canonical,values in result.residuals.items():
        channel_weight=float(policy.telemetry_weights.get(canonical,1.0))
        if channel_weight <= 0: continue
        scale=float(policy.telemetry_scales.get(canonical,default_scales.get(canonical,1.0)))
        if scale <= 0: raise ValueError(f"Telemetry scale for {canonical} must be positive")
        x=result.distance_ft; values=np.asarray(values,float)
        for window in windows:
            if window.weight <= 0: continue
            mask=np.isfinite(x)&np.isfinite(values)&(x>=float(window.start_ft))&(x<=float(window.end_ft))
            idx=np.flatnonzero(mask)
            if len(idx)<1: continue
            max_per=max(1,int(policy.max_points)//max(1,len(windows)))
            if len(idx)>max_per: idx=idx[np.linspace(0,len(idx)-1,max_per).astype(int)]
            for j in idx:
                r=(float(values[j])/scale)*channel_weight*float(window.weight)
                residuals.append(r)
                detail.append({"source":f"strip:{canonical}","x":float(x[j]),"x_domain":"distance_ft","window":window.name,"observed":float(result.observed[canonical][j]),"predicted":float(result.modeled[canonical][j]),"normalized_residual":float(r)})
    return residuals,detail


_TIMING_FIELDS = [
    ("sixty_ft_s", 0.015),
    ("three_thirty_ft_s", 0.020),
    ("eighth_mile_s", 0.025),
    ("eighth_mile_mph", 0.50),
    ("thousand_ft_s", 0.030),
    ("quarter_mile_s", 0.040),
    ("quarter_mile_mph", 0.60),
]


def _timing_residuals(obs: TimingData, pred: TimingData, field_weights: Optional[Dict[str,float]] = None) -> Tuple[List[float], List[Dict[str, Any]]]:
    residuals: List[float] = []
    detail: List[Dict[str, Any]] = []
    for field, scale in _TIMING_FIELDS:
        weight=float((field_weights or {}).get(field,1.0))
        if weight <= 0: continue
        o = getattr(obs, field)
        p = getattr(pred, field)
        if o is None:
            continue
        if p is None:
            r = 100.0 * weight
            residuals.append(r)
            detail.append({
                "source": f"timing:{field}", "x": field, "observed": float(o),
                "predicted": np.nan, "normalized_residual": float(r),
            })
            continue
        r = ((float(p) - float(o)) / scale) * weight
        residuals.append(r)
        detail.append({
            "source": f"timing:{field}",
            "x": field,
            "observed": float(o),
            "predicted": float(p),
            "normalized_residual": float(r),
        })
    return residuals, detail


def fit_vehicle(
    base_vehicle: VehicleConfig,
    runs: Sequence[FitRun],
    unknowns: Sequence[str],
    *,
    parameter_overrides: Optional[Dict[str, Dict[str, float]]] = None,
    nuisance_terms: Sequence[str] = (),
    max_nfev: int = 120,
    fit_dt_s: float = 0.010,
    final_dt_s: float = 0.0025,
) -> FitResult:
    if not runs:
        raise ValueError("At least one run is required for inverse fitting.")
    if not unknowns:
        raise ValueError("Select at least one unknown parameter to estimate.")
    if not any(run.timing.count() > 0 or run.telemetry is not None for run in runs):
        raise ValueError("No measured timing or telemetry was supplied.")

    shared_specs = make_parameter_specs(unknowns, base_vehicle)
    nuisance_specs = make_run_nuisance_specs(runs, nuisance_terms)
    specs = shared_specs + nuisance_specs
    for spec in specs:
        ov = (parameter_overrides or {}).get(spec.name, {})
        spec.initial = float(ov.get("initial", spec.initial))
        spec.lower = float(ov.get("lower", spec.lower))
        spec.upper = float(ov.get("upper", spec.upper))
        if not spec.lower < spec.upper:
            raise ValueError(f"Invalid bounds for {spec.name}")
        spec.initial = min(spec.upper, max(spec.lower, spec.initial))

    x0 = np.array([s.initial for s in specs], dtype=float)
    lo = np.array([s.lower for s in specs], dtype=float)
    hi = np.array([s.upper for s in specs], dtype=float)

    last_detail: List[Dict[str, Any]] = []

    def objective(x: np.ndarray, detail: bool = False):
        nonlocal last_detail
        v, knobs = _apply_parameters(base_vehicle, specs, x)
        residuals: List[float] = []
        details: List[Dict[str, Any]] = []
        for run_idx, run in enumerate(runs):
            try:
                run_vehicle = copy.deepcopy(v)
                run_vehicle.traction_index = max(1.0, min(10.0, run_vehicle.traction_index + _run_nuisance_value(knobs, run_idx, "traction_delta", 0.0)))
                run_vehicle.rollout_in = max(0.0, run_vehicle.rollout_in + _run_nuisance_value(knobs, run_idx, "rollout_delta_in", 0.0))
                run_power = knobs["power_scale"] * _run_nuisance_value(knobs, run_idx, "power_scale", 1.0)
                sim = simulate(
                    run_vehicle,
                    run.environment,
                    power_scale=run_power,
                    curve_multipliers=knobs["curve_multipliers"],
                    efficiency_scale=knobs["efficiency_scale"],
                    shift_rpm_offset=knobs["shift_rpm_offset"],
                    options=SolverOptions(dt_s=fit_dt_s),
                )
            except Exception:
                # Keep optimizer alive if a trial point becomes numerically bad.
                n = max(8, run.timing.count() + (20 if run.telemetry is not None else 0))
                residuals.extend([100.0] * n)
                continue

            tr, td = _timing_residuals(run.timing, sim.timing, run.evidence.timing_weights if run.evidence else None)
            residuals.extend([r * run.timing_weight for r in tr])
            for row in td:
                row["run"] = run.name
                row["normalized_residual"] *= run.timing_weight
                details.append(row)
            if run.telemetry is not None:
                if run.evidence and run.evidence.telemetry_domain == "distance":
                    rr, rd = _telemetry_distance_residuals(run.telemetry, sim, run.evidence)
                else:
                    rr, rd = _telemetry_residuals(run.telemetry, sim.trace, max_points=(run.evidence.max_points if run.evidence else 90), channel_weights=(run.evidence.telemetry_weights if run.evidence else None), channel_scales=(run.evidence.telemetry_scales if run.evidence else None))
                residuals.extend([r * run.telemetry_weight for r in rr])
                for row in rd:
                    row["run"] = run.name
                    row["normalized_residual"] *= run.telemetry_weight
                    details.append(row)

        # Weak regularization on the local torque-curve multipliers prevents a
        # perfectly flexible curve from fitting noise point-by-point.
        for spec, value in zip(specs, x):
            if spec.name.startswith("curve_node_"):
                residuals.append((float(value) - 1.0) / 0.20)
                details.append({"run": "regularization", "source": spec.name, "x": spec.name, "observed": 1.0, "predicted": float(value), "normalized_residual": residuals[-1]})
            elif spec.name.startswith("run__"):
                if spec.name.endswith("__power_scale"):
                    center, sigma = 1.0, 0.03
                elif spec.name.endswith("__traction_delta"):
                    center, sigma = 0.0, 0.50
                elif spec.name.endswith("__rollout_delta_in"):
                    center, sigma = 0.0, 0.50
                else:
                    continue
                residuals.append((float(value) - center) / sigma)
                details.append({"run": "regularization", "source": spec.name, "x": spec.name, "observed": center, "predicted": float(value), "normalized_residual": residuals[-1]})

        if not residuals:
            raise ValueError("No usable observations found. Add official timing or map telemetry channels including time plus speed/RPM.")
        last_detail = details
        arr = np.asarray(residuals, dtype=float)
        arr[~np.isfinite(arr)] = 100.0
        return (arr, details) if detail else arr

    # Validate initial observation count before entering scipy.
    r0 = objective(x0)
    if len(r0) < len(specs):
        raise ValueError(
            f"Only {len(r0)} independent residuals are available for {len(specs)} unknowns. "
            "Provide more timing/telemetry data or estimate fewer variables."
        )

    res = least_squares(
        objective,
        x0,
        bounds=(lo, hi),
        x_scale=np.maximum(np.abs(x0), (hi - lo) * 0.15),
        max_nfev=int(max_nfev),
        loss="soft_l1",
        f_scale=1.5,
        verbose=0,
    )

    optimized_raw, knobs = _apply_parameters(base_vehicle, specs, res.x)
    optimized_vehicle = _materialize_vehicle(optimized_raw, knobs)
    final_predictions: Dict[str, Any] = {}
    final_details: List[Dict[str, Any]] = []
    for run_idx, run in enumerate(runs):
        run_vehicle = copy.deepcopy(optimized_vehicle)
        run_vehicle.traction_index = max(1.0, min(10.0, run_vehicle.traction_index + _run_nuisance_value(knobs, run_idx, "traction_delta", 0.0)))
        run_vehicle.rollout_in = max(0.0, run_vehicle.rollout_in + _run_nuisance_value(knobs, run_idx, "rollout_delta_in", 0.0))
        run_power = _run_nuisance_value(knobs, run_idx, "power_scale", 1.0)
        sim = simulate(
            run_vehicle,
            run.environment,
            power_scale=run_power,
            options=SolverOptions(dt_s=final_dt_s),
        )
        final_predictions[run.name] = sim
        _, td = _timing_residuals(run.timing, sim.timing, run.evidence.timing_weights if run.evidence else None)
        for row in td:
            row["run"] = run.name
            final_details.append(row)
        if run.telemetry is not None:
            if run.evidence and run.evidence.telemetry_domain == "distance":
                _, rd = _telemetry_distance_residuals(run.telemetry, sim, run.evidence)
            else:
                _, rd = _telemetry_residuals(run.telemetry, sim.trace, max_points=(run.evidence.max_points if run.evidence else 90), channel_weights=(run.evidence.telemetry_weights if run.evidence else None), channel_scales=(run.evidence.telemetry_scales if run.evidence else None))
            for row in rd:
                row["run"] = run.name
                final_details.append(row)

    # Second-opinion validation with the source-faithful Quarter Pro engine.
    # The inverse optimizer intentionally uses the smoother fixed-step engine;
    # this pass exposes solutions that only look good because of approximation
    # error in that optimization model.
    reference_predictions: Dict[str, Any] = {}
    reference_details: List[Dict[str, Any]] = []
    for run_idx, run in enumerate(runs):
        run_vehicle = copy.deepcopy(optimized_vehicle)
        run_vehicle.traction_index = max(1.0, min(10.0, run_vehicle.traction_index + _run_nuisance_value(knobs, run_idx, "traction_delta", 0.0)))
        run_vehicle.rollout_in = max(0.0, run_vehicle.rollout_in + _run_nuisance_value(knobs, run_idx, "rollout_delta_in", 0.0))
        run_power = _run_nuisance_value(knobs, run_idx, "power_scale", 1.0)
        try:
            ref_sim = simulate_legacy_reference(run_vehicle, run.environment, power_scale=run_power)
            reference_predictions[run.name] = ref_sim
            _, td = _timing_residuals(run.timing, ref_sim.timing, run.evidence.timing_weights if run.evidence else None)
            for row in td:
                row["run"] = run.name
                row["engine"] = "Quarter Pro reference"
                reference_details.append(row)
            if run.telemetry is not None:
                if run.evidence and run.evidence.telemetry_domain == "distance":
                    _, rd = _telemetry_distance_residuals(run.telemetry, ref_sim, run.evidence)
                else:
                    _, rd = _telemetry_residuals(run.telemetry, ref_sim.trace, max_points=(run.evidence.max_points if run.evidence else 90), channel_weights=(run.evidence.telemetry_weights if run.evidence else None), channel_scales=(run.evidence.telemetry_scales if run.evidence else None))
                for row in rd:
                    row["run"] = run.name
                    row["engine"] = "Quarter Pro reference"
                    reference_details.append(row)
        except Exception as exc:
            reference_details.append({
                "run": run.name,
                "engine": "Quarter Pro reference",
                "source": "reference_solver",
                "x": "validation",
                "observed": np.nan,
                "predicted": np.nan,
                "normalized_residual": np.nan,
                "note": str(exc),
            })
    reference_residuals = pd.DataFrame(reference_details)
    if not reference_residuals.empty and "normalized_residual" in reference_residuals.columns:
        reference_residuals["abs_normalized_residual"] = reference_residuals["normalized_residual"].abs()
        reference_residuals = reference_residuals.sort_values("abs_normalized_residual", ascending=False, na_position="last").reset_index(drop=True)

    # Local covariance / correlation around optimum.
    npar = len(specs)
    m = len(res.fun)
    std = np.full(npar, np.nan)
    corr = np.eye(npar)
    if res.jac is not None and m > npar:
        try:
            j = np.asarray(res.jac, dtype=float)
            jtj_inv = np.linalg.pinv(j.T @ j, rcond=1e-10)
            sigma2 = max(1e-12, float(np.sum(res.fun ** 2)) / max(1, m - npar))
            cov = jtj_inv * sigma2
            std = np.sqrt(np.maximum(0.0, np.diag(cov)))
            denom = np.outer(std, std)
            with np.errstate(divide="ignore", invalid="ignore"):
                corr = np.divide(cov, denom, out=np.eye(npar), where=denom > 0)
                corr = np.clip(corr, -1.0, 1.0)
        except Exception:
            pass

    estimate_rows: List[Dict[str, Any]] = []
    notes: List[str] = []
    for i, spec in enumerate(specs):
        value = float(res.x[i])
        se = float(std[i]) if np.isfinite(std[i]) else np.nan
        low95 = value - 1.96 * se if np.isfinite(se) else np.nan
        hi95 = value + 1.96 * se if np.isfinite(se) else np.nan
        low95 = max(spec.lower, low95) if np.isfinite(low95) else np.nan
        hi95 = min(spec.upper, hi95) if np.isfinite(hi95) else np.nan
        maxcorr = float(np.nanmax(np.abs(np.delete(corr[i], i)))) if npar > 1 else 0.0
        span = spec.upper - spec.lower
        uncertainty_frac = (3.92 * se / span) if np.isfinite(se) and span > 0 else np.inf
        at_bound = abs(value - spec.lower) < 0.01 * span or abs(value - spec.upper) < 0.01 * span
        if at_bound or uncertainty_frac > 0.45 or maxcorr > 0.97:
            ident = "Weak"
        elif uncertainty_frac > 0.20 or maxcorr > 0.90:
            ident = "Moderate"
        else:
            ident = "Good"
        if spec.name.startswith("run__"):
            _, idx_text, term = spec.name.split("__", 2)
            run_name = runs[int(idx_text)].name if int(idx_text) < len(runs) else f"Run {idx_text}"
            display_parameter = f"{run_name}: {term}"
            scope = "run-specific nuisance"
        else:
            display_parameter = spec.name
            scope = "shared vehicle"
        estimate_rows.append({
            "parameter": display_parameter,
            "internal_name": spec.name,
            "scope": scope,
            "estimate": value,
            "std_error": se,
            "95%_low": low95,
            "95%_high": hi95,
            "lower_bound": spec.lower,
            "upper_bound": spec.upper,
            "max_abs_correlation": maxcorr,
            "identifiability": ident,
            "description": spec.description,
        })
        if ident == "Weak" and not spec.name.startswith("run__"):
            notes.append(f"{spec.name}: weakly identified; add another independent measurement/run or fix a correlated parameter.")

    names = []
    for spec in specs:
        if spec.name.startswith("run__"):
            _, idx_text, term = spec.name.split("__", 2)
            run_name = runs[int(idx_text)].name if int(idx_text) < len(runs) else f"Run {idx_text}"
            names.append(f"{run_name}: {term}")
        else:
            names.append(spec.name)
    corr_df = pd.DataFrame(corr, index=names, columns=names)
    residual_df = pd.DataFrame(final_details)
    if not residual_df.empty:
        residual_df["abs_normalized_residual"] = residual_df["normalized_residual"].abs()
        residual_df = residual_df.sort_values("abs_normalized_residual", ascending=False).reset_index(drop=True)

    # Physics-specific identifiability reminders.
    if "cda_ft2" in unknowns:
        notes.append("CdA is estimated as one combined term. Separating Cd from frontal area requires an independent area measurement or aero test.")
    if "power_scale" in unknowns and ("efficiency_scale" in unknowns or "final_drive_efficiency" in unknowns):
        notes.append("Power scale and driveline efficiency can be strongly confounded without an independent torque/power anchor.")
    if "final_drive_ratio" in unknowns and "tire_diameter_in" in unknowns:
        notes.append("Final-drive ratio and effective tire circumference are strongly coupled. Driveshaft RPM + true vehicle speed or a measured tire rollout helps separate them.")
    if "traction_index" in unknowns and ("cg_height_in" in unknowns or "static_front_weight_lb" in unknowns):
        notes.append("Traction index and rear-axle load transfer can mimic each other near the traction limit. Scale/CG measurements are valuable anchors.")
    if any(n.startswith("curve_node_") for n in unknowns) and not any(r.telemetry and "engine_rpm" in r.telemetry.channel_map for r in runs):
        notes.append("Torque-curve shape is much better identified when engine RPM is present in telemetry; timing slips alone mostly constrain integrated power.")
    if nuisance_terms:
        notes.append("Run-specific nuisance terms are regularized toward zero/no-correction so isolated pass variation is less likely to distort the shared vehicle model. Inspect their fitted values; large corrections usually mean a missing physical input or a genuinely different run configuration.")

    return FitResult(
        success=bool(res.success),
        message=str(res.message),
        estimates=pd.DataFrame(estimate_rows),
        correlation=corr_df,
        residuals=residual_df,
        optimized_vehicle=optimized_vehicle,
        optimizer_result=res,
        predicted_runs=final_predictions,
        reference_predictions=reference_predictions,
        reference_residuals=reference_residuals,
        identifiability_notes=list(dict.fromkeys(notes)),
    )
