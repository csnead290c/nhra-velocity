# Changelog — v0.28

## Joint Reconstruction Studies

- Added `runlab.fit_study` and portable `.nhrafit` format v2.
- Shared vehicle unknowns can be fitted across several measured Runs.
- Each Run retains independent evidence selection, Tech Services source Run identity/role and an explicit nuisance-term allowlist.
- Added per-Run local power, traction and rollout correction controls in Inference Center; nuisance terms remain regularized.
- Added headless `fit-study` CLI workflow.
- Added fit-quality decomposition by Run, evidence source and named downtrack window.
- Added parameter diagnostics including strongest parameter correlation and identifiability.
- Inference Results now shows per-Run normalized error and objective share.
- `.nhrafit` v1 remains readable.

## Provenance

- Added `REFERENCE_REPOSITORIES.md` defining RacingSystemsAnalysis as the physics/source-fidelity reference and nhratechservices as the identity/auth/data-integration reference.
- Release reports should record pinned upstream SHAs whenever those public repositories are reachable and explicitly mark them unverified otherwise.

## Compatibility

- Catalog schema remains v7.
- Workbook format remains unchanged.
- Raw Run/Asset authority remains in NHRA Tech Services.
