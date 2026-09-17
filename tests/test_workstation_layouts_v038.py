from __future__ import annotations

import pandas as pd

from runlab.layout_profiles import channel_reference, resolve_channel_reference, capture_display_specs, resolve_display_specs
from runlab.models import TelemetryRun


def _run(engine_name='ENGINE RPM', ds_name='DS RPM'):
    return TelemetryRun(
        name='test',
        data=pd.DataFrame({'Time':[0.,1.,2.], engine_name:[1000.,2000.,3000.], ds_name:[10.,20.,30.], 'Oil P':[40.,50.,60.]}),
        channel_map={'time_s':'Time','engine_rpm':engine_name,'driveshaft_rpm':ds_name},
        units={'Time':'s',engine_name:'rpm',ds_name:'rpm','Oil P':'psi'},
        metadata={'original_channel_map':{'time_s':'Time','engine_rpm':engine_name,'driveshaft_rpm':ds_name}},
    )


def test_common_channel_reference_is_portable_but_raw_source_is_exact():
    a=_run('ENGINE RPM','DS RPM')
    b=_run('RPM2','SHAFT')
    common=channel_reference(a,'ENGINE RPM')
    raw=channel_reference(a,'Oil P')
    assert common['kind']=='common' and common['key']=='engine_rpm'
    assert resolve_channel_reference(b,common)=='RPM2'
    assert raw['kind']=='source'
    assert resolve_channel_reference(b,raw)=='Oil P'
    b.data=b.data.drop(columns=['Oil P'])
    assert resolve_channel_reference(b,raw)==''


def test_waveform_template_resolves_common_roles_and_preserves_styles():
    a=_run('ENGINE RPM','DS RPM')
    b=_run('RPM2','SHAFT')
    specs=[{'type':'waveform','title':'Waveform','object_name':'wf','config':{
        'channels':['ENGINE RPM','DS RPM','Oil P'],
        'channel_styles':{
            'ENGINE RPM':{'color':'#fff','axis_group':'RPM'},
            'DS RPM':{'axis_group':'RPM'},
            'Oil P':{'axis_group':'Pressure'},
        },
        'layout_mode':'Grouped Channels',
    }}]
    portable=capture_display_specs(a,specs)
    resolved,missing=resolve_display_specs(b,portable)
    cfg=resolved[0]['config']
    assert cfg['channels']==['RPM2','SHAFT','Oil P']
    assert cfg['channel_styles']['RPM2']['axis_group']=='RPM'
    assert cfg['channel_styles']['SHAFT']['axis_group']=='RPM'
    assert not missing


def test_template_missing_raw_channel_is_reported_not_guessed():
    a=_run()
    specs=[{'type':'histogram','config':{'channel':'Oil P','bins':20}}]
    portable=capture_display_specs(a,specs)
    b=_run(); b.data=b.data.drop(columns=['Oil P'])
    resolved,missing=resolve_display_specs(b,portable)
    assert resolved[0]['config']['channel']==''
    assert missing==['Oil P']


def test_worksheet_template_scope_is_contextual_and_vehicle_is_more_specific(tmp_path):
    from runlab.preferences import save_worksheet_template, worksheet_templates, delete_worksheet_template
    p=tmp_path/'prefs.json'
    a=_run(); a.metadata.update({'catalog_category':'PRO STOCK MOTORCYCLE','catalog_driver_id':'d1','catalog_vehicle_id':'bike-a','catalog_vehicle_name':'Bike A'})
    b=_run(); b.metadata.update({'catalog_category':'PRO STOCK MOTORCYCLE','catalog_driver_id':'d2','catalog_vehicle_id':'bike-b','catalog_vehicle_name':'Bike B'})
    global_id=save_worksheet_template('Global',{'display_specs':[]},run=a,scope='global',path=p)
    cat_id=save_worksheet_template('PSM',{'display_specs':[]},run=a,scope='category',path=p)
    veh_id=save_worksheet_template('Bike A',{'display_specs':[]},run=a,scope='vehicle_category',path=p)
    rows=worksheet_templates(run=a,compatible_only=True,path=p)
    assert [r['id'] for r in rows]==[veh_id,cat_id,global_id]
    rows_b=worksheet_templates(run=b,compatible_only=True,path=p)
    assert veh_id not in [r['id'] for r in rows_b]
    assert cat_id in [r['id'] for r in rows_b]
    assert delete_worksheet_template(veh_id,path=p)
