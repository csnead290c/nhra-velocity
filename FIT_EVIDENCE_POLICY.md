# Fit Evidence Policy — v0.27

## Purpose

Inverse modeling should answer **which vehicle/model parameters best explain trusted observations**, not simply minimize every available logger sample. `FitEvidencePolicy` makes the evidence selection and trust explicit and reproducible.

## Evidence families

### Official timing

Official NHRA ET incrementals and trap speeds remain independent constraints. They use the simulator's real timing-system outputs; trap MPH is not replaced by instantaneous speed at the beam. Each field can be weighted or excluded.

Default normalization scales inherited from the inverse solver are approximately:

- 60 ft ET: 0.015 s
- 330 ft ET: 0.020 s
- 660 ft ET: 0.025 s
- 660 ft trap: 0.50 mph
- 1000 ft ET: 0.030 s
- 1320 ft ET: 0.040 s
- 1320 ft trap: 0.60 mph

### Telemetry

Supported fit channels currently include speed, engine RPM, driveshaft RPM and longitudinal G. Default engineering uncertainty scales are:

- speed: 1.5 mph
- engine RPM: 125 rpm
- driveshaft RPM: 80 rpm
- longitudinal G: 0.05 g

A channel weight of zero excludes the channel. Nonzero weights scale its normalized residual contribution.

## Time vs distance domain

`telemetry_domain="time"` preserves the historical time-domain fit. `telemetry_domain="distance"` projects measured and modeled channels onto physical downtrack distance using the v0.26 strip-analysis coordinate system. Distance fitting is useful for questions such as:

- ignore launch/tire shake and fit power from 330–1320 ft;
- isolate a gear or downtrack aero-sensitive region;
- compare how the car performs at the same physical location even when ET differs.

Distance windows carry start/end feet and a weight. Windows do not time-warp the measured Run.

## Residual convention

Residuals are **model minus measured**. Optimization uses normalized residuals based on the configured engineering uncertainty and evidence weight. The exported residual table retains the source and time/distance coordinate so fit quality can be inspected rather than reduced to one scalar objective.

## Provenance

The Inference Center stores the active policy, selected unknowns and nuisance terms in Run analysis metadata. Capturing a ModelSnapshot freezes that fit context with the model version and outputs. Headless fit JSON may carry the same policy and `--residual-output` writes the evidence table.

## Current limitation / next step

The desktop currently applies one policy to the included Main/Reference/Overlay Runs. The next multi-run evolution should support explicit per-Run policies and event/section-relative windows, followed by robust losses and posterior/profile-likelihood uncertainty.
