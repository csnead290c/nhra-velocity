from __future__ import annotations

"""NHRA class/run analysis profiles.

Profiles are workstation defaults, not evidence.  They describe which channels
are normally useful for a class and provide explicit, overridable RSA seed
values.  Applying a profile never rewrites source telemetry or official timing.
"""

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Iterable

from .models import TelemetryRun, VehicleConfig, DEFAULT_PRO_STOCK
from .workstation import resolve_channel


@dataclass(frozen=True)
class RunProfile:
    key: str
    label: str
    aliases: tuple[str, ...] = ()
    finish_distance_ft: int = 1320
    waveform_groups: tuple[tuple[str, tuple[str, ...]], ...] = ()
    report_types: tuple[str, ...] = ()
    rsa_vehicle_defaults: VehicleConfig | None = None
    rsa_defaults_provenance: str = ""

    @property
    def primary_roles(self) -> tuple[str, ...]:
        seen: list[str] = []
        for _name, roles in self.waveform_groups:
            for role in roles:
                if role not in seen:
                    seen.append(role)
        return tuple(seen)


_PRO_STOCK_DEFAULT = deepcopy(DEFAULT_PRO_STOCK)
_PRO_STOCK_DEFAULT.name = "NHRA Pro Stock reference default"

RUN_PROFILES: tuple[RunProfile, ...] = (
    RunProfile(
        "generic_drag", "Generic Drag Run", ("drag",), 1320,
        (
            ("Driveline", ("engine_rpm", "driveshaft_rpm", "clutch_rpm", "speed_mph", "longitudinal_g")),
            ("Driver / Engine", ("throttle_pct", "engine_rpm", "lambda", "afr")),
        ),
    ),
    RunProfile(
        "pro_stock", "Pro Stock", ("ps", "prostock", "pro stock"), 1320,
        (
            ("Shift / Driveline", ("engine_rpm", "driveshaft_rpm", "clutch_rpm", "longitudinal_g", "speed_mph", "gear")),
            ("Engine / EFI", ("engine_rpm", "throttle_pct", "ignition_timing_deg", "fuel_pressure_psi", "oil_pressure_psi", "lambda", "afr", "battery_voltage")),
            ("Chassis", ("longitudinal_g", "wheel_speed_mph", "speed_mph")),
        ),
        ("pro_stock_shift",),
        _PRO_STOCK_DEFAULT,
        "Bundled Quarter Pro / Racing Systems Analysis Pro Stock reference. Values are analysis seeds and remain user-overridable.",
    ),
    RunProfile(
        "top_fuel", "Top Fuel", ("tf", "topfuel", "top fuel"), 1000,
        (
            ("Driveline", ("engine_rpm", "driveshaft_rpm", "clutch_rpm", "longitudinal_g", "speed_mph")),
            ("Engine / Fuel", ("engine_rpm", "throttle_pct", "fuel_pressure_psi", "oil_pressure_psi", "ignition_timing_deg")),
        ),
    ),
    RunProfile(
        "funny_car", "Funny Car", ("fc", "funnycar", "funny car"), 1000,
        (
            ("Driveline", ("engine_rpm", "driveshaft_rpm", "clutch_rpm", "longitudinal_g", "speed_mph")),
            ("Engine / Fuel", ("engine_rpm", "throttle_pct", "fuel_pressure_psi", "oil_pressure_psi", "ignition_timing_deg")),
        ),
    ),
    RunProfile(
        "pro_stock_motorcycle", "Pro Stock Motorcycle", ("psm", "pro stock motorcycle"), 1320,
        (
            ("Performance", ("engine_rpm", "speed_mph", "wheel_speed_mph", "longitudinal_g", "gear")),
            ("Engine / Rider", ("engine_rpm", "throttle_pct", "lambda", "afr", "ignition_timing_deg")),
        ),
    ),
)

_BY_KEY = {p.key: p for p in RUN_PROFILES}


def profile(key: str) -> RunProfile:
    return _BY_KEY[str(key)]


def profile_rows() -> list[dict[str, object]]:
    return [
        {
            "key": p.key,
            "label": p.label,
            "finish_distance_ft": p.finish_distance_ft,
            "groups": [name for name, _roles in p.waveform_groups],
            "reports": list(p.report_types),
        }
        for p in RUN_PROFILES
    ]


def infer_profile(run: TelemetryRun) -> RunProfile:
    explicit = str(run.metadata.get("analysis_profile", "") or "").strip()
    if explicit in _BY_KEY:
        return _BY_KEY[explicit]
    haystack = " ".join(
        str(x or "") for x in (
            run.name,
            run.metadata.get("category"),
            run.metadata.get("class"),
            run.metadata.get("vehicle_class"),
            run.metadata.get("source_file"),
        )
    ).lower()
    # Long/specific names first so "pro stock" does not steal PSM.
    for key in ("pro_stock_motorcycle", "top_fuel", "funny_car", "pro_stock"):
        p = _BY_KEY[key]
        if any(alias in haystack for alias in p.aliases if len(alias) >= 3):
            return p
    return _BY_KEY["generic_drag"]


def set_run_profile(run: TelemetryRun, key: str) -> RunProfile:
    p = profile(key)
    run.metadata["analysis_profile"] = p.key
    return p


def resolve_profile_channels(
    run: TelemetryRun,
    key: str | None = None,
    *,
    group: str | None = None,
    limit: int | None = None,
) -> list[str]:
    p = profile(key) if key else infer_profile(run)
    roles: Iterable[str]
    if group:
        match = next((r for name, r in p.waveform_groups if name.lower() == str(group).lower()), ())
        roles = match
    else:
        roles = p.primary_roles
    out: list[str] = []
    for role in roles:
        source = resolve_channel(run, role)
        if source and source not in out:
            out.append(source)
        if limit is not None and len(out) >= int(limit):
            break
    return out


def profile_vehicle_defaults(key: str) -> VehicleConfig | None:
    p = profile(key)
    return deepcopy(p.rsa_vehicle_defaults) if p.rsa_vehicle_defaults is not None else None


def apply_profile_rsa_defaults(run: TelemetryRun, key: str, *, overwrite: bool = False) -> dict[str, object]:
    """Apply profile RSA seed values into the ordinary vehicle-input metadata.

    These are explicit analysis inputs with provenance.  They do not modify raw
    data, official timing, or the source logger configuration.
    """
    p = set_run_profile(run, key)
    vehicle = profile_vehicle_defaults(key)
    if vehicle is None:
        return {}
    existing = run.metadata.setdefault("vehicle_inputs", {})
    source = vehicle.to_dict()
    # Dyno/gear arrays remain available to dedicated simulation workflows, but
    # the common geometry/mass inputs are the standardized class seed layer.
    fields = (
        "weight_lb", "wheelbase_in", "rollout_in", "front_overhang_in",
        "frontal_area_ft2", "drag_coefficient", "lift_coefficient",
        "final_drive_ratio", "tire_diameter_in", "tire_width_in",
    )
    applied: dict[str, object] = {}
    for name in fields:
        if overwrite or name not in existing or existing.get(name) in (None, ""):
            value = source.get(name)
            if value is not None:
                existing[name] = value
                applied[name] = value
    run.metadata["analysis_profile"] = p.key
    run.metadata["rsa_profile_defaults"] = {
        "profile": p.key,
        "provenance": p.rsa_defaults_provenance,
        "applied": dict(applied),
    }
    return applied
