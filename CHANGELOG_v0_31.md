# NHRA Tech Data v0.31 — Platform Consolidation & RSA Enrichment

## Product/release manifest

- Centralized product, catalog, workbook, library, study and sync-contract versions in `runlab.product_manifest`.
- Added explicit RacingSystemsAnalysis and nhratechservices upstream-reference slots with pinned-SHA environment bindings.
- `.nhrafit` advances to v5 and `.nhrastudy` to v2 so new study artifacts embed those upstream-reference records; older packages remain readable.
- Added `release manifest` and `release audit` CLI workflows.
- Release audit flags documentation/runtime version drift; unreachable upstream SHAs are warnings labeled `unverified`, never guessed.

## RSA enrichment

- Added `runlab.model_enrichment`.
- RSA forward results can publish namespaced `Model.*` channels into a measured Run while preserving raw logger channels and canonical measured roles.
- Added explicit model-minus-measured `Residual.*` channels for speed, engine RPM, driveshaft RPM and longitudinal G when matching measured evidence exists.
- Model/residual channels retain an explicit RSA Run-time grid and provenance/fingerprint.
- Channel Explorer classifies `model` and `residual` source kinds and resolves stable virtual canonical roles such as `model_speed_mph`.
- Added `Model Validation` Quick Graph preset.
- Desktop action **Attach RSA Model / Residual Channels…** supports source-faithful or smooth solver output and persists enough derived-analysis configuration to rebuild on workbook load.
- Added headless `enrich` CLI output.

## Architecture consolidation

- Added canonical `PRODUCT_ARCHITECTURE.md` defining Tech Services, workstation and RSA as equal product pillars.
- Rewrote the long-term roadmap around integration readiness rather than continuing isolated uncertainty features by default.
- Corrected copied documentation version/section drift and the strip-map capability status.
