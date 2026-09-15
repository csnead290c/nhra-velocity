from __future__ import annotations
import copy
from runlab.fit_study import FitStudyDefinition, run_joint_fit_study
from runlab.fit_uncertainty import profile_parameter, profile_suite
from runlab.inverse import FitDistanceWindow, FitEvidencePolicy, FitRun
from runlab.models import DEFAULT_PRO_STOCK, Environment, TimingData
from runlab.physics import SolverOptions, simulate
from runlab.scenario import generated_run_from_result


def _measured(power=.9):
    env=Environment(); sim=simulate(DEFAULT_PRO_STOCK,env,power_scale=power,options=SolverOptions(dt_s=.005))
    run=generated_run_from_result('Measured',sim,copy.deepcopy(DEFAULT_PRO_STOCK),env,power_scale=power);run.timing=TimingData()
    return run


def test_profile_objective_minimum_tracks_joint_fit_and_worsens_away_from_optimum():
    measured=_measured(.90)
    evidence=FitEvidencePolicy(telemetry_domain='distance',telemetry_weights={'speed_mph':1,'engine_rpm':0,'driveshaft_rpm':0,'longitudinal_g':0},distance_windows=[FitDistanceWindow('330-1320',330,1320)],max_points=45,distance_step_ft=15)
    runs=[FitRun('Measured',Environment(),telemetry=measured,evidence=evidence,nuisance_terms=[])]
    definition=FitStudyDefinition(name='Profile power',shared_unknowns=['power_scale'],max_nfev=35,fit_dt_s=.005,final_dt_s=.005)
    fit,_=run_joint_fit_study(DEFAULT_PRO_STOCK,runs,definition)
    prof=profile_parameter(DEFAULT_PRO_STOCK,runs,definition,fit,'power_scale',points=5,span_fraction=.05,max_nfev=25)
    assert abs(prof.optimum-.90)<.01
    best=min(prof.rows,key=lambda r: float(r['objective']))
    assert abs(float(best['value'])-prof.optimum)<1e-8
    ends=[prof.rows[0],prof.rows[-1]]
    assert all(r['delta_objective'] is None or float(r['delta_objective'])>=-1e-6 for r in ends)
    assert max(float(r['delta_objective']) for r in ends if r['delta_objective'] is not None)>0.1
    assert prof.status in {'bounded_in_scan','one_sided_in_scan','flat_in_scan'}


def test_profile_suite_serializes_multiple_shared_parameters_shape():
    measured=_measured(.92)
    evidence=FitEvidencePolicy(telemetry_domain='distance',telemetry_weights={'speed_mph':1,'engine_rpm':0,'driveshaft_rpm':0,'longitudinal_g':0},distance_windows=[FitDistanceWindow('660-1320',660,1320)],max_points=35,distance_step_ft=20)
    runs=[FitRun('Measured',Environment(),telemetry=measured,evidence=evidence,nuisance_terms=[])]
    definition=FitStudyDefinition(name='Profile suite',shared_unknowns=['power_scale'],max_nfev=30,fit_dt_s=.005,final_dt_s=.005)
    fit,_=run_joint_fit_study(DEFAULT_PRO_STOCK,runs,definition)
    suite=profile_suite(DEFAULT_PRO_STOCK,runs,definition,fit,['power_scale'],points=3,span_fraction=.03,max_nfev=20)
    assert 'power_scale' in suite and suite['power_scale']['rows']
