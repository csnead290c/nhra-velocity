from __future__ import annotations

"""Composable time synchronization for AnalysisCases.

Time is deliberately mapped in two auditable stages:

    Asset clock -> authoritative Run clock -> AnalysisCase clock

The raw files are never rewritten and the two mappings remain independently
inspectable.  The Asset→Run mapping is affine so source-clock drift can be corrected. The
Run→Case stage preserves physical seconds and applies only a translation. Both
stages remain simple enough to audit during an incident investigation.
"""

from dataclasses import dataclass
from typing import Iterable, Sequence
import math
import numpy as np



@dataclass(frozen=True)
class CaseTimeAnchor:
    run_time_s: float
    case_time_s: float


@dataclass(frozen=True)
class CaseRunAlignment:
    scale: float = 1.0
    offset_s: float = 0.0
    method: str = "run_time"
    confidence: float | None = None
    uncertainty_s: float | None = None
    anchors: tuple[CaseTimeAnchor, ...] = ()

    def to_case_time(self, run_time_s):
        arr=np.asarray(run_time_s,dtype=float)
        out=arr*float(self.scale)+float(self.offset_s)
        return float(out) if out.ndim==0 else out

    def to_run_time(self, case_time_s):
        if abs(float(self.scale))<1e-12:raise ValueError("Case alignment scale cannot be zero")
        arr=np.asarray(case_time_s,dtype=float)
        out=(arr-float(self.offset_s))/float(self.scale)
        return float(out) if out.ndim==0 else out

    def to_dict(self):
        return {
            "scale":float(self.scale),"offset_s":float(self.offset_s),"method":self.method,
            "confidence":self.confidence,"uncertainty_s":self.uncertainty_s,
            "anchors":[{"run_time_s":float(a.run_time_s),"case_time_s":float(a.case_time_s)} for a in self.anchors],
        }


@dataclass(frozen=True)
class ComposedCaseTimeMapping:
    """Direct Asset-clock -> Case-clock mapping derived from the two stored stages."""
    scale: float
    offset_s: float
    confidence: float | None = None
    uncertainty_s: float | None = None

    def to_case_time(self, asset_time_s):
        arr=np.asarray(asset_time_s,dtype=float);out=arr*self.scale+self.offset_s
        return float(out) if out.ndim==0 else out

    def to_asset_time(self, case_time_s):
        if abs(self.scale)<1e-12:raise ValueError("Composed time scale cannot be zero")
        arr=np.asarray(case_time_s,dtype=float);out=(arr-self.offset_s)/self.scale
        return float(out) if out.ndim==0 else out


def fit_case_run_alignment(
    anchors: Iterable[CaseTimeAnchor | Sequence[float] | dict], *,
    method: str = "case anchors", confidence: float | None = None,
) -> CaseRunAlignment:
    parsed=[]
    for a in anchors:
        if isinstance(a,CaseTimeAnchor):parsed.append(a)
        elif isinstance(a,dict):parsed.append(CaseTimeAnchor(float(a["run_time_s"]),float(a["case_time_s"])))
        else:parsed.append(CaseTimeAnchor(float(a[0]),float(a[1])))
    if not parsed:
        return CaseRunAlignment(method=method,confidence=confidence)
    offsets=np.asarray([a.case_time_s-a.run_time_s for a in parsed],dtype=float)
    if not np.all(np.isfinite(offsets)):
        raise ValueError("No finite case synchronization anchors")
    offset=float(np.mean(offsets))
    # Run Time is already canonical physical time. Do not time-warp one pass to
    # make multiple anchors fit. Disagreement becomes synchronization uncertainty.
    residual=offsets-offset
    uncertainty=None if len(parsed)==1 else float(np.sqrt(np.mean(residual**2)))
    return CaseRunAlignment(
        scale=1.0,offset_s=offset,method=method,confidence=confidence,
        uncertainty_s=uncertainty,anchors=tuple(parsed),
    )


def compose_asset_and_case_mapping(asset_mapping: dict, case_alignment: dict) -> ComposedCaseTimeMapping:
    """Compose run=a*asset+b and case=c*run+d into case=(c*a)*asset+(c*b+d)."""
    a=float(asset_mapping.get("scale",1.0));b=float(asset_mapping.get("offset_s",0.0))
    c=float(case_alignment.get("time_scale",case_alignment.get("scale",1.0)))
    d=float(case_alignment.get("time_offset_s",case_alignment.get("offset_s",0.0)))
    confs=[x for x in (asset_mapping.get("confidence"),case_alignment.get("alignment_confidence",case_alignment.get("confidence"))) if x is not None]
    confidence=min(float(x) for x in confs) if confs else None
    au=asset_mapping.get("uncertainty_s");cu=case_alignment.get("alignment_uncertainty_s",case_alignment.get("uncertainty_s"))
    vals=[]
    if au is not None:vals.append((abs(c)*float(au))**2)
    if cu is not None:vals.append(float(cu)**2)
    uncertainty=math.sqrt(sum(vals)) if vals else None
    return ComposedCaseTimeMapping(scale=c*a,offset_s=c*b+d,confidence=confidence,uncertainty_s=uncertainty)


def store_case_run_alignment(catalog, case_id: str, run_id: str, alignment: CaseRunAlignment) -> None:
    catalog.update_case_run_alignment(
        case_id,run_id,scale=alignment.scale,offset_s=alignment.offset_s,method=alignment.method,
        confidence=alignment.confidence,uncertainty_s=alignment.uncertainty_s,
        anchors=[{"run_time_s":a.run_time_s,"case_time_s":a.case_time_s} for a in alignment.anchors],
    )


def composed_mapping_for_asset(catalog, case_id: str, asset_id: str) -> ComposedCaseTimeMapping:
    asset=catalog.get_asset(asset_id)
    if asset is None:raise KeyError(asset_id)
    asset_mapping=catalog.get_time_mapping(asset_id)
    if asset_mapping is None:raise KeyError(f"Asset {asset_id} has no Asset→Run time mapping")
    case_alignment=catalog.get_case_run_alignment(case_id,str(asset["run_id"]))
    if case_alignment is None:raise KeyError(f"Asset owning Run is not a member of analysis case {case_id}")
    return compose_asset_and_case_mapping(asset_mapping,case_alignment)
