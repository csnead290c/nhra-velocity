from __future__ import annotations

from pathlib import Path

from runlab.catalog import LocalCatalog
from runlab.local_store import LocalObjectStore
from runlab.tech_services_metadata import sync_tech_services_season


class FakeClient:
    def tech_master_events(self, *, season_year, limit):
        assert season_year == 2026
        return {"events":[{
            "id":12,"uuid":"evt-12","name":"PSM Indianapolis Test","event_code":"II1-TEST","race_lookup":"20260908",
            "season_year":2026,"track_id":14,"track_name":"Lucas Oil Indianapolis Raceway Park","city":"Indianapolis","state":"IN",
            "start_date_local":"2026-09-08","end_date_local":"2026-09-08",
        }],"count":1}

    def tech_master_entries(self, *, event_instance_id, class_index=""):
        assert event_instance_id == 12
        return {"entries":[{
            "id":44,"uuid":"entry-44","event_instance_id":12,"person_id":9,"person_name":"Gaige Herrera",
            "vehicle_id":5,"vehicle_description":"PSM Test Bike","class_index":"PRO STOCK MOTORCYCLE","competition_number":"1",
        }],"count":1}

    def parity_runs_with_weather(self, **kwargs):
        assert kwargs["race_lookup"] == "20260908"
        assert kwargs["window_minutes"] == 30
        return {"runs":[{
            "id":101,"uuid":"run-101","race_lookup":"20260908","run_timestamp_utc":"2026-09-08 14:30:00",
            "category":"PRO STOCK MOTORCYCLE","round":"T1","driver_name":"Gaige Herrera","car_number":"1","lane":"1",
            "rt":0.051,"ft60":1.04,"ft330":2.85,"ft660":4.33,"mph660":164.2,"ft1000":5.62,"mph1000":184.3,"ft1320":6.72,"mph1320":201.0,
            "source_ref":"test","incident_count":2,
            "weather":{
                "timestamp_utc":"2026-09-08 14:30:10","temp_f":82.5,"rh_pct":47.0,"pressure_inhg":29.18,
                "delta_seconds":10,"canonical_source_kind":"mixed","canonical_source_detail":"tempest=3, open_meteo=1","sample_count":4,
            },
        }],"total":1,"joinedCount":1,"limit":2000,"offset":0}

    def parity_runs(self, **kwargs):
        assert kwargs["race_lookup"] == "20260908"
        return {"runs":[{
            "id":101,"uuid":"run-101","race_lookup":"20260908","run_timestamp_utc":"2026-09-08 14:30:00",
            "category":"PRO STOCK MOTORCYCLE","round":"T1","driver_name":"Gaige Herrera","car_number":"1","lane":"1",
            "rt":0.051,"ft60":1.04,"ft330":2.85,"ft660":4.33,"mph660":164.2,"ft1000":5.62,"mph1000":184.3,"ft1320":6.72,"mph1320":201.0,
            "source_ref":"test","row_hash":"abc",
        }],"total":1,"limit":1000,"offset":0}


def test_read_only_site_metadata_sync_is_idempotent_and_does_not_infer_entry_run_link(tmp_path: Path):
    catalog=LocalCatalog(path=tmp_path/"catalog.sqlite",object_store=LocalObjectStore(tmp_path/"objects"))
    first=sync_tech_services_season(catalog,FakeClient(),2026)
    assert first.events_created == 1
    assert first.entries_created == 1
    assert first.runs_created == 1

    runs=catalog.list_runs()
    assert len(runs)==1
    run=catalog.get_run(str(runs[0]["id"]))
    assert run["entry_id"] in (None, "")
    assert run["driver_name"] == "Gaige Herrera"
    assert run["timing"]["quarter_mile_s"] == 6.72
    assert run["timing"]["three_thirty_ft_s"] == 2.85
    assert run["weather"]["temperature_f"] == 82.5
    assert run["weather"]["barometer_inhg"] == 29.18
    assert run["weather"]["humidity_pct"] == 47.0
    assert run["weather"]["canonical_source_kind"] == "mixed"
    assert run["weather"]["delta_seconds"] == 10
    assert run["weather_provenance"] == "official"
    assert run["source"]["incident_count"] == 2
    assert run["source"]["entry_link_status"] == "server_not_exposed"
    assert first.runs_with_weather == 1
    assert first.weather_fallback_events == 0

    second=sync_tech_services_season(catalog,FakeClient(),2026)
    assert second.events_updated == 1
    assert second.runs_updated == 1
    assert len(catalog.list_runs()) == 1
    assert len(catalog.list_entries(event_id=str(run["event_id"]))) == 1


class FallbackClient(FakeClient):
    def parity_runs_with_weather(self, **kwargs):
        raise RuntimeError("weather endpoint unavailable")


def test_weather_join_failure_falls_back_to_timing_only_without_writing_server(tmp_path: Path):
    catalog=LocalCatalog(path=tmp_path/"catalog.sqlite",object_store=LocalObjectStore(tmp_path/"objects"))
    result=sync_tech_services_season(catalog,FallbackClient(),2026)
    assert result.runs_created == 1
    assert result.runs_with_weather == 0
    assert result.weather_fallback_events == 1
    assert any("timing-only" in w for w in result.warnings)
    run=catalog.get_run(str(catalog.list_runs()[0]["id"]))
    assert run["weather"] == {}
    assert run["weather_provenance"] == "unknown"
