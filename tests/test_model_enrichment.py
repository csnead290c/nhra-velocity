import numpy as np

from runlab.models import DEFAULT_PRO_STOCK, Environment
from runlab.physics import simulate
from runlab.scenario import generated_run_from_result
from runlab.model_enrichment import attach_model_enrichment, model_enrichment_frame, clear_model_enrichment
from runlab.workstation import channel_catalog, resolve_channel


def test_rsa_model_channels_are_namespaced_and_do_not_replace_measured_roles():
    env=Environment()
    result=simulate(DEFAULT_PRO_STOCK,env)
    run=generated_run_from_result("measured fixture",result,DEFAULT_PRO_STOCK,env)
    measured_speed=run.channel_map["speed_mph"]
    original_columns=list(run.data.columns)
    info=attach_model_enrichment(run,result,vehicle=DEFAULT_PRO_STOCK,environment=env,engine="smooth")
    assert run.channel_map["speed_mph"] == measured_speed
    assert list(run.data.columns) == original_columns
    assert "Model.Speed" in run.native_channels
    assert resolve_channel(run,"model_speed_mph") == "Model.Speed"
    assert resolve_channel(run,"residual_speed_mph") == "Residual.Speed"
    assert info["fingerprint_sha256"]
    kinds={x.name:x.source_kind for x in channel_catalog(run)}
    assert kinds["Model.Speed"] == "model"
    assert kinds["Residual.Speed"] == "residual"


def test_rsa_residual_is_small_when_measured_run_came_from_same_model():
    env=Environment()
    result=simulate(DEFAULT_PRO_STOCK,env)
    run=generated_run_from_result("same model",result,DEFAULT_PRO_STOCK,env)
    attach_model_enrichment(run,result,vehicle=DEFAULT_PRO_STOCK,environment=env,engine="smooth")
    residual=np.asarray(run.native_channels["Residual.Speed"].values,float)
    finite=residual[np.isfinite(residual)]
    assert len(finite)>100
    assert float(np.nanmax(np.abs(finite))) < 0.05
    mt=np.asarray(run.native_channels["Model.Speed"].time_s,float)
    assert np.all(np.diff(mt)>0)
    assert mt[0]>=0.0


def test_model_enrichment_frame_and_clear():
    env=Environment(); result=simulate(DEFAULT_PRO_STOCK,env)
    run=generated_run_from_result("frame",result,DEFAULT_PRO_STOCK,env)
    attach_model_enrichment(run,result,vehicle=DEFAULT_PRO_STOCK,environment=env)
    frame=model_enrichment_frame(run)
    assert "run_time_s" in frame.columns and "Model.Speed" in frame.columns and "Residual.Speed" in frame.columns
    assert len(frame)>100
    clear_model_enrichment(run)
    assert "Model.Speed" not in run.native_channels
    assert "model_enrichment" not in run.metadata


def test_persisted_model_enrichment_rebuilds_from_vehicle_model():
    from runlab.model_enrichment import run_rsa_model_enrichment, rebuild_rsa_model_enrichment
    env=Environment(); result=simulate(DEFAULT_PRO_STOCK,env)
    run=generated_run_from_result("persist",result,DEFAULT_PRO_STOCK,env)
    first=run_rsa_model_enrichment(run,DEFAULT_PRO_STOCK,environment=env,engine="smooth",dt_s=.0025,persist=True)
    cfg=dict(run.metadata['derived_analyses']['rsa_model_enrichment'])
    for name in list(run.metadata.get('model_virtual_channels',{}))+list(run.metadata.get('model_residual_channels',{})):
        run.native_channels.pop(name,None);run.units.pop(name,None)
    run.metadata.pop('model_virtual_channels',None);run.metadata.pop('model_residual_channels',None);run.metadata.pop('model_enrichment',None)
    assert run.metadata['derived_analyses']['rsa_model_enrichment']==cfg
    second=rebuild_rsa_model_enrichment(run,DEFAULT_PRO_STOCK)
    assert second and second['fingerprint_sha256']==first['fingerprint_sha256']
    assert 'Model.Speed' in run.native_channels and 'Residual.Speed' in run.native_channels
