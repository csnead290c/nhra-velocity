# Changelog — v0.30

## Run Influence

- Added leave-one-Run-out refitting for Joint Reconstruction Studies.
- Added shared-parameter movement and engineering-bound-span influence metrics.
- Added low/moderate/high influence classification and dominant-parameter reporting.
- Correctly remaps retained Run-specific nuisance warm starts/overrides after a Run is omitted.
- Added `fit-study --leave-one-run-out` CLI support.
- Added Inference Center **Run Influence (Leave-One-Out)…** workflow.
- `.nhrafit` advances to v4 and stores Run influence; v1–v3 remain readable.

## Compatibility

- Catalog schema remains v7.
- Tech Services remains the authoritative Run/Asset system.
- RacingSystemsAnalysis and nhratechservices remain the two mandatory upstream reference repositories defined in `REFERENCE_REPOSITORIES.md`.
