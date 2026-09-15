from __future__ import annotations

"""Transparent first-stage vehicle incident pulse calculations.

This module is intentionally *not* a standards-compliance layer. Inputs are
assumed to already be calibrated into vehicle axes. No CFC filter, sensor
orientation correction, sensor-to-CG rigid-body correction, occupant model or
HIC calculation is implied. Those must be explicit future processing stages.
"""

from dataclasses import dataclass
from typing import Any, Dict
import math
import numpy as np

G0_MPS2 = 9.80665


@dataclass(frozen=True)
class VehiclePulseSummary:
    sample_count: int
    duration_s: float
    peak_resultant_g: float
    peak_abs_x_g: float
    peak_abs_y_g: float
    peak_abs_z_g: float
    delta_v_x_mps: float
    delta_v_y_mps: float
    delta_v_z_mps: float
    delta_v_resultant_mps: float
    horizontal_delta_v_angle_deg: float | None

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def _clean(time_s, ax_g, ay_g, az_g):
    t=np.asarray(time_s,dtype=float);ax=np.asarray(ax_g,dtype=float);ay=np.asarray(ay_g,dtype=float);az=np.asarray(az_g,dtype=float)
    if not (len(t)==len(ax)==len(ay)==len(az)) or len(t)<2:
        raise ValueError('Incident pulse requires equal-length time/X/Y/Z arrays with at least two samples')
    valid=np.isfinite(t)&np.isfinite(ax)&np.isfinite(ay)&np.isfinite(az)
    t,ax,ay,az=t[valid],ax[valid],ay[valid],az[valid]
    if len(t)<2:raise ValueError('Incident pulse has fewer than two finite samples')
    order=np.argsort(t,kind='stable');t,ax,ay,az=t[order],ax[order],ay[order],az[order]
    keep=np.r_[True,np.diff(t)>0];t,ax,ay,az=t[keep],ax[keep],ay[keep],az[keep]
    if len(t)<2:raise ValueError('Incident timebase must contain increasing samples')
    return t,ax,ay,az


def analyze_vehicle_pulse(time_s, ax_g, ay_g, az_g) -> tuple[VehiclePulseSummary, Dict[str,np.ndarray]]:
    """Calculate unfiltered vehicle-axis pulse quantities.

    ΔV is trapezoidally integrated from acceleration in g. The result is only as
    physically meaningful as the supplied calibrated axes and preprocessing.
    """
    t,ax,ay,az=_clean(time_s,ax_g,ay_g,az_g)
    resultant=np.sqrt(ax*ax+ay*ay+az*az)
    dvx=float(np.trapezoid(ax*G0_MPS2,t));dvy=float(np.trapezoid(ay*G0_MPS2,t));dvz=float(np.trapezoid(az*G0_MPS2,t))
    dvr=float(math.sqrt(dvx*dvx+dvy*dvy+dvz*dvz))
    horiz=math.sqrt(dvx*dvx+dvy*dvy)
    angle=float(math.degrees(math.atan2(dvy,dvx))) if horiz>1e-12 else None
    summary=VehiclePulseSummary(
        sample_count=len(t),duration_s=float(t[-1]-t[0]),peak_resultant_g=float(np.max(resultant)),
        peak_abs_x_g=float(np.max(np.abs(ax))),peak_abs_y_g=float(np.max(np.abs(ay))),peak_abs_z_g=float(np.max(np.abs(az))),
        delta_v_x_mps=dvx,delta_v_y_mps=dvy,delta_v_z_mps=dvz,delta_v_resultant_mps=dvr,horizontal_delta_v_angle_deg=angle,
    )
    traces={'time_s':t,'ax_g':ax,'ay_g':ay,'az_g':az,'resultant_g':resultant}
    return summary,traces
