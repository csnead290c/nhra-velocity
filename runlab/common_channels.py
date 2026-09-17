from __future__ import annotations

"""Canonical/common engineering channel registry used by the desktop.

The internal keys remain stable machine-facing identifiers (``engine_rpm``,
``speed_mph`` ...).  This module gives them durable human-facing labels and
ordering so the UI, reusable math definitions and future server-side templates
all speak the same vocabulary without depending on a logger vendor's names.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List

from .importers import CANONICAL_CHANNELS
from .units import CANONICAL_TARGET_UNITS, display_label


@dataclass(frozen=True)
class CommonChannelSpec:
    key: str
    label: str
    group: str
    unit: str = ""
    description: str = ""

    @property
    def unit_label(self) -> str:
        return display_label(self.unit) or self.unit


# Deliberately ordered for drag-racing engineering workflows rather than
# alphabetically.  Keys not explicitly listed below are still surfaced using a
# deterministic title-case fallback so extending CANONICAL_CHANNELS never makes
# a role disappear from the mapping UI.
_SPECS: Dict[str, CommonChannelSpec] = {
    "time_s": CommonChannelSpec("time_s", "Logger Time", "Timing", "s", "Primary monotonic logger timebase."),
    "engine_rpm": CommonChannelSpec("engine_rpm", "Engine Speed", "Driveline", "rpm"),
    "driveshaft_rpm": CommonChannelSpec("driveshaft_rpm", "Driveshaft Speed", "Driveline", "rpm"),
    "clutch_rpm": CommonChannelSpec("clutch_rpm", "Clutch / Input Speed", "Driveline", "rpm"),
    "gear": CommonChannelSpec("gear", "Gear", "Driveline", ""),
    "speed_mph": CommonChannelSpec("speed_mph", "Vehicle Speed", "Vehicle", "mph"),
    "wheel_speed_mph": CommonChannelSpec("wheel_speed_mph", "Wheel Speed", "Vehicle", "mph"),
    "longitudinal_g": CommonChannelSpec("longitudinal_g", "Longitudinal Acceleration", "Vehicle", "g"),
    "lateral_g": CommonChannelSpec("lateral_g", "Lateral Acceleration", "Vehicle", "g"),
    "vertical_g": CommonChannelSpec("vertical_g", "Vertical Acceleration", "Vehicle", "g"),
    "throttle_pct": CommonChannelSpec("throttle_pct", "Throttle Position", "Driver / Controls", "pct"),
    "brake_pressure_psi": CommonChannelSpec("brake_pressure_psi", "Brake Pressure", "Driver / Controls", "psi"),
    "steering_angle_deg": CommonChannelSpec("steering_angle_deg", "Steering Angle", "Driver / Controls", "deg"),
    "boost_psi": CommonChannelSpec("boost_psi", "Boost / Manifold Pressure", "Engine", "psi"),
    "lambda": CommonChannelSpec("lambda", "Lambda", "Engine", ""),
    "afr": CommonChannelSpec("afr", "Air/Fuel Ratio", "Engine", ""),
    "ignition_timing_deg": CommonChannelSpec("ignition_timing_deg", "Ignition Timing", "Engine", "deg"),
    "oil_pressure_psi": CommonChannelSpec("oil_pressure_psi", "Oil Pressure", "Engine", "psi"),
    "fuel_pressure_psi": CommonChannelSpec("fuel_pressure_psi", "Fuel Pressure", "Engine", "psi"),
    "coolant_temp_f": CommonChannelSpec("coolant_temp_f", "Coolant Temperature", "Engine", "f"),
    "oil_temp_f": CommonChannelSpec("oil_temp_f", "Oil Temperature", "Engine", "f"),
    "intake_air_temp_f": CommonChannelSpec("intake_air_temp_f", "Intake Air Temperature", "Engine", "f"),
    "fuel_temp_f": CommonChannelSpec("fuel_temp_f", "Fuel Temperature", "Engine", "f"),
    "injector_duty_pct": CommonChannelSpec("injector_duty_pct", "Injector Duty Cycle", "Engine", "pct"),
    "power_hp": CommonChannelSpec("power_hp", "Engine Power", "Performance", "hp"),
    "torque_lbft": CommonChannelSpec("torque_lbft", "Engine Torque", "Performance", "lbft"),
    "battery_voltage": CommonChannelSpec("battery_voltage", "Battery Voltage", "Electrical", "v"),
    "gps_latitude_deg": CommonChannelSpec("gps_latitude_deg", "GPS Latitude", "Position / GPS", "deg"),
    "gps_longitude_deg": CommonChannelSpec("gps_longitude_deg", "GPS Longitude", "Position / GPS", "deg"),
    "heading_deg": CommonChannelSpec("heading_deg", "Heading", "Position / GPS", "deg"),
    "altitude_ft": CommonChannelSpec("altitude_ft", "Altitude", "Position / GPS", "ft"),
    "yaw_rate_degps": CommonChannelSpec("yaw_rate_degps", "Yaw Rate", "Position / GPS", "degps"),
}

_GROUP_ORDER = {
    "Timing": 0,
    "Driveline": 1,
    "Vehicle": 2,
    "Driver / Controls": 3,
    "Engine": 4,
    "Performance": 5,
    "Electrical": 6,
    "Position / GPS": 7,
    "Other": 99,
}


def _fallback_label(key: str) -> str:
    text = str(key or "").replace("_pct", "").replace("_psi", "").replace("_mph", "").replace("_rpm", "")
    text = text.replace("_degps", "").replace("_deg", "").replace("_ft", "").replace("_f", "")
    return " ".join(part.capitalize() for part in text.split("_") if part) or str(key)


def common_channel_spec(key: str) -> CommonChannelSpec:
    key = str(key or "").strip()
    if key in _SPECS:
        return _SPECS[key]
    return CommonChannelSpec(
        key,
        _fallback_label(key),
        "Other",
        CANONICAL_TARGET_UNITS.get(key, ""),
    )


def common_channel_label(key: str) -> str:
    return common_channel_spec(key).label


def common_channel_specs(keys: Iterable[str] | None = None) -> List[CommonChannelSpec]:
    raw = list(keys if keys is not None else CANONICAL_CHANNELS.keys())
    out = [common_channel_spec(key) for key in raw]
    explicit_order = {key: i for i, key in enumerate(_SPECS)}
    return sorted(
        out,
        key=lambda s: (
            _GROUP_ORDER.get(s.group, 99),
            explicit_order.get(s.key, 10_000),
            s.label.lower(),
            s.key,
        ),
    )


def common_channel_key_from_label(label_or_key: str) -> str | None:
    needle = str(label_or_key or "").strip().lower()
    if not needle:
        return None
    for spec in common_channel_specs():
        if needle in {spec.key.lower(), spec.label.lower()}:
            return spec.key
    return None
