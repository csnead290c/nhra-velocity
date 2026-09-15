from __future__ import annotations

"""Tech Services contract v4 helpers.

The server owns Run→Asset relationships. Desktop payloads never attempt to
match, re-parent, or invent server assets.
"""

from pathlib import Path
from typing import Any, Dict
from .catalog import LocalCatalog
from .branding import PRODUCT_VERSION
from .product_manifest import SYNC_CONTRACT_VERSION


def asset_manifest(asset: Dict[str,Any]) -> Dict[str,Any]:
    return {
        'remote_id':asset.get('remote_id'),
        'revision':asset.get('revision'),
        'asset_type':asset.get('asset_type'),
        'filename':asset.get('filename'),
        'sha256':asset.get('sha256'),
        'size_bytes':asset.get('size_bytes',0),
        'mime_type':asset.get('mime_type',''),
        'vendor':asset.get('vendor',''),
        'uploaded_at':asset.get('uploaded_at',''),
        'metadata':asset.get('metadata',{}),
    }


def run_analysis_payload(catalog: LocalCatalog, run_id: str) -> Dict[str,Any]:
    run=catalog.get_run(run_id)
    if run is None: raise KeyError(run_id)
    models=[{k:v for k,v in m.items() if k!='run_id'} for m in catalog.list_model_snapshots(run_id)]
    return {'contract_version':SYNC_CONTRACT_VERSION,'application_version':PRODUCT_VERSION,'run_remote_id':run.get('remote_id'),'run_id':run_id,'model_snapshots':models}


def run_sync_payload(catalog: LocalCatalog, run_id: str) -> Dict[str,Any]:
    """Compatibility/debug payload showing the mirrored authoritative run package."""
    run=catalog.get_run(run_id)
    if run is None: raise KeyError(run_id)
    return {'contract_version':SYNC_CONTRACT_VERSION,'application_version':PRODUCT_VERSION,'run':run,'assets':[asset_manifest(x) for x in catalog.list_assets(run_id)],'model_snapshots':[{k:v for k,v in m.items() if k!='run_id'} for m in catalog.list_model_snapshots(run_id)]}


def event_offline_manifest(catalog: LocalCatalog,event_id: str) -> Dict[str,Any]:
    rows=[];missing=[]
    for r in catalog.list_runs(event_id=event_id,limit=100000):
        assets=[]
        for a in catalog.list_assets(str(r['id'])):
            cached=catalog.asset_cache_valid(str(a['id']))
            assets.append({'id':a['id'],'remote_id':a.get('remote_id'),'filename':a['filename'],'sha256':a.get('sha256',''),'cached':cached})
            if not cached: missing.append(a['id'])
        rows.append({'run_id':r['id'],'remote_id':r.get('remote_id'),'run_key':r.get('run_key',''),'assets':assets})
    return {'event_id':event_id,'runs':rows,'missing_cached_asset_ids':missing}


def analysis_case_bundle(catalog: LocalCatalog, case_id: str) -> Dict[str,Any]:
    """Serialize one local AnalysisCase without machine-specific paths.

    This is a provider-neutral analysis bundle, *not* a guessed Tech Services
    HTTP contract. A future backend adapter may translate this structure into
    the site's existing incident-analysis/session API once that API is fully
    inspected and authenticated.
    """
    case=catalog.get_analysis_case(case_id)
    if case is None:raise KeyError(case_id)
    primary=catalog.get_run(str(case.get('primary_run_id') or '')) if case.get('primary_run_id') else None
    runs=[]
    for r in catalog.list_case_runs(case_id):
        runs.append({
            'role':r.get('role','reference'),
            'sort_order':int(r.get('sort_order') or 0),
            'notes':r.get('case_notes',''),
            'case_time_mapping':{
                'scale':float(r.get('time_scale') or 1.0),
                'offset_s':float(r.get('time_offset_s') or 0.0),
                'method':r.get('alignment_method','run_time'),
                'confidence':r.get('alignment_confidence'),
                'uncertainty_s':r.get('alignment_uncertainty_s'),
                'anchors':r.get('alignment_anchors',[]),
            },
            'run_id':r.get('id'),
            'run_remote_id':r.get('remote_id'),
            'run_key':r.get('run_key',''),
            'event_name':r.get('event_name',''),
            'driver_name':r.get('driver_name',''),
            'category':r.get('category',''),
            'round':r.get('round',''),
            'run_datetime':r.get('run_datetime',''),
        })
    evidence=[]
    for e in catalog.list_case_evidence(case_id):
        evidence.append({
            'id':e.get('id'),
            'evidence_type':e.get('evidence_type','other'),
            'label':e.get('label',''),
            'asset_id':e.get('asset_id'),
            'asset_remote_id':e.get('linked_remote_id') if e.get('asset_id') else e.get('remote_id'),
            'linked_run_id':e.get('linked_run_id'),
            'filename':e.get('filename',''),
            'sha256':e.get('sha256',''),
            'size_bytes':int(e.get('size_bytes') or 0),
            'mime_type':e.get('mime_type',''),
            'source_kind':e.get('source_kind',''),
            'metadata':e.get('metadata',{}),
        })
    models=[]
    for m in catalog.list_model_snapshots(analysis_case_id=case_id):
        models.append({k:v for k,v in m.items() if k not in {'run_id','analysis_case_id'}})
    return {
        'analysis_bundle_version':2,
        'application_version':PRODUCT_VERSION,
        'case':{
            'id':case['id'],
            'remote_id':case.get('remote_id'),
            'revision':case.get('revision'),
            'case_type':case.get('case_type','engineering'),
            'title':case.get('title',''),
            'status':case.get('status','open'),
            'summary':case.get('summary',''),
            'primary_run_id':case.get('primary_run_id'),
            'primary_run_remote_id':primary.get('remote_id') if primary else None,
            'created_at':case.get('created_at'),
            'updated_at':case.get('updated_at'),
        },
        'runs':runs,
        'evidence':evidence,
        'timeline_markers':[
            {k:v for k,v in marker.items() if k not in {'payload_json'}}
            for marker in catalog.list_case_markers(case_id)
        ],
        'model_snapshots':models,
    }


def analysis_case_offline_manifest(catalog: LocalCatalog, case_id: str) -> Dict[str,Any]:
    """Describe which case evidence is locally available without fetching anything."""
    case=catalog.get_analysis_case(case_id)
    if case is None:raise KeyError(case_id)
    runs=[];missing=[]
    for r in catalog.list_case_runs(case_id):
        assets=[]
        for a in catalog.list_assets(str(r['id'])):
            cached=catalog.asset_cache_valid(str(a['id']))
            assets.append({'id':a['id'],'remote_id':a.get('remote_id'),'filename':a.get('filename',''),'sha256':a.get('sha256',''),'cached':cached})
            if not cached:missing.append(str(a['id']))
        runs.append({'run_id':r['id'],'role':r.get('role','reference'),'case_time_mapping':{'scale':float(r.get('time_scale') or 1.0),'offset_s':float(r.get('time_offset_s') or 0.0),'method':r.get('alignment_method','run_time')},'assets':assets})
    standalone=[]
    for e in catalog.list_case_evidence(case_id):
        if e.get('asset_id'):continue
        local=str(e.get('local_path') or '')
        available=bool(local and Path(local).is_file())
        if available and e.get('sha256'):
            try:
                available=catalog.object_store.verify(str(e['sha256'])) if e.get('storage_mode')=='managed' else True
            except Exception:
                available=False
        standalone.append({'id':e['id'],'filename':e.get('filename',''),'sha256':e.get('sha256',''),'available':available})
    return {'case_id':case_id,'runs':runs,'standalone_evidence':standalone,'missing_cached_asset_ids':missing}
