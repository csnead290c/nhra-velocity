from __future__ import annotations

"""Run-centric workspace summaries for NHRA Velocity.

The desktop should revolve around the authoritative Run, not around whichever
logger file happens to be open.  This module assembles the read-only canonical
Run context plus local engineering evidence into one UI-neutral structure.
"""

from dataclasses import dataclass, field
from typing import Any

from .catalog import LocalCatalog
from .run_profiles import profile_for_category, profile_vehicle_defaults
from .shift_report import compare_shift_reports


TIMING_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("reaction_time_s", "RT", "s"),
    ("sixty_ft_s", "60 ft", "s"),
    ("three_thirty_ft_s", "330 ft", "s"),
    ("eighth_mile_s", "660 ft", "s"),
    ("eighth_mile_mph", "660 MPH", "mph"),
    ("thousand_ft_s", "1000 ft", "s"),
    ("thousand_ft_mph", "1000 MPH", "mph"),
    ("quarter_mile_s", "1320 ft", "s"),
    ("quarter_mile_mph", "1320 MPH", "mph"),
)

WEATHER_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("temperature_f", "Air temperature", "°F"),
    ("barometer_inhg", "Barometer", "inHg"),
    ("humidity_pct", "Humidity", "%"),
    ("wind_mph", "Wind speed", "mph"),
    ("wind_angle_deg", "Wind direction", "deg"),
)

PROFILE_INPUT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("weight_lb", "Race weight", "lb"),
    ("wheelbase_in", "Wheelbase", "in"),
    ("rollout_in", "Rollout", "in"),
    ("front_overhang_in", "Front overhang", "in"),
    ("frontal_area_ft2", "Frontal area", "ft²"),
    ("drag_coefficient", "Drag coefficient", ""),
    ("lift_coefficient", "Lift coefficient", ""),
    ("final_drive_ratio", "Final drive ratio", ""),
    ("tire_diameter_in", "Tire diameter", "in"),
    ("tire_width_in", "Tire width", "in"),
)


@dataclass(frozen=True)
class WorkspaceValue:
    key: str
    label: str
    value: Any
    unit: str = ""
    provenance: str = ""


@dataclass
class RunWorkspaceState:
    run: dict[str, Any]
    profile_key: str
    profile_label: str
    finish_distance_ft: int
    timing: list[WorkspaceValue] = field(default_factory=list)
    weather: list[WorkspaceValue] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    engineering: list[dict[str, Any]] = field(default_factory=list)
    model_snapshots: list[dict[str, Any]] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)
    profile_defaults: list[WorkspaceValue] = field(default_factory=list)
    expected_reports: tuple[str, ...] = ()
    report_comparisons: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def telemetry_assets(self) -> list[dict[str, Any]]:
        return [a for a in self.assets if str(a.get("asset_type") or "").lower() == "telemetry"]

    @property
    def has_local_telemetry(self) -> bool:
        return bool(self.telemetry_assets)

    @property
    def report_types_present(self) -> set[str]:
        return {str(r.get("report_type") or "") for r in self.reports}

    @property
    def missing_expected_reports(self) -> tuple[str, ...]:
        present = self.report_types_present
        return tuple(x for x in self.expected_reports if x not in present)


def _profile_defaults(category: str) -> tuple[str, str, int, tuple[str, ...], list[WorkspaceValue]]:
    p = profile_for_category(category)
    vehicle = profile_vehicle_defaults(p.key)
    rows: list[WorkspaceValue] = []
    if vehicle is not None:
        values = vehicle.to_dict()
        for key, label, unit in PROFILE_INPUT_FIELDS:
            value = values.get(key)
            if value is not None:
                rows.append(WorkspaceValue(key, label, value, unit, p.rsa_defaults_provenance or "class profile default"))
    return p.key, p.label, p.finish_distance_ft, p.report_types, rows


def build_run_workspace(catalog: LocalCatalog, run_id: str) -> RunWorkspaceState:
    run = catalog.get_run(str(run_id))
    if run is None:
        raise KeyError(f"Unknown run {run_id}")
    pkey, plabel, finish, expected, defaults = _profile_defaults(str(run.get("category") or ""))

    timing_map = run.get("timing") or {}
    timing = [
        WorkspaceValue(key, label, timing_map[key], unit, str(run.get("timing_provenance") or "unknown"))
        for key, label, unit in TIMING_FIELDS
        if timing_map.get(key) not in (None, "")
    ]

    weather_map = run.get("weather") or {}
    weather = [
        WorkspaceValue(key, label, weather_map[key], unit, str(run.get("weather_provenance") or "unknown"))
        for key, label, unit in WEATHER_FIELDS
        if weather_map.get(key) not in (None, "")
    ]
    # Keep weather evidence/provenance details available without crowding the
    # primary condition rows.
    for key, label in (
        ("timestamp_utc", "Weather timestamp UTC"),
        ("delta_seconds", "Weather join delta"),
        ("canonical_source_kind", "Weather source"),
        ("canonical_source_detail", "Weather source detail"),
        ("sample_count", "Weather sample count"),
    ):
        if weather_map.get(key) not in (None, ""):
            unit = "s" if key == "delta_seconds" else ""
            weather.append(WorkspaceValue(key, label, weather_map[key], unit, str(run.get("weather_provenance") or "unknown")))

    reports=catalog.list_run_reports(str(run_id))
    comparisons: dict[str, dict[str, Any]] = {}
    for report_type in expected:
        current=next((x for x in reports if str(x.get("report_type") or "")==report_type),None)
        previous=catalog.previous_run_report(str(run_id),report_type) if current else None
        if not current or not previous:
            continue
        detail: dict[str, Any] = {
            "previous_run_id": previous.get("run_id"),
            "previous_run_key": previous.get("run_key"),
            "previous_event_name": previous.get("event_name"),
            "previous_run_datetime": previous.get("run_datetime"),
            "alerts": 0,
            "rows": [],
        }
        if report_type=="pro_stock_shift":
            rows=compare_shift_reports(current.get("payload") or {},previous.get("payload") or {})
            detail["rows"]=rows
            detail["alerts"]=sum(1 for row in rows if row.get("alert"))
        comparisons[report_type]=detail

    return RunWorkspaceState(
        run=run,
        profile_key=pkey,
        profile_label=plabel,
        finish_distance_ft=finish,
        timing=timing,
        weather=weather,
        assets=catalog.list_assets(str(run_id)),
        engineering=catalog.list_engineering_values(str(run_id), latest_only=True),
        model_snapshots=catalog.list_model_snapshots(str(run_id)),
        reports=reports,
        profile_defaults=defaults,
        expected_reports=expected,
        report_comparisons=comparisons,
    )
