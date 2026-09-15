# Changelog — v0.27

## Evidence-aware inverse fitting

- Added `FitEvidencePolicy` and weighted `FitDistanceWindow`.
- Added physical-distance telemetry residuals using the shared NHRA strip-analysis coordinate system.
- Added independent timing-field and telemetry-channel weights plus engineering uncertainty scales.
- Added trusted downtrack windows and residual sample limits.
- Default policy preserves prior time-domain inverse behavior.

## Inference Center

- Added Time vs Downtrack Distance fit domain.
- Added trusted distance-window controls.
- Added selectable Speed / Engine RPM / Driveshaft RPM / Longitudinal G evidence.
- Added separate Official ET and Official Trap MPH inclusion controls.
- Persists fit policy, unknowns and nuisance terms for provenance.

## Provenance / CLI

- ModelSnapshots now retain fit-context evidence policy, selected unknowns and nuisance terms.
- Headless `fit` run JSON can include an evidence policy.
- Added `--residual-output` CSV export of normalized fit evidence.

## Persistence

- Catalog schema remains v7.
- Fit policy is derived analysis metadata / ModelSnapshot input provenance, not a second source of Run truth.
