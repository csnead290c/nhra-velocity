from __future__ import annotations

import copy

from runlab.fit_study import FitStudyDefinition, load_fit_study_package, run_joint_fit_study, save_fit_study_package
from runlab.inverse import FitDistanceWindow, FitEvidencePolicy, FitRun, make_run_nuisance_specs
from runlab.models import DEFAULT_PRO_STOCK, Environment, TimingData
from runlab.physics import SolverOptions, simulate
from runlab.scenario import generated_run_from_result


def _smooth_measured(name: str, power_scale: float):
    env=Environment()
    result=simulate(DEFAULT_PRO_STOCK,env,power_scale=power_scale,options=SolverOptions(dt_s=.005))
    run=generated_run_from_result(name,result,copy.deepcopy(DEFAULT_PRO_STOCK),env,power_scale=power_scale)
    run.timing=TimingData()
    return run


def test_per_run_nuisance_allowlist_only_creates_requested_local_terms():
    env=Environment()
    runs=[
        FitRun('Baseline',env,nuisance_terms=[]),
        FitRun('Track change',env,nuisance_terms=['traction_delta']),
        FitRun('Power variation',env,nuisance_terms=['power_scale']),
    ]
    specs=make_run_nuisance_specs(runs,['traction_delta','power_scale'])
    assert [s.name for s in specs]==['run__1__traction_delta','run__2__power_scale']


def test_joint_fit_uses_distinct_per_run_downtrack_evidence_and_recovers_shared_power(tmp_path):
    a=_smooth_measured('Early evidence',.90)
    b=_smooth_measured('Late evidence',.90)
    early=FitEvidencePolicy(telemetry_domain='distance',telemetry_weights={'speed_mph':1,'engine_rpm':0,'driveshaft_rpm':0,'longitudinal_g':0},distance_windows=[FitDistanceWindow('330-660',330,660)],max_points=35,distance_step_ft=10)
    late=FitEvidencePolicy(telemetry_domain='distance',telemetry_weights={'speed_mph':1,'engine_rpm':0,'driveshaft_rpm':0,'longitudinal_g':0},distance_windows=[FitDistanceWindow('660-1320',660,1320)],max_points=45,distance_step_ft=10)
    runs=[
        FitRun('Early evidence',Environment(),telemetry=a,evidence=early,nuisance_terms=[],source_run_id='run-a',role='baseline'),
        FitRun('Late evidence',Environment(),telemetry=b,evidence=late,nuisance_terms=[],source_run_id='run-b',role='comparison'),
    ]
    definition=FitStudyDefinition(name='Shared power',shared_unknowns=['power_scale'],max_nfev=40,fit_dt_s=.005,final_dt_s=.005)
    fit,package=run_joint_fit_study(DEFAULT_PRO_STOCK,runs,definition)
    estimate=float(fit.estimates.loc[fit.estimates.internal_name=='power_scale','estimate'].iloc[0])
    assert fit.success and abs(estimate-.90)<.01
    by_run={name:set(rows.source) for name,rows in fit.residuals.groupby('run')}
    assert by_run['Early evidence']=={'strip:speed_mph'}
    assert by_run['Late evidence']=={'strip:speed_mph'}
    assert fit.residuals.loc[fit.residuals.run=='Early evidence','x'].between(330,660).all()
    assert fit.residuals.loc[fit.residuals.run=='Late evidence','x'].between(660,1320).all()
    # Shared power is baked into optimized_vehicle; final predictions must not
    # multiply it a second time after materialization.
    direct=simulate(fit.optimized_vehicle,Environment(),power_scale=1.0,options=SolverOptions(dt_s=.005))
    assert abs(fit.predicted_runs['Early evidence'].timing.quarter_mile_s-direct.timing.quarter_mile_s)<1e-10
    assert package.runs[0]['source_run_id']=='run-a'
    assert package.runs[1]['evidence']['distance_windows'][0]['start_ft']==660.0

    path=save_fit_study_package(tmp_path/'shared_power.nhrafit',package)
    restored=load_fit_study_package(path)
    assert restored.definition.shared_unknowns==['power_scale']
    assert restored.runs[1]['role']=='comparison'
    assert restored.estimates[0]['internal_name']=='power_scale'


def test_fit_study_package_includes_quality_decomposition_and_parameter_diagnostics(tmp_path):
    a=_smooth_measured('Early evidence',.90)
    b=_smooth_measured('Late evidence',.90)
    early=FitEvidencePolicy(telemetry_domain='distance',telemetry_weights={'speed_mph':1,'engine_rpm':0,'driveshaft_rpm':0,'longitudinal_g':0},distance_windows=[FitDistanceWindow('330-660',330,660)],max_points=30,distance_step_ft=10)
    late=FitEvidencePolicy(telemetry_domain='distance',telemetry_weights={'speed_mph':1,'engine_rpm':0,'driveshaft_rpm':0,'longitudinal_g':0},distance_windows=[FitDistanceWindow('660-1320',660,1320)],max_points=40,distance_step_ft=10)
    runs=[
        FitRun('Early evidence',Environment(),telemetry=a,evidence=early,nuisance_terms=[],source_run_id='run-a',role='baseline'),
        FitRun('Late evidence',Environment(),telemetry=b,evidence=late,nuisance_terms=[],source_run_id='run-b',role='comparison'),
    ]
    definition=FitStudyDefinition(name='Quality decomposition',shared_unknowns=['power_scale'],max_nfev=35,fit_dt_s=.005,final_dt_s=.005)
    fit,package=run_joint_fit_study(DEFAULT_PRO_STOCK,runs,definition)
    assert package.format_version==5
    assert package.residual_summary['overall']['count']==len(fit.residuals)
    by_run={r['run']:r for r in package.residual_summary['by_run']}
    assert set(by_run)=={'Early evidence','Late evidence'}
    assert abs(sum(r['objective_fraction'] for r in by_run.values())-1.0)<1e-9
    windows={(r['run'],r['window']) for r in package.residual_summary['by_window']}
    assert ('Early evidence','330-660') in windows
    assert ('Late evidence','660-1320') in windows
    assert package.parameter_diagnostics[0]['internal_name']=='power_scale'
    assert {x['name'] for x in package.upstream_references}=={'RacingSystemsAnalysis','nhratechservices'}
    path=save_fit_study_package(tmp_path/'quality.nhrafit',package)
    restored=load_fit_study_package(path)
    assert restored.residual_summary['overall']['count']==len(fit.residuals)
    assert restored.parameter_diagnostics[0]['internal_name']=='power_scale'


def test_fit_study_v1_package_remains_backward_readable():
    payload={
        'format':'nhra-fit-study','format_version':1,'definition':{'name':'Old','shared_unknowns':['power_scale']},
        'base_vehicle':{},'optimized_vehicle':{},'runs':[],'estimates':[],'correlation':{},'residuals':[],
        'reference_residuals':[],'identifiability_notes':[],'success':True,'message':'ok'
    }
    from runlab.fit_study import FitStudyPackage
    pkg=FitStudyPackage.from_dict(payload)
    assert pkg.success and pkg.residual_summary=={} and pkg.parameter_diagnostics==[]


def test_v2_fit_study_package_remains_backward_readable():
    payload={
        'format':'nhra-fit-study','format_version':2,'definition':{'name':'v2','shared_unknowns':['power_scale']},
        'base_vehicle':{},'optimized_vehicle':{},'runs':[],'estimates':[],'correlation':{},'residuals':[],
        'reference_residuals':[],'identifiability_notes':[],'residual_summary':{},'reference_residual_summary':{},
        'parameter_diagnostics':[],'success':True,'message':'ok'
    }
    from runlab.fit_study import FitStudyPackage
    pkg=FitStudyPackage.from_dict(payload)
    assert pkg.success and pkg.profiles=={}


def test_v3_fit_study_package_remains_backward_readable():
    payload={
        'format':'nhra-fit-study','format_version':3,'definition':{'name':'v3','shared_unknowns':['power_scale']},
        'base_vehicle':{},'optimized_vehicle':{},'runs':[],'estimates':[],'correlation':{},'residuals':[],
        'reference_residuals':[],'identifiability_notes':[],'residual_summary':{},'reference_residual_summary':{},
        'parameter_diagnostics':[],'profiles':{'power_scale':{'status':'bounded_in_scan'}},'success':True,'message':'ok'
    }
    from runlab.fit_study import FitStudyPackage
    pkg=FitStudyPackage.from_dict(payload)
    assert pkg.success and pkg.run_influence=={} and 'power_scale' in pkg.profiles


def test_v4_fit_study_package_remains_backward_readable_without_upstream_provenance():
    payload={
        'format':'nhra-fit-study','format_version':4,'definition':{'name':'v4','shared_unknowns':['power_scale']},
        'base_vehicle':{},'optimized_vehicle':{},'runs':[],'estimates':[],'correlation':{},'residuals':[],
        'reference_residuals':[],'identifiability_notes':[],'residual_summary':{},'reference_residual_summary':{},
        'parameter_diagnostics':[],'profiles':{},'run_influence':{'runs':[]},'success':True,'message':'ok'
    }
    from runlab.fit_study import FitStudyPackage
    pkg=FitStudyPackage.from_dict(payload)
    assert pkg.success and pkg.format_version==4 and pkg.upstream_references==[]
