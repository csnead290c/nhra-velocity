from __future__ import annotations

"""Practical identifiability tools for joint inverse reconstruction.

The inverse engine uses scipy least_squares with a robust soft-L1 loss.  The
profile scans here therefore report a *profile objective* rather than claiming
an exact statistical likelihood.  A selected shared parameter is forced across
a grid while all remaining allowed parameters/nuisance terms are re-optimized.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence
import copy
import math

import numpy as np
import pandas as pd

from .fit_study import FitStudyDefinition
from .inverse import FitRun, FitResult, fit_vehicle
from .models import VehicleConfig


@dataclass
class ProfileScanResult:
    parameter: str
    optimum: float
    lower_bound: float
    upper_bound: float
    threshold_delta_objective: float
    rows: List[Dict[str, Any]] = field(default_factory=list)
    practical_low: Optional[float] = None
    practical_high: Optional[float] = None
    status: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter":self.parameter,"optimum":float(self.optimum),
            "lower_bound":float(self.lower_bound),"upper_bound":float(self.upper_bound),
            "threshold_delta_objective":float(self.threshold_delta_objective),
            "rows":list(self.rows),"practical_low":self.practical_low,
            "practical_high":self.practical_high,"status":self.status,"note":self.note,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProfileScanResult":
        return cls(
            parameter=str(value.get("parameter") or ""), optimum=float(value.get("optimum")),
            lower_bound=float(value.get("lower_bound")), upper_bound=float(value.get("upper_bound")),
            threshold_delta_objective=float(value.get("threshold_delta_objective",3.84)),
            rows=list(value.get("rows") or []), practical_low=value.get("practical_low"),
            practical_high=value.get("practical_high"), status=str(value.get("status") or ""),
            note=str(value.get("note") or ""),
        )


def _shared_estimate_row(fit: FitResult, parameter: str) -> pd.Series:
    rows=fit.estimates.loc[fit.estimates["internal_name"].astype(str)==str(parameter)]
    if rows.empty:
        raise KeyError(f"Parameter {parameter!r} is not a fitted shared parameter")
    row=rows.iloc[0]
    if str(row.get("scope"))!="shared vehicle":
        raise ValueError("Profile scans currently support shared vehicle parameters only")
    return row


def _nuisance_vocabulary(definition: FitStudyDefinition, runs: Sequence[FitRun]) -> List[str]:
    return list(dict.fromkeys(list(definition.nuisance_terms)+[x for r in runs for x in (r.nuisance_terms or [])]))


def profile_parameter(
    base_vehicle: VehicleConfig,
    runs: Sequence[FitRun],
    definition: FitStudyDefinition,
    baseline_fit: FitResult,
    parameter: str,
    *,
    points: int = 7,
    span_fraction: float = 0.12,
    threshold_delta_objective: float = 3.84,
    max_nfev: Optional[int] = None,
) -> ProfileScanResult:
    if int(points)<3: raise ValueError("Profile scan needs at least three points")
    if float(span_fraction)<=0: raise ValueError("span_fraction must be positive")
    row=_shared_estimate_row(baseline_fit,parameter)
    optimum=float(row["estimate"]); lower=float(row["lower_bound"]); upper=float(row["upper_bound"])
    span=max(upper-lower,1e-12)
    se=float(row.get("std_error",np.nan))
    half=max(float(span_fraction)*span, 4.0*se if math.isfinite(se) else 0.0)
    eps=max(1e-9,span*1e-8)
    scan_low=max(lower+10*eps,optimum-half); scan_high=min(upper-10*eps,optimum+half)
    if scan_high<=scan_low: raise ValueError("Profile scan has no usable interval inside parameter bounds")
    grid=np.linspace(scan_low,scan_high,int(points))
    grid[int(np.argmin(np.abs(grid-optimum)))]=optimum
    grid=np.unique(np.sort(grid))

    base_cost=float(2.0*baseline_fit.optimizer_result.cost)
    nuisance=_nuisance_vocabulary(definition,runs)
    baseline_initial={str(r["internal_name"]):float(r["estimate"]) for _,r in baseline_fit.estimates.iterrows()}
    rows=[]
    for value in grid:
        value=float(value)
        if abs(value-optimum)<=eps:
            fit=baseline_fit; cost=base_cost; ok=bool(fit.success); message=str(fit.message)
        else:
            overrides=copy.deepcopy(definition.parameter_overrides)
            # Warm-start all shared/nuisance parameters from the joint optimum.
            for name,initial in baseline_initial.items():
                overrides.setdefault(name,{})["initial"]=initial
            lo=max(lower,value-eps); hi=min(upper,value+eps)
            if not lo<hi:
                if value<=lower+eps: lo,hi=lower,lower+2*eps
                else: lo,hi=upper-2*eps,upper
            overrides.setdefault(parameter,{}).update({"initial":value,"lower":lo,"upper":hi})
            try:
                fit=fit_vehicle(
                    base_vehicle,runs,definition.shared_unknowns,parameter_overrides=overrides,
                    nuisance_terms=nuisance,max_nfev=int(max_nfev or max(30,definition.max_nfev//2)),
                    fit_dt_s=definition.fit_dt_s,final_dt_s=definition.final_dt_s,
                )
                cost=float(2.0*fit.optimizer_result.cost);ok=bool(fit.success);message=str(fit.message)
            except Exception as exc:
                cost=float("inf");ok=False;message=str(exc)
        rows.append({"value":value,"objective":cost,"delta_objective":float(cost-base_cost) if math.isfinite(cost) else None,"success":ok,"message":message})

    finite=[r for r in rows if r["delta_objective"] is not None and math.isfinite(float(r["delta_objective"]))]
    inside=[r for r in finite if float(r["delta_objective"])<=float(threshold_delta_objective)]
    practical_low=min((float(r["value"]) for r in inside),default=None)
    practical_high=max((float(r["value"]) for r in inside),default=None)
    left_cross=any(float(r["value"])<optimum and float(r["delta_objective"])>threshold_delta_objective for r in finite)
    right_cross=any(float(r["value"])>optimum and float(r["delta_objective"])>threshold_delta_objective for r in finite)
    if left_cross and right_cross: status="bounded_in_scan"
    elif left_cross or right_cross: status="one_sided_in_scan"
    else: status="flat_in_scan"
    note=("Profile objective uses the same robust soft-L1 residual objective as the inverse fit. "
          "The threshold is a practical identifiability aid, not an exact posterior confidence interval.")
    return ProfileScanResult(parameter,optimum,lower,upper,float(threshold_delta_objective),rows,practical_low,practical_high,status,note)


def profile_suite(
    base_vehicle: VehicleConfig,
    runs: Sequence[FitRun],
    definition: FitStudyDefinition,
    baseline_fit: FitResult,
    parameters: Sequence[str],
    **kwargs,
) -> Dict[str, Dict[str, Any]]:
    out={}
    for name in parameters:
        out[str(name)]=profile_parameter(base_vehicle,runs,definition,baseline_fit,str(name),**kwargs).to_dict()
    return out


def leave_one_run_out_influence(
    base_vehicle: VehicleConfig,
    runs: Sequence[FitRun],
    definition: FitStudyDefinition,
    baseline_fit: FitResult,
    *,
    max_nfev: Optional[int] = None,
) -> Dict[str, Any]:
    """Refit after omitting each Run and quantify shared-parameter movement.

    This is an influence/stability diagnostic, not cross-validation of the
    omitted Run's prediction.  Large shared-parameter movement means the joint
    reconstruction depends strongly on that particular pass.
    """
    if len(runs)<2:
        raise ValueError("Leave-one-Run-out influence requires at least two Runs")
    baseline_rows=baseline_fit.estimates.loc[baseline_fit.estimates["scope"]=="shared vehicle"].copy()
    if baseline_rows.empty:
        raise ValueError("Joint fit has no shared vehicle parameters to assess")
    baseline={str(r["internal_name"]):r for _,r in baseline_rows.iterrows()}
    baseline_all={str(r["internal_name"]):float(r["estimate"]) for _,r in baseline_fit.estimates.iterrows()}
    run_results=[]
    for omitted_idx,omitted in enumerate(runs):
        retained=[r for i,r in enumerate(runs) if i!=omitted_idx]
        original_indices=[i for i in range(len(runs)) if i!=omitted_idx]
        overrides={}
        # Preserve study-level shared overrides and warm-start at full-data optimum.
        for name,cfg in (definition.parameter_overrides or {}).items():
            if not str(name).startswith("run__"):
                overrides[str(name)]=copy.deepcopy(cfg)
        for name,row in baseline.items():
            overrides.setdefault(name,{})["initial"]=float(row["estimate"])
        # Remap any retained local nuisance starts/overrides from original Run index.
        for new_idx,orig_idx in enumerate(original_indices):
            for term in (retained[new_idx].nuisance_terms or []):
                old_name=f"run__{orig_idx}__{term}"; new_name=f"run__{new_idx}__{term}"
                cfg=copy.deepcopy((definition.parameter_overrides or {}).get(old_name,{}))
                if old_name in baseline_all: cfg["initial"]=baseline_all[old_name]
                if cfg: overrides[new_name]=cfg
        nuisance=_nuisance_vocabulary(definition,retained)
        try:
            refit=fit_vehicle(
                base_vehicle,retained,definition.shared_unknowns,parameter_overrides=overrides,
                nuisance_terms=nuisance,max_nfev=int(max_nfev or definition.max_nfev),
                fit_dt_s=definition.fit_dt_s,final_dt_s=definition.final_dt_s,
            )
            estimates={str(r["internal_name"]):r for _,r in refit.estimates.iterrows() if str(r.get("scope"))=="shared vehicle"}
            shifts=[]
            for name,brow in baseline.items():
                if name not in estimates: continue
                b=float(brow["estimate"]); v=float(estimates[name]["estimate"]); delta=v-b
                span=max(float(brow["upper_bound"])-float(brow["lower_bound"]),1e-12)
                se=float(brow.get("std_error",np.nan))
                shifts.append({
                    "parameter":name,"baseline_estimate":b,"without_run_estimate":v,"delta":delta,
                    "abs_delta":abs(delta),"bound_span_fraction":abs(delta)/span,
                    "baseline_std_error":se if math.isfinite(se) else None,
                    "std_error_shift":abs(delta)/se if math.isfinite(se) and se>1e-12 else None,
                })
            max_span=max((float(x["bound_span_fraction"]) for x in shifts),default=0.0)
            if max_span>=.05: status="high_influence"
            elif max_span>=.02: status="moderate_influence"
            else: status="low_influence"
            dominant=max(shifts,key=lambda x:float(x["bound_span_fraction"]),default=None)
            run_results.append({
                "omitted_run":omitted.name,"source_run_id":omitted.source_run_id,"role":omitted.role,
                "success":bool(refit.success),"message":str(refit.message),"status":status,
                "max_bound_span_fraction":max_span,"dominant_parameter":dominant["parameter"] if dominant else "",
                "parameter_shifts":shifts,
            })
        except Exception as exc:
            run_results.append({
                "omitted_run":omitted.name,"source_run_id":omitted.source_run_id,"role":omitted.role,
                "success":False,"message":str(exc),"status":"refit_failed",
                "max_bound_span_fraction":None,"dominant_parameter":"","parameter_shifts":[],
            })
    return {
        "method":"leave-one-run-out joint refit",
        "runs":run_results,
        "note":"Influence measures movement of shared fitted parameters when one measured Run is omitted. It is a dataset-dependence diagnostic, not a probability statement or omitted-Run prediction score.",
    }
