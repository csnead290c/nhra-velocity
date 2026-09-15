from __future__ import annotations

"""Reproducible derived-analysis channels attached to telemetry sessions."""

from typing import Optional
import numpy as np

from .models import TelemetryRun, VehicleConfig, Environment, ChannelSeries
from .reconstruction import reconstruct_delivered_power, ReconstructionResult
from .knowledge import set_vehicle_input


def attach_delivered_power_reconstruction(
    run: TelemetryRun,
    vehicle: VehicleConfig,
    env: Optional[Environment]=None,
    *,
    smoothing_s: float=0.12,
    rpm_bin: float=250.0,
    min_throttle_pct: float=80.0,
    persist: bool=True,
    run_label: Optional[str]=None,
) -> ReconstructionResult:
    """Run delivered-power reconstruction and attach clearly derived channels.

    Existing canonical logger/measured power and torque mappings are preserved.
    The derivation recipe is stored separately so projects can rebuild these
    traces rather than serializing potentially huge derived arrays.
    """
    result=reconstruct_delivered_power(run,vehicle,env or run.environment,smoothing_s=smoothing_s,rpm_bin=rpm_bin,min_throttle_pct=min_throttle_pct)
    samples=result.samples;t=samples['time_s'].to_numpy(float)
    additions=[
        ('Reconstructed Engine HP','apparent_engine_hp','hp','power_hp'),
        ('Reconstructed Engine Torque','apparent_engine_torque_lbft','lbft','torque_lbft'),
        ('Reconstructed Accel G','accel_g_speed','g','longitudinal_g'),
    ]
    for display,col,unit,canonical in additions:
        vals=samples[col].to_numpy(float)
        run.native_channels[display]=ChannelSeries(display,t.copy(),vals,unit,None,3,True,{'provenance':'inferred by delivered-power reconstruction'})
        run.units[display]=unit
        run.metadata.setdefault('unit_provenance',{})[display]='inferred by delivered-power reconstruction'
        # A measured/logger canonical source remains authoritative. Derived
        # channels become canonical only when no safe source currently exists.
        if canonical and canonical not in run.channel_map:
            run.channel_map[canonical]=display
            run.metadata.setdefault('original_channel_map',{})[canonical]=display
    dyn=result.dyno_curve
    if not dyn.empty:
        rpm=[float(x) for x in dyn['rpm']];hp=[float(x) for x in dyn['hp_median']]
        run.metadata['inferred_dyno_curve']={'rpm':rpm,'hp':hp,'p10':[float(x) for x in dyn['hp_p10']],'p90':[float(x) for x in dyn['hp_p90']]}
        label=run_label or run.name
        set_vehicle_input(run,'dyno_rpm',rpm,'rpm','inferred',method='delivered-power reconstruction',runs=[label])
        set_vehicle_input(run,'dyno_hp',hp,'hp','inferred',method='delivered-power reconstruction',runs=[label])
    run.metadata['power_reconstruction_diagnostics']=dict(result.diagnostics)
    if persist:
        run.metadata.setdefault('derived_analyses',{})['delivered_power']={
            'enabled':True,'smoothing_s':float(smoothing_s),'rpm_bin':float(rpm_bin),'min_throttle_pct':float(min_throttle_pct),
            'channels':[x[0] for x in additions],
        }
    return result
