# Changelog — v0.29

## Practical Identifiability

- Added `runlab.fit_uncertainty`.
- Added profile-objective scans for shared Joint Reconstruction parameters.
- Each scan forces one parameter across a bounded grid while re-optimizing all other permitted fit freedom.
- Added practical bounded / one-sided / flat-in-scan classification.
- Added configurable scan points, span and Δobjective threshold.
- Added `fit-study --profile ...` CLI support.
- Added Inference Center **Profile Shared Parameter…** workflow.
- `.nhrafit` advances to format v3 and stores completed profile scans; v1/v2 remain readable.

## Compatibility

- Catalog schema remains v7.
- Raw Tech Services Run/Asset authority is unchanged.
- The two external reference repositories remain governed by `REFERENCE_REPOSITORIES.md`.
