from __future__ import annotations

"""Run-centric engineering knowledge and provenance.

The telemetry session is the primary object.  Measured channels, official timing,
weather, entered setup values, solver estimates and generated scenario values all
live with the run, but they must never be indistinguishable from one another.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple
import copy
import math

from .models import DEFAULT_PRO_STOCK, DynoCurve, TelemetryRun, VehicleConfig

PROVENANCE = {
    "logger": "logger metadata",
    "official": "official timing",
    "measured": "measured",
    "user": "entered by user",
    "inherited": "inherited configuration",
    "inferred": "inferred by analysis",
    "generated": "generated scenario",
    "default": "development default",
}

@dataclass
class ParameterRecord:
    key: str
    value: Any
    unit: str = ""
    provenance: str = "user"
    confidence: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    method: str = ""
    runs: Optional[List[str]] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _store(run: TelemetryRun) -> Dict[str, Dict[str, Any]]:
    return run.metadata.setdefault("parameter_knowledge", {})


def set_parameter(
    run: TelemetryRun,
    key: str,
    value: Any,
    unit: str = "",
    provenance: str = "user",
    *,
    confidence: Optional[float] = None,
    lower: Optional[float] = None,
    upper: Optional[float] = None,
    method: str = "",
    runs: Optional[Iterable[str]] = None,
    notes: str = "",
) -> None:
    rec = ParameterRecord(
        str(key), value, str(unit or ""), str(provenance or "user"),
        None if confidence is None else float(confidence),
        None if lower is None else float(lower),
        None if upper is None else float(upper),
        str(method or ""), list(runs) if runs is not None else None, str(notes or ""),
    )
    _store(run)[str(key)] = rec.to_dict()


def get_parameter(run: TelemetryRun, key: str) -> Optional[ParameterRecord]:
    rec = _store(run).get(str(key))
    if not isinstance(rec, dict):
        return None
    fields = ParameterRecord.__dataclass_fields__
    data = {k: v for k, v in rec.items() if k in fields}
    data.setdefault("key", str(key))
    return ParameterRecord(**data)


def delete_parameter(run: TelemetryRun, key: str) -> None:
    _store(run).pop(str(key), None)


def vehicle_inputs(run: TelemetryRun) -> Dict[str, Any]:
    """Return the editable vehicle/model inputs, migrating old prototype keys."""
    vals = run.metadata.setdefault("vehicle_inputs", {})
    old = run.metadata.pop("quarterpro_inputs", None)
    if isinstance(old, dict):
        for k, v in old.items():
            vals.setdefault(k, v)
    return vals


def set_vehicle_input(run: TelemetryRun, key: str, value: Any, unit: str = "", provenance: str = "user", **kwargs) -> None:
    vehicle_inputs(run)[key] = value
    set_parameter(run, f"vehicle.{key}", value, unit, provenance, **kwargs)


def get_vehicle_input(run: TelemetryRun, key: str, default=None):
    return vehicle_inputs(run).get(key, default)


def _float_list(value: Any) -> List[float]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [float(x) for x in value]
    return [float(x.strip()) for x in str(value).replace(";", ",").split(",") if x.strip()]


VEHICLE_FIELDS = {
    "weight_lb", "wheelbase_in", "rollout_in", "front_overhang_in",
    "frontal_area_ft2", "drag_coefficient", "lift_coefficient", "body_style",
    "traction_index", "transmission_type", "launch_rpm", "stall_rpm", "slippage",
    "torque_multiplication", "lockup_after_first", "shift_duration_s",
    "final_drive_ratio", "final_drive_efficiency", "tire_diameter_in", "tire_width_in",
    "tire_growth_scale", "gear_ratios", "gear_efficiencies", "shift_rpms", "hp_multiplier",
    "engine_pmi", "transmission_pmi", "tires_pmi", "cg_height_in", "static_front_weight_lb",
}


def vehicle_from_run(run: TelemetryRun, *, require_explicit: bool = False) -> Tuple[VehicleConfig, List[str]]:
    """Build the vehicle model associated with a run.

    Development defaults are permitted when ``require_explicit`` is false and are
    returned in ``missing`` so the UI can disclose them.  Generated scenario work
    should generally require an explicit/calibrated model.
    """
    values = vehicle_inputs(run)
    base = DEFAULT_PRO_STOCK.to_dict()
    missing: List[str] = []
    for key in VEHICLE_FIELDS:
        if key in values and values[key] not in (None, "", []):
            base[key] = values[key]
        else:
            missing.append(key)
    # Normalize list fields stored from editable setup rows.
    for key in ("gear_ratios", "gear_efficiencies", "shift_rpms"):
        if key in base:
            base[key] = _float_list(base[key])
    # Explicit dyno nodes are part of the run knowledge model.  A reconstructed
    # curve may populate these without ever mutating the raw logger channels.
    rpm = _float_list(values.get("dyno_rpm"))
    hp = _float_list(values.get("dyno_hp"))
    if not rpm or not hp or len(rpm) != len(hp) or len(rpm) < 2:
        inferred = run.metadata.get("inferred_dyno_curve")
        if isinstance(inferred, dict):
            rpm = _float_list(inferred.get("rpm")); hp = _float_list(inferred.get("hp"))
    if rpm and hp and len(rpm) == len(hp) and len(rpm) >= 2:
        base["dyno"] = {"rpm": rpm, "hp": hp}
    else:
        missing.append("dyno_curve")
    if require_explicit and missing:
        raise ValueError(
            "This analysis requires a calibrated vehicle model. Missing run/setup fields: "
            + ", ".join(sorted(set(missing)))
        )
    return VehicleConfig.from_dict(base), sorted(set(missing))


def persist_knowledge_snapshot(run: TelemetryRun) -> Dict[str, Any]:
    return copy.deepcopy(_store(run))


def restore_knowledge_snapshot(run: TelemetryRun, data: Any) -> None:
    run.metadata["parameter_knowledge"] = copy.deepcopy(data if isinstance(data, dict) else {})
