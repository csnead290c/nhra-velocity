from __future__ import annotations

"""Generated compare-run support.

A scenario is represented as a normal TelemetryRun so measured and generated
sessions use exactly the same viewer, cursor, overlay and math infrastructure.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional
import copy
import numpy as np
import pandas as pd

from .legacy_reference import simulate_legacy_reference
from .models import ChannelSeries, Environment, TelemetryRun, VehicleConfig
from .knowledge import set_parameter


@dataclass
class ScenarioResult:
    run: TelemetryRun
    vehicle: VehicleConfig
    changes: Dict[str, Any]


def apply_vehicle_changes(vehicle: VehicleConfig, changes: Dict[str, Any]) -> VehicleConfig:
    data = vehicle.to_dict()
    for key, value in (changes or {}).items():
        if value is None or value == "":
            continue
        if key == "power_scale":
            continue
        if key in ("gear_ratios", "gear_efficiencies", "shift_rpms") and isinstance(value, str):
            value = [float(x.strip()) for x in value.replace(";", ",").split(",") if x.strip()]
        if key in data:
            data[key] = value
    return VehicleConfig.from_dict(data)


def generated_run_from_result(
    name: str,
    result,
    vehicle: VehicleConfig,
    environment: Environment,
    *,
    changes: Optional[Dict[str, Any]] = None,
    source_run_name: str = "",
    power_scale: float = 1.0,
) -> TelemetryRun:
    tr = result.trace.copy()
    engine_rpm = pd.to_numeric(tr["engine_rpm"], errors="coerce").to_numpy(float)
    engine_hp = np.asarray([vehicle.dyno.hp_at(r) * vehicle.hp_multiplier * float(power_scale) for r in engine_rpm], dtype=float)
    engine_tq = np.divide(5252.113 * engine_hp, np.maximum(engine_rpm, 1.0))
    df = pd.DataFrame({
        "Time": pd.to_numeric(tr["physical_time_s"], errors="coerce"),
        "ET Clock": pd.to_numeric(tr["et_clock_s"], errors="coerce"),
        "Distance": pd.to_numeric(tr["axle_distance_ft"], errors="coerce"),
        "Timing Distance": pd.to_numeric(tr["timing_distance_ft"], errors="coerce"),
        "Speed": pd.to_numeric(tr["speed_mph"], errors="coerce"),
        "Longitudinal G": pd.to_numeric(tr["accel_g"], errors="coerce"),
        "Engine RPM": engine_rpm,
        "Engine Power": engine_hp,
        "Engine Torque": engine_tq,
        "Driveshaft RPM": pd.to_numeric(tr["driveshaft_rpm"], errors="coerce"),
        "Wheel RPM": pd.to_numeric(tr["wheel_rpm"], errors="coerce"),
        "Gear": pd.to_numeric(tr["gear"], errors="coerce"),
        "Tire Slip Ratio": pd.to_numeric(tr["tire_slip_ratio"], errors="coerce"),
        "Traction Limited": pd.to_numeric(tr["traction_limited"], errors="coerce"),
    })
    units = {
        "Time":"s", "ET Clock":"s", "Distance":"ft", "Timing Distance":"ft",
        "Speed":"mph", "Longitudinal G":"g", "Engine RPM":"rpm",
        "Engine Power":"hp", "Engine Torque":"lbft", "Driveshaft RPM":"rpm", "Wheel RPM":"rpm", "Gear":"ratio",
        "Tire Slip Ratio":"ratio", "Traction Limited":"ratio",
    }
    cmap = {
        "time_s":"Time", "speed_mph":"Speed", "longitudinal_g":"Longitudinal G",
        "engine_rpm":"Engine RPM", "power_hp":"Engine Power", "torque_lbft":"Engine Torque",
        "driveshaft_rpm":"Driveshaft RPM", "gear":"Gear",
    }
    t = df["Time"].to_numpy(float)
    native = {}
    for col in df.columns:
        vals = pd.to_numeric(df[col], errors="coerce").to_numpy(float)
        native[col] = ChannelSeries(col, t.copy(), vals, units.get(col,""), None, 3, True, {"generated":True})
    run = TelemetryRun(
        name=name, data=df, channel_map=cmap, units=units, vendor="NHRA Tech Data generated",
        metadata={
            "generated_scenario": True,
            "generated_from": source_run_name,
            "scenario_changes": copy.deepcopy(changes or {}),
            "scenario_power_scale": float(power_scale),
            "vehicle_model": vehicle.to_dict(),
            "vehicle_inputs": {**{k:v for k,v in vehicle.to_dict().items() if k != "dyno"}, "dyno_rpm": list(vehicle.dyno.rpm), "dyno_hp": list(vehicle.dyno.hp)},
            "unit_provenance": {k:"generated scenario" for k in df.columns},
            "original_channel_map": dict(cmap),
        },
        environment=copy.deepcopy(environment), timing=copy.deepcopy(result.timing), native_channels=native,
    )
    for k,v in (changes or {}).items():
        set_parameter(run, f"scenario.{k}", v, "", "generated", method="forward vehicle simulation")
    return run


def create_compare_run(
    source_name: str,
    vehicle: VehicleConfig,
    environment: Environment,
    changes: Optional[Dict[str, Any]] = None,
    *,
    name: Optional[str] = None,
) -> ScenarioResult:
    changes = dict(changes or {})
    modified = apply_vehicle_changes(vehicle, changes)
    power_scale = float(changes.get("power_scale", 1.0) or 1.0)
    result = simulate_legacy_reference(modified, environment, power_scale=power_scale)
    run = generated_run_from_result(
        name or f"{source_name} — Compare", result, modified, environment,
        changes=changes, source_run_name=source_name, power_scale=power_scale,
    )
    return ScenarioResult(run=run, vehicle=modified, changes=changes)
