from __future__ import annotations

from pathlib import Path

from runlab.catalog import LocalCatalog
from runlab.local_store import LocalObjectStore
from runlab.run_profiles import profile_for_category
from runlab.run_workspace import build_run_workspace
from runlab.models import TimingData
from runlab.tech_services_metadata import sync_tech_services_season


def _catalog(tmp_path: Path) -> LocalCatalog:
    return LocalCatalog(tmp_path / "catalog.sqlite3", object_store=LocalObjectStore(tmp_path / "objects"))


def test_profile_resolution_uses_authoritative_category_not_filename():
    assert profile_for_category("PRO STOCK").key == "pro_stock"
    assert profile_for_category("Pro Stock Motorcycle").key == "pro_stock_motorcycle"
    assert profile_for_category("TOP FUEL").key == "top_fuel"
    assert profile_for_category("FUNNY CAR").key == "funny_car"
    assert profile_for_category("SUPER COMP").key == "generic_drag"


def test_run_reports_are_idempotent_and_visible_in_run_workspace(tmp_path: Path):
    c = _catalog(tmp_path)
    event_id = c.create_event("US Nationals", season=2026, event_code="20260903", remote_id="tm:99", sync_state="synced")
    run_id = c.create_run(
        event_id=event_id,
        run_key="tech-services:run-123",
        category="PRO STOCK",
        round="Q1",
        run_datetime="2026-09-04T18:12:00",
        timing={"sixty_ft_s": 0.971, "three_thirty_ft_s": 2.756, "quarter_mile_s": 6.493, "quarter_mile_mph": 211.4},
        weather={"temperature_f": 78.0, "barometer_inhg": 29.34, "humidity_pct": 51.0},
        timing_provenance="official",
        weather_provenance="official",
        remote_id="run-123",
        sync_state="synced",
    )
    telemetry = tmp_path / "Q1.ddf"
    telemetry.write_bytes(b"test evidence")
    asset_id = c.register_asset(run_id, telemetry, asset_type="telemetry", vendor="RacePak", managed=True, metadata={"attachment_mode": "local_working_copy"})
    report = {
        "report_type": "pro_stock_shift",
        "report_version": 1,
        "profile": "pro_stock",
        "generated_at_utc": "2026-09-15T19:00:00+00:00",
        "fingerprint_sha256": "a" * 64,
        "events": [{"shift": 1, "time_s": 1.25, "engine_rpm": 10850.0}],
    }
    rid1, created1 = c.save_run_report(run_id, report, source_asset_id=asset_id, label="Pro Stock Shift Report")
    rid2, created2 = c.save_run_report(run_id, report, source_asset_id=asset_id, label="Pro Stock Shift Report")
    assert rid1 == rid2
    assert created1 is True and created2 is False

    state = build_run_workspace(c, run_id)
    assert state.profile_key == "pro_stock"
    assert state.finish_distance_ft == 1320
    assert state.has_local_telemetry is True
    assert state.missing_expected_reports == ()
    assert len(state.reports) == 1
    assert state.reports[0]["payload"]["events"][0]["engine_rpm"] == 10850.0
    assert any(v.key == "weight_lb" and v.value == 2355 for v in state.profile_defaults)
    assert any(v.key == "quarter_mile_s" and v.value == 6.493 for v in state.timing)


def test_run_workspace_marks_expected_report_pending_until_generated(tmp_path: Path):
    c = _catalog(tmp_path)
    event_id = c.create_event("Test", season=2026, event_code="TEST")
    run_id = c.create_run(event_id=event_id, run_key="PS-Q2", category="PRO STOCK")
    state = build_run_workspace(c, run_id)
    assert state.expected_reports == ("pro_stock_shift",)
    assert state.missing_expected_reports == ("pro_stock_shift",)


def test_timing_data_accepts_canonical_1000_mph():
    timing = TimingData.from_dict({"1000ft": 3.812, "1000ft_mph": 289.6})
    assert timing.thousand_ft_s == 3.812
    assert timing.thousand_ft_mph == 289.6


class _TimingClient:
    def tech_master_events(self, *, season_year, limit):
        return {"events": [{"id": 1, "uuid": "evt-1", "name": "Event", "race_lookup": "20260901", "season_year": 2026, "track_id": 1, "track_name": "Track", "city": "X", "state": "IN", "start_date_local": "2026-09-01", "end_date_local": "2026-09-01"}]}

    def tech_master_entries(self, *, event_instance_id, class_index=""):
        return {"entries": []}

    def parity_runs_with_weather(self, **kwargs):
        return {"runs": [{"id": 11, "uuid": "run-11", "race_lookup": "20260901", "run_timestamp_utc": "2026-09-01 12:00:00", "category": "TOP FUEL", "round": "Q1", "driver_name": "Driver", "ft60": 0.842, "ft330": 2.114, "ft1000": 3.701, "mph1000": 333.2, "weather": None}], "total": 1}

    def parity_runs(self, **kwargs):
        raise AssertionError("weather path should be used")


def test_tech_services_timing_names_hydrate_timingdata_without_alias_loss(tmp_path: Path):
    c = _catalog(tmp_path)
    sync_tech_services_season(c, _TimingClient(), 2026, include_entries=False)
    run = c.get_run(c.list_runs()[0]["id"])
    assert run["timing"]["sixty_ft_s"] == 0.842
    assert run["timing"]["three_thirty_ft_s"] == 2.114
    assert run["timing"]["thousand_ft_s"] == 3.701
    assert run["timing"]["thousand_ft_mph"] == 333.2
    hydrated = TimingData.from_dict(run["timing"])
    assert hydrated.sixty_ft_s == 0.842
    assert hydrated.thousand_ft_s == 3.701
    assert hydrated.thousand_ft_mph == 333.2

def test_run_workspace_compares_latest_shift_report_to_previous_same_driver(tmp_path: Path):
    c = _catalog(tmp_path)
    event1 = c.create_event("Reading", season=2026, event_code="20260815")
    event2 = c.create_event("Indy", season=2026, event_code="20260903")
    driver = c.create_driver("Pro Stock Driver")
    r1 = c.create_run(event_id=event1, driver_id=driver, run_key="R1", category="PRO STOCK", run_datetime="2026-08-16T15:00:00")
    r2 = c.create_run(event_id=event2, driver_id=driver, run_key="R2", category="PRO STOCK", run_datetime="2026-09-04T15:00:00")
    base = {"report_type": "pro_stock_shift", "report_version": 1, "profile": "pro_stock", "generated_at_utc": "2026-08-16T15:05:00+00:00", "fingerprint_sha256": "b" * 64, "events": [{"shift": 1, "time_s": 1.20, "engine_rpm": 10800.0}]}
    cur = {"report_type": "pro_stock_shift", "report_version": 1, "profile": "pro_stock", "generated_at_utc": "2026-09-04T15:05:00+00:00", "fingerprint_sha256": "c" * 64, "events": [{"shift": 1, "time_s": 1.31, "engine_rpm": 11025.0}]}
    c.save_run_report(r1, base)
    c.save_run_report(r2, cur)
    state = build_run_workspace(c, r2)
    comp = state.report_comparisons["pro_stock_shift"]
    assert comp["previous_run_id"] == r1
    assert comp["alerts"] == 1
    assert comp["rows"][0]["delta_rpm"] == 225.0
    assert abs(comp["rows"][0]["delta_time_s"] - 0.11) < 1e-9
