from __future__ import annotations

"""Repeatable RSA / Quarter Pro simulation studies.

The study layer keeps forward scenario sweeps, inverse fitting and observed-vs-
predicted validation connected to the same VehicleConfig/Environment model used
elsewhere in NHRA Tech Data.  It is intentionally headless so the desktop UI,
batch jobs and future Tech Services derived-analysis bundles can share one
implementation.
"""

from dataclasses import asdict, dataclass, field
from itertools import product
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from .inverse import FitRun, FitResult, fit_vehicle
from .legacy_reference import simulate_legacy_reference
from .models import Environment, SimulationResult, TimingData, VehicleConfig
from .physics import SolverOptions, simulate
from .branding import PRODUCT_VERSION
from .product_manifest import SIMULATION_STUDY_FORMAT_VERSION, upstream_references


TIMING_FIELDS = (
    ("60_ft_s", "sixty_ft_s"),
    ("330_ft_s", "three_thirty_ft_s"),
    ("660_ft_s", "eighth_mile_s"),
    ("660_mph", "eighth_mile_mph"),
    ("1000_ft_s", "thousand_ft_s"),
    ("1320_ft_s", "quarter_mile_s"),
    ("1320_mph", "quarter_mile_mph"),
)


@dataclass(frozen=True)
class ScenarioAxis:
    parameter: str
    values: tuple[float, ...]
    mode: str = "absolute"  # absolute | delta | scale
    label: str = ""

    def __post_init__(self):
        if not self.parameter.strip():
            raise ValueError("Scenario axis requires a parameter")
        if not self.values:
            raise ValueError(f"Scenario axis {self.parameter!r} requires at least one value")
        if self.mode not in {"absolute", "delta", "scale"}:
            raise ValueError("Scenario axis mode must be absolute, delta or scale")

    def to_dict(self) -> dict[str, Any]:
        return {"parameter": self.parameter, "values": list(self.values), "mode": self.mode, "label": self.label}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScenarioAxis":
        return cls(
            parameter=str(value.get("parameter") or ""),
            values=tuple(float(x) for x in (value.get("values") or ())),
            mode=str(value.get("mode") or "absolute"),
            label=str(value.get("label") or ""),
        )


@dataclass
class SimulationStudyDefinition:
    name: str = "Simulation Study"
    engine: str = "reference"  # reference | smooth
    axes: list[ScenarioAxis] = field(default_factory=list)
    include_baseline: bool = True
    max_cases: int = 250
    smooth_dt_s: float = 0.0025
    notes: str = ""

    def __post_init__(self):
        if self.engine not in {"reference", "smooth"}:
            raise ValueError("engine must be 'reference' or 'smooth'")
        if self.max_cases < 1:
            raise ValueError("max_cases must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "nhra-simulation-study",
            "version": SIMULATION_STUDY_FORMAT_VERSION,
            "name": self.name,
            "engine": self.engine,
            "axes": [a.to_dict() for a in self.axes],
            "include_baseline": bool(self.include_baseline),
            "max_cases": int(self.max_cases),
            "smooth_dt_s": float(self.smooth_dt_s),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationStudyDefinition":
        return cls(
            name=str(value.get("name") or "Simulation Study"),
            engine=str(value.get("engine") or "reference"),
            axes=[ScenarioAxis.from_dict(x) for x in (value.get("axes") or ())],
            include_baseline=bool(value.get("include_baseline", True)),
            max_cases=int(value.get("max_cases") or 250),
            smooth_dt_s=float(value.get("smooth_dt_s") or 0.0025),
            notes=str(value.get("notes") or ""),
        )

    @classmethod
    def load(cls, path: str | Path) -> "SimulationStudyDefinition":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> Path:
        target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(self.to_dict(),indent=2),encoding="utf-8")
        return target


@dataclass
class SimulationStudyPackage:
    definition: SimulationStudyDefinition
    vehicle: VehicleConfig
    environment: Environment
    result_rows: list[dict[str, Any]] = field(default_factory=list)
    source_run_id: str = ""
    source_run_name: str = ""
    software_version: str = PRODUCT_VERSION
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    upstream_references: list[dict[str, Any]] = field(default_factory=lambda:[r.to_dict() for r in upstream_references()])

    def to_dict(self) -> dict[str, Any]:
        return {
            "format":"nhra-simulation-study-package","version":SIMULATION_STUDY_FORMAT_VERSION,
            "software_version":self.software_version,"created_at_utc":self.created_at_utc,
            "source_run_id":self.source_run_id,"source_run_name":self.source_run_name,
            "definition":self.definition.to_dict(),"vehicle":self.vehicle.to_dict(),
            "environment":self.environment.to_dict(),"results":list(self.result_rows),
            "upstream_references":list(self.upstream_references),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationStudyPackage":
        return cls(
            definition=SimulationStudyDefinition.from_dict(value.get("definition") or {}),
            vehicle=VehicleConfig.from_dict(value.get("vehicle") or {}),
            environment=Environment.from_dict(value.get("environment") or {}),
            result_rows=list(value.get("results") or []),
            source_run_id=str(value.get("source_run_id") or ""),source_run_name=str(value.get("source_run_name") or ""),
            software_version=str(value.get("software_version") or ""),created_at_utc=str(value.get("created_at_utc") or ""),
            upstream_references=list(value.get("upstream_references") or []),
        )

    def save(self,path: str | Path) -> Path:
        target=Path(path);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(self.to_dict(),indent=2),encoding="utf-8");return target

    @classmethod
    def load(cls,path: str | Path) -> "SimulationStudyPackage":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass
class SimulationStudyResult:
    definition: SimulationStudyDefinition
    table: pd.DataFrame
    baseline_result: SimulationResult


def _get_parameter(vehicle: VehicleConfig, parameter: str) -> float:
    if parameter == "power_scale" or parameter == "efficiency_scale" or parameter == "shift_rpm_offset":
        return 1.0 if parameter != "shift_rpm_offset" else 0.0
    if parameter == "cda_ft2":
        return float(vehicle.cda_ft2)
    if parameter == "cla_ft2":
        return float(vehicle.lift_coefficient * vehicle.frontal_area_ft2)
    if parameter.startswith("gear_ratio_"):
        idx=int(parameter.rsplit("_",1)[1])-1
        return float(vehicle.gear_ratios[idx])
    if parameter.startswith("shift_rpm_"):
        idx=int(parameter.rsplit("_",1)[1])-1
        return float(vehicle.shift_rpms[idx])
    if not hasattr(vehicle, parameter):
        raise KeyError(f"Unsupported simulation-study parameter: {parameter}")
    value=getattr(vehicle,parameter)
    if value is None:
        raise ValueError(f"Simulation-study parameter {parameter!r} has no baseline value")
    if isinstance(value,(list,tuple,dict)):
        raise ValueError(f"Use an indexed simulation-study parameter for {parameter!r}")
    return float(value)


def _axis_absolute_value(vehicle: VehicleConfig, axis: ScenarioAxis, raw: float) -> float:
    base=_get_parameter(vehicle,axis.parameter)
    if axis.mode == "absolute": return float(raw)
    if axis.mode == "delta": return base + float(raw)
    return base * float(raw)


def _apply_study_values(base: VehicleConfig, assignments: Mapping[str,float]) -> tuple[VehicleConfig,dict[str,float]]:
    v=VehicleConfig.from_dict(base.to_dict())
    knobs={"power_scale":1.0,"efficiency_scale":1.0,"shift_rpm_offset":0.0}
    for name,value in assignments.items():
        value=float(value)
        if name in knobs:
            knobs[name]=value;continue
        if name == "cda_ft2":
            v.drag_coefficient=value/max(float(v.frontal_area_ft2),1e-9);continue
        if name == "cla_ft2":
            v.lift_coefficient=value/max(float(v.frontal_area_ft2),1e-9);continue
        if name.startswith("gear_ratio_"):
            idx=int(name.rsplit("_",1)[1])-1
            if not 0 <= idx < len(v.gear_ratios): raise KeyError(name)
            v.gear_ratios[idx]=value;continue
        if name.startswith("shift_rpm_"):
            idx=int(name.rsplit("_",1)[1])-1
            if not 0 <= idx < len(v.shift_rpms): raise KeyError(name)
            v.shift_rpms[idx]=value;continue
        if not hasattr(v,name): raise KeyError(f"Unsupported simulation-study parameter: {name}")
        current=getattr(v,name)
        if isinstance(current,(list,tuple,dict)): raise ValueError(f"Use an indexed parameter for {name!r}")
        setattr(v,name,value)
    return v.normalized(),knobs


def _simulate(vehicle: VehicleConfig, environment: Environment, engine: str, knobs: Mapping[str,float], dt_s: float) -> SimulationResult:
    kwargs=dict(
        power_scale=float(knobs.get("power_scale",1.0)),
        efficiency_scale=float(knobs.get("efficiency_scale",1.0)),
        shift_rpm_offset=float(knobs.get("shift_rpm_offset",0.0)),
    )
    if engine == "reference":
        return simulate_legacy_reference(vehicle,environment,**kwargs)
    return simulate(vehicle,environment,options=SolverOptions(dt_s=float(dt_s)),**kwargs)


def _timing_payload(timing: TimingData) -> dict[str,Optional[float]]:
    return {label:(None if getattr(timing,attr) is None else float(getattr(timing,attr))) for label,attr in TIMING_FIELDS}


def run_scenario_sweep(
    vehicle: VehicleConfig,
    environment: Environment,
    definition: SimulationStudyDefinition,
) -> SimulationStudyResult:
    baseline=_simulate(vehicle,environment,definition.engine,{},definition.smooth_dt_s)
    baseline_t=_timing_payload(baseline.timing)
    combos=list(product(*[axis.values for axis in definition.axes])) if definition.axes else [()]
    total=len(combos)+(1 if definition.include_baseline and definition.axes else 0)
    if total > definition.max_cases:
        raise ValueError(f"Study requests {total} cases; max_cases is {definition.max_cases}")
    rows:list[dict[str,Any]]=[]

    def add_case(case_name:str, assignments:Mapping[str,float], raw_values:Mapping[str,float], result:SimulationResult):
        timing=_timing_payload(result.timing)
        row:dict[str,Any]={"case":case_name,"engine":definition.engine}
        for k,v in assignments.items(): row[f"input.{k}"]=float(v)
        for k,v in raw_values.items(): row[f"axis.{k}"]=float(v)
        row.update(timing)
        for label,_ in TIMING_FIELDS:
            b=baseline_t.get(label);p=timing.get(label)
            row[f"delta.{label}"]=np.nan if b is None or p is None else float(p-b)
        for key in ("max_accel_g","traction_limited_steps","static_front_pct","weather_hp_correction"):
            if key in result.diagnostics: row[f"diag.{key}"]=result.diagnostics[key]
        rows.append(row)

    if definition.include_baseline and definition.axes:
        add_case("Baseline",{}, {}, baseline)

    for idx,raw_combo in enumerate(combos,1):
        assignments={axis.parameter:_axis_absolute_value(vehicle,axis,raw) for axis,raw in zip(definition.axes,raw_combo)}
        raw_values={axis.parameter:float(raw) for axis,raw in zip(definition.axes,raw_combo)}
        modified,knobs=_apply_study_values(vehicle,assignments)
        result=_simulate(modified,environment,definition.engine,knobs,definition.smooth_dt_s)
        label=" / ".join(f"{axis.label or axis.parameter}={raw:g}" for axis,raw in zip(definition.axes,raw_combo)) or "Baseline"
        add_case(label,assignments,raw_values,result)
    return SimulationStudyResult(definition,pd.DataFrame(rows),baseline)



def create_scenario_run(
    source_name: str,
    vehicle: VehicleConfig,
    environment: Environment,
    assignments: Mapping[str, float],
    *,
    engine: str = "reference",
    smooth_dt_s: float = 0.0025,
    name: Optional[str] = None,
):
    """Materialize one study case as a normal generated TelemetryRun."""
    from .scenario import generated_run_from_result
    modified,knobs=_apply_study_values(vehicle,assignments)
    result=_simulate(modified,environment,engine,knobs,smooth_dt_s)
    return generated_run_from_result(
        name or f"{source_name} — Simulation",
        result,modified,environment,changes=dict(assignments),source_run_name=source_name,
        power_scale=float(knobs.get("power_scale",1.0)),
    )

def timing_residuals(observed: TimingData, predicted: TimingData, *, run_name: str="Run") -> pd.DataFrame:
    rows=[]
    for label,attr in TIMING_FIELDS:
        obs=getattr(observed,attr);pred=getattr(predicted,attr)
        if obs is None or pred is None: continue
        rows.append({"run":run_name,"measurement":label,"observed":float(obs),"predicted":float(pred),"residual":float(pred-obs)})
    return pd.DataFrame(rows)


def validate_vehicle_against_runs(vehicle: VehicleConfig, runs: Sequence[FitRun], *, engine: str="reference", smooth_dt_s: float=0.0025) -> pd.DataFrame:
    frames=[]
    for run in runs:
        pred=_simulate(vehicle,run.environment,engine,{},smooth_dt_s)
        frames.append(timing_residuals(run.timing,pred.timing,run_name=run.name))
    return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=["run","measurement","observed","predicted","residual"])


def fit_simulation_study(
    vehicle: VehicleConfig,
    runs: Sequence[FitRun],
    unknowns: Sequence[str],
    *,
    nuisance_terms: Sequence[str]=(),
    max_nfev: int=120,
    fit_dt_s: float=0.010,
    final_dt_s: float=0.0025,
) -> FitResult:
    """Multi-run inverse fit entry point for RSA-oriented studies."""
    return fit_vehicle(
        vehicle,runs,unknowns,nuisance_terms=nuisance_terms,max_nfev=max_nfev,
        fit_dt_s=fit_dt_s,final_dt_s=final_dt_s,
    )



def package_study_result(result: SimulationStudyResult, vehicle: VehicleConfig, environment: Environment, *, source_run_id: str="", source_run_name: str="") -> SimulationStudyPackage:
    clean=result.table.replace({np.nan:None}).to_dict(orient="records")
    return SimulationStudyPackage(
        definition=result.definition,vehicle=VehicleConfig.from_dict(vehicle.to_dict()),environment=Environment.from_dict(environment.to_dict()),
        result_rows=clean,source_run_id=source_run_id,source_run_name=source_run_name,
    )

def export_study_table(frame: pd.DataFrame, path: str | Path) -> Path:
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    suffix=target.suffix.lower()
    if suffix == ".xlsx": frame.to_excel(target,index=False)
    elif suffix == ".json": target.write_text(frame.to_json(orient="records",indent=2),encoding="utf-8")
    else: frame.to_csv(target,index=False)
    return target
