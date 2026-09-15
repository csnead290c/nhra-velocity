from __future__ import annotations
import copy
from runlab.fit_study import FitStudyDefinition, run_joint_fit_study
from runlab.fit_uncertainty import leave_one_run_out_influence
from runlab.inverse import FitDistanceWindow, FitEvidencePolicy, FitRun
from runlab.models import DEFAULT_PRO_STOCK, Environment, TimingData
from runlab.physics import SolverOptions, simulate
from runlab.scenario import generated_run_from_result


def _run(name,power):
    env=Environment();res=simulate(DEFAULT_PRO_STOCK,env,power_scale=power,options=SolverOptions(dt_s=.005))
    r=generated_run_from_result(name,res,copy.deepcopy(DEFAULT_PRO_STOCK),env,power_scale=power);r.timing=TimingData();return r


def test_leave_one_run_out_exposes_conflicting_run_influence():
    evidence=FitEvidencePolicy(telemetry_domain='distance',telemetry_weights={'speed_mph':1,'engine_rpm':0,'driveshaft_rpm':0,'longitudinal_g':0},distance_windows=[FitDistanceWindow('330-1320',330,1320)],max_points=45,distance_step_ft=20)
    runs=[
        FitRun('Low power',Environment(),telemetry=_run('Low power',.80),evidence=evidence,nuisance_terms=[],source_run_id='low',role='baseline'),
        FitRun('High power',Environment(),telemetry=_run('High power',1.10),evidence=evidence,nuisance_terms=[],source_run_id='high',role='comparison'),
    ]
    definition=FitStudyDefinition(name='Influence',shared_unknowns=['power_scale'],max_nfev=35,fit_dt_s=.005,final_dt_s=.005)
    fit,_=run_joint_fit_study(DEFAULT_PRO_STOCK,runs,definition)
    influence=leave_one_run_out_influence(DEFAULT_PRO_STOCK,runs,definition,fit,max_nfev=30)
    assert len(influence['runs'])==2
    by={r['omitted_run']:r for r in influence['runs']}
    low_shift=by['Low power']['parameter_shifts'][0]
    high_shift=by['High power']['parameter_shifts'][0]
    assert low_shift['without_run_estimate']>low_shift['baseline_estimate']
    assert high_shift['without_run_estimate']<high_shift['baseline_estimate']
    assert abs(low_shift['delta'])>.015 and abs(high_shift['delta'])>.015
    assert by['Low power']['status'] in {'moderate_influence','high_influence'}
    assert by['High power']['status'] in {'moderate_influence','high_influence'}


def test_leave_one_run_out_requires_multiple_runs():
    evidence=FitEvidencePolicy(telemetry_domain='distance',telemetry_weights={'speed_mph':1},distance_windows=[FitDistanceWindow('660-1320',660,1320)],max_points=20,distance_step_ft=30)
    runs=[FitRun('One',Environment(),telemetry=_run('One',.9),evidence=evidence,nuisance_terms=[])]
    definition=FitStudyDefinition(name='One',shared_unknowns=['power_scale'],max_nfev=20,fit_dt_s=.005,final_dt_s=.005)
    fit,_=run_joint_fit_study(DEFAULT_PRO_STOCK,runs,definition)
    import pytest
    with pytest.raises(ValueError): leave_one_run_out_influence(DEFAULT_PRO_STOCK,runs,definition,fit)
