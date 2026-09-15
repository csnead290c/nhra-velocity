import numpy as np
import pandas as pd

from runlab.definition_library import (
    DefinitionLibrary, ConstantDefinition, CalculatedChannelDefinition, PortableGateDefinition,
    SegmentTemplate, PortableMetricDefinition, ConditionalRule, ReportDefinition,
    apply_library, validate_library, run_saved_report, export_report,
)
from runlab.models import TelemetryRun, TimingData


def _run(engine_name="RPM", g_name="Accel", sixty=1.0, three=2.5):
    t=np.linspace(0,4,81)
    df=pd.DataFrame({"Time":t, engine_name:7000+1000*t, g_name:1.5+0.4*t})
    r=TelemetryRun(name="test", data=df, units={"Time":"s",engine_name:"rpm",g_name:"g"}, channel_map={"time_s":"Time","engine_rpm":engine_name,"longitudinal_g":g_name})
    r.metadata["original_channel_map"]={"engine_rpm":engine_name,"longitudinal_g":g_name}
    r.timing=TimingData(sixty_ft_s=sixty,three_thirty_ft_s=three,quarter_mile_s=4.0)
    return r


def _lib():
    lib=DefinitionLibrary(name="Portable")
    lib.constants["RPM_LIMIT"]=ConstantDefinition("RPM_LIMIT",9500,"rpm")
    lib.calculated_channels["RPM Margin"]=CalculatedChannelDefinition("RPM Margin","RPM_LIMIT - engine_rpm","rpm")
    lib.gates["Winding Out"]=PortableGateDefinition("Winding Out","engine_rpm > 8500")
    lib.segments["60 to 330"]=SegmentTemplate("60 to 330",source="official",start_ref="60",end_ref="330")
    lib.metrics["Peak G"]=PortableMetricDefinition("Peak G","longitudinal_g","max")
    lib.conditions["High G"]=ConditionalRule("High G","Peak G","60 to 330",">",2.1,severity="warning",message="High acceleration")
    lib.reports["Review"]=ReportDefinition("Review",metrics=["Peak G"],segments=["60 to 330"],conditions=["High G"])
    return lib


def test_portable_roles_apply_across_vendor_names():
    lib=_lib(); a=_run("Engine RPM","G Meter"); b=_run("RPM","Accel")
    assert validate_library(lib,a).valid and validate_library(lib,b).valid
    apply_library(a,lib); apply_library(b,lib)
    assert "RPM Margin" in a.data and "RPM Margin" in b.data
    assert np.isclose(a.data["RPM Margin"].iloc[0],2500)
    assert np.isclose(b.data["RPM Margin"].iloc[0],2500)


def test_cycle_and_missing_input_validation():
    lib=DefinitionLibrary(); lib.calculated_channels["A"]=CalculatedChannelDefinition("A","B+1"); lib.calculated_channels["B"]=CalculatedChannelDefinition("B","A+1")
    check=validate_library(lib,_run())
    assert not check.valid and check.cycles
    lib2=DefinitionLibrary();lib2.metrics["Bad"]=PortableMetricDefinition("Bad","boost_psi","max")
    check2=validate_library(lib2,_run()); assert not check2.valid and any("boost_psi" in x for x in check2.missing)


def test_saved_report_uses_each_runs_own_official_segment():
    lib=_lib(); a=_run("Engine RPM","G Meter",1.0,2.0); b=_run("RPM","Accel",1.3,3.2)
    frame=run_saved_report(lib,"Review",[("Q1",a),("Q2",b)])
    assert list(frame["run"])==["Q1","Q2"]
    assert np.isclose(frame.loc[0,"start"],1.0) and np.isclose(frame.loc[0,"end"],2.0)
    assert np.isclose(frame.loc[1,"start"],1.3) and np.isclose(frame.loc[1,"end"],3.2)


def test_library_roundtrip_and_report_exports(tmp_path):
    lib=_lib(); path=lib.save(tmp_path/"portable.nhralib"); loaded=DefinitionLibrary.load(path)
    assert loaded.to_dict()==lib.to_dict()
    frame=run_saved_report(loaded,"Review",[("Q1",_run())])
    for suffix in (".csv",".json",".xlsx"):
        out=export_report(frame,tmp_path/("report"+suffix)); assert out.exists() and out.stat().st_size>0
