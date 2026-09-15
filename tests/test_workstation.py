from __future__ import annotations

import numpy as np

from runlab.knowledge import get_parameter, set_vehicle_input, vehicle_from_run, vehicle_inputs
from runlab.models import DEFAULT_PRO_STOCK, Environment, TelemetryRun
from runlab.scenario import create_compare_run


def _blank_run():
    import pandas as pd
    return TelemetryRun(
        name='test',
        data=pd.DataFrame({'Time':[0.0,0.1], 'Speed':[0.0,10.0]}),
        channel_map={'time_s':'Time','speed_mph':'Speed'},
        units={'Time':'s','Speed':'mph'},
    )


def test_vehicle_input_provenance_is_persistent_and_separate_from_raw_data():
    run=_blank_run()
    set_vehicle_input(run,'weight_lb',2350.0,'lb','measured',confidence=0.99,method='scales')
    assert vehicle_inputs(run)['weight_lb']==2350.0
    rec=get_parameter(run,'vehicle.weight_lb')
    assert rec is not None
    assert rec.provenance=='measured'
    assert rec.unit=='lb'
    assert rec.method=='scales'
    assert rec.confidence==0.99
    assert 'weight_lb' not in run.data.columns


def test_vehicle_model_can_be_built_from_run_knowledge():
    run=_blank_run()
    v=DEFAULT_PRO_STOCK
    vals=v.to_dict()
    dyn=vals.pop('dyno')
    for key,value in vals.items():
        set_vehicle_input(run,key,value,'','user')
    set_vehicle_input(run,'dyno_rpm',dyn['rpm'],'rpm','measured')
    set_vehicle_input(run,'dyno_hp',dyn['hp'],'hp','measured')
    out,missing=vehicle_from_run(run,require_explicit=False)
    assert 'dyno_curve' not in missing
    assert np.isclose(out.weight_lb,v.weight_lb)
    assert out.gear_ratios==v.gear_ratios
    assert out.dyno.hp==v.dyno.hp


def test_generated_compare_run_is_first_class_telemetry_and_power_stays_physical():
    env=Environment()
    scenario=create_compare_run('Measured Run',DEFAULT_PRO_STOCK,env,{'power_scale':0.90,'final_drive_ratio':4.70},name='Compare - taller gear')
    run=scenario.run
    assert run.metadata['generated_scenario'] is True
    assert run.channel_map['power_hp']=='Engine Power'
    assert run.channel_map['speed_mph']=='Speed'
    assert run.units['Engine Power']=='hp'
    assert len(run.data)>100
    assert float(run.data['Engine Power'].max()) < 2500.0
    assert float(run.data['Engine Power'].max()) > 500.0
    assert run.timing.quarter_mile_s is not None
    assert run.timing.quarter_mile_mph is not None


def test_generated_compare_power_channel_matches_scenario_power_scale():
    env=Environment()
    base=create_compare_run('Measured Run',DEFAULT_PRO_STOCK,env,{'power_scale':1.0},name='Base')
    lower=create_compare_run('Measured Run',DEFAULT_PRO_STOCK,env,{'power_scale':0.90},name='Minus 10 pct')
    p0=float(base.run.data['Engine Power'].max())
    p1=float(lower.run.data['Engine Power'].max())
    assert np.isclose(p1/p0,0.90,rtol=2e-3,atol=2e-3)
    assert lower.run.metadata['scenario_power_scale']==0.90

def test_math_channel_engineering_functions_are_safe_and_time_aware():
    import pandas as pd
    from runlab.math_channels import add_math_channel
    t=np.linspace(0,2,201)
    run=TelemetryRun(
        name='math', data=pd.DataFrame({'Time':t,'Speed':10*t}),
        channel_map={'time_s':'Time'}, units={'Time':'s','Speed':'mph'}
    )
    add_math_channel(run,'AccelLike','derivative(`Speed`)','ratio')
    assert np.allclose(run.data['AccelLike'][5:-5],10.0,rtol=1e-3,atol=1e-3)
    add_math_channel(run,'Smoothed','smooth(`Speed`, 0.2)','mph')
    assert len(run.data['Smoothed'])==len(t)
    add_math_channel(run,'DistanceLike','integral(`Speed`)','ratio')
    assert run.data['DistanceLike'].iloc[-1] > run.data['DistanceLike'].iloc[50]


def test_math_channel_rejects_unapproved_function_calls():
    import pandas as pd
    from runlab.math_channels import add_math_channel
    run=TelemetryRun(name='math',data=pd.DataFrame({'Time':[0.,1.],'A':[1.,2.]}),channel_map={'time_s':'Time'},units={'Time':'s','A':'ratio'})
    try:
        add_math_channel(run,'Bad','sin(`A`)','ratio')
    except ValueError as exc:
        assert 'not allowed' in str(exc)
    else:
        raise AssertionError('unapproved function was accepted')


def test_headless_waveform_uses_sample_index_when_time_is_not_mapped():
    import pandas as pd
    from runlab.display_data import channel_xy
    from runlab.plotability import choose_default_plot_channels
    run=TelemetryRun(
        name='no time',
        data=pd.DataFrame({'RPMish':[1000.,1200.,1400.,1600.], 'Pressure':[5.,6.,7.,8.]}),
        channel_map={},
        units={'RPMish':'rpm','Pressure':'psi'},
    )
    channels=choose_default_plot_channels(run)
    assert channels
    x,y=channel_xy(run,channels[0],'Time from Launch')
    assert np.array_equal(x,np.arange(len(y),dtype=float))
    assert np.isfinite(y).sum()==4


def test_default_waveform_contract_returns_plot_points_for_legacy_racepak_fixture(tmp_path):
    import struct
    from runlab.display_data import validate_default_waveform
    from runlab.importers import load_telemetry
    from runlab.plotability import choose_default_plot_channels

    def lp(text: str) -> bytes:
        raw=text.encode('latin1'); return bytes([len(raw)])+raw
    def channel(st: str, name: str, desc: str, timer: str='Timer_20sps') -> bytes:
        return b'\x43\x09\x02\x00'+lp(st)+lp(name)+lp(desc)+lp('0.0')+lp(timer)+b'\x00'*12
    def buffer(values) -> bytes:
        values=list(map(float,values)); n=len(values)
        return bytes([12])+b'ScaledBuffer'+struct.pack('<4I',n,0,n,1)+struct.pack('<'+'f'*n,*values)

    raw=b'\\\x07'+b'\x00'*254
    raw+=channel('RPM','ENGINE RPM','ScaledBuffer: (0=>0,1=>1) [(0,10000),%-5.0lf,RPM]')
    raw+=channel('RPM','DRIVE SHAFT','ScaledBuffer: (0=>0,1=>1) [(0,10000),%-5.0lf,RPM]')
    raw+=b'\x00'*64
    raw+=buffer([0,2000,5000,7000,8000])
    raw+=buffer([0,100,300,600,1000])
    path=tmp_path/'PSDemo.rpk.bin'
    path.write_bytes(raw)
    run=load_telemetry(path)
    channels=choose_default_plot_channels(run)
    results=validate_default_waveform(run,channels)
    assert channels
    assert all(count >= 2 for count in results.values())


def test_bundled_native_demo_logs_decode_and_produce_default_waveforms():
    from pathlib import Path
    from runlab.display_data import validate_default_waveform
    from runlab.importers import load_telemetry
    from runlab.plotability import assess_plotability
    root=Path(__file__).resolve().parents[1]
    expected={
        'native_demo_racepak.rpk':'RacePak',
        'native_demo_motec.ld':'MoTeC',
        'native_demo_maxxecu.MaxxECU-log':'MaxxECU',
    }
    for filename,vendor in expected.items():
        run=load_telemetry(root/'examples'/filename)
        report=assess_plotability(run)
        assert run.vendor==vendor
        assert report.plotable
        assert len(report.default_channels)>=3
        points=validate_default_waveform(run,report.default_channels)
        assert points and all(v>=2 for v in points.values())


def test_native_fueltech_binary_is_rejected_explicitly(tmp_path):
    from runlab.importers import load_telemetry
    p=tmp_path/'example.ftlog'
    p.write_bytes(b'\x00FTLOG'+bytes(range(64))*4)
    try:
        load_telemetry(p)
    except ValueError as exc:
        text=str(exc)
        assert 'FuelTech' in text
        assert 'not qualified' in text
        assert 'silently mis-decoded' in text
    else:
        raise AssertionError('native FuelTech binary should fail closed until a validated decoder exists')


def test_folder_candidate_filter_is_permissive_but_not_every_bin(tmp_path):
    from runlab.importers import telemetry_file_candidate
    assert telemetry_file_candidate(tmp_path/'run.ld')
    assert telemetry_file_candidate(tmp_path/'run.rpk')
    assert telemetry_file_candidate(tmp_path/'run.MaxxECU-log')
    assert telemetry_file_candidate(tmp_path/'run.ftlog')
    assert telemetry_file_candidate(tmp_path/'download.rpk.bin')
    assert not telemetry_file_candidate(tmp_path/'firmware.bin')
    assert not telemetry_file_candidate(tmp_path/'notes.docx')


def test_bundled_data_pipeline_selftest_passes():
    from pathlib import Path
    from runlab.selftest import run_data_pipeline_selftest, format_selftest
    root=Path(__file__).resolve().parents[1]/'examples'
    rows=run_data_pipeline_selftest(root)
    assert len(rows)==3
    assert all(r['pass'] for r in rows)
    text=format_selftest(rows)
    assert '3/3 native demo pipelines passed' in text


def test_diagnostic_log_path_can_be_redirected(tmp_path, monkeypatch):
    from runlab.diagnostics import app_data_root, configure_logging
    monkeypatch.setenv('NHRA_TECH_DATA_HOME',str(tmp_path/'state'))
    assert app_data_root()==(tmp_path/'state').resolve()
    path=configure_logging()
    assert path.parent.exists()
    assert path.name=='nhra-tech-data.log'


def test_prepare_plot_series_repairs_clock_reset_and_keeps_longest_ordered_segment():
    from runlab.display_data import prepare_plot_series
    x=np.array([0.,.1,.2,.3, 0.,.1,.2])
    y=np.arange(len(x),dtype=float)
    p=prepare_plot_series(x,y,max_points=None)
    assert p.monotonic_repair
    assert np.all(np.diff(p.x)>0)
    assert p.output_points==4
    assert np.array_equal(p.y,np.array([0.,1.,2.,3.]))


def test_prepare_plot_series_peak_preserving_decimation_keeps_narrow_spike():
    from runlab.display_data import prepare_plot_series
    x=np.linspace(0,10,100001); y=np.zeros_like(x); y[54321]=1234.5
    p=prepare_plot_series(x,y,max_points=2000)
    assert p.decimated
    assert p.output_points<=2000
    assert np.isclose(np.max(p.y),1234.5)


def test_reference_delta_series_aligns_and_converts_units():
    import pandas as pd
    from runlab.compare import reference_delta_series, delta_statistics
    t=np.linspace(0,2,201)
    main=TelemetryRun(name='main',data=pd.DataFrame({'Time':t,'Speed':100+10*t}),channel_map={'time_s':'Time','speed_mph':'Speed'},units={'Time':'s','Speed':'mph'},metadata={'original_channel_map':{'speed_mph':'Speed'}})
    ref=TelemetryRun(name='ref',data=pd.DataFrame({'Time':t,'SpeedK':(105+10*t)*1.609344}),channel_map={'time_s':'Time','speed_mph':'SpeedK'},units={'Time':'s','SpeedK':'kmh'},metadata={'original_channel_map':{'speed_mph':'SpeedK'}})
    d=reference_delta_series(main,ref,'Speed',x_mode='Logger Time')
    stats=delta_statistics(d)
    assert d.unit=='mph'
    assert len(d.x)>100
    assert np.allclose(d.delta,5.0,atol=1e-6)
    assert np.isclose(stats['mean'],5.0,atol=1e-6)


def test_run_annotations_bookmarks_regions_persist_and_filter_by_axis():
    from runlab.annotations import add_bookmark, add_region, annotations, annotations_for_mode, delete_annotation
    run=_blank_run()
    b=add_bookmark(run,1.25,'Shift 1-2',x_mode='Time from Launch',note='manual review')
    r=add_region(run,0.8,1.1,'Launch window',x_mode='Time from Launch')
    add_bookmark(run,330.0,'330 marker',x_mode='Distance from Launch')
    rows=annotations(run)
    assert len(rows)==3
    assert {x.label for x in annotations_for_mode(run,'Time from Launch')}=={'Shift 1-2','Launch window'}
    assert r.x1==0.8 and r.x2==1.1
    assert delete_annotation(run,b.id)
    assert len(annotations(run))==2


def test_default_waveform_does_not_use_time_channel_as_y_trace():
    import pandas as pd
    from runlab.plotability import choose_default_plot_channels
    run=TelemetryRun(name='x',data=pd.DataFrame({'Time':[0.,.1,.2],'RPM':[1000,2000,3000],'P':[1,2,3]}),channel_map={'time_s':'Time','engine_rpm':'RPM'},units={'Time':'s','RPM':'rpm','P':'psi'},metadata={'original_channel_map':{'time_s':'Time','engine_rpm':'RPM'}})
    chosen=choose_default_plot_channels(run,limit=5)
    assert 'Time' not in chosen
    assert 'RPM' in chosen


def test_region_statistics_matches_known_ab_window():
    import pandas as pd
    from runlab.statistics import region_statistics
    t=np.linspace(0,1,11); y=2*t+1
    run=TelemetryRun(name='stats',data=pd.DataFrame({'Time':t,'Y':y}),channel_map={'time_s':'Time'},units={'Time':'s','Y':'psi'})
    rows=region_statistics(run,['Y'],0.2,0.6,x_mode='Logger Time')
    assert len(rows)==1
    r=rows[0]
    assert r['count']==5
    assert np.isclose(r['start'],1.4)
    assert np.isclose(r['end'],2.2)
    assert np.isclose(r['delta'],0.8)
    assert np.isclose(r['mean'],1.8)



def test_project_json_atomic_roundtrip_and_recovery_freshness(tmp_path):
    import os, time
    from runlab.project_io import atomic_write_json, read_project_json, is_recovery_newer
    project=tmp_path/'analysis.nhratech'
    recovery=tmp_path/'autosave-recovery.nhratech'
    atomic_write_json(project, {'version':3,'sessions':[{'path':'a.rpk'}]})
    assert read_project_json(project)['sessions'][0]['path']=='a.rpk'
    time.sleep(0.01)
    atomic_write_json(recovery, {'version':3,'source_project_path':str(project)})
    assert is_recovery_newer(recovery,project)
    # No temporary file should remain beside the committed project.
    assert not any(x.suffix=='.tmp' for x in tmp_path.iterdir())


def test_project_equivalence_ignores_save_bookkeeping():
    from runlab.project_io import projects_equivalent
    a={'version':3,'sessions':[{'path':'x.rpk'}]}
    b={**a,'saved_at_utc':'2026-09-13T00:00:00Z','source_project_path':'/tmp/a.nhratech'}
    assert projects_equivalent(a,b)
    assert not projects_equivalent(a,{**b,'sessions':[{'path':'y.rpk'}]})


def test_signal_analysis_lowpass_and_fft_recover_known_frequency():
    from runlab.signal_analysis import filter_signal, fft_spectrum
    t=np.arange(0,4,0.001)
    y=3.0*np.sin(2*np.pi*12*t)+0.8*np.sin(2*np.pi*120*t)
    low=filter_signal(t,y,kind='lowpass',cutoff_hz=30,order=4)
    assert len(low.values)==len(t)
    # High-frequency content should be strongly attenuated.
    spec=fft_spectrum(low.time_s,low.values,max_frequency_hz=200)
    f=float(spec.frequency_hz[np.argmax(spec.amplitude[1:])+1])
    assert abs(f-12.0) < 0.5
    a12=float(spec.amplitude[np.argmin(np.abs(spec.frequency_hz-12.0))])
    a120=float(spec.amplitude[np.argmin(np.abs(spec.frequency_hz-120.0))])
    assert a12 > 2.5
    assert a120 < 0.15


def test_signal_analysis_resamples_irregular_timebase_and_bandpass():
    from runlab.signal_analysis import uniform_time_signal, filter_signal
    rng=np.random.default_rng(4)
    dt=0.01+rng.normal(0,0.0003,800)
    t=np.cumsum(dt); t-=t[0]
    y=np.sin(2*np.pi*7*t)+0.2*np.sin(2*np.pi*40*t)
    u=uniform_time_signal(t,y)
    assert u.resampled
    assert 90 < u.sample_rate_hz < 110
    result=filter_signal(t,y,kind='bandpass',cutoff_hz=(4,12),order=3)
    assert result.resampled
    assert np.isfinite(result.values).all()


def test_math_channels_support_engineering_filters_and_rolling_rms():
    import pandas as pd
    from runlab.math_channels import add_math_channel
    t=np.arange(0,3,0.002)
    low=np.sin(2*np.pi*5*t); high=0.4*np.sin(2*np.pi*100*t)
    run=TelemetryRun(name='filters',data=pd.DataFrame({'Time':t,'Signal':low+high}),channel_map={'time_s':'Time'},units={'Time':'s','Signal':'v'})
    add_math_channel(run,'Low','lowpass(`Signal`, 20, 4)','v')
    add_math_channel(run,'Band','bandpass(`Signal`, 3, 10)','v')
    add_math_channel(run,'RMS','rollingrms(`Low`, 0.2)','v')
    assert np.std(run.data['Low']-low) < 0.08
    assert np.nanmax(run.data['RMS']) > 0.5
    assert np.isfinite(run.data['Band']).all()


def test_multi_run_envelope_aligns_canonical_channels_and_converts_units():
    import pandas as pd
    from runlab.envelope import multi_run_envelope
    t=np.linspace(0,2,401)
    main=TelemetryRun(name='main',data=pd.DataFrame({'Time':t,'Speed':100+20*t}),channel_map={'time_s':'Time','speed_mph':'Speed'},units={'Time':'s','Speed':'mph'},metadata={'original_channel_map':{'speed_mph':'Speed'}})
    ref=TelemetryRun(name='ref',data=pd.DataFrame({'Time':t,'Vel':(102+20*t)*1.609344}),channel_map={'time_s':'Time','speed_mph':'Vel'},units={'Time':'s','Vel':'kmh'},metadata={'original_channel_map':{'speed_mph':'Vel'}})
    out=multi_run_envelope([(main,0.0),(ref,0.0)],'Speed',x_mode='Logger Time',grid_points=301)
    assert out.run_count==2
    assert out.unit=='mph'
    assert np.allclose(out.maximum-out.minimum,2.0,atol=1e-6)
    assert np.allclose(out.mean,(out.minimum+out.maximum)/2,atol=1e-6)


def test_global_channel_preferences_persist_by_canonical_role(tmp_path, monkeypatch):
    import pandas as pd
    from runlab.preferences import set_channel_preference, get_channel_preference, preference_key
    monkeypatch.setenv('NHRA_TECH_DATA_HOME',str(tmp_path/'state'))
    run=TelemetryRun(name='prefs',data=pd.DataFrame({'Time':[0.,1.],'RPM':[1000.,2000.]}),channel_map={'time_s':'Time','engine_rpm':'RPM'},units={'Time':'s','RPM':'rpm'},metadata={'original_channel_map':{'engine_rpm':'RPM'}})
    assert preference_key(run,'RPM')=='canonical:engine_rpm'
    set_channel_preference(run,'RPM',{'color':'#abcdef','width':2.2,'display_unit':'rpm'})
    rec=get_channel_preference(run,'RPM')
    assert rec['color']=='#abcdef'
    assert rec['width']==2.2


def test_math_channel_unit_inference_rejects_clear_dimension_mismatch():
    import pandas as pd
    from runlab.math_channels import add_math_channel, infer_expression_dimension
    run=TelemetryRun(name='units',data=pd.DataFrame({'A':[1000.,2000.],'B':[500.,1000.]}),channel_map={},units={'A':'rpm','B':'rpm'})
    assert infer_expression_dimension(run,'`A` / `B`')=='ratio'
    assert infer_expression_dimension(run,'`A` + `B`')=='angular_speed'
    try:add_math_channel(run,'Bad','`A` + `B`','psi')
    except ValueError as exc:assert 'dimensionally incompatible' in str(exc)
    else:raise AssertionError('clear calculated-channel unit mismatch was accepted')


def test_sensor_health_flags_flatline_missing_and_clock_reset():
    import pandas as pd
    from runlab.sensor_health import sensor_health
    t=np.r_[np.arange(0,1,.01),0.5+np.arange(0,.2,.01)]
    flat=np.ones(len(t))*42
    noisy=np.sin(np.linspace(0,10,len(t))); noisy[10:20]=np.nan
    run=TelemetryRun(name='health',data=pd.DataFrame({'Time':t,'Flat':flat,'Noisy':noisy}),channel_map={'time_s':'Time'},units={'Time':'s','Flat':'psi','Noisy':'v'})
    table=sensor_health(run).set_index('channel')
    assert table.loc['Flat','status'] in {'WARN','ERROR'}
    assert 'flat' in table.loc['Flat','note']
    assert table.loc['Noisy','status'] in {'WARN','ERROR'}
    assert table.loc['Time','clock_violations']>0


def test_comparison_summary_combines_timeslip_and_aligned_telemetry():
    import pandas as pd
    from runlab.comparison_report import comparison_summary
    from runlab.models import TimingData
    t=np.linspace(0,7,701)
    main=TelemetryRun(name='main',data=pd.DataFrame({'Time':t,'RPM':7000+100*t,'Speed':30*t}),channel_map={'time_s':'Time','engine_rpm':'RPM','speed_mph':'Speed'},units={'Time':'s','RPM':'rpm','Speed':'mph'},metadata={'original_channel_map':{'engine_rpm':'RPM','speed_mph':'Speed'}},timing=TimingData(sixty_ft_s=1.0,three_thirty_ft_s=2.8,eighth_mile_s=4.3,quarter_mile_s=6.8,quarter_mile_mph=200))
    ref=TelemetryRun(name='ref',data=pd.DataFrame({'Time':t,'RPM2':7050+100*t,'SpeedK':(31*t)*1.609344}),channel_map={'time_s':'Time','engine_rpm':'RPM2','speed_mph':'SpeedK'},units={'Time':'s','RPM2':'rpm','SpeedK':'kmh'},metadata={'original_channel_map':{'engine_rpm':'RPM2','speed_mph':'SpeedK'}},timing=TimingData(sixty_ft_s=.99,three_thirty_ft_s=2.77,eighth_mile_s=4.26,quarter_mile_s=6.75,quarter_mile_mph=202))
    table=comparison_summary(main,ref)
    assert not table.empty
    q=table[(table.section=='Timing')&(table.metric=='1320 ft ET')].iloc[0]
    assert np.isclose(q.delta,-0.05)
    s=table[(table.section=='Telemetry')&(table.location=='60 ft')&(table.metric=='Vehicle Speed')].iloc[0]
    assert s.unit=='mph'
    assert np.isfinite(s.main) and np.isfinite(s.reference)
    assert 0.5 < (s.reference-s.main) < 2.0


def test_reconstruction_derivation_does_not_replace_existing_measured_power_mapping(monkeypatch):
    import pandas as pd
    import runlab.derived as derived
    from runlab.reconstruction import ReconstructionResult
    run=_blank_run()
    run.channel_map['power_hp']='Measured Power'; run.data['Measured Power']=[300.,400.]; run.units['Measured Power']='hp'
    fake_samples=pd.DataFrame({
        'time_s':[0.,.1],
        'apparent_engine_hp':[310.,420.],
        'apparent_engine_torque_lbft':[500.,510.],
        'accel_g_speed':[1.,1.2],
    })
    fake=ReconstructionResult(fake_samples,pd.DataFrame(),pd.DataFrame(),{'ok':True})
    monkeypatch.setattr(derived,'reconstruct_delivered_power',lambda *a,**k: fake)
    original_power=run.channel_map.get('power_hp')
    result=derived.attach_delivered_power_reconstruction(run,DEFAULT_PRO_STOCK,Environment(),persist=True)
    assert 'Reconstructed Engine HP' in run.native_channels
    assert run.channel_map.get('power_hp')==original_power
    assert run.metadata['derived_analyses']['delivered_power']['enabled'] is True
    assert result.diagnostics['ok'] is True



def test_batch_qualification_reports_bundled_native_formats():
    from pathlib import Path
    from runlab.qualification import qualify_corpus
    root=Path(__file__).resolve().parents[1]
    rows=qualify_corpus([root/'examples'/'native_demo_racepak.rpk',root/'examples'/'native_demo_motec.ld',root/'examples'/'native_demo_maxxecu.MaxxECU-log'])
    assert len(rows)==3
    assert {r.vendor for r in rows}=={'RacePak','MoTeC','MaxxECU'}
    assert all(r.status=='pass' and r.plotable and r.sha256 for r in rows)


def test_channel_catalog_alias_search_and_roles():
    import pandas as pd
    from runlab.workstation import channel_catalog, set_channel_alias, resolve_channel
    run=TelemetryRun(name='catalog',data=pd.DataFrame({'Time':[0.,1.],'RPM':[7000.,8000.],'Boost':[20.,25.]}),channel_map={'time_s':'Time','engine_rpm':'RPM','boost_psi':'Boost'},units={'Time':'s','RPM':'rpm','Boost':'psi'},metadata={'original_channel_map':{'engine_rpm':'RPM','boost_psi':'Boost'}})
    set_channel_alias(run,'RPM','Motor Speed')
    rows=channel_catalog(run,'motor')
    assert len(rows)==1 and rows[0].name=='RPM' and rows[0].canonical_role=='engine_rpm'
    assert resolve_channel(run,'Motor Speed')=='RPM'
    assert resolve_channel(run,'engine_rpm')=='RPM'


def test_safe_data_gate_supports_boolean_comparisons_between_and_finite():
    import pandas as pd
    from runlab.workstation import evaluate_gate, GateDefinition, save_gate, gates
    run=TelemetryRun(name='gate',data=pd.DataFrame({'RPM':[5000.,7000.,8000.,9000.],'TPS':[100.,100.,50.,100.],'P':[1.,np.nan,3.,4.]}),channel_map={},units={})
    mask=evaluate_gate(run,'(`RPM` >= 7000) and (`TPS` > 90) and isfinite(`P`)')
    assert mask.tolist()==[False,False,False,True]
    mask2=evaluate_gate(run,'between(`RPM`, 6000, 8500) or (`TPS` < 60)')
    assert mask2.tolist()==[False,True,True,False]
    save_gate(run,GateDefinition('WOT','`TPS` > 90'))
    assert gates(run)[0].name=='WOT'


def test_official_segments_and_metric_report_cover_drag_incrementals():
    import pandas as pd
    from runlab.models import TimingData
    from runlab.workstation import official_drag_segments, MetricDefinition, metric_report
    t=np.linspace(0,7,701); rpm=7000+100*t
    run=TelemetryRun(name='metrics',data=pd.DataFrame({'Time':t,'RPM':rpm}),channel_map={'time_s':'Time','engine_rpm':'RPM'},units={'Time':'s','RPM':'rpm'},metadata={'original_channel_map':{'engine_rpm':'RPM'}},timing=TimingData(sixty_ft_s=1.0,three_thirty_ft_s=2.8,eighth_mile_s=4.3,thousand_ft_s=5.6,quarter_mile_s=6.8))
    segs=official_drag_segments(run,'Time from Launch')
    assert segs[0].name=='Launch → 1320 ft'
    report=metric_report([('Q1',run)],[MetricDefinition('Avg RPM','RPM','mean'),MetricDefinition('RPM Delta','engine_rpm','delta')],segs[:2])
    assert len(report)==4
    assert np.isfinite(report['value']).all()


def test_normalized_run_axis_uses_official_et_without_mutating_time():
    import pandas as pd
    from runlab.display_data import channel_xy
    from runlab.models import TimingData
    t=np.linspace(0,8,81)
    run=TelemetryRun(name='norm',data=pd.DataFrame({'Time':t,'Y':t}),channel_map={'time_s':'Time'},units={'Time':'s'},timing=TimingData(quarter_mile_s=6.8))
    x,y=channel_xy(run,'Y','Normalized Run %')
    assert np.isclose(np.interp(6.8,t,x),100.0,atol=1e-9)
    assert np.allclose(y,t)


def test_psd_and_spectrogram_identify_tire_shake_frequency():
    from runlab.signal_analysis import power_spectral_density, spectrogram
    t=np.arange(0,3,0.001)
    y=2*np.sin(2*np.pi*38*t)+0.2*np.sin(2*np.pi*7*t)
    psd=power_spectral_density(t,y,max_frequency_hz=100,segment_points=1024)
    peak=float(psd.frequency_hz[np.argmax(psd.density[1:])+1])
    assert abs(peak-38)<1.5
    spec=spectrogram(t,y,max_frequency_hz=100,segment_points=512)
    assert spec.density.shape==(len(spec.frequency_hz),len(spec.time_s))
    assert np.nanmax(spec.density)>0


def test_binned_load_map_mean_and_count():
    from runlab.heatmap import binned_map
    x=np.repeat([1000.,2000.],100); y=np.tile(np.repeat([0.2,0.8],50),2); z=x*0.01+y
    result=binned_map(x,y,z,bins=(2,2),statistic='mean')
    assert result.values.shape==(2,2)
    assert int(np.nansum(result.counts))==200
    occupancy=binned_map(x,y,bins=(2,2),statistic='count')
    assert int(np.nansum(occupancy.values))==200


def test_drag_metric_report_uses_each_runs_own_official_segment_times():
    import pandas as pd
    from runlab.models import TimingData
    from runlab.workstation import MetricDefinition, drag_metric_report
    t=np.linspace(0,7,701)
    r1=TelemetryRun(name='r1',data=pd.DataFrame({'Time':t,'Y':t}),channel_map={'time_s':'Time'},units={'Y':'psi'},timing=TimingData(sixty_ft_s=1.0,three_thirty_ft_s=2.8,quarter_mile_s=6.8))
    r2=TelemetryRun(name='r2',data=pd.DataFrame({'Time':t,'Y':t}),channel_map={'time_s':'Time'},units={'Y':'psi'},timing=TimingData(sixty_ft_s=.9,three_thirty_ft_s=2.6,quarter_mile_s=6.5))
    out=drag_metric_report([('A',r1),('B',r2)],[MetricDefinition('Delta Y','Y','delta')],x_mode='Time from Launch')
    a=out[(out['run']=='A')&(out['segment']=='60 ft → 330 ft')].iloc[0]
    b=out[(out['run']=='B')&(out['segment']=='60 ft → 330 ft')].iloc[0]
    assert np.isclose(a.value,1.8,atol=.02)
    assert np.isclose(b.value,1.7,atol=.02)
