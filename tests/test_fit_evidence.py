from __future__ import annotations

import numpy as np

from runlab.inverse import FitDistanceWindow, FitEvidencePolicy, FitRun, fit_vehicle
from runlab.models import DEFAULT_PRO_STOCK, Environment, TimingData
from runlab.scenario import create_compare_run


def test_fit_evidence_policy_validates_domain_windows_and_scales():
    policy=FitEvidencePolicy(telemetry_domain='distance',distance_windows=[FitDistanceWindow('330-660',330,660,.5)],telemetry_scales={'speed_mph':2.0})
    assert policy.telemetry_domain=='distance'
    assert policy.distance_windows[0].weight==.5
    try:
        FitDistanceWindow('bad',660,330)
    except ValueError:
        pass
    else:
        raise AssertionError('backward distance window accepted')


def test_distance_domain_fit_can_recover_withheld_power_from_downtrack_speed():
    measured=create_compare_run('Measured',DEFAULT_PRO_STOCK,Environment(),{'power_scale':0.90},name='Measured').run
    measured.timing=TimingData()  # telemetry-only recovery
    policy=FitEvidencePolicy(
        telemetry_domain='distance',
        telemetry_weights={'speed_mph':1.0,'engine_rpm':0.0,'driveshaft_rpm':0.0,'longitudinal_g':0.0},
        distance_windows=[FitDistanceWindow('Downtrack',330,1320,1.0)],
        max_points=50,distance_step_ft=10,
    )
    result=fit_vehicle(DEFAULT_PRO_STOCK,[FitRun('Measured',Environment(),telemetry=measured,evidence=policy)],['power_scale'],max_nfev=35,fit_dt_s=.015,final_dt_s=.005)
    estimate=float(result.estimates.loc[result.estimates['internal_name']=='power_scale','estimate'].iloc[0])
    assert result.success
    assert abs(estimate-.90)<.01
    assert set(result.residuals['source'])=={'strip:speed_mph'}
    assert result.residuals['x'].between(330,1320).all()


def test_timing_field_weight_zero_excludes_that_observation():
    measured=create_compare_run('Measured',DEFAULT_PRO_STOCK,Environment(),{'power_scale':.95},name='Measured').run
    policy=FitEvidencePolicy(timing_weights={'quarter_mile_s':0.0,'quarter_mile_mph':0.0},telemetry_weights={'speed_mph':0.0,'engine_rpm':0.0,'driveshaft_rpm':0.0,'longitudinal_g':0.0})
    result=fit_vehicle(DEFAULT_PRO_STOCK,[FitRun('Measured',Environment(),timing=measured.timing,evidence=policy)],['power_scale'],max_nfev=20,fit_dt_s=.02,final_dt_s=.005)
    sources=set(result.residuals['source'])
    assert 'timing:quarter_mile_s' not in sources
    assert 'timing:quarter_mile_mph' not in sources
    assert 'timing:sixty_ft_s' in sources


def test_fit_evidence_policy_json_roundtrip_preserves_windows_and_weights():
    original=FitEvidencePolicy(
        telemetry_domain="distance",
        timing_weights={"quarter_mile_s":2.0,"quarter_mile_mph":0.0},
        telemetry_weights={"speed_mph":1.5,"engine_rpm":0.25},
        telemetry_scales={"speed_mph":2.5},
        distance_windows=[FitDistanceWindow("330-660",330,660,.75),FitDistanceWindow("660-1320",660,1320,1.25)],
        max_points=77,distance_step_ft=7.5,
    )
    restored=FitEvidencePolicy.from_dict(original.to_dict())
    assert restored.to_dict()==original.to_dict()
