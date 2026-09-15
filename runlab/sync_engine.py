from __future__ import annotations

"""Apply authoritative Tech Services Event/Run/Asset snapshots to the local mirror."""

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping
import hashlib
import json

from .catalog import LocalCatalog
from .official_runs import normalize_category


def _stable_hash(value: Any) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


@dataclass
class SyncApplyResult:
    provider: str
    cursor: str = ""
    events_created: int = 0
    events_updated: int = 0
    runs_created: int = 0
    runs_updated: int = 0
    assets_created: int = 0
    assets_updated: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str,Any]:
        return self.__dict__.copy()


def apply_tech_services_snapshot(catalog: LocalCatalog, payload: Mapping[str,Any], *, provider: str='nhra-tech-services') -> SyncApplyResult:
    """Mirror Tech Services identity and permanent Run→Asset relationships.

    Contract v4 intentionally models assets *inside their authoritative run*.
    Assets are not discovered elsewhere and are never matched to runs locally.
    Omitted asset arrays leave existing mirrored assets unchanged.
    """
    version=int(payload.get('contract_version') or 0)
    if version!=4:
        raise ValueError(f'Unsupported Tech Services sync contract version {version}; expected 4')
    result=SyncApplyResult(provider=provider,cursor=str(payload.get('cursor') or ''))
    for event in payload.get('events',[]) or []:
        if not isinstance(event,Mapping): continue
        code=str(event.get('event_code') or '').strip();remote_event_id=str(event.get('remote_id') or '').strip()
        name=str(event.get('name') or code or 'NHRA Event').strip()
        before=catalog.find_event(event_code=code,remote_id=remote_event_id)
        event_id=catalog.upsert_event(name,season=int(event['season']) if event.get('season') not in (None,'') else None,event_code=code,start_date=str(event.get('start_date') or ''),end_date=str(event.get('end_date') or ''),track_name=str(event.get('track_name') or ''),track_id=str(event.get('track_id') or ''),location=str(event.get('location') or ''),remote_id=remote_event_id,sync_state='synced')
        result.events_created+=int(before is None);result.events_updated+=int(before is not None)
        if remote_event_id:
            catalog.upsert_remote_entity(provider,'event',remote_event_id,event_id,revision=str(event.get('revision') or ''),payload_hash=_stable_hash(event))
        for run in event.get('runs',[]) or []:
            if not isinstance(run,Mapping): continue
            remote_run_id=str(run.get('remote_id') or '').strip()
            if not remote_run_id:
                result.warnings.append(f'Skipped Tech Services run without remote_id in event {code or name}');continue
            driver_name=str(run.get('driver_name') or run.get('driver') or '').strip();category=normalize_category(str(run.get('category') or run.get('class') or ''))
            driver_id=catalog.find_or_create_driver(driver_name,remote_id=str(run.get('driver_remote_id') or '')) if driver_name else None
            car_number=str(run.get('car_number') or '')
            vehicle_id=None
            if car_number or run.get('vehicle_name'):
                vehicle_id=catalog.find_or_create_vehicle(name=str(run.get('vehicle_name') or f'{category} {car_number}' or 'Vehicle'),category=category,car_number=car_number,remote_id=str(run.get('vehicle_remote_id') or ''))
            entry_id=catalog.find_or_create_entry(event_id,driver_id=driver_id,vehicle_id=vehicle_id,category=category,car_number=car_number,remote_id=str(run.get('entry_remote_id') or ''))
            run_key=str(run.get('run_key') or f'remote:{provider}:{remote_run_id}')
            _,created=catalog.upsert_run(run_key=run_key,event_id=event_id,entry_id=entry_id,driver_id=driver_id,vehicle_id=vehicle_id,round=str(run.get('round') or ''),run_number=str(run.get('run_number') or ''),lane=str(run.get('lane') or ''),category=category,car_number=car_number,run_datetime=str(run.get('run_datetime') or ''),timing=dict(run.get('timing') or {}) if run.get('timing') is not None else None,weather=dict(run.get('weather') or {}) if run.get('weather') is not None else None,timing_provenance='official' if run.get('timing') is not None else 'unknown',weather_provenance='official' if run.get('weather') is not None else 'unknown',source={'kind':'tech_services_sync','provider':provider,'remote_id':remote_run_id,'revision':str(run.get('revision') or '')},notes=None,remote_id=remote_run_id,sync_state='synced')
            local=catalog.get_run_by_key(run_key)
            if not local: continue
            local_run_id=str(local['id'])
            catalog.upsert_remote_entity(provider,'run',remote_run_id,local_run_id,revision=str(run.get('revision') or ''),payload_hash=_stable_hash(run))
            result.runs_created+=int(created);result.runs_updated+=int(not created)
            if run.get('assets') is not None:
                for asset in run.get('assets') or []:
                    if not isinstance(asset,Mapping): continue
                    remote_asset_id=str(asset.get('remote_id') or '').strip()
                    if not remote_asset_id:
                        result.warnings.append(f'Skipped asset without remote_id on run {remote_run_id}');continue
                    _,asset_created=catalog.upsert_server_asset(local_run_id,remote_id=remote_asset_id,filename=str(asset.get('filename') or remote_asset_id),asset_type=str(asset.get('asset_type') or asset.get('type') or 'other'),sha256=str(asset.get('sha256') or ''),size_bytes=int(asset.get('size_bytes') or 0),mime_type=str(asset.get('mime_type') or ''),vendor=str(asset.get('vendor') or ''),remote_uri=str(asset.get('remote_uri') or ''),revision=str(asset.get('revision') or ''),uploaded_at=str(asset.get('uploaded_at') or ''),metadata=dict(asset.get('metadata') or {}))
                    result.assets_created+=int(asset_created);result.assets_updated+=int(not asset_created)
                    local_asset=catalog.get_asset_by_remote_id(remote_asset_id)
                    if local_asset:
                        catalog.upsert_remote_entity(provider,'asset',remote_asset_id,str(local_asset['id']),revision=str(asset.get('revision') or ''),payload_hash=_stable_hash(asset))
    if result.cursor:
        catalog.set_sync_cursor(provider,'catalog',result.cursor)
    return result

# Compatibility alias for v0.15/v0.16 callers during migration.
apply_official_snapshot=apply_tech_services_snapshot
