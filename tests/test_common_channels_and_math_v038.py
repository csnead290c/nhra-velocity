from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from runlab.common_channels import common_channel_label, common_channel_specs
from runlab.importers import apply_channel_overrides
from runlab.math_channels import add_math_channel, evaluate_run_expression, resolve_expression_references
from runlab.models import TelemetryRun
from runlab.preferences import (
    common_channel_profile_scope_options,
    learned_common_channel_overrides,
    math_channel_templates,
    remember_common_channel_mapping,
    save_common_channel_profile,
    save_math_channel_template,
)


def _run(vendor: str = "VendorA") -> TelemetryRun:
    t = np.linspace(0.0, 1.0, 11)
    return TelemetryRun(
        name="demo",
        vendor=vendor,
        data=pd.DataFrame({"Clock": t, "EngSpd": 7000 + 1000 * t, "DS": 1000 + 500 * t, "Pretty TPS": 100.0}),
        channel_map={"time_s": "Clock"},
        units={"Clock": "s", "EngSpd": "rpm", "DS": "rpm", "Pretty TPS": "pct"},
        metadata={},
    )


def test_common_channel_registry_has_human_labels():
    labels={s.key:s.label for s in common_channel_specs()}
    assert labels["engine_rpm"] == "Engine Speed"
    assert labels["driveshaft_rpm"] == "Driveshaft Speed"
    assert common_channel_label("throttle_pct") == "Throttle Position"


def test_channel_override_updates_durable_raw_source_and_can_explicitly_clear():
    run=_run()
    run=apply_channel_overrides(run,{"engine_rpm":"EngSpd","driveshaft_rpm":"DS"},{})
    assert run.metadata["original_channel_map"]["engine_rpm"] == "EngSpd"
    assert run.channel_map["engine_rpm"] == "__engine_rpm"
    run=apply_channel_overrides(run,{"engine_rpm":""},{})
    assert "engine_rpm" not in run.metadata["original_channel_map"]
    assert "engine_rpm" not in run.channel_map


def _authoritative_context(run: TelemetryRun, *, driver: str = "Angie Smith", driver_id: str = "drv-angie", category: str = "PRO STOCK MOTORCYCLE", vehicle_id: str = "veh-1", car_number: str = "8") -> TelemetryRun:
    run.metadata.update({
        "catalog_driver_id": driver_id,
        "catalog_driver_name": driver,
        "catalog_category": category,
        "catalog_vehicle_id": vehicle_id,
        "catalog_car_number": car_number,
    })
    return run


def test_learned_common_mapping_is_context_scoped_and_dimension_safe(tmp_path: Path):
    pref=tmp_path/"preferences.json"
    a=_authoritative_context(_run("MaxxECU"))
    remember_common_channel_mapping(a,"EngSpd","engine_rpm",scope="driver_category",path=pref)

    same=_authoritative_context(_run("MaxxECU"))
    other_driver=_authoritative_context(_run("MaxxECU"),driver="Richard Gadson",driver_id="drv-richard")
    other_category=_authoritative_context(_run("MaxxECU"),category="PRO STOCK")
    other_vendor=_authoritative_context(_run("MoTeC"))
    assert learned_common_channel_overrides(same,path=pref)["engine_rpm"] == "EngSpd"
    assert learned_common_channel_overrides(other_driver,path=pref) == {}
    assert learned_common_channel_overrides(other_category,path=pref) == {}
    assert learned_common_channel_overrides(other_vendor,path=pref) == {}

    bad=_authoritative_context(_run("MaxxECU"))
    bad.units["EngSpd"]="psi"
    assert learned_common_channel_overrides(bad,path=pref) == {}


def test_common_profile_never_falls_back_to_vendor_global_guess(tmp_path: Path):
    pref=tmp_path/"preferences.json"
    scratch=_run("RacePak")
    assert common_channel_profile_scope_options(scratch) == []
    try:
        remember_common_channel_mapping(scratch,"EngSpd","engine_rpm",path=pref)
    except ValueError as exc:
        assert "driver" in str(exc).lower() or "category" in str(exc).lower()
    else:
        raise AssertionError("Context-free learned mapping must fail closed")


def test_profile_application_is_all_or_none_when_logger_configuration_changes(tmp_path: Path):
    pref=tmp_path/"preferences.json"
    a=_authoritative_context(_run("RacePak"))
    save_common_channel_profile(a,{"engine_rpm":"EngSpd","driveshaft_rpm":"DS"},scope="driver_category",path=pref)
    same=_authoritative_context(_run("RacePak"))
    assert learned_common_channel_overrides(same,path=pref) == {"engine_rpm":"EngSpd","driveshaft_rpm":"DS"}
    changed=_authoritative_context(_run("RacePak"))
    changed.data=changed.data.drop(columns=["DS"])
    changed.units.pop("DS",None)
    assert learned_common_channel_overrides(changed,path=pref) == {}


def test_portable_math_common_references_follow_different_source_names():
    t=np.linspace(0.0,1.0,6)
    a=TelemetryRun(name="a",vendor="A",data=pd.DataFrame({"T":t,"RPM":6000+1000*t,"Shaft":1000+100*t}),channel_map={"time_s":"T"},units={"T":"s","RPM":"rpm","Shaft":"rpm"})
    b=TelemetryRun(name="b",vendor="B",data=pd.DataFrame({"Clock":t,"Engine Speed Raw":6000+1000*t,"Prop":1000+100*t}),channel_map={"time_s":"Clock"},units={"Clock":"s","Engine Speed Raw":"rpm","Prop":"rpm"})
    a=apply_channel_overrides(a,{"engine_rpm":"RPM","driveshaft_rpm":"Shaft"},{})
    b=apply_channel_overrides(b,{"engine_rpm":"Engine Speed Raw","driveshaft_rpm":"Prop"},{})
    expression="@engine_rpm / @driveshaft_rpm"
    va=evaluate_run_expression(a,expression)
    vb=evaluate_run_expression(b,expression)
    assert np.allclose(va,vb)
    add_math_channel(a,"Overall Ratio",expression,"ratio")
    assert "Overall Ratio" in a.data
    assert a.metadata["math_channels"][-1]["expression"] == expression


def test_math_expression_can_reference_display_alias():
    run=_run()
    run.metadata["channel_aliases"]={"EngSpd":"Engine Speed Display"}
    resolved=resolve_expression_references(run,"`Engine Speed Display` / 1000")
    assert "`EngSpd`" in resolved
    values=evaluate_run_expression(run,"`Engine Speed Display` / 1000")
    assert np.isclose(values[0],7.0)


def test_reusable_math_templates_persist(tmp_path: Path):
    pref=tmp_path/"preferences.json"
    save_math_channel_template("My Ratio","@engine_rpm / @driveshaft_rpm","ratio",path=pref)
    templates=math_channel_templates(path=pref)
    assert templates["My Ratio"]["expression"] == "@engine_rpm / @driveshaft_rpm"
    assert "Engine / Driveshaft Ratio" in templates


def test_math_builder_engineering_rolling_functions_and_rate_units():
    run=_run()
    run=apply_channel_overrides(run,{"engine_rpm":"EngSpd"},{})
    for fn in ("rollingmean","rollingrms","rollingmin","rollingmax","rollingstd"):
        values=evaluate_run_expression(run,f"{fn}(@engine_rpm, 0.2)")
        assert len(values)==len(run.data)
        assert np.isfinite(values).all()
    add_math_channel(run,"Engine Accel","derivative(@engine_rpm)","rpmps")
    assert run.units["Engine Accel"]=="rpmps"


def test_portable_math_recomputes_after_common_channel_remap():
    from runlab.math_channels import reapply_math_channels
    t=np.linspace(0,1,6)
    run=TelemetryRun(
        name='remap',data=pd.DataFrame({'T':t,'EngineA':6000+100*t,'EngineB':9000+100*t,'DS':1000+50*t}),
        channel_map={'time_s':'T'},units={'T':'s','EngineA':'rpm','EngineB':'rpm','DS':'rpm'}
    )
    run=apply_channel_overrides(run,{'engine_rpm':'EngineA','driveshaft_rpm':'DS'},{})
    add_math_channel(run,'Ratio','@engine_rpm / @driveshaft_rpm','ratio')
    before=run.data['Ratio'].to_numpy().copy();defs=list(run.metadata['math_channels'])
    run=apply_channel_overrides(run,{'engine_rpm':'EngineB','driveshaft_rpm':'DS'},{})
    reapply_math_channels(run,defs)
    after=run.data['Ratio'].to_numpy()
    assert np.all(after>before)


def test_friendly_common_channel_label_resolves_as_channel_reference():
    from runlab.workstation import resolve_channel
    run = apply_channel_overrides(_run(), {"engine_rpm": "EngSpd"}, {})
    assert resolve_channel(run, "Engine Speed") == "EngSpd"
    values = evaluate_run_expression(run, "`Engine Speed` / 1000")
    assert np.isclose(values[0], 7.0)


def test_analysis_library_accepts_portable_at_common_math_references():
    from runlab.definition_library import (
        CalculatedChannelDefinition,
        DefinitionLibrary,
        apply_library,
        validate_library,
    )
    run = apply_channel_overrides(
        _run(), {"engine_rpm": "EngSpd", "driveshaft_rpm": "DS"}, {}
    )
    lib = DefinitionLibrary(name="Portable Math")
    lib.calculated_channels["Overall Ratio"] = CalculatedChannelDefinition(
        "Overall Ratio", "@engine_rpm / @driveshaft_rpm", "ratio"
    )
    check = validate_library(lib, run)
    assert check.valid, check.missing
    result = apply_library(run, lib)
    assert result["calculated_channels"] == ["Overall Ratio"]
    expected = run.data["__engine_rpm"].to_numpy() / run.data["__driveshaft_rpm"].to_numpy()
    assert np.allclose(run.data["Overall Ratio"].to_numpy(), expected)


def test_run_local_math_dependencies_reapply_in_safe_order_and_cycles_fail():
    from runlab.math_channels import reapply_math_channels
    run = apply_channel_overrides(_run(), {"engine_rpm": "EngSpd"}, {})
    defs = [
        {"name": "Scaled", "expression": "`Base` * 2", "unit": "rpm"},
        {"name": "Base", "expression": "@engine_rpm", "unit": "rpm"},
    ]
    reapply_math_channels(run, defs)
    assert np.allclose(run.data["Scaled"], run.data["Base"] * 2)
    assert [d["name"] for d in run.metadata["math_channels"]] == ["Base", "Scaled"]

    bad = [
        {"name": "A", "expression": "`B` + 1", "unit": "rpm"},
        {"name": "B", "expression": "`A` + 1", "unit": "rpm"},
    ]
    try:
        reapply_math_channels(run, bad)
    except ValueError as exc:
        assert "dependency cycle" in str(exc).lower()
    else:
        raise AssertionError("Expected dependency-cycle rejection")
