from __future__ import annotations

"""Read-only metadata/timing synchronization from nhratechservices.com.

This adapter intentionally consumes only the existing protected GET endpoints.
It does not write to Tech Services and it does not infer the server's missing
EventEntry -> parity Run relationship.  Entries and Runs are therefore mirrored
independently under the authoritative Event until the API exposes that bridge.
"""

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping

from .catalog import LocalCatalog
from .official_runs import normalize_category
from .tech_services_http import TechServicesHttpClient


PROVIDER = "nhra-tech-services"


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _remote_id(prefix: str, row: Mapping[str, Any]) -> str:
    return str(row.get("uuid") or "").strip() or (f"{prefix}:{row.get('id')}" if row.get("id") not in (None, "") else "")


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timing(row: Mapping[str, Any]) -> dict[str, Any]:
    aliases = {
        "rt": "reaction_time_s",
        "ft60": "sixty_ft_s",
        "ft330": "three_thirty_ft_s",
        "ft660": "eighth_mile_s",
        "mph660": "eighth_mile_mph",
        "ft1000": "thousand_ft_s",
        "mph1000": "thousand_ft_mph",
        "ft1320": "quarter_mile_s",
        "mph1320": "quarter_mile_mph",
        "dial_in": "dial_in_s",
        "mov": "margin_of_victory_s",
    }
    result: dict[str, Any] = {}
    for source, target in aliases.items():
        value = _number(row.get(source))
        if value is not None:
            result[target] = value
    for key in ("win_flag", "dq_flag", "place"):
        if row.get(key) not in (None, ""):
            result[key] = row.get(key)
    return result


def _weather(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Translate the site's canonical-weather payload into Velocity names.

    Provenance/join metadata is intentionally retained beside the canonical
    Environment fields. Unknown keys remain evidence; ``Environment.from_dict``
    simply ignores fields it does not model.
    """
    value = row.get("weather")
    if not isinstance(value, Mapping):
        return None
    raw = dict(value)
    aliases = {
        "temp_f": "temperature_f",
        "pressure_inhg": "barometer_inhg",
        "rh_pct": "humidity_pct",
        "wind_speed_mph": "wind_mph",
        "wind_dir_deg": "wind_angle_deg",
    }
    for source, target in aliases.items():
        if raw.get(source) not in (None, "") and target not in raw:
            raw[target] = raw[source]
    return raw


@dataclass
class MetadataSyncResult:
    season_year: int
    events_created: int = 0
    events_updated: int = 0
    entries_created: int = 0
    entries_existing: int = 0
    runs_created: int = 0
    runs_updated: int = 0
    runs_with_weather: int = 0
    weather_fallback_events: int = 0
    events_without_race_lookup: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def event_count(self) -> int:
        return self.events_created + self.events_updated

    @property
    def run_count(self) -> int:
        return self.runs_created + self.runs_updated


def _sync_entry(catalog: LocalCatalog, event_id: str, row: Mapping[str, Any]) -> tuple[str, bool]:
    remote_entry = _remote_id("tm-entry", row)
    existing_ids = {str(x.get("id")) for x in catalog.list_entries(event_id=event_id)}
    driver_name = str(row.get("person_name") or "").strip()
    person_remote = f"tm-person:{row.get('person_id')}" if row.get("person_id") not in (None, "") else ""
    driver_id = catalog.find_or_create_driver(driver_name, remote_id=person_remote) if driver_name else None

    category = normalize_category(str(row.get("class_index") or row.get("category") or ""))
    car_number = str(row.get("competition_number") or "").strip()
    vehicle_desc = str(row.get("vehicle_description") or "").strip()
    vehicle_remote = f"tm-vehicle:{row.get('vehicle_id')}" if row.get("vehicle_id") not in (None, "") else ""
    vehicle_id = None
    if vehicle_desc or vehicle_remote:
        vehicle_id = catalog.find_or_create_vehicle(
            name=vehicle_desc or f"{category} #{car_number}".strip(),
            category=category,
            car_number=car_number,
            remote_id=vehicle_remote,
        )
    entry_id = catalog.find_or_create_entry(
        event_id,
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        category=category,
        car_number=car_number,
        remote_id=remote_entry,
    )
    created = entry_id not in existing_ids
    if remote_entry:
        catalog.upsert_remote_entity(PROVIDER, "entry", remote_entry, entry_id, payload_hash=_stable_hash(row))
    return entry_id, created


def _sync_run(catalog: LocalCatalog, event_id: str, row: Mapping[str, Any]) -> bool:
    remote_run = _remote_id("parity-run", row)
    if not remote_run:
        raise ValueError("Tech Services parity run has no stable id/uuid")
    driver_name = str(row.get("driver_name") or "").strip()
    driver_id = catalog.find_or_create_driver(driver_name) if driver_name else None
    category = normalize_category(str(row.get("category") or row.get("class_index") or ""))
    car_number = str(row.get("car_number") or "").strip()
    vehicle_id = None
    if car_number:
        vehicle_id = catalog.find_or_create_vehicle(
            name=f"{category} #{car_number}".strip(),
            category=category,
            car_number=car_number,
        )

    run_datetime = str(row.get("run_timestamp_utc") or row.get("run_time_local") or "").strip()
    weather = _weather(row)
    local_id, created = catalog.upsert_run(
        run_key=f"tech-services:{remote_run}",
        event_id=event_id,
        # IMPORTANT: parity.php does not expose event_entry_id. Do not infer it
        # from driver name, number, or the independently synchronized roster.
        entry_id=None,
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        round=str(row.get("round") or ""),
        run_number=str(row.get("place") or ""),
        lane=str(row.get("lane") or ""),
        category=category,
        car_number=car_number,
        run_datetime=run_datetime,
        timing=_timing(row),
        weather=weather,
        timing_provenance="official",
        weather_provenance="official" if weather is not None else "unknown",
        source={
            "kind": "nhratechservices_parity",
            "provider": PROVIDER,
            "remote_id": remote_run,
            "race_lookup": str(row.get("race_lookup") or ""),
            "entry_link_status": "server_not_exposed",
            "source_ref": str(row.get("source_ref") or ""),
            "row_hash": str(row.get("row_hash") or ""),
            "incident_count": row.get("incident_count"),
            "weather_join": dict(row.get("weather")) if isinstance(row.get("weather"), Mapping) else None,
        },
        remote_id=remote_run,
        sync_state="synced",
    )
    catalog.upsert_remote_entity(PROVIDER, "run", remote_run, local_id, payload_hash=_stable_hash(row))
    return created


def sync_tech_services_season(
    catalog: LocalCatalog,
    client: TechServicesHttpClient,
    season_year: int,
    *,
    include_entries: bool = True,
    include_runs: bool = True,
) -> MetadataSyncResult:
    """Mirror one Tech Services season into the local catalog using GETs only."""
    year = int(season_year)
    result = MetadataSyncResult(season_year=year)
    payload = client.tech_master_events(season_year=year, limit=500)
    events = payload.get("events") or []
    if not isinstance(events, list):
        raise ValueError("Tech Services listEvents response did not contain an events array")

    for event in events:
        if not isinstance(event, Mapping):
            continue
        remote_event = _remote_id("tm-event", event)
        name = str(event.get("name") or event.get("event_code") or event.get("race_lookup") or "NHRA Event").strip()
        race_lookup = str(event.get("race_lookup") or "").strip()
        server_code = str(event.get("event_code") or "").strip()
        # Event type/session codes (e.g. II1) can repeat every season.  The
        # race_lookup date is the safer local event code when available.
        code = race_lookup or (f"{year}:{server_code}" if server_code else "")
        before = catalog.find_event(event_code=code, remote_id=remote_event)
        location = ", ".join(x for x in (str(event.get("city") or "").strip(), str(event.get("state") or "").strip()) if x)
        local_event = catalog.upsert_event(
            name,
            season=int(event.get("season_year") or year),
            event_code=code,
            start_date=str(event.get("start_date_local") or ""),
            end_date=str(event.get("end_date_local") or ""),
            track_name=str(event.get("track_name") or ""),
            track_id=f"tech-services:{event.get('track_id')}" if event.get("track_id") not in (None, "") else "",
            location=location,
            remote_id=remote_event,
            sync_state="synced",
        )
        result.events_created += int(before is None)
        result.events_updated += int(before is not None)
        if remote_event:
            catalog.upsert_remote_entity(PROVIDER, "event", remote_event, local_event, payload_hash=_stable_hash(event))

        if include_entries and event.get("id") not in (None, ""):
            try:
                entry_payload = client.tech_master_entries(event_instance_id=int(event["id"]))
                entries = entry_payload.get("entries") or []
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, Mapping):
                            _, created = _sync_entry(catalog, local_event, entry)
                            result.entries_created += int(created)
                            result.entries_existing += int(not created)
            except Exception as exc:
                result.warnings.append(f"{name}: entries were not synchronized ({exc})")

        if include_runs:
            if not race_lookup:
                result.events_without_race_lookup += 1
                continue
            offset = 0
            page_size = 2000
            use_weather_endpoint = hasattr(client, "parity_runs_with_weather")
            weather_endpoint_failed = False
            while True:
                try:
                    if use_weather_endpoint and not weather_endpoint_failed:
                        run_payload = client.parity_runs_with_weather(
                            race_lookup=race_lookup, window_minutes=30, limit=page_size, offset=offset
                        )
                    else:
                        # Backward-compatible/read-only fallback for deployments
                        # where the verified weather-join action is unavailable.
                        run_payload = client.parity_runs(
                            race_lookup=race_lookup, dq="include", include_bad=True,
                            limit=page_size, offset=offset,
                        )
                except Exception as exc:
                    if use_weather_endpoint and not weather_endpoint_failed:
                        weather_endpoint_failed = True
                        result.weather_fallback_events += 1
                        result.warnings.append(
                            f"{name}: canonical weather join unavailable; timing-only Run sync used ({exc})"
                        )
                        continue
                    result.warnings.append(f"{name}: official runs were not synchronized ({exc})")
                    break
                runs = run_payload.get("runs") or []
                if not isinstance(runs, list):
                    if use_weather_endpoint and not weather_endpoint_failed:
                        weather_endpoint_failed = True
                        result.weather_fallback_events += 1
                        result.warnings.append(
                            f"{name}: canonical weather response had no runs array; timing-only Run sync used"
                        )
                        continue
                    result.warnings.append(f"{name}: parity response did not contain a runs array")
                    break
                for run in runs:
                    if not isinstance(run, Mapping):
                        continue
                    try:
                        created = _sync_run(catalog, local_event, run)
                    except Exception as exc:
                        result.warnings.append(f"{name}: skipped one run ({exc})")
                        continue
                    result.runs_created += int(created)
                    result.runs_updated += int(not created)
                    result.runs_with_weather += int(isinstance(run.get("weather"), Mapping))
                offset += len(runs)
                total = int(run_payload.get("total") or 0)
                if not runs or len(runs) < page_size or (total and offset >= total):
                    break
    return result
