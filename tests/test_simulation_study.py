import numpy as np
from runlab.models import DEFAULT_PRO_STOCK, Environment, TimingData
from runlab.inverse import FitRun
from runlab.simulation_study import (
    ScenarioAxis, SimulationStudyDefinition, run_scenario_sweep,
    timing_residuals, validate_vehicle_against_runs,
)


def test_multi_axis_sweep_has_baseline_and_deltas():
    study=SimulationStudyDefinition(
        name="gear/power",
        engine="reference",
        axes=[
            ScenarioAxis("power_scale",(0.98,1.02)),
            ScenarioAxis("weight_lb",(-10.0,10.0),mode="delta"),
        ],
        include_baseline=True,
        max_cases=10,
    )
    out=run_scenario_sweep(DEFAULT_PRO_STOCK,Environment(),study)
    assert len(out.table)==5
    assert "input.power_scale" in out.table
    assert "input.weight_lb" in out.table
    assert "delta.1320_ft_s" in out.table
    base=out.table.iloc[0]
    assert base["case"]=="Baseline"
    assert abs(float(base["delta.1320_ft_s"])) < 1e-12
    faster=out.table[out.table["input.power_scale"]==1.02]
    assert np.isfinite(faster["1320_ft_s"]).all()


def test_indexed_ratio_and_cda_axes_are_supported():
    study=SimulationStudyDefinition(
        engine="smooth",smooth_dt_s=.01,
        axes=[ScenarioAxis("gear_ratio_1",(0.98,1.02),mode="scale"),ScenarioAxis("cda_ft2",(0.9,1.1),mode="scale")],
        max_cases=10,
    )
    out=run_scenario_sweep(DEFAULT_PRO_STOCK,Environment(),study)
    assert len(out.table)==5
    assert out.table["input.gear_ratio_1"].dropna().nunique()==2
    assert out.table["input.cda_ft2"].dropna().nunique()==2


def test_timing_residuals_and_multi_run_validation():
    obs=TimingData(sixty_ft_s=1.0,quarter_mile_s=7.0,quarter_mile_mph=190)
    pred=TimingData(sixty_ft_s=1.01,quarter_mile_s=6.98,quarter_mile_mph=191)
    r=timing_residuals(obs,pred,run_name="Q1")
    assert set(r.measurement)=={"60_ft_s","1320_ft_s","1320_mph"}
    assert np.isclose(r.loc[r.measurement=="60_ft_s","residual"].iloc[0],.01)

    # Use the model's own baseline prediction as measured data to verify the
    # validation plumbing without assuming one exact historical ET.
    baseline=run_scenario_sweep(DEFAULT_PRO_STOCK,Environment(),SimulationStudyDefinition(axes=[])).baseline_result
    runs=[FitRun("A",Environment(),baseline.timing,None),FitRun("B",Environment(temperature_f=85),TimingData(),None)]
    frame=validate_vehicle_against_runs(DEFAULT_PRO_STOCK,runs)
    assert (frame[frame.run=="A"].residual.abs() < 1e-9).all()


def test_study_package_round_trip(tmp_path):
    from runlab.simulation_study import package_study_result, SimulationStudyPackage
    study=SimulationStudyDefinition(engine='reference',axes=[ScenarioAxis('power_scale',(1.0,1.01))])
    result=run_scenario_sweep(DEFAULT_PRO_STOCK,Environment(),study)
    package=package_study_result(result,DEFAULT_PRO_STOCK,Environment(),source_run_id='run-123',source_run_name='Q1')
    path=package.save(tmp_path/'study.nhrastudy')
    restored=SimulationStudyPackage.load(path)
    assert restored.source_run_id=='run-123'
    assert restored.definition.axes[0].parameter=='power_scale'
    assert len(restored.result_rows)==3
    assert restored.vehicle.weight_lb==DEFAULT_PRO_STOCK.weight_lb
    assert {x['name'] for x in restored.upstream_references}=={'RacingSystemsAnalysis','nhratechservices'}


def test_v1_simulation_package_remains_backward_readable_without_upstream_provenance():
    from runlab.simulation_study import SimulationStudyPackage
    payload={
        'format':'nhra-simulation-study-package','version':1,'software_version':'old','created_at_utc':'',
        'source_run_id':'','source_run_name':'','definition':SimulationStudyDefinition().to_dict(),
        'vehicle':DEFAULT_PRO_STOCK.to_dict(),'environment':Environment().to_dict(),'results':[]
    }
    restored=SimulationStudyPackage.from_dict(payload)
    assert restored.upstream_references==[]
