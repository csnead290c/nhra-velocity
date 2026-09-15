from __future__ import annotations

"""Repeatable multi-Run inverse reconstruction studies.

A FitStudyDefinition describes what is shared across the vehicle and what
Run-specific nuisance freedom is allowed.  Raw telemetry remains owned by the
Run/Asset system; .nhrafit packages carry only definitions, Run references and
derived fit results/provenance.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence
import json
import math

import numpy as np
import pandas as pd

from .branding import PRODUCT_VERSION
from .product_manifest import FIT_STUDY_FORMAT_VERSION, upstream_references
from .inverse import FitRun, FitResult, fit_vehicle
from .models import VehicleConfig


@dataclass
class FitStudyDefinition:
    name: str = "Joint reconstruction"
    shared_unknowns: List[str] = field(default_factory=lambda:["power_scale"])
    nuisance_terms: List[str] = field(default_factory=list)
    parameter_overrides: Dict[str, Dict[str, float]] = field(default_factory=dict)
    max_nfev: int = 120
    fit_dt_s: float = 0.010
    final_dt_s: float = 0.0025
    notes: str = ""

    def __post_init__(self):
        if not self.shared_unknowns:
            raise ValueError("Joint fit study needs at least one shared unknown")
        if self.max_nfev < 1: raise ValueError("max_nfev must be positive")
        if self.fit_dt_s <= 0 or self.final_dt_s <= 0: raise ValueError("fit time steps must be positive")

    def to_dict(self)->Dict[str,Any]:
        return {"name":self.name,"shared_unknowns":list(self.shared_unknowns),"nuisance_terms":list(self.nuisance_terms),
                "parameter_overrides":self.parameter_overrides,"max_nfev":int(self.max_nfev),
                "fit_dt_s":float(self.fit_dt_s),"final_dt_s":float(self.final_dt_s),"notes":self.notes}

    @classmethod
    def from_dict(cls,v:Mapping[str,Any])->"FitStudyDefinition":
        return cls(name=str(v.get("name") or "Joint reconstruction"),shared_unknowns=[str(x) for x in v.get("shared_unknowns",["power_scale"])],
                   nuisance_terms=[str(x) for x in v.get("nuisance_terms",[])],parameter_overrides={str(k):dict(x) for k,x in (v.get("parameter_overrides") or {}).items()},
                   max_nfev=int(v.get("max_nfev",120)),fit_dt_s=float(v.get("fit_dt_s",.010)),final_dt_s=float(v.get("final_dt_s",.0025)),notes=str(v.get("notes") or ""))


def _clean_scalar(v:Any)->Any:
    if isinstance(v,(np.integer,)): return int(v)
    if isinstance(v,(np.floating,)): return None if not math.isfinite(float(v)) else float(v)
    if isinstance(v,float): return None if not math.isfinite(v) else v
    return v


def _records(df:pd.DataFrame)->List[Dict[str,Any]]:
    if df is None or df.empty:return []
    return [{str(k):_clean_scalar(v) for k,v in row.items()} for row in df.to_dict(orient="records")]


def _matrix(df:pd.DataFrame)->Dict[str,Any]:
    if df is None or df.empty:return {"index":[],"columns":[],"values":[]}
    return {"index":[str(x) for x in df.index],"columns":[str(x) for x in df.columns],
            "values":[[_clean_scalar(x) for x in row] for row in df.to_numpy().tolist()]}


def _evidence_group(source: str) -> str:
    text=str(source or "")
    if text.startswith("timing:"): return "official_timing"
    if text.startswith("strip:"): return "downtrack_telemetry"
    if text.startswith("telemetry:"): return "time_telemetry"
    if text.startswith("run__") or text.startswith("curve_node_"): return "regularization"
    return "other"


def summarize_fit_residuals(df: pd.DataFrame) -> Dict[str, Any]:
    """Compact objective-quality decomposition for audit/reporting."""
    if df is None or df.empty or "normalized_residual" not in df.columns:
        return {"overall":{},"by_run":[],"by_source":[],"by_window":[]}
    w=df.copy()
    w["normalized_residual"]=pd.to_numeric(w["normalized_residual"],errors="coerce")
    w=w[np.isfinite(w["normalized_residual"].to_numpy(dtype=float))].copy()
    if w.empty:return {"overall":{},"by_run":[],"by_source":[],"by_window":[]}
    w["sq"]=w["normalized_residual"]**2
    w["abs"]=w["normalized_residual"].abs()
    w["evidence_group"]=[_evidence_group(x) for x in w.get("source",pd.Series([""]*len(w)))]
    total_sse=float(w["sq"].sum())
    def rows(group_cols):
        out=[]
        for key,g in w.groupby(group_cols,dropna=False,sort=False):
            keys=key if isinstance(key,tuple) else (key,)
            row={str(k):_clean_scalar(v) for k,v in zip(group_cols,keys)}
            sse=float(g["sq"].sum())
            row.update({
                "count":int(len(g)),
                "rms_normalized_residual":float(np.sqrt(g["sq"].mean())),
                "mean_abs_normalized_residual":float(g["abs"].mean()),
                "max_abs_normalized_residual":float(g["abs"].max()),
                "mean_signed_normalized_residual":float(g["normalized_residual"].mean()),
                "sum_squared_normalized_residual":sse,
                "objective_fraction":float(sse/total_sse) if total_sse>0 else 0.0,
            })
            out.append(row)
        return out
    by_window=[]
    if "window" in w.columns:
        ww=w[w["window"].notna()].copy()
        if not ww.empty:
            # use the same helper on a filtered frame without mutating the original
            for key,g in ww.groupby(["run","source","window"],dropna=False,sort=False):
                sse=float(g["sq"].sum()); by_window.append({
                    "run":str(key[0]),"source":str(key[1]),"window":str(key[2]),"count":int(len(g)),
                    "rms_normalized_residual":float(np.sqrt(g["sq"].mean())),
                    "mean_abs_normalized_residual":float(g["abs"].mean()),
                    "max_abs_normalized_residual":float(g["abs"].max()),
                    "sum_squared_normalized_residual":sse,
                    "objective_fraction":float(sse/total_sse) if total_sse>0 else 0.0,
                })
    overall={
        "count":int(len(w)),
        "rms_normalized_residual":float(np.sqrt(w["sq"].mean())),
        "mean_abs_normalized_residual":float(w["abs"].mean()),
        "max_abs_normalized_residual":float(w["abs"].max()),
        "sum_squared_normalized_residual":total_sse,
    }
    return {"overall":overall,"by_run":rows(["run"]),"by_source":rows(["run","evidence_group","source"]),"by_window":by_window}


def parameter_diagnostics(estimates: pd.DataFrame, correlation: pd.DataFrame) -> List[Dict[str, Any]]:
    if estimates is None or estimates.empty:return []
    out=[]
    for _,r in estimates.iterrows():
        name=str(r.get("parameter") or r.get("internal_name") or "")
        top_name=""; top_corr=0.0
        if correlation is not None and not correlation.empty and name in correlation.index:
            vals=correlation.loc[name].drop(labels=[name],errors="ignore").abs().dropna()
            if not vals.empty:
                top_name=str(vals.idxmax()); top_corr=float(vals.max())
        out.append({
            "parameter":name,"internal_name":str(r.get("internal_name") or ""),"scope":str(r.get("scope") or ""),
            "estimate":_clean_scalar(r.get("estimate")),"std_error":_clean_scalar(r.get("std_error")),
            "95%_low":_clean_scalar(r.get("95%_low")),"95%_high":_clean_scalar(r.get("95%_high")),
            "identifiability":str(r.get("identifiability") or ""),
            "top_correlated_parameter":top_name,"top_abs_correlation":top_corr,
        })
    return out


@dataclass
class FitStudyPackage:
    definition: FitStudyDefinition
    base_vehicle: Dict[str,Any]
    optimized_vehicle: Dict[str,Any]
    runs: List[Dict[str,Any]]
    estimates: List[Dict[str,Any]]
    correlation: Dict[str,Any]
    residuals: List[Dict[str,Any]]
    reference_residuals: List[Dict[str,Any]]
    identifiability_notes: List[str]
    residual_summary: Dict[str,Any] = field(default_factory=dict)
    reference_residual_summary: Dict[str,Any] = field(default_factory=dict)
    parameter_diagnostics: List[Dict[str,Any]] = field(default_factory=list)
    profiles: Dict[str,Any] = field(default_factory=dict)
    run_influence: Dict[str,Any] = field(default_factory=dict)
    success: bool = False
    message: str = ""
    software_version: str = PRODUCT_VERSION
    created_at_utc: str = field(default_factory=lambda:datetime.now(timezone.utc).isoformat())
    upstream_references: List[Dict[str,Any]] = field(default_factory=lambda:[r.to_dict() for r in upstream_references()])
    format_version: int = FIT_STUDY_FORMAT_VERSION

    def to_dict(self)->Dict[str,Any]:
        return {"format":"nhra-fit-study","format_version":self.format_version,"software_version":self.software_version,
                "created_at_utc":self.created_at_utc,"definition":self.definition.to_dict(),"base_vehicle":self.base_vehicle,
                "optimized_vehicle":self.optimized_vehicle,"runs":self.runs,"estimates":self.estimates,"correlation":self.correlation,
                "residuals":self.residuals,"reference_residuals":self.reference_residuals,"identifiability_notes":self.identifiability_notes,
                "residual_summary":self.residual_summary,"reference_residual_summary":self.reference_residual_summary,
                "parameter_diagnostics":self.parameter_diagnostics,"profiles":self.profiles,"run_influence":self.run_influence,
                "upstream_references":self.upstream_references,
                "success":bool(self.success),"message":self.message}

    @classmethod
    def from_dict(cls,v:Mapping[str,Any])->"FitStudyPackage":
        if v.get("format") not in {None,"nhra-fit-study"}: raise ValueError("Not an NHRA fit-study package")
        return cls(definition=FitStudyDefinition.from_dict(v.get("definition") or {}),base_vehicle=dict(v.get("base_vehicle") or {}),
                   optimized_vehicle=dict(v.get("optimized_vehicle") or {}),runs=list(v.get("runs") or []),estimates=list(v.get("estimates") or []),
                   correlation=dict(v.get("correlation") or {}),residuals=list(v.get("residuals") or []),reference_residuals=list(v.get("reference_residuals") or []),
                   identifiability_notes=[str(x) for x in v.get("identifiability_notes",[])],
                   residual_summary=dict(v.get("residual_summary") or {}),reference_residual_summary=dict(v.get("reference_residual_summary") or {}),
                   parameter_diagnostics=list(v.get("parameter_diagnostics") or []),profiles=dict(v.get("profiles") or {}),
                   run_influence=dict(v.get("run_influence") or {}),upstream_references=list(v.get("upstream_references") or []),success=bool(v.get("success",False)),message=str(v.get("message") or ""),
                   software_version=str(v.get("software_version") or ""),created_at_utc=str(v.get("created_at_utc") or ""),format_version=int(v.get("format_version",1)))


def run_joint_fit_study(base_vehicle:VehicleConfig,runs:Sequence[FitRun],definition:FitStudyDefinition)->tuple[FitResult,FitStudyPackage]:
    if not runs: raise ValueError("Joint fit study needs at least one Run")
    # A study-level nuisance list defines the vocabulary; individual FitRuns can
    # opt out or limit which of those local corrections they are allowed to use.
    nuisance=list(dict.fromkeys(list(definition.nuisance_terms)+[x for r in runs for x in (r.nuisance_terms or [])]))
    fit=fit_vehicle(base_vehicle,runs,definition.shared_unknowns,parameter_overrides=definition.parameter_overrides,
                    nuisance_terms=nuisance,max_nfev=definition.max_nfev,fit_dt_s=definition.fit_dt_s,final_dt_s=definition.final_dt_s)
    run_rows=[]
    for r in runs:
        run_rows.append({"name":r.name,"source_run_id":r.source_run_id,"role":r.role,
                         "timing_weight":float(r.timing_weight),"telemetry_weight":float(r.telemetry_weight),
                         "nuisance_terms":None if r.nuisance_terms is None else list(r.nuisance_terms),
                         "evidence":r.evidence.to_dict() if r.evidence else None,
                         "environment":r.environment.to_dict(),"timing":r.timing.to_dict(),
                         "telemetry_name":r.telemetry.name if r.telemetry is not None else ""})
    package=FitStudyPackage(definition=definition,base_vehicle=base_vehicle.to_dict(),optimized_vehicle=fit.optimized_vehicle.to_dict(),runs=run_rows,
                            estimates=_records(fit.estimates),correlation=_matrix(fit.correlation),residuals=_records(fit.residuals),
                            reference_residuals=_records(fit.reference_residuals),identifiability_notes=list(fit.identifiability_notes),
                            residual_summary=summarize_fit_residuals(fit.residuals),
                            reference_residual_summary=summarize_fit_residuals(fit.reference_residuals),
                            parameter_diagnostics=parameter_diagnostics(fit.estimates,fit.correlation),
                            success=fit.success,message=fit.message)
    return fit,package


def save_fit_study_package(path:str|Path,package:FitStudyPackage)->Path:
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(package.to_dict(),indent=2,allow_nan=False),encoding="utf-8");return p


def load_fit_study_package(path:str|Path)->FitStudyPackage:
    return FitStudyPackage.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
