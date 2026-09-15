# RSA / Quarter Pro Simulation Studies — v0.25

## Product role

Simulation is a core pillar of NHRA Tech Data, not an accessory to telemetry viewing. The target workflow remains bidirectional:

**Measured Runs → reconstruct/fit the most likely vehicle → change setup/power/aero/etc. → predict new Runs → compare predictions back against measured Runs.**

The existing smooth inverse-fitting engine and the source-faithful Quarter Pro reference engine remain separate intentionally. v0.25 adds a study layer above them so simulation becomes repeatable engineering work rather than a single throw-away dialog.

## `runlab.simulation_study`

A `SimulationStudyDefinition` contains:

- study name/notes;
- solver (`reference` or `smooth`);
- one or more `ScenarioAxis` definitions;
- maximum case count;
- smooth-engine timestep when applicable.

Each axis can be:

- `absolute` — use the supplied values directly;
- `delta` — add the supplied value to the baseline;
- `scale` — multiply the baseline by the supplied value.

Supported study parameters include normal `VehicleConfig` scalar fields plus study knobs such as:

- power scale;
- CdA / ClA;
- weight;
- traction index;
- final drive and efficiency;
- tire diameter/growth;
- drivetrain efficiency scale;
- global shift-RPM offset;
- individual gear ratios and shift RPMs.

## Study results

Every forward case reports the available official-style outputs:

- 60 ft;
- 330 ft;
- 660 ft and trap MPH;
- 1000 ft;
- 1320 ft and trap MPH;
- deltas versus the unchanged baseline;
- selected solver diagnostics such as traction-limited steps and static-front percentage.

A selected case can be materialized as a normal generated `TelemetryRun`, so it immediately participates in the same waveform, scatter, KPI, gate, event-rule, comparison and report infrastructure as measured data.

## Reproducible `.nhrastudy` package

`SimulationStudyPackage` preserves:

- exact study definition;
- complete baseline `VehicleConfig`, including dyno curve;
- exact environment;
- source Run ID/name when available;
- software/model version;
- UTC creation time;
- complete result rows.

This is deliberately more rigorous than merely saving a few changed values. A later engineer must be able to determine exactly what model and assumptions produced a result.

## Inverse and validation connection

`fit_simulation_study()` is the study-level entry point to the existing multi-run inverse solver. `validate_vehicle_against_runs()` runs a candidate vehicle against each Run's own environment/timing and returns observed-vs-predicted residuals.

Long term the Simulation Study Center should be AnalysisCase-aware so a case can own:

- the measured primary/baseline/comparison Runs;
- the fitted vehicle ModelSnapshot;
- one or more `.nhrastudy` forward sweeps;
- residual/KPI reports;
- approved conclusions.

That is the bridge from RSA/Quarter Pro source knowledge to an auditable NHRA engineering digital twin.
