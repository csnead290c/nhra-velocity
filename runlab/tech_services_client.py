from __future__ import annotations

"""Application service for mirroring Tech Services runs and caching their assets."""

from dataclasses import dataclass, field
from typing import Any

from .catalog import LocalCatalog
from .sync_engine import apply_tech_services_snapshot, SyncApplyResult
from .transport import TechServicesTransport


@dataclass
class CacheResult:
    cached: int = 0
    already_cached: int = 0
    skipped_local: int = 0
    errors: list[dict[str,str]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.errors


def sync_catalog(catalog: LocalCatalog, transport: TechServicesTransport) -> SyncApplyResult:
    cursor=catalog.get_sync_cursor(transport.capabilities.provider,'catalog')
    payload=transport.pull_catalog_snapshot(cursor=cursor)
    return apply_tech_services_snapshot(catalog,payload,provider=transport.capabilities.provider)


def ensure_asset_cached(catalog: LocalCatalog, transport: TechServicesTransport, asset_id: str) -> str:
    asset=catalog.get_asset(asset_id)
    if asset is None:
        raise KeyError(asset_id)
    local=str(asset.get('local_path') or '')
    if local and catalog.asset_cache_valid(asset_id):
        return local
    if str(asset.get('source_kind') or '')!='tech_services' or not asset.get('remote_id'):
        return catalog.mark_asset_managed(asset_id)
    content=transport.fetch_asset(str(asset['remote_id']))
    return catalog.cache_server_asset_bytes(asset_id,content)


def cache_run(catalog: LocalCatalog, transport: TechServicesTransport, run_id: str) -> CacheResult:
    out=CacheResult()
    for asset in catalog.list_assets(run_id):
        try:
            if catalog.asset_cache_valid(str(asset['id'])):
                out.already_cached+=1
            elif str(asset.get('source_kind') or '')=='tech_services':
                ensure_asset_cached(catalog,transport,str(asset['id']));out.cached+=1
            else:
                ensure_asset_cached(catalog,transport,str(asset['id']));out.cached+=1;out.skipped_local+=1
        except Exception as exc:
            out.errors.append({'asset_id':str(asset.get('id') or ''),'filename':str(asset.get('filename') or ''),'error':str(exc)})
    return out


def cache_event(catalog: LocalCatalog, transport: TechServicesTransport, event_id: str) -> CacheResult:
    out=CacheResult()
    for run in catalog.list_runs(event_id=event_id,limit=100000):
        item=cache_run(catalog,transport,str(run['id']))
        out.cached+=item.cached;out.already_cached+=item.already_cached;out.skipped_local+=item.skipped_local;out.errors.extend(item.errors)
    return out


def cache_case(catalog: LocalCatalog, transport: TechServicesTransport, case_id: str) -> CacheResult:
    """Cache every authoritative Run Asset referenced by an AnalysisCase.

    Standalone case evidence is already local by definition in v0.18; linked
    Run Assets continue to use the authoritative Tech Services fetch path.
    """
    if catalog.get_analysis_case(case_id) is None:
        raise KeyError(case_id)
    out=CacheResult();seen:set[str]=set()
    for run in catalog.list_case_runs(case_id):
        for asset in catalog.list_assets(str(run['id'])):
            asset_id=str(asset['id'])
            if asset_id in seen:continue
            seen.add(asset_id)
            try:
                if catalog.asset_cache_valid(asset_id):
                    out.already_cached+=1
                elif str(asset.get('source_kind') or '')=='tech_services':
                    ensure_asset_cached(catalog,transport,asset_id);out.cached+=1
                else:
                    ensure_asset_cached(catalog,transport,asset_id);out.cached+=1;out.skipped_local+=1
            except Exception as exc:
                out.errors.append({'asset_id':asset_id,'filename':str(asset.get('filename') or ''),'error':str(exc)})
    return out
