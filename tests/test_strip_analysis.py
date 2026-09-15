from __future__ import annotations
import numpy as np
import pandas as pd
from runlab.models import DEFAULT_PRO_STOCK, Environment, TelemetryRun
from runlab.legacy_reference import simulate_legacy_reference
from runlab.scenario import create_compare_run
from runlab.strip_analysis import analyze_strip, timing_residual_table, time_to_distance


def _measured(power_scale=1.0):
    return create_compare_run('Measured',DEFAULT_PRO_STOCK,Environment(),{'power_scale':power_scale},name='Measured').run


def test_strip_analysis_same_model_is_close():
    run=_measured(1.0); model=simulate_legacy_reference(DEFAULT_PRO_STOCK,Environment())
    out=analyze_strip(run,model,distance_step_ft=10)
    valid=np.isfinite(out.residuals['speed_mph'])
    assert valid.sum()>50
    downtrack=valid & (out.distance_ft >= 100.0)
    assert np.nanmax(np.abs(out.residuals['speed_mph'][downtrack])) < 2.0
    assert np.nanmax(np.abs(out.timing_residuals['et_residual_s'].to_numpy(float))) < 0.03


def test_timing_residual_sign_is_modeled_minus_observed():
    run=_measured(0.90); model=simulate_legacy_reference(DEFAULT_PRO_STOCK,Environment())
    finish=timing_residual_table(run,model).query("point == '1320 ft'").iloc[0]
    assert finish['et_residual_s'] < 0
    assert finish['mph_residual'] > 0


def test_rule_event_projects_to_downtrack_distance():
    run=_measured(1.0); d=time_to_distance(run,1.0)
    assert np.isfinite(d) and d>0
    events=pd.DataFrame([{'rule':'Test Event','event_type':'warning','severity':'warning','start_s':1.0,'end_s':1.0,'duration_s':0,'trigger':'rising'}])
    out=analyze_strip(run,None,rule_events=events)
    ev=[x for x in out.events if x.label=='Test Event'][0]
    assert np.isclose(ev.distance_ft,d)


def test_strip_without_speed_fails_softly():
    run=TelemetryRun('x',pd.DataFrame({'Time':[0.,1.,2.],'RPM':[1000,2000,3000]}),{'time_s':'Time','engine_rpm':'RPM'},units={'Time':'s','RPM':'rpm'})
    out=analyze_strip(run,None)
    assert not np.isfinite(out.observed['engine_rpm']).any()
    assert out.events[0].label=='Launch'

def test_section_residuals_break_model_error_into_beam_intervals():
    from runlab.strip_analysis import section_residual_table
    run=_measured(.90); model=simulate_legacy_reference(DEFAULT_PRO_STOCK,Environment())
    frame=section_residual_table(run,model)
    assert 'Launch → 1320 ft' in set(frame['section'])
    assert '60 ft → 330 ft' in set(frame['section'])
    total=frame[frame['section']=='Launch → 1320 ft'].iloc[0]
    assert total['residual_s'] < 0
