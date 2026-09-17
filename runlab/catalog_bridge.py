from __future__ import annotations

"""Adapters between the legacy in-memory TelemetryRun and the local run catalog."""

from pathlib import Path
from typing import Any, Dict, Tuple
import math
import numpy as np

from .branding import PRODUCT_VERSION
from .catalog import LocalCatalog
from .knowledge import vehicle_inputs
from .models import TelemetryRun, Environment, TimingData
from .telemetry import detect_drag_pass_window


def channel_summary(run: TelemetryRun) -> Dict[str, Any]:
    rates=[]
    for ch in run.native_channels.values():
        if ch.sample_rate_hz and math.isfinite(float(ch.sample_rate_hz)):
            rates.append(float(ch.sample_rate_hz))
    return {
        "vendor": run.vendor,
        "channels": len({*map(str, run.data.columns), *map(str, run.native_channels.keys())}),
        "native_channels": len(run.native_channels),
        "sample_rate_min_hz": min(rates) if rates else None,
        "sample_rate_max_hz": max(rates) if rates else None,
        "canonical_roles": sorted(run.channel_map.keys()),
    }


def apply_catalog_run_authority(catalog: LocalCatalog, run_id: str, run: TelemetryRun) -> dict[str, Any]:
    """Hydrate a decoded logger session with authoritative catalog context.

    The catalog record wins for official timing/weather. Raw logger channels and
    native metadata remain untouched. The complete official values are also
    retained in metadata so fields that are not represented by ``TimingData``
    (RT, DQ, MOV, etc.) remain available to downstream displays/reporting.
    """
    record=catalog.get_run(run_id)
    if record is None:
        raise KeyError(f"Unknown catalog run {run_id}")
    timing=record.get("timing") or {}
    weather=record.get("weather") or {}
    if timing:
        run.timing=TimingData.from_dict(timing)
    if weather:
        run.environment=Environment.from_dict(weather)
    run.metadata["catalog_run_id"]=run_id
    run.metadata["catalog_run_key"]=str(record.get("run_key") or "")
    run.metadata["catalog_event_id"]=str(record.get("event_id") or "")
    run.metadata["catalog_event_name"]=str(record.get("event_name") or "")
    run.metadata["catalog_driver_id"]=str(record.get("driver_id") or "")
    run.metadata["catalog_driver_name"]=str(record.get("driver_name") or "")
    run.metadata["catalog_vehicle_id"]=str(record.get("vehicle_id") or "")
    run.metadata["catalog_vehicle_name"]=str(record.get("vehicle_name") or "")
    run.metadata["catalog_entry_id"]=str(record.get("entry_id") or "")
    official_category=str(record.get("category") or "")
    run.metadata["catalog_category"]=official_category
    run.metadata["official_category"]=official_category
    if official_category and not str(run.metadata.get("category") or "").strip():
        run.metadata["category"]=official_category
    run.metadata["catalog_car_number"]=str(record.get("car_number") or "")
    run.metadata["catalog_round"]=str(record.get("round") or "")
    run.metadata["catalog_run_datetime"]=str(record.get("run_datetime") or "")
    run.metadata["official_timing"]=dict(timing)
    run.metadata["official_weather"]=dict(weather)
    run.metadata["official_timing_provenance"]=str(record.get("timing_provenance") or "unknown")
    run.metadata["official_weather_provenance"]=str(record.get("weather_provenance") or "unknown")
    run.metadata["official_source"]=dict(record.get("source") or {})
    return record


def register_opened_telemetry(
    catalog: LocalCatalog,
    path: str,
    run: TelemetryRun,
    *,
    run_id: str | None = None,
    managed: bool = False,
    local_attachment: bool = False,
) -> tuple[str, str, str]:
    try:
        window=detect_drag_pass_window(run)
        launch=float(window.launch_time_s)
        # Logger/native time maps to canonical run time where launch is zero.
        offset=-launch if math.isfinite(launch) else 0.0
        method=f"auto launch detection ({window.confidence})"
    except Exception:
        offset=0.0; method="provisional identity"
    metadata={
        "application_version": PRODUCT_VERSION,
        "import_decoder": run.metadata.get("import_decoder", ""),
        "import_probe_reason": run.metadata.get("import_probe_reason", ""),
        "data_warnings": list(run.metadata.get("data_warnings", []) or []),
        "source_name": run.name,
    }
    if local_attachment:
        if not run_id:
            raise ValueError("local_attachment requires an explicit canonical run_id")
        metadata.update({
            "attachment_mode":"local_working_copy",
            "canonical_run_id":str(run_id),
            "local_persistence":True,
            "persistence_scope":"velocity_local_catalog",
            "server_persistence":False,
            "authority_note":"Locally managed run data associated by the user with an authoritative NHRA Tech Services Run; persists in Velocity local storage and is not uploaded to Tech Services.",
        })
    run_id,asset_id,session_id=catalog.register_telemetry_file(
        path, run_id=run_id, vendor=run.vendor, display_name=run.name, channel_summary=channel_summary(run),
        metadata=metadata,
        managed=managed, time_offset_s=offset, time_method=method,
    )
    # Logger/session metadata may enrich a local record, but an existing official
    # timing/weather value is protected by set_run_conditions().
    sync_run_state(catalog,run_id,run)
    apply_catalog_run_authority(catalog,run_id,run)
    run.metadata["catalog_asset_id"]=asset_id
    run.metadata["catalog_telemetry_session_id"]=session_id
    return run_id,asset_id,session_id


def sync_run_state(catalog: LocalCatalog, run_id: str, run: TelemetryRun) -> None:
    # Logger/session state may contain useful timing or weather, but it must not
    # silently replace authoritative official values already attached to the
    # canonical NHRA Run.  Only persist timing when at least one timing value is
    # actually populated, and only persist environment when the session carries
    # explicit provenance (native metadata or a user edit).
    timing = run.timing.to_dict()
    timing_has_value = any(v is not None for v in timing.values())
    timing_sources = run.metadata.get("timing_provenance", {})
    environment_sources = run.metadata.get("environment_provenance", {})
    timing_provenance = "user" if isinstance(timing_sources, dict) and any(str(v).lower() == "user" for v in timing_sources.values()) else "telemetry"
    weather_provenance = "user" if isinstance(environment_sources, dict) and any(str(v).lower() == "user" for v in environment_sources.values()) else "telemetry"
    catalog.set_run_conditions(
        run_id,
        timing=timing if timing_has_value else None,
        weather=run.environment.to_dict() if environment_sources else None,
        notes=str(run.metadata.get("user_notes", "")),
        timing_provenance=timing_provenance if timing_has_value else None,
        weather_provenance=weather_provenance if environment_sources else None,
        overwrite_official=False,
    )
    # Engineering knowledge is append-only in the catalog. Avoid spraying
    # duplicates merely because a waveform refreshed; callers use snapshots for
    # durable historical engineering values.


def capture_model_snapshot(catalog: LocalCatalog, run_id: str, run: TelemetryRun, *, name: str = "Vehicle model snapshot") -> str:
    inputs=dict(vehicle_inputs(run))
    knowledge=dict(run.metadata.get("parameter_knowledge",{}))
    outputs: Dict[str, Any]={}
    quality: Dict[str, Any]={"application_version":PRODUCT_VERSION}
    dyno=run.metadata.get("inferred_dyno_curve")
    if isinstance(dyno,dict):
        hp=np.asarray(dyno.get("hp",[]),dtype=float)
        rpm=np.asarray(dyno.get("rpm",[]),dtype=float)
        if hp.size and np.isfinite(hp).any():
            outputs["peak_hp"]=float(np.nanmax(hp))
            if rpm.size==hp.size and np.isfinite(rpm).any():outputs["peak_hp_rpm"]=float(rpm[int(np.nanargmax(hp))])
        outputs["inferred_dyno_curve"]=dyno
    # Explicit dyno inputs are equally useful for historical tracking.
    try:
        hp=np.asarray(inputs.get("dyno_hp",[]),dtype=float);rpm=np.asarray(inputs.get("dyno_rpm",[]),dtype=float)
        if hp.size and np.isfinite(hp).any() and "peak_hp" not in outputs:
            outputs["peak_hp"]=float(np.nanmax(hp))
            if rpm.size==hp.size:outputs["peak_hp_rpm"]=float(rpm[int(np.nanargmax(hp))])
    except Exception:pass
    fit_context={
        "evidence_policy": run.metadata.get("last_fit_evidence_policy"),
        "unknowns": list(run.metadata.get("last_fit_unknowns",[]) or []),
        "nuisance_terms": list(run.metadata.get("last_fit_nuisance_terms",[]) or []),
        "run_policies": list(run.metadata.get("last_fit_run_policies",[]) or []),
    }
    if run.metadata.get("last_inference_notes"):
        quality["inference_notes"]=list(run.metadata.get("last_inference_notes") or [])
    snapshot_id=catalog.create_model_snapshot(run_id,name=name,model_version=PRODUCT_VERSION,inputs={"vehicle_inputs":inputs,"parameter_knowledge":knowledge,"fit_context":fit_context},outputs=outputs,quality=quality)
    # Persist high-value scalar quantities as queryable historical observations.
    for key,value in outputs.items():
        if isinstance(value,(int,float)) and math.isfinite(float(value)):
            unit="hp" if key=="peak_hp" else ("rpm" if key.endswith("rpm") else "")
            catalog.set_engineering_value(run_id,f"model.{key}",float(value),unit=unit,provenance="inferred" if "inferred_dyno_curve" in outputs else "model",method=f"model snapshot {PRODUCT_VERSION}",model_snapshot_id=snapshot_id)
    for key,value in inputs.items():
        if isinstance(value,(int,float)) and math.isfinite(float(value)):
            rec=knowledge.get(f'vehicle.{key}',{}) if isinstance(knowledge,dict) else {}
            provenance=str(rec.get('provenance') or 'snapshot') if isinstance(rec,dict) else 'snapshot'
            method=str(rec.get('method') or f'model snapshot {PRODUCT_VERSION}') if isinstance(rec,dict) else f'model snapshot {PRODUCT_VERSION}'
            confidence=rec.get('confidence') if isinstance(rec,dict) else None
            catalog.set_engineering_value(run_id,f"vehicle.{key}",float(value),unit=str(rec.get('unit') or '') if isinstance(rec,dict) else '',provenance=provenance,confidence=confidence,method=method,model_snapshot_id=snapshot_id)
    return snapshot_id
