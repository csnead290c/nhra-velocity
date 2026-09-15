from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from runlab.catalog import LocalCatalog
from runlab.catalog_bridge import capture_model_snapshot, register_opened_telemetry
from runlab.local_store import LocalObjectStore, sha256_file
from runlab.models import TelemetryRun
from runlab.knowledge import set_vehicle_input
from runlab.sync_contract import analysis_case_bundle, analysis_case_offline_manifest, event_offline_manifest, run_sync_payload
from runlab.time_mapping import TimeAnchor, fit_time_mapping


def _catalog(tmp_path):
    return LocalCatalog(tmp_path/'catalog.sqlite3',object_store=LocalObjectStore(tmp_path/'objects'))


def _run():
    t=np.linspace(0,2,101)
    return TelemetryRun(
        name='Catalog test',
        data=pd.DataFrame({'Time':t,'Engine RPM':4000+2000*t,'Speed':50*t}),
        channel_map={'time_s':'Time','engine_rpm':'Engine RPM','speed_mph':'Speed'},
        units={'Time':'s','Engine RPM':'rpm','Speed':'mph'},
        vendor='Synthetic',
    )


def test_catalog_initializes_run_centric_schema(tmp_path):
    c=_catalog(tmp_path)
    assert c.schema_version==8
    stats=c.stats()
    assert set(stats)>={'events','runs','assets','telemetry_sessions','engineering_values','model_snapshots','analysis_cases','analysis_case_runs','analysis_case_evidence','incident_cases'}
    assert all(v==0 for v in stats.values())


def test_opened_telemetry_registers_once_and_can_be_reopened_by_hash(tmp_path):
    c=_catalog(tmp_path)
    p=tmp_path/'run.csv';_run().data.to_csv(p,index=False)
    run=_run()
    r1,a1,s1=register_opened_telemetry(c,str(p),run)
    r2,a2,s2=register_opened_telemetry(c,str(p),_run())
    assert (r1,a1,s1)==(r2,a2,s2)
    assert c.stats()['runs']==1
    assert c.stats()['assets']==1
    assert c.stats()['telemetry_sessions']==1
    mapping=c.get_time_mapping(a1)
    assert mapping is not None
    assert mapping['scale']==1.0
    assert 'launch' in mapping['method'].lower() or 'identity' in mapping['method'].lower()


def test_managed_evidence_is_content_addressed_and_hash_verified(tmp_path):
    c=_catalog(tmp_path)
    event=c.create_event('Test Event',season=2026,event_code='TEST26')
    run_id=c.create_run(event_id=event,run_key='TEST-Q1')
    p=tmp_path/'evidence.bin';p.write_bytes(b'NHRA evidence\x00'*500)
    asset_id=c.register_asset(run_id,p,asset_type='idr',managed=False)
    managed=Path(c.mark_asset_managed(asset_id))
    digest,size=sha256_file(p)
    assert managed.exists()
    assert managed.name==digest
    assert c.object_store.verify(digest)
    asset=c.get_asset(asset_id)
    assert asset['storage_mode']=='managed'
    assert asset['sha256']==digest
    assert asset['size_bytes']==size


def test_time_mapping_recovers_offset_and_constant_clock_drift():
    anchors=[TimeAnchor(0.0,1.25),TimeAnchor(100.0,101.27),TimeAnchor(200.0,201.29)]
    m=fit_time_mapping(anchors,method='manual anchors')
    assert abs(m.scale-1.0002)<1e-8
    assert abs(m.offset_s-1.25)<1e-8
    assert np.isclose(m.to_run_time(50.0),51.26)
    assert np.isclose(m.to_asset_time(51.26),50.0)
    assert m.uncertainty_s is not None and m.uncertainty_s<1e-9


def test_model_snapshots_create_queryable_historical_engineering_values(tmp_path):
    c=_catalog(tmp_path)
    p=tmp_path/'run.csv';_run().data.to_csv(p,index=False)
    run=_run();run_id,_,_=register_opened_telemetry(c,str(p),run)
    set_vehicle_input(run,'weight_lb',2355.0,'lb','measured')
    set_vehicle_input(run,'dyno_rpm',[7000,8000,9000],'rpm','inferred')
    set_vehicle_input(run,'dyno_hp',[1200,1300,1275],'hp','inferred')
    run.metadata['last_fit_evidence_policy']={'telemetry_domain':'distance','distance_windows':[{'name':'330-1320','start_ft':330.0,'end_ft':1320.0,'weight':1.0}]}
    run.metadata['last_fit_unknowns']=['power_scale','cda']
    run.metadata['last_fit_nuisance_terms']=['run:traction_index']
    sid=capture_model_snapshot(c,run_id,run,name='Q1 reconstructed model')
    snapshots=c.list_model_snapshots(run_id)
    assert snapshots and snapshots[0]['id']==sid
    fit_context=snapshots[0]['inputs']['fit_context']
    assert fit_context['evidence_policy']['telemetry_domain']=='distance'
    assert fit_context['unknowns']==['power_scale','cda']
    assert fit_context['nuisance_terms']==['run:traction_index']
    hist=c.engineering_history('model.peak_hp')
    assert len(hist)==1
    assert hist[0]['value']==1300.0
    assert hist[0]['unit']=='hp'


def test_sync_payload_omits_machine_specific_paths_and_exposes_hash_manifest(tmp_path):
    c=_catalog(tmp_path)
    event=c.create_event('Sync Event',season=2026,event_code='SYNC26')
    run_id=c.create_run(event_id=event,run_key='SYNC-Q1',category='PRO STOCK')
    p=tmp_path/'run.csv';p.write_text('Time,RPM\n0,7000\n1,8000\n')
    c.register_asset(run_id,p,asset_type='telemetry',vendor='Generic')
    payload=run_sync_payload(c,run_id)
    assert payload['contract_version']==4
    assert payload['run']['run_key']=='SYNC-Q1'
    assert len(payload['assets'])==1
    assert 'local_path' not in payload['assets'][0]
    assert len(payload['assets'][0]['sha256'])==64
    manifest=event_offline_manifest(c,event)
    assert manifest['event_id']==event
    assert len(manifest['runs'])==1
    assert len(manifest['missing_cached_asset_ids'])==1


def test_incident_case_and_sync_journal_are_local_first(tmp_path):
    c=_catalog(tmp_path)
    run_id=c.create_run(run_key='INCIDENT-1')
    case_id=c.create_incident_case(run_id,'Wall contact review')
    assert case_id
    jid=c.queue_sync('incident_case',case_id,'upsert',{'status':'open'})
    pending=c.pending_sync()
    assert len(pending)==1 and pending[0]['id']==jid
    assert pending[0]['payload']['status']=='open'


def test_season_engineering_trend_reports_descriptive_change(tmp_path):
    from runlab.trends import compare_seasons, engineering_trend_frame
    c=_catalog(tmp_path)
    driver=c.find_or_create_driver('Driver X')
    e25=c.create_event('Event A',season=2025,event_code='A25')
    e26=c.create_event('Event A',season=2026,event_code='A26')
    for i,value in enumerate((1000.0,1020.0,980.0)):
        rid=c.create_run(event_id=e25,driver_id=driver,run_key=f'25-{i}')
        c.set_engineering_value(rid,'model.peak_hp',value,unit='hp',provenance='inferred')
    for i,value in enumerate((1050.0,1071.0,1029.0)):
        rid=c.create_run(event_id=e26,driver_id=driver,run_key=f'26-{i}')
        c.set_engineering_value(rid,'model.peak_hp',value,unit='hp',provenance='inferred')
    frame=engineering_trend_frame(c,'model.peak_hp',driver_id=driver)
    assert len(frame)==6
    comp=compare_seasons(c,'model.peak_hp',2025,2026,driver_id=driver)
    assert comp.count_a==3 and comp.count_b==3
    assert np.isclose(comp.percent_change_mean,5.0,atol=1e-9)
    assert comp.unit=='hp'


def test_vehicle_incident_pulse_resultant_and_delta_v_are_transparent():
    from runlab.incident_analysis import analyze_vehicle_pulse, G0_MPS2
    t=np.linspace(0,0.1,101)
    ax=np.full_like(t,10.0);ay=np.full_like(t,5.0);az=np.zeros_like(t)
    summary,traces=analyze_vehicle_pulse(t,ax,ay,az)
    assert np.isclose(summary.peak_resultant_g,np.sqrt(125.0))
    assert np.isclose(summary.delta_v_x_mps,10.0*G0_MPS2*0.1,rtol=1e-9)
    assert np.isclose(summary.delta_v_y_mps,5.0*G0_MPS2*0.1,rtol=1e-9)
    assert np.isclose(summary.horizontal_delta_v_angle_deg,np.degrees(np.arctan2(5.0,10.0)))
    assert 'resultant_g' in traces


def test_keep_run_and_event_offline_are_core_catalog_operations(tmp_path):
    c=_catalog(tmp_path)
    event=c.create_event('Offline Event',season=2026,event_code='OFF26')
    r1=c.create_run(event_id=event,run_key='OFF-Q1')
    r2=c.create_run(event_id=event,run_key='OFF-Q2')
    p1=tmp_path/'q1.bin';p1.write_bytes(b'q1 evidence'*100)
    p2=tmp_path/'q2.bin';p2.write_bytes(b'q2 evidence'*100)
    a1=c.register_asset(r1,p1,asset_type='video',managed=False)
    a2=c.register_asset(r2,p2,asset_type='idr',managed=False)
    one=c.keep_run_offline(r1)
    assert one['managed']==1 and one['already_managed']==0 and one['complete']
    assert c.get_asset(a1)['storage_mode']=='managed'
    all_event=c.keep_event_offline(event)
    assert all_event['managed']==1
    assert all_event['already_managed']==1
    assert all_event['complete']
    assert c.get_asset(a2)['storage_mode']=='managed'


def test_relink_unassigned_asset_to_canonical_run_preserves_session_and_time_mapping(tmp_path):
    c=_catalog(tmp_path)
    p=tmp_path/'run.csv';_run().data.to_csv(p,index=False)
    run=_run();old_run,asset,session=register_opened_telemetry(c,str(p),run)
    c.update_time_mapping(asset,scale=1.0001,offset_s=0.25,method='manual anchors',confidence=.9,uncertainty_s=.01,anchors=[{'asset_time_s':0,'run_time_s':.25}])
    event=c.create_event('Canonical Event',season=2026,event_code='CAN26')
    new_run=c.create_run(event_id=event,run_key='CAN-Q1')
    c.relink_asset_to_run(asset,new_run)
    assert c.get_asset(asset)['run_id']==new_run
    mapping=c.get_time_mapping(asset)
    assert mapping['run_id']==new_run
    assert np.isclose(mapping['scale'],1.0001)
    assert np.isclose(mapping['offset_s'],.25)
    with c._connect() as conn:
        row=conn.execute('SELECT run_id,id FROM telemetry_sessions WHERE asset_id=?',(asset,)).fetchone()
    assert row['run_id']==new_run and row['id']==session
    assert c.list_assets(old_run)==[]


def test_official_event_csv_import_is_idempotent_and_authoritative(tmp_path):
    from runlab.official_runs import import_official_run_csv
    c=_catalog(tmp_path)
    p=tmp_path/'event-runs-20260908.csv'
    p.write_text(
        'Time,Driver,Class,Rnd,Ln,RT,60ft,330ft,660ft,660 MPH,1000ft,ET,MPH,CF\n'
        '2026-09-08 16:03,"Gaige Herrera",PSM,T5,,0.086,1.069,2.853,4.365,162.04,5.683,6.812,198.44,1.0848\n'
        '2026-09-08 13:02,"Richard Gadson",PSM,T3,R,0.042,1.069,2.867,4.379,162.39,5.694,6.818,199.46,1.0776\n',
        encoding='utf-8',
    )
    first=import_official_run_csv(c,p,event_name='PSM Indianapolis Test',event_code='20260908',season=2026)
    assert first.runs_created==2 and first.runs_updated==0
    assert c.schema_version==8
    runs=c.list_runs(event_id=first.event_id,limit=10)
    assert len(runs)==2
    gaige=next(x for x in runs if x['driver_name']=='Gaige Herrera')
    assert gaige['category']=='PRO STOCK MOTORCYCLE'
    assert gaige['timing_provenance']=='official'
    assert np.isclose(float(gaige['et_s']),6.812)
    record=c.get_run(gaige['id'])
    assert record['source']['kind']=='nhra_official_run_csv'
    assert len(record['source']['sha256'])==64
    assert np.isclose(record['timing']['reaction_time_s'],.086)
    second=import_official_run_csv(c,p,event_name='PSM Indianapolis Test',event_code='20260908',season=2026)
    assert second.runs_created==0 and second.runs_updated==2
    assert len(c.list_runs(event_id=first.event_id,limit=10))==2


def test_official_import_merges_duplicate_partial_rows_without_erasing_timing(tmp_path):
    from runlab.official_runs import import_official_run_csv
    c=_catalog(tmp_path)
    p=tmp_path/'event-runs-20260902.csv'
    p.write_text(
        'Time,Driver,Class,Rnd,Ln,RT,60ft,330ft,660ft,660 MPH,1000ft,ET,MPH,CF\n'
        '2026-09-07 13:36,Matt Smith,PSM,E2,L,0.049,1.063,2.827,4.332,163.00,5.643,6.762,199.88,1.0691\n'
        '2026-09-07 13:36,Matt Smith,PSM,E2,L,,,,,,,,,1.0691\n',
        encoding='utf-8',
    )
    result=import_official_run_csv(c,p,event_name='U.S. Nationals',event_code='20260902',season=2026)
    assert result.rows_seen==2
    assert result.rows_imported==1
    assert result.duplicate_rows_merged==1
    assert result.runs_created==1
    runs=c.list_runs(event_id=result.event_id,limit=10)
    assert len(runs)==1
    record=c.get_run(runs[0]['id'])
    assert np.isclose(record['timing']['quarter_mile_s'],6.762)
    assert np.isclose(record['timing']['quarter_mile_mph'],199.88)
    assert np.isclose(record['timing']['correction_factor'],1.0691)
    assert record['source']['source_rows']==[2,3]


def test_telemetry_sync_cannot_overwrite_official_timing(tmp_path):
    c=_catalog(tmp_path)
    event=c.create_event('Official Event',season=2026,event_code='AUTH26')
    rid=c.create_run(event_id=event,run_key='official:AUTH26:1',timing={'quarter_mile_s':6.812,'quarter_mile_mph':198.44},timing_provenance='official')
    p=tmp_path/'logger.csv';_run().data.to_csv(p,index=False)
    run=_run();run.timing.quarter_mile_s=7.999;run.metadata['timing_provenance']={'quarter_mile_s':'native logger metadata'}
    from runlab.catalog_bridge import sync_run_state
    sync_run_state(c,rid,run)
    rec=c.get_run(rid)
    assert rec['timing_provenance']=='official'
    assert np.isclose(rec['timing']['quarter_mile_s'],6.812)



def test_catalog_v1_schema_migrates_to_v7_without_losing_run(tmp_path):
    import sqlite3
    db=tmp_path/'legacy.sqlite3'
    conn=sqlite3.connect(db)
    conn.executescript("""
      CREATE TABLE catalog_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      INSERT INTO catalog_meta VALUES('schema_version','1');
      CREATE TABLE events(id TEXT PRIMARY KEY,name TEXT NOT NULL,season INTEGER,event_code TEXT,start_date TEXT,end_date TEXT,track_name TEXT,track_id TEXT,location TEXT,remote_id TEXT,sync_state TEXT NOT NULL DEFAULT 'local',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE TABLE drivers(id TEXT PRIMARY KEY,name TEXT NOT NULL,nhra_member_id TEXT,remote_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE TABLE vehicles(id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT,car_number TEXT,make TEXT,model TEXT,year INTEGER,remote_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE TABLE entries(id TEXT PRIMARY KEY,event_id TEXT,driver_id TEXT,vehicle_id TEXT,category TEXT,car_number TEXT,remote_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE TABLE runs(id TEXT PRIMARY KEY,event_id TEXT,entry_id TEXT,driver_id TEXT,vehicle_id TEXT,run_key TEXT,round TEXT,run_number TEXT,lane TEXT,category TEXT,car_number TEXT,run_datetime TEXT,official_timing_json TEXT NOT NULL DEFAULT '{}',weather_json TEXT NOT NULL DEFAULT '{}',notes TEXT,remote_id TEXT,sync_state TEXT NOT NULL DEFAULT 'local',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      INSERT INTO runs(id,run_key,official_timing_json,weather_json,sync_state,created_at,updated_at) VALUES('run_old','OLD-Q1','{"quarter_mile_s":6.9}','{}','local','2026-01-01','2026-01-01');
    """)
    conn.commit();conn.close()
    c=LocalCatalog(db,object_store=LocalObjectStore(tmp_path/'objects'))
    assert c.schema_version==8
    rec=c.get_run('run_old')
    assert np.isclose(rec['timing']['quarter_mile_s'],6.9)
    assert rec['timing_provenance']=='unknown'


def test_tech_services_snapshot_mirrors_permanent_run_assets_idempotently(tmp_path):
    from runlab.sync_engine import apply_tech_services_snapshot
    import hashlib
    c=_catalog(tmp_path)
    content=b'authoritative racepak bytes'
    digest=hashlib.sha256(content).hexdigest()
    payload={
      'contract_version':4,'cursor':'catalog:100',
      'events':[{'remote_id':'evt-1','event_code':'II1','name':'U.S. Nationals','season':2026,'track_name':'Lucas Oil Indianapolis Raceway Park','revision':'9','runs':[
        {'remote_id':'run-1','revision':'4','driver_name':'Gaige Herrera','driver_remote_id':'drv-1','category':'PSM','car_number':'1','round':'Q1','lane':'Left','run_datetime':'2026-09-04T22:00:00+00:00','timing':{'quarter_mile_s':6.74,'quarter_mile_mph':201.2},'weather':{'temperature_f':81.0},'assets':[
          {'remote_id':'asset-rpk-1','revision':'2','asset_type':'telemetry','filename':'anything_the_team_named_it.rpk','sha256':digest,'size_bytes':len(content),'mime_type':'application/octet-stream','vendor':'RacePak','uploaded_at':'2026-09-04T22:05:00Z'}
        ]}
      ]}]
    }
    a=apply_tech_services_snapshot(c,payload);b=apply_tech_services_snapshot(c,payload)
    assert a.events_created==1 and a.runs_created==1 and a.assets_created==1
    assert b.events_created==0 and b.runs_created==0 and b.runs_updated==1 and b.assets_updated==1
    assert c.get_sync_cursor('nhra-tech-services','catalog')=='catalog:100'
    rows=c.list_runs(event_id=c.find_event_by_code('II1')['id'])
    assert len(rows)==1 and rows[0]['category']=='PRO STOCK MOTORCYCLE'
    run=c.get_run(rows[0]['id']);assets=c.list_assets(run['id'])
    assert run['remote_id']=='run-1' and run['timing_provenance']=='official'
    assert len(assets)==1
    assert assets[0]['remote_id']=='asset-rpk-1'
    assert assets[0]['run_id']==run['id']
    assert assets[0]['source_kind']=='tech_services'
    assert assets[0]['storage_mode']=='remote'


def test_server_asset_cache_is_hash_verified_and_identity_stays_with_run(tmp_path):
    import hashlib
    import pytest
    c=_catalog(tmp_path)
    e=c.create_event('Event',remote_id='evt');r1=c.create_run(event_id=e,run_key='r1',remote_id='run1');r2=c.create_run(event_id=e,run_key='r2',remote_id='run2')
    content=b'permanent server asset';digest=hashlib.sha256(content).hexdigest()
    aid,created=c.upsert_server_asset(r1,remote_id='asset-1',filename='weirdname.bin',asset_type='telemetry',sha256=digest,size_bytes=len(content))
    assert created
    path=Path(c.cache_server_asset_bytes(aid,content))
    assert path.is_file() and c.asset_cache_valid(aid)
    asset=c.get_asset(aid)
    assert asset['run_id']==r1 and asset['storage_mode']=='managed'
    with pytest.raises(ValueError,match='cannot be re-parented'):
        c.relink_asset_to_run(aid,r2)
    with pytest.raises(IOError,match='SHA-256 mismatch'):
        c.cache_server_asset_bytes(aid,b'wrong bytes')


def test_server_asset_revision_invalidates_stale_cache(tmp_path):
    import hashlib
    c=_catalog(tmp_path);r=c.create_run(run_key='server-run',remote_id='run-1')
    one=b'one';two=b'two'
    aid,_=c.upsert_server_asset(r,remote_id='asset-1',filename='log.rpk',asset_type='telemetry',sha256=hashlib.sha256(one).hexdigest(),size_bytes=len(one),revision='1')
    c.cache_server_asset_bytes(aid,one);assert c.asset_cache_valid(aid)
    aid2,created=c.upsert_server_asset(r,remote_id='asset-1',filename='log.rpk',asset_type='telemetry',sha256=hashlib.sha256(two).hexdigest(),size_bytes=len(two),revision='2')
    assert aid2==aid and not created
    asset=c.get_asset(aid);assert asset['storage_mode']=='remote' and not asset['local_path']
    assert not c.asset_cache_valid(aid)


def test_unbound_transport_fails_closed_without_guessing_routes():
    import pytest
    from runlab.transport import UnboundTechServicesTransport
    t=UnboundTechServicesTransport()
    assert not t.capabilities.catalog_pull and not t.capabilities.asset_fetch
    with pytest.raises(RuntimeError,match='not bound'):t.pull_catalog_snapshot()
    with pytest.raises(RuntimeError,match='not bound'):t.fetch_asset('asset-1')


def test_v4_catalog_migrates_to_v7_without_losing_runs(tmp_path):
    import sqlite3
    path=tmp_path/'old.sqlite3';c=LocalCatalog(path)
    e=c.create_event('Legacy',event_code='OLD');r=c.create_run(event_id=e,run_key='old-run')
    with sqlite3.connect(path) as db:db.execute("UPDATE catalog_meta SET value='4' WHERE key='schema_version'")
    reopened=LocalCatalog(path)
    assert reopened.schema_version==8
    assert reopened.get_run(r)['run_key']=='old-run'
    with reopened._connect() as db:
        cols={row[1] for row in db.execute('PRAGMA table_info(assets)').fetchall()}
    assert {'remote_id','revision','source_kind','uploaded_at'}<=cols


def test_tech_services_client_sync_and_cache_run(tmp_path):
    import hashlib
    from runlab.tech_services_client import sync_catalog, cache_run
    from runlab.transport import ProviderCapabilities

    content=b'client fetched telemetry'
    digest=hashlib.sha256(content).hexdigest()

    class FakeTransport:
        capabilities=ProviderCapabilities(provider='nhra-tech-services',catalog_pull=True,asset_fetch=True,incremental_cursor=True)
        def __init__(self): self.seen_cursor=None;self.fetches=[]
        def pull_catalog_snapshot(self,*,cursor=''):
            self.seen_cursor=cursor
            return {
                'contract_version':4,'cursor':'next-1','events':[{
                    'remote_id':'evt','event_code':'EVT','name':'Event','season':2026,'runs':[{
                        'remote_id':'run','driver_name':'Driver','category':'PS','round':'Q1','assets':[{
                            'remote_id':'asset','filename':'teamfile.rpk','asset_type':'telemetry','sha256':digest,'size_bytes':len(content)
                        }]
                    }]
                }]
            }
        def fetch_asset(self,remote_asset_id):
            self.fetches.append(remote_asset_id);return content
        def push_analysis_bundle(self,payload): return {'ok':True}

    c=_catalog(tmp_path);t=FakeTransport()
    result=sync_catalog(c,t)
    assert result.runs_created==1 and result.assets_created==1
    assert t.seen_cursor==''
    run=c.list_runs(event_id=c.find_event_by_code('EVT')['id'])[0]
    cached=cache_run(c,t,run['id'])
    assert cached.cached==1 and cached.complete
    asset=c.list_assets(run['id'])[0]
    assert c.asset_cache_valid(asset['id'])
    assert t.fetches==['asset']
    # A second cache request must not re-download the same immutable object.
    cached2=cache_run(c,t,run['id'])
    assert cached2.cached==0 and cached2.already_cached==1
    assert t.fetches==['asset']



def test_analysis_case_can_span_runs_and_switch_primary(tmp_path):
    c=_catalog(tmp_path)
    event=c.create_event('Case Event',season=2026,event_code='CASE26')
    r1=c.create_run(event_id=event,run_key='CASE-Q1',category='PRO STOCK')
    r2=c.create_run(event_id=event,run_key='CASE-Q2',category='PRO STOCK')
    r3=c.create_run(event_id=event,run_key='CASE-Q3',category='PRO STOCK')
    case_id=c.create_analysis_case('Multi-run reconstruction',case_type='performance',primary_run_id=r1)
    c.add_run_to_case(case_id,r2,role='baseline',sort_order=1)
    c.add_run_to_case(case_id,r3,role='comparison',sort_order=2)
    case=c.get_analysis_case(case_id)
    assert case is not None and case['primary_run_id']==r1 and case['run_count']==3
    rows=c.list_case_runs(case_id)
    assert [(r['run_key'],r['role']) for r in rows]==[('CASE-Q1','primary'),('CASE-Q2','baseline'),('CASE-Q3','comparison')]
    c.set_case_primary_run(case_id,r3)
    case=c.get_analysis_case(case_id)
    assert case['primary_run_id']==r3
    roles={r['run_key']:r['role'] for r in c.list_case_runs(case_id)}
    assert roles['CASE-Q3']=='primary' and roles['CASE-Q1']=='reference'


def test_incident_case_wrapper_uses_general_analysis_case(tmp_path):
    c=_catalog(tmp_path)
    run_id=c.create_run(run_key='INCIDENT-2')
    case_id=c.create_incident_case(run_id,'Wall contact review')
    case=c.get_analysis_case(case_id)
    assert case is not None
    assert case['case_type']=='incident'
    assert case['primary_run_id']==run_id
    assert c.list_case_runs(case_id)[0]['role']=='primary'
    assert c.stats()['incident_cases']==0  # legacy table is retained only for migration


def test_case_evidence_can_link_run_asset_or_store_standalone_evidence(tmp_path):
    c=_catalog(tmp_path)
    run_id=c.create_run(run_key='CASE-EVIDENCE')
    case_id=c.create_analysis_case('Evidence review',case_type='incident',primary_run_id=run_id)
    raw=tmp_path/'logger.bin';raw.write_bytes(b'logger bytes')
    asset_id=c.register_asset(run_id,raw,asset_type='telemetry',managed=False)
    ev1=c.link_asset_to_case(case_id,asset_id,evidence_type='telemetry',label='Primary logger')
    ev1b=c.link_asset_to_case(case_id,asset_id,evidence_type='telemetry')
    assert ev1==ev1b
    photo=tmp_path/'inspection.jpg';photo.write_bytes(b'not really jpeg but immutable evidence')
    ev2=c.register_case_evidence(case_id,photo,evidence_type='photo',label='Chassis inspection')
    evidence=c.list_case_evidence(case_id)
    assert {e['id'] for e in evidence}=={ev1,ev2}
    linked=next(e for e in evidence if e['id']==ev1)
    standalone=next(e for e in evidence if e['id']==ev2)
    assert linked['asset_id']==asset_id and linked['linked_run_id']==run_id and linked['sha256']==c.get_asset(asset_id)['sha256']
    assert standalone['asset_id'] is None and standalone['storage_mode']=='managed'
    assert c.object_store.verify(standalone['sha256'])


def test_case_scoped_model_snapshot_does_not_require_single_run_owner(tmp_path):
    c=_catalog(tmp_path)
    r1=c.create_run(run_key='MODEL-Q1');r2=c.create_run(run_key='MODEL-Q2')
    case_id=c.create_analysis_case('Shared vehicle model',case_type='performance',primary_run_id=r1)
    c.add_run_to_case(case_id,r2,role='comparison')
    sid=c.create_model_snapshot(analysis_case_id=case_id,name='Joint fit',model_type='multi_run_inverse',inputs={'runs':[r1,r2]},outputs={'peak_hp':1350},quality={'rmse_et_s':0.004})
    rows=c.list_model_snapshots(analysis_case_id=case_id)
    assert len(rows)==1 and rows[0]['id']==sid
    assert rows[0]['run_id'] is None and rows[0]['analysis_case_id']==case_id
    assert rows[0]['inputs']['runs']==[r1,r2]
    assert rows[0]['quality']['rmse_et_s']==0.004


def test_analysis_case_bundle_is_path_safe_and_preserves_roles(tmp_path):
    c=_catalog(tmp_path)
    event=c.create_event('Bundle Event',event_code='BUNDLE26',remote_id='event-remote')
    r1=c.create_run(event_id=event,run_key='B-Q1',remote_id='run-remote-1')
    r2=c.create_run(event_id=event,run_key='B-Q2',remote_id='run-remote-2')
    case_id=c.create_analysis_case('Bundle Case',case_type='incident',primary_run_id=r1)
    c.add_run_to_case(case_id,r2,role='comparison')
    raw=tmp_path/'video.mp4';raw.write_bytes(b'video bytes')
    asset_id=c.register_asset(r1,raw,asset_type='video',managed=True)
    c.link_asset_to_case(case_id,asset_id,evidence_type='video')
    local=tmp_path/'notes.txt';local.write_text('inspection notes')
    c.register_case_evidence(case_id,local,evidence_type='document')
    c.create_model_snapshot(analysis_case_id=case_id,name='Incident reconstruction',outputs={'delta_v_mps':12.3})
    bundle=analysis_case_bundle(c,case_id)
    assert bundle['analysis_bundle_version']==2
    assert bundle['case']['primary_run_remote_id']=='run-remote-1'
    assert [r['role'] for r in bundle['runs']]==['primary','comparison']
    assert len(bundle['evidence'])==2 and len(bundle['model_snapshots'])==1
    text=str(bundle)
    assert str(tmp_path) not in text
    manifest=analysis_case_offline_manifest(c,case_id)
    assert manifest['case_id']==case_id


def test_v017_incident_and_run_model_migrate_into_v7_analysis_case(tmp_path):
    import sqlite3
    db=tmp_path/'v017.sqlite3'
    conn=sqlite3.connect(db)
    conn.executescript("""
      CREATE TABLE catalog_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      INSERT INTO catalog_meta VALUES('schema_version','5');
      CREATE TABLE events(id TEXT PRIMARY KEY,name TEXT NOT NULL,season INTEGER,event_code TEXT,start_date TEXT,end_date TEXT,track_name TEXT,track_id TEXT,location TEXT,remote_id TEXT,sync_state TEXT NOT NULL DEFAULT 'local',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE TABLE drivers(id TEXT PRIMARY KEY,name TEXT NOT NULL,nhra_member_id TEXT,remote_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE TABLE vehicles(id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT,car_number TEXT,make TEXT,model TEXT,year INTEGER,remote_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE TABLE entries(id TEXT PRIMARY KEY,event_id TEXT,driver_id TEXT,vehicle_id TEXT,category TEXT,car_number TEXT,remote_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE TABLE runs(id TEXT PRIMARY KEY,event_id TEXT,entry_id TEXT,driver_id TEXT,vehicle_id TEXT,run_key TEXT,round TEXT,run_number TEXT,lane TEXT,category TEXT,car_number TEXT,run_datetime TEXT,official_timing_json TEXT NOT NULL DEFAULT '{}',weather_json TEXT NOT NULL DEFAULT '{}',timing_provenance TEXT NOT NULL DEFAULT 'unknown',weather_provenance TEXT NOT NULL DEFAULT 'unknown',official_source_json TEXT NOT NULL DEFAULT '{}',notes TEXT,remote_id TEXT,sync_state TEXT NOT NULL DEFAULT 'local',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      INSERT INTO runs(id,run_key,official_timing_json,weather_json,sync_state,created_at,updated_at) VALUES('run17','IND-Q4','{}','{}','local','2026-09-01','2026-09-01');
      CREATE TABLE model_snapshots(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,name TEXT NOT NULL,model_type TEXT NOT NULL,model_version TEXT,inputs_json TEXT NOT NULL DEFAULT '{}',outputs_json TEXT NOT NULL DEFAULT '{}',quality_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL);
      INSERT INTO model_snapshots VALUES('mdl17','run17','Old run model','vehicle_performance','0.17','{}','{"peak_hp":1200}','{}','2026-09-01');
      CREATE TABLE incident_cases(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,title TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',summary TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      INSERT INTO incident_cases VALUES('inc17','run17','Old incident','open','legacy case','2026-09-01','2026-09-02');
    """)
    conn.commit();conn.close()
    c=LocalCatalog(db,object_store=LocalObjectStore(tmp_path/'objects'))
    assert c.schema_version==8
    migrated=c.get_analysis_case('inc17')
    assert migrated is not None and migrated['case_type']=='incident' and migrated['primary_run_id']=='run17'
    assert c.list_case_runs('inc17')[0]['role']=='primary'
    models=c.list_model_snapshots('run17')
    assert models[0]['id']=='mdl17' and models[0]['analysis_case_id'] is None and models[0]['outputs']['peak_hp']==1200


def test_linked_asset_automatically_adds_owning_run_as_case_reference(tmp_path):
    c=_catalog(tmp_path)
    primary=c.create_run(run_key='AUTO-PRIMARY')
    source_run=c.create_run(run_key='AUTO-SOURCE')
    case_id=c.create_analysis_case('Auto context',case_type='incident',primary_run_id=primary)
    raw=tmp_path/'source.rpk';raw.write_bytes(b'source telemetry')
    asset_id=c.register_asset(source_run,raw,asset_type='telemetry',managed=True)
    c.link_asset_to_case(case_id,asset_id,evidence_type='telemetry')
    roles={r['run_key']:r['role'] for r in c.list_case_runs(case_id)}
    assert roles=={'AUTO-PRIMARY':'primary','AUTO-SOURCE':'reference'}
    evidence=c.list_case_evidence(case_id)
    assert evidence[0]['linked_run_id']==source_run


def test_case_cache_fetches_each_server_asset_once_across_member_runs(tmp_path):
    import hashlib
    from runlab.tech_services_client import cache_case
    from runlab.transport import ProviderCapabilities

    payloads={'asset-a':b'alpha telemetry','asset-b':b'beta video'}
    c=_catalog(tmp_path)
    r1=c.create_run(run_key='CACHE-A',remote_id='remote-run-a')
    r2=c.create_run(run_key='CACHE-B',remote_id='remote-run-b')
    for run_id,asset_remote,name in [(r1,'asset-a','a.rpk'),(r2,'asset-b','b.mp4')]:
        content=payloads[asset_remote]
        c.upsert_server_asset(run_id,remote_id=asset_remote,filename=name,asset_type='telemetry' if name.endswith('.rpk') else 'video',sha256=hashlib.sha256(content).hexdigest(),size_bytes=len(content))
    case_id=c.create_analysis_case('Offline case',case_type='performance',primary_run_id=r1)
    c.add_run_to_case(case_id,r2,role='comparison')

    class FakeTransport:
        capabilities=ProviderCapabilities(provider='nhra-tech-services',catalog_pull=False,asset_fetch=True)
        def __init__(self):self.fetches=[]
        def fetch_asset(self,remote_asset_id):
            self.fetches.append(remote_asset_id);return payloads[remote_asset_id]

    t=FakeTransport()
    first=cache_case(c,t,case_id)
    assert first.complete and first.cached==2 and first.already_cached==0
    assert sorted(t.fetches)==['asset-a','asset-b']
    second=cache_case(c,t,case_id)
    assert second.complete and second.cached==0 and second.already_cached==2
    assert sorted(t.fetches)==['asset-a','asset-b']
    manifest=analysis_case_offline_manifest(c,case_id)
    assert manifest['missing_cached_asset_ids']==[]


def test_case_offline_manifest_detects_missing_standalone_evidence(tmp_path):
    c=_catalog(tmp_path)
    case_id=c.create_analysis_case('Standalone evidence',case_type='engineering')
    evidence=tmp_path/'notes.txt';evidence.write_text('evidence')
    ev_id=c.register_case_evidence(case_id,evidence,evidence_type='document',managed=True)
    before=analysis_case_offline_manifest(c,case_id)
    assert before['standalone_evidence'][0]['available'] is True
    row=next(e for e in c.list_case_evidence(case_id) if e['id']==ev_id)
    Path(row['local_path']).unlink()
    after=analysis_case_offline_manifest(c,case_id)
    assert after['standalone_evidence'][0]['available'] is False


def test_case_run_alignment_and_asset_mapping_compose_without_rewriting_raw_time(tmp_path):
    from runlab.case_timeline import CaseTimeAnchor, fit_case_run_alignment, store_case_run_alignment, composed_mapping_for_asset
    c=_catalog(tmp_path)
    run_id=c.create_run(run_key='SYNC-Q1')
    case_id=c.create_analysis_case('Synchronized incident',case_type='incident',primary_run_id=run_id)
    raw=tmp_path/'camera.mp4';raw.write_bytes(b'video clock bytes')
    asset_id=c.register_asset(run_id,raw,asset_type='video',managed=True)
    # Camera clock: run_time = 1.002*asset_time - 2.0 seconds.
    c.update_time_mapping(asset_id,scale=1.002,offset_s=-2.0,method='flash + impact',confidence=.95,uncertainty_s=.010,anchors=[{'asset_time_s':2.0,'run_time_s':.004},{'asset_time_s':12.0,'run_time_s':10.024}])
    # Case clock aligns this Run so run 3.0 s appears at case 10.0 s.
    alignment=fit_case_run_alignment([CaseTimeAnchor(3.0,10.0),CaseTimeAnchor(13.0,20.0)],method='incident anchors',confidence=.98)
    store_case_run_alignment(c,case_id,run_id,alignment)
    assert np.isclose(c.map_run_time_to_case(case_id,run_id,3.0),10.0)
    assert np.isclose(c.map_case_time_to_run(case_id,run_id,20.0),13.0)
    direct=composed_mapping_for_asset(c,case_id,asset_id)
    for asset_t in (2.0,5.0,12.0):
        via_catalog=c.map_asset_time_to_case(case_id,asset_id,asset_t)
        assert np.isclose(via_catalog,direct.to_case_time(asset_t))
        assert np.isclose(c.map_case_time_to_asset(case_id,asset_id,via_catalog),asset_t)
    assert direct.confidence==.95
    assert direct.uncertainty_s is not None


def test_case_markers_follow_refined_asset_sync_dynamically(tmp_path):
    c=_catalog(tmp_path)
    run_id=c.create_run(run_key='MARKER-RUN')
    case_id=c.create_analysis_case('Marker case',case_type='incident',primary_run_id=run_id)
    raw=tmp_path/'idr.bin';raw.write_bytes(b'idr')
    asset_id=c.register_asset(run_id,raw,asset_type='idr',managed=True)
    c.update_time_mapping(asset_id,scale=1.0,offset_s=-5.0,method='first sync')
    marker=c.create_case_marker(case_id,label='Impact',start_s=8.0,kind='impact',time_domain='asset',asset_id=asset_id,payload={'source':'IDR trigger'})
    rows=c.list_case_markers(case_id)
    assert rows[0]['id']==marker and np.isclose(rows[0]['case_start_s'],3.0)
    # Refine only the Asset→Run sync. Marker source time remains immutable, but
    # its resolved case position moves with the corrected mapping.
    c.update_time_mapping(asset_id,scale=1.0,offset_s=-4.75,method='frame review')
    rows=c.list_case_markers(case_id)
    assert np.isclose(rows[0]['source_start_s'],8.0)
    assert np.isclose(rows[0]['case_start_s'],3.25)
    assert rows[0]['payload']['source']=='IDR trigger'


def test_case_marker_supports_run_and_case_time_domains(tmp_path):
    c=_catalog(tmp_path)
    r=c.create_run(run_key='DOMAIN-RUN')
    case_id=c.create_analysis_case('Domains',primary_run_id=r)
    c.update_case_run_alignment(case_id,r,offset_s=2.0,method='launch aligned')
    c.create_case_marker(case_id,label='Run event',start_s=1.5,time_domain='run',run_id=r)
    c.create_case_marker(case_id,label='Case note',start_s=-1.0,time_domain='case')
    rows=c.list_case_markers(case_id)
    got={x['label']:x['case_start_s'] for x in rows}
    assert got['Run event']==3.5 and got['Case note']==-1.0


def test_v6_case_membership_migrates_to_v7_timeline_defaults(tmp_path):
    import sqlite3
    path=tmp_path/'v6.sqlite3'
    c=LocalCatalog(path,object_store=LocalObjectStore(tmp_path/'objects'))
    r=c.create_run(run_key='V6-RUN');case_id=c.create_analysis_case('V6 case',primary_run_id=r)
    # Rebuild only the membership table in its v0.18/v6 shape to exercise the
    # real ALTER-column migration path when the catalog is reopened.
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=OFF')
        db.executescript('''
          ALTER TABLE analysis_case_runs RENAME TO analysis_case_runs_v7;
          CREATE TABLE analysis_case_runs(case_id TEXT NOT NULL,run_id TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'reference',sort_order INTEGER NOT NULL DEFAULT 0,notes TEXT,added_at TEXT NOT NULL,PRIMARY KEY(case_id,run_id));
          INSERT INTO analysis_case_runs(case_id,run_id,role,sort_order,notes,added_at) SELECT case_id,run_id,role,sort_order,notes,added_at FROM analysis_case_runs_v7;
          DROP TABLE analysis_case_runs_v7;
          UPDATE catalog_meta SET value='6' WHERE key='schema_version';
        ''')
        db.commit()
    reopened=LocalCatalog(path,object_store=LocalObjectStore(tmp_path/'objects'))
    assert reopened.schema_version==8
    align=reopened.get_case_run_alignment(case_id,r)
    assert align is not None and align['time_scale']==1.0 and align['time_offset_s']==0.0 and align['alignment_method']=='run_time'
    assert align['anchors']==[]


def test_analysis_case_bundle_v2_contains_alignment_and_resolved_markers(tmp_path):
    c=_catalog(tmp_path)
    r=c.create_run(run_key='BUNDLE-TIME',remote_id='remote-time-run')
    case_id=c.create_analysis_case('Timeline bundle',case_type='incident',primary_run_id=r)
    c.update_case_run_alignment(case_id,r,scale=1.0,offset_s=4.0,method='impact aligned',confidence=.9,anchors=[{'run_time_s':1.0,'case_time_s':5.0}])
    c.create_case_marker(case_id,label='Impact',start_s=2.0,time_domain='run',run_id=r,kind='impact')
    bundle=analysis_case_bundle(c,case_id)
    assert bundle['analysis_bundle_version']==2
    mapping=bundle['runs'][0]['case_time_mapping']
    assert mapping['offset_s']==4.0 and mapping['method']=='impact aligned' and mapping['anchors'][0]['case_time_s']==5.0
    assert bundle['timeline_markers'][0]['label']=='Impact'
    assert bundle['timeline_markers'][0]['case_start_s']==6.0


def test_case_run_alignment_preserves_physical_seconds_instead_of_time_warping():
    from runlab.case_timeline import CaseTimeAnchor, fit_case_run_alignment
    m=fit_case_run_alignment([CaseTimeAnchor(0.0,0.0),CaseTimeAnchor(10.0,10.10)],method='two event check')
    assert m.scale==1.0
    assert np.isclose(m.offset_s,0.05)
    assert np.isclose(m.uncertainty_s,0.05)
    assert np.isclose(m.to_case_time(5.0),5.05)


def test_case_playback_frame_maps_case_cursor_into_video_clock(tmp_path):
    from runlab.case_playback import case_playback_frame
    c=_catalog(tmp_path)
    r=c.create_run(run_key='PLAY-RUN')
    case_id=c.create_analysis_case('Playback',case_type='incident',primary_run_id=r)
    c.update_case_run_alignment(case_id,r,offset_s=10.0,method='impact aligned')
    raw=tmp_path/'camera.mp4';raw.write_bytes(b'video')
    aid=c.register_asset(r,raw,asset_type='video',managed=True,metadata={'media':{'duration_s':20.0,'fps':1000.0}})
    c.update_time_mapping(aid,scale=1.002,offset_s=-2.0,method='flash sync',uncertainty_s=.004)
    frame=case_playback_frame(c,case_id,15.0)
    assert len(frame.sources)==1
    src=frame.sources[0]
    assert np.isclose(src.run_time_s,5.0)
    assert np.isclose(src.asset_time_s,(5.0+2.0)/1.002)
    assert src.source_kind=='video' and src.in_range is True
    assert src.frame_index==round(src.asset_time_s*1000.0)
    assert src.mapping_method=='flash sync' and np.isclose(src.mapping_uncertainty_s,.004)


def test_case_playback_extent_uses_prelaunch_media_and_markers(tmp_path):
    from runlab.case_playback import case_time_extent
    c=_catalog(tmp_path)
    r=c.create_run(run_key='EXTENT-RUN')
    case_id=c.create_analysis_case('Extent',primary_run_id=r)
    raw=tmp_path/'vid.mp4';raw.write_bytes(b'v')
    aid=c.register_asset(r,raw,asset_type='video',managed=True,metadata={'duration_s':30.0})
    # run = asset - 8, so a 30 s source spans case -8 .. 22.
    c.update_time_mapping(aid,scale=1.0,offset_s=-8.0,method='launch flash')
    c.create_case_marker(case_id,label='late note',start_s=25.0,time_domain='case')
    lo,hi=case_time_extent(c,case_id)
    assert np.isclose(lo,-10.0)
    assert np.isclose(hi,28.0)


def test_case_playback_controller_steps_and_navigates_markers(tmp_path):
    from runlab.case_playback import CasePlaybackController
    c=_catalog(tmp_path)
    r=c.create_run(run_key='CONTROL-RUN')
    case_id=c.create_analysis_case('Control',primary_run_id=r)
    c.create_case_marker(case_id,label='Launch',start_s=0.0,kind='launch',time_domain='case')
    c.create_case_marker(case_id,label='Impact',start_s=3.5,kind='impact',time_domain='case')
    ctl=CasePlaybackController(c,case_id,case_time_s=1.0)
    assert np.isclose(ctl.step(.25).case_time_s,1.25)
    assert np.isclose(ctl.jump_marker(1).case_time_s,3.5)
    assert np.isclose(ctl.jump_marker(-1).case_time_s,0.0)


def test_case_playback_active_interval_marker(tmp_path):
    from runlab.case_playback import case_playback_frame
    c=_catalog(tmp_path)
    r=c.create_run(run_key='INTERVAL-RUN')
    case_id=c.create_analysis_case('Interval',primary_run_id=r)
    c.create_case_marker(case_id,label='Loss of control',start_s=2.0,end_s=2.8,kind='failure',time_domain='case')
    frame=case_playback_frame(c,case_id,2.4)
    assert [m['label'] for m in frame.active_markers]==['Loss of control']


def test_synchronized_numeric_source_readout_uses_nearest_asset_sample():
    from runlab.case_playback import sample_telemetry_at_asset_time
    from runlab.models import TelemetryRun
    df=pd.DataFrame({'Time':[0.0,0.5,1.0,1.5],'Accel':[0.0,1.0,4.0,2.0],'Trigger':[0,0,1,1]})
    run=TelemetryRun(name='IDR export',vendor='Generic',data=df,channel_map={'time_s':'Time'},units={'Time':'s','Accel':'g','Trigger':''})
    rows=sample_telemetry_at_asset_time(run,1.1,channels=['Accel','Trigger'])
    got={r['channel']:r for r in rows}
    assert got['Accel']['value']==4.0 and got['Accel']['sample_time_s']==1.0
    assert got['Trigger']['value']==1.0


def test_case_playback_remote_asset_is_not_reported_viewable_until_cache_exists(tmp_path):
    from runlab.case_playback import case_playback_frame
    c=_catalog(tmp_path)
    r=c.create_run(run_key='REMOTE-MEDIA',remote_id='remote-run')
    case_id=c.create_analysis_case('Remote media',case_type='incident',primary_run_id=r)
    aid,_=c.upsert_server_asset(r,remote_id='video-remote',filename='incident.mp4',asset_type='video',sha256='a'*64,size_bytes=123,metadata={'duration_s':12.0})
    c.update_time_mapping(aid,scale=1.0,offset_s=0.0,method='manual')
    src=case_playback_frame(c,case_id,1.0).sources[0]
    assert src.mapped is True and src.cached is False and src.local_path==''
