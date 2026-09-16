from __future__ import annotations

from pathlib import Path

import pandas as pd

from runlab.catalog import LocalCatalog
from runlab.catalog_bridge import register_opened_telemetry
from runlab.local_store import LocalObjectStore
from runlab.models import Environment, TelemetryRun, TimingData


def _catalog(tmp_path: Path) -> LocalCatalog:
    return LocalCatalog(path=tmp_path / "catalog.sqlite", object_store=LocalObjectStore(tmp_path / "objects"))


def test_explicit_local_attachment_uses_selected_canonical_run_and_inherits_official_context(tmp_path: Path):
    catalog = _catalog(tmp_path)
    event_id = catalog.create_event(
        "PSM Indianapolis Test",
        season=2026,
        event_code="20260908",
        remote_id="evt-12",
        sync_state="synced",
    )
    run_id = catalog.create_run(
        event_id=event_id,
        run_key="tech-services:run-101",
        round="T1",
        category="PRO STOCK MOTORCYCLE",
        car_number="1",
        run_datetime="2026-09-08 14:30:00",
        timing={
            "sixty_foot_s": 1.04,
            "three_thirty_ft_s": 2.85,
            "eighth_mile_s": 4.33,
            "quarter_mile_s": 6.72,
            "quarter_mile_mph": 201.0,
            "reaction_time_s": 0.051,
        },
        weather={"temperature_f": 72.0, "barometer_inhg": 29.83, "humidity_pct": 42.0},
        timing_provenance="official",
        weather_provenance="official",
        source={"kind": "nhratechservices_parity", "remote_id": "run-101"},
        remote_id="run-101",
        sync_state="synced",
    )

    source = tmp_path / "logger.csv"
    source.write_text("time,engine_rpm\n0,5000\n0.1,6000\n")
    decoded = TelemetryRun(
        name="logger",
        data=pd.DataFrame({"time_s": [0.0, 0.1], "engine_rpm": [5000.0, 6000.0]}),
        channel_map={"time_s": "time_s", "engine_rpm": "engine_rpm"},
        vendor="generic",
        timing=TimingData(quarter_mile_s=9.99),
        environment=Environment(temperature_f=100.0),
        metadata={"timing_provenance": {"quarter_mile_s": "user"}, "environment_provenance": {"temperature_f": "user"}},
    )

    actual_run_id, asset_id, session_id = register_opened_telemetry(
        catalog,
        str(source),
        decoded,
        run_id=run_id,
        managed=True,
        local_attachment=True,
    )

    assert actual_run_id == run_id
    assert session_id
    asset = catalog.get_asset(asset_id)
    assert asset is not None
    assert asset["run_id"] == run_id
    assert asset["source_kind"] == "local_dev"
    assert asset["storage_mode"] == "managed"
    assert Path(asset["local_path"]).is_file()
    assert asset["metadata"]["attachment_mode"] == "local_working_copy"
    assert asset["metadata"]["server_persistence"] is False

    # Official catalog data wins over values embedded/edited in the logger session.
    assert decoded.timing.quarter_mile_s == 6.72
    assert decoded.timing.three_thirty_ft_s == 2.85
    assert decoded.environment.temperature_f == 72.0
    assert decoded.metadata["official_timing"]["reaction_time_s"] == 0.051
    assert decoded.metadata["catalog_run_id"] == run_id

    persisted = catalog.get_run(run_id)
    assert persisted is not None
    assert persisted["timing_provenance"] == "official"
    assert persisted["weather_provenance"] == "official"
    assert persisted["timing"]["quarter_mile_s"] == 6.72
    assert persisted["weather"]["temperature_f"] == 72.0


def test_local_attachment_requires_explicit_run_identity(tmp_path: Path):
    catalog = _catalog(tmp_path)
    source = tmp_path / "logger.csv"
    source.write_text("time,engine_rpm\n0,5000\n0.1,6000\n")
    decoded = TelemetryRun(
        name="logger",
        data=pd.DataFrame({"time_s": [0.0, 0.1], "engine_rpm": [5000.0, 6000.0]}),
        channel_map={"time_s": "time_s", "engine_rpm": "engine_rpm"},
    )

    try:
        register_opened_telemetry(catalog, str(source), decoded, managed=True, local_attachment=True)
    except ValueError as exc:
        assert "explicit canonical run_id" in str(exc)
    else:
        raise AssertionError("local attachment must fail closed without an explicit Run")


def test_local_run_data_attachment_persists_across_catalog_reopen(tmp_path: Path):
    db_path = tmp_path / "catalog.sqlite"
    object_root = tmp_path / "objects"
    catalog = LocalCatalog(path=db_path, object_store=LocalObjectStore(object_root))
    event_id = catalog.create_event("Persistence Test", season=2026, remote_id="evt-persist", sync_state="synced")
    run_id = catalog.create_run(
        event_id=event_id,
        run_key="tech-services:run-persist",
        round="Q1",
        category="PRO STOCK",
        car_number="7",
        remote_id="run-persist",
        sync_state="synced",
    )
    source = tmp_path / "persistent-log.csv"
    source.write_text("time,engine_rpm\n0,5000\n0.1,6000\n")
    decoded = TelemetryRun(
        name="persistent-log",
        data=pd.DataFrame({"time_s": [0.0, 0.1], "engine_rpm": [5000.0, 6000.0]}),
        channel_map={"time_s": "time_s", "engine_rpm": "engine_rpm"},
        vendor="generic",
    )
    _, asset_id, _ = register_opened_telemetry(
        catalog, str(source), decoded, run_id=run_id, managed=True, local_attachment=True
    )
    first = catalog.get_asset(asset_id)
    assert first is not None
    managed_path = Path(first["local_path"])
    assert managed_path.is_file()
    assert first["metadata"]["local_persistence"] is True
    assert first["metadata"]["persistence_scope"] == "velocity_local_catalog"

    # Simulate leaving/reopening Velocity: a new LocalCatalog instance must
    # retain the exact canonical Run -> local managed data-log association.
    reopened = LocalCatalog(path=db_path, object_store=LocalObjectStore(object_root))
    assets = [a for a in reopened.list_assets(run_id) if a.get("asset_type") == "telemetry"]
    assert len(assets) == 1
    assert assets[0]["id"] == asset_id
    assert Path(assets[0]["local_path"]).is_file()
    assert assets[0]["storage_mode"] == "managed"

    run_rows = reopened.list_runs(event_id=event_id)
    assert len(run_rows) == 1
    assert run_rows[0]["data_log_count"] == 1
    assert run_rows[0]["local_data_log_count"] == 1


def test_managed_run_data_reopens_through_filename_preserving_alias(tmp_path: Path):
    """A managed object is hash-named, but native decoders need the source suffix.

    This is the real close/reopen path that the earlier persistence test missed:
    not only must the Run->Asset row survive, the stored bytes must still be
    decodable after the original user-selected file is no longer being used.
    """
    db_path = tmp_path / "catalog.sqlite"
    object_root = tmp_path / "objects"
    catalog = LocalCatalog(path=db_path, object_store=LocalObjectStore(object_root))
    event_id = catalog.create_event("Decode Persistence", season=2026, remote_id="evt-decode", sync_state="synced")
    run_id = catalog.create_run(event_id=event_id, run_key="tech-services:run-decode", remote_id="run-decode", sync_state="synced")
    source = tmp_path / "team-run.csv"
    source.write_text("Time (s),Engine RPM\n0,5000\n0.1,6000\n")
    decoded = TelemetryRun(
        name="team-run",
        data=pd.DataFrame({"Time (s)": [0.0, 0.1], "Engine RPM": [5000.0, 6000.0]}),
        channel_map={"time_s": "Time (s)", "engine_rpm": "Engine RPM"},
        vendor="generic",
    )
    _, asset_id, _ = register_opened_telemetry(catalog, str(source), decoded, run_id=run_id, managed=True, local_attachment=True)

    reopened = LocalCatalog(path=db_path, object_store=LocalObjectStore(object_root))
    read_path = Path(reopened.local_asset_read_path(asset_id))
    assert read_path.is_file()
    assert read_path.name == "team-run.csv"

    from runlab.importers import load_telemetry
    restored = load_telemetry(read_path)
    assert len(restored.data) == 2
    assert "engine_rpm" in restored.channel_map
    assert restored.channel_map["engine_rpm"] in restored.data.columns
