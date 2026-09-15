# NHRA Tech Data — v0.9 development changelog

## Product / architecture

- Removed previous product branding and browser-app distribution paths.
- Working application identity is now **NHRA Tech Data**.
- New project extension: `.nhratech`.
- Added run-centric engineering knowledge/provenance model.
- Added Engineering Knowledge display.

## Desktop analysis tools

- Reconstruct Delivered Power is now wired into the desktop application.
- Inference Center now performs observability preflight and multi-run nonlinear fitting.
- Inferred values are written back with provenance/confidence rather than masquerading as measured setup.
- Create Compare Run now creates/export/loads a synthetic telemetry session for normal overlay analysis.

## Viewer workflow

- snap-to-sample cursors
- previous-view zoom history
- waveform settings persist these behaviors
- cleaned internal drag/drop MIME identity

## Calculated channels

Added restricted engineering functions:

- `abs()`
- `sqrt()`
- `clip()`
- `smooth()`
- `derivative()`
- `integral()`

Derivative/integral functions require a valid increasing mapped timebase. Arbitrary function calls remain prohibited.

## Generated sessions

Synthetic compare runs now include generated engine HP/torque in addition to time, distance, speed, acceleration, engine/driveshaft/wheel RPM, gear, tire slip and traction state.

## Testing

Core suite increased from 26 to **32 tests**. New coverage includes run-knowledge provenance, rebuilding a vehicle model from run knowledge, first-class generated compare sessions, physically bounded scenario power and safe time-aware math functions.

## Late v0.9 workstation hardening

- Added persistent waveform Trace Properties: line color/width, compatible preferred display unit, and manual/automatic Y range.
- Compare traces are converted into the active trace display unit without mutating raw source data.
- Fixed generated scenario power telemetry so `Engine Power` and `Engine Torque` honor the same scenario power multiplier used by the forward physics.
- Added a regression test requiring generated power telemetry to scale with the scenario input.
- Added waveform keyboard sample stepping: Left/Right = one native sample; Ctrl+Left/Right = ten.
- Core suite: 32/32 passing.
