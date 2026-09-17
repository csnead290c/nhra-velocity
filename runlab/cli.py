from __future__ import annotations

import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd

from .inverse import FitRun, FitEvidencePolicy, fit_vehicle
from .models import Environment, TimingData, VehicleConfig
from .physics import SolverOptions, simulate, timeslip_table
from .legacy_reference import simulate_legacy_reference
from .quarterpro import parse_quarter_pro_dat
from .importers import load_telemetry
from .plotability import assess_plotability
from .display_data import validate_default_waveform
from .selftest import run_data_pipeline_selftest, format_selftest
from .resources import bundled_examples_dir
from .catalog import LocalCatalog
from .sync_contract import run_sync_payload, analysis_case_bundle, analysis_case_offline_manifest
from .official_runs import import_official_run_csv
from .sync_engine import apply_tech_services_snapshot
from .qualification import qualify_corpus, extension_inventory
from .racepak_channel_library import build_channel_id_census, save_census, install_census
from .import_registry import registry_rows
from .case_playback import case_playback_frame, case_time_extent
from .workstation import channel_catalog, evaluate_gate, MetricDefinition, drag_metric_report, resolve_channel
from .display_data import channel_xy
from .signal_analysis import power_spectral_density
from .heatmap import binned_map
from .display_analysis import paired_channel_data, linear_regression, channel_distribution, sample_channel_at
from .definition_library import DefinitionLibrary, starter_library, validate_library, apply_library, run_saved_report, export_report
from .rule_events import evaluate_event_rules
from .simulation_study import SimulationStudyDefinition, ScenarioAxis, run_scenario_sweep, validate_vehicle_against_runs, export_study_table
from .strip_analysis import analyze_strip, strip_table, section_residual_table
from .fit_study import FitStudyDefinition, run_joint_fit_study, save_fit_study_package
from .fit_uncertainty import profile_suite, leave_one_run_out_influence
from .knowledge import vehicle_from_run
from .model_enrichment import run_rsa_model_enrichment, model_enrichment_frame
from .release_audit import audit_release_tree
from .product_manifest import manifest_dict
from .tech_services_http import build_http_transport_from_env, TECH_SERVICES_AUDITED_SHA


def _vehicle(args):
    if args.qpro:
        return parse_quarter_pro_dat(args.qpro)[:2]
    if args.vehicle:
        v = VehicleConfig.from_dict(json.loads(Path(args.vehicle).read_text()))
    else:
        raise SystemExit("Use --qpro or --vehicle")
    if args.environment:
        e = Environment.from_dict(json.loads(Path(args.environment).read_text()))
    else:
        e = Environment()
    return v, e


def cmd_simulate(args):
    v, e = _vehicle(args)
    if args.engine == "reference":
        r = simulate_legacy_reference(v, e, power_scale=args.power_scale)
    else:
        r = simulate(v, e, power_scale=args.power_scale, options=SolverOptions(dt_s=args.dt))
    print(timeslip_table(r).to_string(index=False))
    if args.trace:
        r.trace.to_csv(args.trace, index=False)
        print(f"\nTrace written to {args.trace}")


def cmd_inspect(args):
    for file in args.files:
        try:
            r = load_telemetry(file, vendor=args.vendor)
        except Exception as exc:
            print(f"\n{file}\n  ERROR: {exc}")
            continue
        report = assess_plotability(r)
        points = validate_default_waveform(r, report.default_channels)
        print(f"\n{file}")
        print(f"  vendor={r.vendor}")
        print(f"  decoder={r.metadata.get('import_decoder','')}")
        print(f"  probe={r.metadata.get('import_probe_reason','')}")
        print(f"  rows={len(r.data)} native_channels={len(r.native_channels)}")
        print(f"  canonical_map={r.channel_map}")
        print(f"  plotable={report.plotable} timebase={report.timebase}")
        print(f"  default_traces={report.default_channels}")
        print(f"  default_plot_points={points}")
        for warning in r.metadata.get('data_warnings', []):
            print(f"  WARNING: {warning}")



def cmd_qualify(args):
    rows=qualify_corpus(args.paths,recursive=args.recursive,sample_per_format=args.sample_per_format,compute_sha=not args.skip_hash)
    payload=[r.to_dict() for r in rows]
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload,indent=2),encoding='utf-8')
    if args.csv_out:
        import pandas as pd
        pd.DataFrame(payload).to_csv(args.csv_out,index=False)
    if args.inventory_json or args.inventory_csv:
        inventory=extension_inventory(args.paths,recursive=args.recursive)
        if args.inventory_json:
            Path(args.inventory_json).write_text(json.dumps(inventory,indent=2),encoding='utf-8')
        if args.inventory_csv:
            import pandas as pd
            inv_frame=pd.DataFrame(inventory)
            if 'examples' in inv_frame.columns:
                inv_frame['examples']=inv_frame['examples'].map(lambda values:' | '.join(values or []))
            inv_frame.to_csv(args.inventory_csv,index=False)
    passed=sum(1 for r in rows if r.status=='pass')
    print(f"Qualified {len(rows)} candidate file(s): {passed} pass, {len(rows)-passed} need attention")
    for r in rows:
        detail=r.error[:120] or r.integrity_flags[:120]
        print(f"{r.status:22} {r.vendor:10} {r.filename}  channels={r.numeric_channels}  {detail}")
    if args.strict and passed != len(rows): raise SystemExit(2)


def cmd_racepak_ids(args):
    payload = build_channel_id_census(
        args.paths,
        recursive=args.recursive,
        rpk_mode=args.rpk_mode,
        rpk_quick_limit=args.rpk_quick_limit,
    )
    if args.json_out:
        save_census(payload, args.json_out)
    if args.csv_out:
        frame = pd.DataFrame(payload.get("channels", []))
        for col in ("distinct_names", "distinct_units", "sample_rates_hz", "source_kinds", "example_files"):
            if col in frame.columns:
                frame[col] = frame[col].map(lambda values: " | ".join(str(x) for x in (values or [])))
        frame.to_csv(args.csv_out, index=False)
    if args.descriptor_csv_out:
        rows = []
        for profile in payload.get("descriptor_profiles", []) or []:
            base = {
                "descriptor_signature_sha256": profile.get("descriptor_signature_sha256", ""),
                "safe_for_exact_descriptor_recovery": bool(profile.get("safe_for_exact_descriptor_recovery")),
                "confidence": profile.get("confidence", ""),
                "recorded_channel_count": profile.get("recorded_channel_count", 0),
                "distinct_bound_configurations": profile.get("distinct_bound_configurations", 0),
                "known_ddf_occurrences": profile.get("known_ddf_occurrences", 0),
                "config_examples": " | ".join(profile.get("config_examples") or []),
                "ddf_examples": " | ".join(profile.get("ddf_examples") or []),
            }
            for channel in profile.get("channels", []) or []:
                row = dict(base)
                row.update({
                    "channel_id": channel.get("channel_id"),
                    "source_name": channel.get("name", ""),
                    "unit": channel.get("unit", ""),
                    "sample_rate_hz": channel.get("sample_rate_hz"),
                    "distinct_names": " | ".join(channel.get("distinct_names") or []),
                    "distinct_units": " | ".join(channel.get("distinct_units") or []),
                })
                rows.append(row)
        pd.DataFrame(rows).to_csv(args.descriptor_csv_out, index=False)
    installed = None
    if args.install:
        installed = install_census(payload)
    summary = payload.get("summary", {})
    scan = payload.get("scan", {})
    print(
        "RacePak corpus evidence: "
        f"{summary.get('channel_ids', 0)} channel ids (ID history is suggestion-only); "
        f"{summary.get('conflicted_ids', 0)} conflicted ids; "
        f"{summary.get('safe_exact_descriptor_profiles', 0)} safe exact DDF descriptor fingerprint(s). "
        f"Scanned {scan.get('definition_files_scanned', 0)} definition file(s)."
    )
    if installed:
        print(f"Installed evidence library: {installed}")
        print("Numeric channel-id history will NOT rename a DDF automatically; only an exact known descriptor fingerprint may recover source names/units.")
    warnings = payload.get("warnings", [])
    if warnings:
        print(f"Corpus-evidence warnings: {len(warnings)} (see JSON report for details)")


def cmd_selftest(args):
    rows = run_data_pipeline_selftest(args.examples or bundled_examples_dir())
    print(format_selftest(rows))
    if not all(bool(r.get("pass")) for r in rows):
        raise SystemExit(2)


def cmd_formats(args):
    rows = registry_rows()
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    frame = pd.DataFrame(rows)
    frame["extensions"] = frame["extensions"].map(lambda values: ", ".join(values))
    cols = ["label", "extensions", "status", "decoder_key"]
    print(frame[cols].to_string(index=False))



def cmd_catalog(args):
    catalog=LocalCatalog(args.catalog) if args.catalog else LocalCatalog()
    if args.action=='stats':
        print(json.dumps({'path':str(catalog.path),'schema_version':catalog.schema_version,'stats':catalog.stats()},indent=2))
    elif args.action=='runs':
        rows=catalog.list_runs(search=args.search or '',limit=args.limit)
        if not rows:
            print('No catalog runs found.');return
        import pandas as pd
        cols=['id','event_name','run_key','driver_name','category','round','run_datetime','asset_count','offline_asset_count']
        print(pd.DataFrame(rows)[[c for c in cols if c in rows[0]]].to_string(index=False))
    elif args.action=='payload':
        if not args.run_id: raise SystemExit('--run-id is required for payload')
        print(json.dumps(run_sync_payload(catalog,args.run_id),indent=2,default=str))
    elif args.action=='cases':
        rows=catalog.list_analysis_cases(case_type=args.case_type or None,status=args.status or None,limit=args.limit)
        print(json.dumps(rows,indent=2,default=str))
    elif args.action=='case-bundle':
        if not args.case_id: raise SystemExit('--case-id is required for case-bundle')
        print(json.dumps(analysis_case_bundle(catalog,args.case_id),indent=2,default=str))
    elif args.action=='case-timeline':
        if not args.case_id: raise SystemExit('--case-id is required for case-timeline')
        print(json.dumps({'case_id':args.case_id,'runs':[{'run_id':r['id'],'role':r.get('role'),'time_scale':r.get('time_scale'),'time_offset_s':r.get('time_offset_s'),'method':r.get('alignment_method'),'uncertainty_s':r.get('alignment_uncertainty_s'),'anchors':r.get('alignment_anchors',[])} for r in catalog.list_case_runs(args.case_id)],'markers':catalog.list_case_markers(args.case_id),'offline':analysis_case_offline_manifest(catalog,args.case_id)},indent=2,default=str))
    elif args.action=='case-playback':
        if not args.case_id: raise SystemExit('--case-id is required for case-playback')
        lo,hi=case_time_extent(catalog,args.case_id)
        frame=case_playback_frame(catalog,args.case_id,float(args.case_time))
        print(json.dumps({'extent_s':[lo,hi],'frame':frame.to_dict()},indent=2,default=str))
    elif args.action=='offline-run':
        if not args.run_id: raise SystemExit('--run-id is required for offline-run')
        print(json.dumps(catalog.keep_run_offline(args.run_id),indent=2,default=str))
    elif args.action=='offline-event':
        if not args.event_id: raise SystemExit('--event-id is required for offline-event')
        print(json.dumps(catalog.keep_event_offline(args.event_id),indent=2,default=str))
    elif args.action=='import-official':
        if not args.file: raise SystemExit('--file is required for import-official')
        result=import_official_run_csv(catalog,args.file,event_name=args.event_name or '',event_code=args.event_code or '',season=args.season,track_name=args.track_name or '',location=args.location or '')
        print(json.dumps(result.to_dict(),indent=2,default=str))
    elif args.action=='apply-sync':
        if not args.file: raise SystemExit('--file is required for apply-sync')
        payload=json.loads(Path(args.file).read_text(encoding='utf-8'))
        print(json.dumps(apply_tech_services_snapshot(catalog,payload,provider=args.provider or 'nhra-tech-services').to_dict(),indent=2))


def cmd_analyze(args):
    run=load_telemetry(args.file,vendor=args.vendor)
    if args.action=='channels':
        rows=[r.to_dict() for r in channel_catalog(run,args.query or '')]
        print(json.dumps(rows,indent=2,default=str));return
    if args.action=='gate':
        if not args.expression: raise SystemExit('--expression is required for analyze gate')
        mask=evaluate_gate(run,args.expression)
        print(json.dumps({'matched':int(mask.sum()),'total':int(len(mask)),'fraction':float(mask.mean()) if len(mask) else 0.0},indent=2));return
    if args.action=='metrics':
        if not args.channel: raise SystemExit('--channel is required for analyze metrics')
        frame=drag_metric_report([(Path(args.file).stem,run)],[MetricDefinition(args.metric_name or f'{args.stat} {args.channel}',args.channel,args.stat)],x_mode=args.x_mode)
        print(frame.to_string(index=False));return
    if args.action=='psd':
        if not args.channel: raise SystemExit('--channel is required for analyze psd')
        channel=resolve_channel(run,args.channel) or args.channel
        x,y=channel_xy(run,channel,'Logger Time')
        result=power_spectral_density(x,y,max_frequency_hz=args.max_frequency,window=args.window)
        if len(result.frequency_hz)>1:
            order=np.argsort(result.density[1:])[::-1][:10]+1
            rows=[{'frequency_hz':float(result.frequency_hz[i]),'density':float(result.density[i])} for i in order]
        else: rows=[]
        print(json.dumps({'channel':channel,'sample_rate_hz':result.sample_rate_hz,'resolution_hz':result.resolution_hz,'peaks':rows},indent=2));return
    if args.action=='loadmap':
        if not args.x_channel or not args.y_channel: raise SystemExit('--x-channel and --y-channel are required for analyze loadmap')
        xn=resolve_channel(run,args.x_channel) or args.x_channel;yn=resolve_channel(run,args.y_channel) or args.y_channel
        if xn not in run.data.columns or yn not in run.data.columns: raise SystemExit('CLI loadmap currently requires normalized rectangular channels.')
        xv=run.data[xn];yv=run.data[yn];zv=None
        if args.map_stat!='count':
            if not args.z_channel: raise SystemExit('--z-channel is required unless --map-stat count')
            zn=resolve_channel(run,args.z_channel) or args.z_channel
            if zn not in run.data.columns: raise SystemExit('CLI loadmap Z channel must be in normalized rectangular data.')
            zv=run.data[zn]
        result=binned_map(xv,yv,zv,bins=(args.bins,args.bins),statistic=args.map_stat)
        print(json.dumps(result.to_dict(),indent=2));return
    if args.action=='scatter':
        if not args.x_channel or not args.y_channel: raise SystemExit('--x-channel and --y-channel are required for analyze scatter')
        data=paired_channel_data(run,args.x_channel,args.y_channel,args.z_channel or None,gate_expression=args.expression or '')
        payload={'points':data.points,'aligned':data.aligned,'gate':data.gate_expression}
        if args.regression:
            fit=linear_regression(data.x,data.y);payload['regression']={'slope':fit.slope,'intercept':fit.intercept,'r_squared':fit.r_squared,'correlation':fit.correlation,'count':fit.count}
        if data.z is not None: payload['z']={'min':float(np.nanmin(data.z)),'max':float(np.nanmax(data.z))}
        print(json.dumps(payload,indent=2));return
    if args.action=='histogram':
        if not args.channel: raise SystemExit('--channel is required for analyze histogram')
        result=channel_distribution(run,args.channel,bins=args.bins,mode=args.hist_mode,cumulative=args.cumulative,gate_expression=args.expression or '')
        print(json.dumps({'channel':args.channel,'mode':result.mode,'cumulative':result.cumulative,'source_points':result.source_points,'used_points':result.used_points,'total_time_s':result.total_time_s,'centers':result.centers.tolist(),'values':result.values.tolist()},indent=2));return
    if args.action=='sample':
        if not args.channel: raise SystemExit('--channel is required for analyze sample')
        snap=sample_channel_at(run,args.channel,args.x_value,x_mode=args.sample_x_mode)
        print(json.dumps({'channel':snap.channel,'x':snap.x,'value':snap.value,'unit':snap.unit,'in_range':snap.in_range},indent=2));return

def cmd_library(args):
    if args.action == 'starter':
        if not args.output: raise SystemExit('--output is required for library starter')
        path=starter_library().save(args.output); print(str(path)); return
    if not args.library: raise SystemExit('--library is required')
    lib=DefinitionLibrary.load(args.library)
    if args.action == 'inspect':
        payload=lib.to_dict(); payload['counts']={
            'constants':len(lib.constants),'calculated_channels':len(lib.calculated_channels),'gates':len(lib.gates),
            'segments':len(lib.segments),'metrics':len(lib.metrics),'conditions':len(lib.conditions),'event_rules':len(lib.event_rules),'reports':len(lib.reports)}
        print(json.dumps(payload,indent=2,default=str)); return
    if args.action in {'validate','apply'}:
        if not args.file: raise SystemExit('--file is required for library validate/apply')
        run=load_telemetry(args.file,vendor=args.vendor)
        check=validate_library(lib,run)
        if args.action == 'validate':
            print(json.dumps(check.to_dict(),indent=2));
            if not check.valid: raise SystemExit(2)
            return
        result=apply_library(run,lib)
        payload={'applied':result,'channels':list(run.data.columns),'gates':run.metadata.get('gates',[])}
        if args.output:
            Path(args.output).parent.mkdir(parents=True,exist_ok=True); run.data.to_csv(args.output,index=False); payload['output']=str(args.output)
        print(json.dumps(payload,indent=2,default=str)); return
    if args.action == 'events':
        if not args.file: raise SystemExit('--file is required for library events')
        run=load_telemetry(args.file,vendor=args.vendor); frame=evaluate_event_rules(lib,run)
        if args.output:
            target=Path(args.output); target.parent.mkdir(parents=True,exist_ok=True)
            if target.suffix.lower()=='.json': target.write_text(frame.to_json(orient='records',indent=2),encoding='utf-8')
            else: frame.to_csv(target,index=False)
        print(frame.to_string(index=False)); return
    if args.action == 'report':
        if not args.report: raise SystemExit('--report is required for library report')
        if not args.files: raise SystemExit('--files requires at least one telemetry file for library report')
        runs=[]
        for file in args.files:
            path=Path(file); runs.append((path.stem,load_telemetry(path,vendor=args.vendor)))
        frame=run_saved_report(lib,args.report,runs)
        if args.output: export_report(frame,args.output)
        print(frame.to_string(index=False)); return



def cmd_study(args):
    if args.action == 'template':
        if not args.output: raise SystemExit('--output is required for study template')
        definition=SimulationStudyDefinition(
            name='RSA Simulation Study',
            engine='reference',
            axes=[
                ScenarioAxis('power_scale',(0.98,1.0,1.02)),
                ScenarioAxis('weight_lb',(-10.0,0.0,10.0),mode='delta'),
            ],
            include_baseline=True,
        )
        definition.save(args.output);print(str(args.output));return
    v,e=_vehicle(args)
    if args.action == 'sweep':
        if not args.definition: raise SystemExit('--definition is required for study sweep')
        definition=SimulationStudyDefinition.load(args.definition)
        result=run_scenario_sweep(v,e,definition)
        if args.output: export_study_table(result.table,args.output)
        print(result.table.to_string(index=False));return
    if args.action == 'validate':
        if not args.runs: raise SystemExit('--runs is required for study validate')
        run_cfg=json.loads(Path(args.runs).read_text())
        runs=[]
        for i,item in enumerate(run_cfg):
            env=Environment.from_dict(item.get('environment',e.to_dict()))
            timing=TimingData.from_dict(item.get('timing',{}))
            telemetry=load_telemetry(item['telemetry'],vendor=item.get('vendor',args.vendor)) if item.get('telemetry') else None
            runs.append(FitRun(item.get('name',f'Run {i+1}'),env,timing,telemetry))
        frame=validate_vehicle_against_runs(v,runs,engine=args.engine,smooth_dt_s=args.dt)
        if args.output: export_study_table(frame,args.output)
        print(frame.to_string(index=False));return


def cmd_strip(args):
    run=load_telemetry(args.file,vendor=args.vendor)
    model=None
    if args.vehicle or args.qpro:
        v,e=_vehicle(args)
        model=simulate_legacy_reference(v,e) if args.engine=='reference' else simulate(v,e,options=SolverOptions(dt_s=args.dt))
    else:
        try:
            v,missing=vehicle_from_run(run,require_explicit=False)
            if not missing:
                model=simulate_legacy_reference(v,run.environment) if args.engine=='reference' else simulate(v,run.environment,options=SolverOptions(dt_s=args.dt))
        except Exception:
            model=None
    events=None
    if args.library:
        events=evaluate_event_rules(DefinitionLibrary.load(args.library),run)
    result=analyze_strip(run,model,distance_step_ft=args.step,max_distance_ft=args.max_distance,rule_events=events)
    if args.output:
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);strip_table(result).to_csv(target,index=False)
    print(strip_table(result).head(20).to_string(index=False))
    if model is not None:
        print('\nOfficial timing residuals')
        print(result.timing_residuals.to_string(index=False))
        print('\nSection residuals')
        print(section_residual_table(run,model).to_string(index=False))


def cmd_fit(args):
    v, default_env = _vehicle(args)
    run_cfg = json.loads(Path(args.runs).read_text())
    runs = []
    for i, item in enumerate(run_cfg):
        env = Environment.from_dict(item.get("environment", default_env.to_dict()))
        timing = TimingData.from_dict(item.get("timing", {}))
        telemetry = load_telemetry(item["telemetry"], vendor=item.get("vendor", args.vendor)) if item.get("telemetry") else None
        evidence = FitEvidencePolicy.from_dict(item["evidence"]) if item.get("evidence") else None
        runs.append(FitRun(item.get("name", f"Run {i+1}"), env, timing, telemetry, evidence=evidence, nuisance_terms=item.get("nuisance_terms"), source_run_id=str(item.get("source_run_id") or ""), role=str(item.get("role") or "measurement")))
    fit = fit_vehicle(v, runs, args.unknown, max_nfev=args.max_nfev, fit_dt_s=args.dt, final_dt_s=min(args.dt, .005))
    print(fit.estimates.to_string(index=False))
    print("\n" + fit.message)
    for note in fit.identifiability_notes:
        print(" -", note)
    if fit.reference_residuals is not None and not fit.reference_residuals.empty:
        print("\nQuarter Pro reference verification (largest residuals):")
        cols = [c for c in ["run", "source", "observed", "predicted", "normalized_residual"] if c in fit.reference_residuals.columns]
        print(fit.reference_residuals[cols].head(12).to_string(index=False))
    if args.output:
        Path(args.output).write_text(json.dumps(fit.optimized_vehicle.to_dict(), indent=2))
        print(f"\nOptimized vehicle written to {args.output}")
    if args.residual_output:
        target=Path(args.residual_output); target.parent.mkdir(parents=True,exist_ok=True)
        fit.residuals.to_csv(target,index=False)
        print(f"Residual evidence written to {target}")



def cmd_fit_study(args):
    v, default_env = _vehicle(args)
    definition = FitStudyDefinition.from_dict(json.loads(Path(args.definition).read_text()))
    run_cfg = json.loads(Path(args.runs).read_text())
    runs = []
    for i, item in enumerate(run_cfg):
        env = Environment.from_dict(item.get("environment", default_env.to_dict()))
        timing = TimingData.from_dict(item.get("timing", {}))
        telemetry = load_telemetry(item["telemetry"], vendor=item.get("vendor", args.vendor)) if item.get("telemetry") else None
        evidence = FitEvidencePolicy.from_dict(item["evidence"]) if item.get("evidence") else None
        runs.append(FitRun(
            item.get("name", f"Run {i+1}"), env, timing, telemetry,
            telemetry_weight=float(item.get("telemetry_weight", 1.0)),
            timing_weight=float(item.get("timing_weight", 1.0)),
            evidence=evidence, nuisance_terms=item.get("nuisance_terms"),
            source_run_id=str(item.get("source_run_id") or ""),
            role=str(item.get("role") or "measurement"),
        ))
    fit, package = run_joint_fit_study(v, runs, definition)
    if args.profile:
        package.profiles.update(profile_suite(v,runs,definition,fit,args.profile,points=args.profile_points,span_fraction=args.profile_span,threshold_delta_objective=args.profile_threshold))
    if args.leave_one_run_out:
        package.run_influence=leave_one_run_out_influence(v,runs,definition,fit)
    print(fit.estimates.to_string(index=False))
    print("\n" + fit.message)
    by_run=package.residual_summary.get("by_run",[])
    if by_run:
        print("\nFit quality by Run:")
        q=pd.DataFrame(by_run)
        cols=[c for c in ("run","count","rms_normalized_residual","mean_abs_normalized_residual","objective_fraction") if c in q.columns]
        print(q[cols].to_string(index=False))
    save_fit_study_package(args.package, package)
    print(f"Fit study package written to {args.package}")
    if args.residual_output:
        target = Path(args.residual_output); target.parent.mkdir(parents=True, exist_ok=True)
        fit.residuals.to_csv(target, index=False)
        print(f"Residual evidence written to {target}")
    if package.profiles:
        print("\nProfile-objective scans:")
        for name,prof in package.profiles.items():
            print(f"  {name}: {prof.get('status','')} practical=[{prof.get('practical_low')}, {prof.get('practical_high')}] threshold={prof.get('threshold_delta_objective')}")
    if package.run_influence.get("runs"):
        print("\nLeave-one-Run-out influence:")
        for row in package.run_influence["runs"]:
            frac=row.get("max_bound_span_fraction")
            frac_text="n/a" if frac is None else f"{100*float(frac):.2f}%"
            print(f"  omit {row.get('omitted_run')}: {row.get('status')} dominant={row.get('dominant_parameter')} max-span-shift={frac_text}")
    if args.summary_output:
        target=Path(args.summary_output);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps({"residual_summary":package.residual_summary,"reference_residual_summary":package.reference_residual_summary,"parameter_diagnostics":package.parameter_diagnostics,"profiles":package.profiles,"run_influence":package.run_influence},indent=2),encoding="utf-8")
        print(f"Fit quality summary written to {target}")


def cmd_release(args):
    if args.action == "manifest":
        print(json.dumps(manifest_dict(), indent=2))
        return
    result=audit_release_tree(args.root or Path(__file__).resolve().parents[1])
    print(json.dumps(result,indent=2))
    if args.strict and not result["ok"]:
        raise SystemExit(2)


def cmd_tech_services(args):
    transport=build_http_transport_from_env()
    client=transport.client
    if args.action == "probe":
        user=client.current_user()
        print(json.dumps({
            "ok": True,
            "base_url": client.base_url,
            "audited_source_sha": TECH_SERVICES_AUDITED_SHA,
            "user": user.get("user", {}),
            "authoritative_catalog_bound": transport.capabilities.catalog_pull,
            "authoritative_asset_download_bound": transport.capabilities.asset_fetch,
            "analysis_write_bound": transport.capabilities.analysis_push,
        },indent=2,default=str))
        return
    if args.action == "simulation-runs":
        print(json.dumps(client.simulation_run_history(limit=args.limit),indent=2,default=str))
        return
    if args.action == "events":
        print(json.dumps(client.tech_master_events(season_year=args.season_year, limit=args.limit),indent=2,default=str))
        return
    if args.action == "event":
        if not args.event_id:
            raise SystemExit("tech-services event requires --event-id")
        print(json.dumps(client.tech_master_event(args.event_id),indent=2,default=str))
        return
    if args.action == "entries":
        if not args.event_id:
            raise SystemExit("tech-services entries requires --event-id")
        print(json.dumps(client.tech_master_entries(event_instance_id=args.event_id, class_index=args.class_index or ""),indent=2,default=str))
        return
    if args.action == "entry":
        if not args.entry_id:
            raise SystemExit("tech-services entry requires --entry-id")
        print(json.dumps(client.tech_master_entry(args.entry_id),indent=2,default=str))
        return
    if args.action == "parity-runs":
        if not args.race_lookup:
            raise SystemExit("tech-services parity-runs requires --race-lookup YYYYMMDD")
        print(json.dumps(client.parity_runs(
            race_lookup=args.race_lookup, category=args.category or "", class_index=args.class_index or "",
            driver_name=args.driver_name or "", lane=args.lane or "", round_name=args.round_name or "",
            dq=args.dq or "", include_bad=args.include_bad, limit=args.limit, offset=args.offset,
        ),indent=2,default=str))
        return
    if args.action == "catalog":
        print(json.dumps(transport.pull_catalog_snapshot(cursor=args.cursor or ""),indent=2,default=str))
        return
    raise SystemExit(f"Unknown Tech Services action: {args.action}")


def cmd_enrich(args):
    run=load_telemetry(args.file,vendor=args.vendor)
    if args.qpro or args.vehicle:
        vehicle, env=_vehicle(args)
    else:
        vehicle, missing=vehicle_from_run(run,require_explicit=False)
        if missing:
            raise SystemExit("Run does not contain a usable vehicle model. Missing: "+", ".join(missing))
        env=run.environment
    info=run_rsa_model_enrichment(run,vehicle,environment=env,engine=args.engine,dt_s=args.dt,include_residuals=not args.no_residuals,persist=True)
    frame=model_enrichment_frame(run)
    if args.output:
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);frame.to_csv(target,index=False)
        info["output"]=str(target)
    info["rows"]=len(frame)
    print(json.dumps(info,indent=2))

def main():
    p = argparse.ArgumentParser(description="NHRA Velocity vehicle-performance development CLI")
    sp = p.add_subparsers(dest="cmd", required=True)

    def common(x):
        x.add_argument("--qpro", help="Quarter Pro DAT baseline")
        x.add_argument("--vehicle", help="Vehicle JSON baseline")
        x.add_argument("--environment", help="Environment JSON (with --vehicle)")

    s = sp.add_parser("simulate")
    common(s)
    s.add_argument("--power-scale", type=float, default=1.0)
    s.add_argument("--engine", choices=["reference", "smooth"], default="reference", help="Forward solver; reference is the high-fidelity Quarter Pro source port")
    s.add_argument("--dt", type=float, default=.0025, help="Smooth-engine step size; ignored by reference engine")
    s.add_argument("--trace", help="Optional output trace CSV")
    s.set_defaults(func=cmd_simulate)

    s = sp.add_parser("inspect")
    s.add_argument("files", nargs="+")
    s.add_argument("--vendor", default="Auto")
    s.set_defaults(func=cmd_inspect)

    s = sp.add_parser("qualify", help="Batch-qualify a real telemetry corpus")
    s.add_argument("paths", nargs="+", help="Files and/or folders")
    s.add_argument("--recursive", action="store_true")
    s.add_argument("--json-out")
    s.add_argument("--csv-out")
    s.add_argument("--inventory-json", help="Write an all-file extension inventory, including unrecognized families")
    s.add_argument("--inventory-csv", help="Write an all-file extension inventory, including unrecognized families")
    s.add_argument("--sample-per-format", type=int, default=0, help="Audit a deterministic spread of N files per recognized format (0 = all)")
    s.add_argument("--skip-hash", action="store_true", help="Skip full-file SHA-256 reads for faster large-corpus sweeps")
    s.add_argument("--strict", action="store_true", help="Exit non-zero when any candidate fails")
    s.set_defaults(func=cmd_qualify)

    s = sp.add_parser("racepak-ids", help="Build RacePak channel-id evidence and exact DDF descriptor fingerprints")
    s.add_argument("paths", nargs="+", help="Files and/or folders containing RacePak DDF/RCG/RPK data")
    s.add_argument("--recursive", action="store_true")
    s.add_argument("--rpk-mode", choices=["none", "quick", "all"], default="quick", help="RCGs are always scanned; quick samples RPK folders, all scans every RPK")
    s.add_argument("--rpk-quick-limit", type=int, default=250, help="Maximum representative RPKs in quick mode")
    s.add_argument("--json-out")
    s.add_argument("--csv-out", help="Write channel-id evidence CSV (suggestion-only)")
    s.add_argument("--descriptor-csv-out", help="Write exact DDF descriptor fingerprint/channel CSV")
    s.add_argument("--install", action="store_true", help="Install evidence library; ID history remains suggestion-only")
    s.set_defaults(func=cmd_racepak_ids)

    s = sp.add_parser("selftest", help="Run bundled native import/plot pipeline diagnostics")
    s.add_argument("--examples", help="Override bundled examples directory")
    s.set_defaults(func=cmd_selftest)

    s = sp.add_parser("formats", help="List recognized telemetry format families and decoder status")
    s.add_argument("--json", action="store_true", help="Emit the registry as JSON")
    s.set_defaults(func=cmd_formats)

    s = sp.add_parser("catalog", help="Inspect the local run-centric catalog")
    s.add_argument("action", choices=["stats","runs","payload","cases","case-bundle","case-timeline","case-playback","offline-run","offline-event","import-official","apply-sync"])
    s.add_argument("--catalog", help="Override SQLite catalog path")
    s.add_argument("--search", default="")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--run-id")
    s.add_argument("--case-id")
    s.add_argument("--case-time", type=float, default=0.0, help="Case time in seconds for case-playback")
    s.add_argument("--case-type", default="")
    s.add_argument("--event-id")
    s.add_argument("--file", help="Official event-runs CSV")
    s.add_argument("--event-name", default="")
    s.add_argument("--event-code", default="")
    s.add_argument("--season", type=int)
    s.add_argument("--track-name", default="")
    s.add_argument("--location", default="")
    s.add_argument("--provider", default="")
    s.add_argument("--remote-asset-id")
    s.add_argument("--link-state", choices=["all","linked","unlinked"], default="all")
    s.add_argument("--category", default="")
    s.add_argument("--round-name", default="")
    s.add_argument("--duplicates-only", action="store_true")
    s.add_argument("--include-linked", action="store_true")
    s.add_argument("--status", default="")
    s.add_argument("--note", default="")
    s.add_argument("--reviewed-by", default="")
    s.set_defaults(func=cmd_catalog)

    s = sp.add_parser("analyze", help="Headless analysis-workstation primitives")
    s.add_argument("action", choices=["channels","gate","metrics","psd","loadmap","scatter","histogram","sample"])
    s.add_argument("--file", required=True)
    s.add_argument("--vendor", default="Auto")
    s.add_argument("--query", default="")
    s.add_argument("--expression", default="")
    s.add_argument("--channel", default="")
    s.add_argument("--stat", default="mean")
    s.add_argument("--metric-name", default="")
    s.add_argument("--x-mode", default="Time from Launch", choices=["Time from Launch","Distance from Launch","Normalized Run %"])
    s.add_argument("--max-frequency", type=float, default=500.0)
    s.add_argument("--window", default="hann")
    s.add_argument("--x-channel", default="")
    s.add_argument("--y-channel", default="")
    s.add_argument("--z-channel", default="")
    s.add_argument("--map-stat", default="mean", choices=["mean","median","min","max","std","sum","count"])
    s.add_argument("--bins", type=int, default=30)
    s.add_argument("--regression", action="store_true")
    s.add_argument("--hist-mode", default="samples", choices=["samples","percent_samples","time","percent_time"])
    s.add_argument("--cumulative", action="store_true")
    s.add_argument("--x-value", type=float, default=0.0)
    s.add_argument("--sample-x-mode", default="Time from Launch", choices=["Time from Launch","Distance from Launch","Normalized Run %","Logger Time","Sample Index"])
    s.set_defaults(func=cmd_analyze)

    s = sp.add_parser("library", help="Portable analysis definition libraries and saved reports")
    s.add_argument("action", choices=["starter","inspect","validate","apply","report","events"])
    s.add_argument("--library", help=".nhralib definition library")
    s.add_argument("--file", help="Telemetry file for validate/apply")
    s.add_argument("--files", nargs="*", help="Telemetry files for saved report execution")
    s.add_argument("--vendor", default="Auto")
    s.add_argument("--report", default="")
    s.add_argument("--output", help="Output path (.nhralib/.csv/.json/.xlsx depending on action)")
    s.set_defaults(func=cmd_library)


    s = sp.add_parser("study", help="Repeatable RSA / Quarter Pro simulation studies")
    s.add_argument("action", choices=["template","sweep","validate"])
    common(s)
    s.add_argument("--definition", help=".json simulation-study definition for sweep")
    s.add_argument("--runs", help="JSON run list for observed-vs-simulation validation")
    s.add_argument("--vendor", default="Auto")
    s.add_argument("--engine", choices=["reference","smooth"], default="reference")
    s.add_argument("--dt", type=float, default=.0025)
    s.add_argument("--output", help="Study definition or CSV/JSON/XLSX result")
    s.set_defaults(func=cmd_study)

    s = sp.add_parser("strip", help="NHRA downtrack analysis and RSA model residuals")
    s.add_argument("--file", required=True)
    s.add_argument("--vendor", default="Auto")
    s.add_argument("--vehicle")
    s.add_argument("--environment")
    s.add_argument("--qpro")
    s.add_argument("--engine", choices=["reference","smooth"], default="reference")
    s.add_argument("--dt", type=float, default=.0025)
    s.add_argument("--step", type=float, default=5.0)
    s.add_argument("--max-distance", type=float, default=1320.0)
    s.add_argument("--library", help="Optional .nhralib for rule-event projection")
    s.add_argument("--output", help="Write downtrack table CSV")
    s.set_defaults(func=cmd_strip)

    s = sp.add_parser("fit-study", help="Repeatable multi-Run joint inverse reconstruction")
    common(s)
    s.add_argument("--definition", required=True, help="FitStudyDefinition JSON")
    s.add_argument("--runs", required=True, help="JSON list of measured Runs with optional per-Run evidence/nuisance policies")
    s.add_argument("--vendor", default="Auto")
    s.add_argument("--package", required=True, help="Write portable .nhrafit study package")
    s.add_argument("--residual-output", help="Write fit residual/evidence CSV")
    s.add_argument("--summary-output", help="Write fit-quality/identifiability summary JSON")
    s.add_argument("--profile", nargs="+", help="Profile selected shared fitted parameters after the joint fit")
    s.add_argument("--profile-points", type=int, default=7)
    s.add_argument("--profile-span", type=float, default=.12, help="Half-width as fraction of the parameter's allowed span")
    s.add_argument("--profile-threshold", type=float, default=3.84, help="Practical delta-objective threshold (not an exact posterior interval)")
    s.add_argument("--leave-one-run-out", action="store_true", help="Refit while omitting each Run to measure dataset influence")
    s.set_defaults(func=cmd_fit_study)


    s = sp.add_parser("tech-services", help="Probe the source-verified NHRA Tech Services read API")
    s.add_argument("action", choices=["probe","simulation-runs","events","event","entries","entry","parity-runs","catalog"])
    s.add_argument("--limit", type=int, default=100, help="Read limit (endpoint-specific caps still apply)")
    s.add_argument("--offset", type=int, default=0, help="Parity run result offset")
    s.add_argument("--season-year", type=int, help="Filter Tech Master events by season year")
    s.add_argument("--event-id", type=int, help="Tech Master event instance numeric ID")
    s.add_argument("--entry-id", type=int, help="Tech Master event entry numeric ID")
    s.add_argument("--race-lookup", help="NHRA parity event lookup in YYYYMMDD form")
    s.add_argument("--category", default="", help="Parity category filter")
    s.add_argument("--class-index", default="", help="Tech Master/parity class-index filter")
    s.add_argument("--driver-name", default="", help="Parity driver-name contains filter")
    s.add_argument("--lane", default="", help="Parity lane filter")
    s.add_argument("--round-name", default="", help="Parity round filter")
    s.add_argument("--dq", choices=["exclude","only","include"], default="", help="Parity DQ filter")
    s.add_argument("--include-bad", action="store_true", help="Include parity runs flagged bad/exclude")
    s.add_argument("--cursor", default="", help="Catalog sync cursor when an authoritative route has been explicitly configured")
    s.set_defaults(func=cmd_tech_services)

    s = sp.add_parser("release", help="Product manifest and release-consistency audit")
    s.add_argument("action", choices=["manifest","audit"])
    s.add_argument("--root", help="Project root for audit; defaults to current package root")
    s.add_argument("--strict", action="store_true", help="Exit non-zero when release-audit errors are found")
    s.set_defaults(func=cmd_release)

    s = sp.add_parser("enrich", help="Publish RSA model/residual virtual channels for a measured Run")
    s.add_argument("--file", required=True)
    s.add_argument("--vendor", default="Auto")
    common(s)
    s.add_argument("--engine", choices=["reference","smooth"], default="reference")
    s.add_argument("--dt", type=float, default=.0025)
    s.add_argument("--no-residuals", action="store_true")
    s.add_argument("--output", help="Write model/residual channels on the model Run-time grid to CSV")
    s.set_defaults(func=cmd_enrich)

    s = sp.add_parser("fit")
    common(s)
    s.add_argument("--runs", required=True, help="JSON list containing run environments, timing and optional telemetry paths")
    s.add_argument("--unknown", nargs="+", required=True)
    s.add_argument("--vendor", default="Auto")
    s.add_argument("--max-nfev", type=int, default=100)
    s.add_argument("--dt", type=float, default=.01)
    s.add_argument("--output", help="Write optimized vehicle JSON")
    s.add_argument("--residual-output", help="Write normalized fit evidence/residuals CSV")
    s.set_defaults(func=cmd_fit)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
