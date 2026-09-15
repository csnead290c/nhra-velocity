# NHRA Strip / Model Residual Analysis — v0.26

## Purpose

Bring the RSA/Quarter Pro simulation directly into normal telemetry analysis instead of treating simulation as a separate mode.

## Coordinates

Measured telemetry remains authoritative in its Run clock. The strip layer derives **distance from launch** from the mapped speed/time channels; it does not rewrite timestamps. Simulation traces are sampled onto the same downtrack grid. Launch/rollout uncertainties are exposed rather than hidden with a time warp.

## Residual convention

All residuals are **modeled − measured**. Positive ET residual means the model is slower. Positive speed residual means the model predicts more speed.

## Official timing vs spatial telemetry

Official 60/330/660/1000/1320 ET and 660/1320 trap-speed residuals are calculated from the simulator's timing-system output and the Run's official timing. They are not replaced by interpolation of an instantaneous telemetry channel. This preserves the Quarter Pro timing-system details, including trap windows.

## Section decomposition

The total ET error is decomposed into Launch→60, 60→330, 330→660, 660→1000 and 1000→1320 intervals. This helps isolate launch/traction, gear/shift/power-curve, and aero/downtrack model discrepancies.

## Events

Official beams are always strip events when timing exists. Portable event/alarm rules may also be projected from Run time onto downtrack distance, so limiter activity, tire-shake rules, chute events or sensor warnings can appear on the same spatial view.

## Next

The next model-development step should let inverse fitting consume selected strip sections and channel residuals with explicit weighting/uncertainty, while retaining official timing as independent evidence.
