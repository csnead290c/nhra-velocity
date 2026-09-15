# NHRA Tech Data v0.31 — Validation Report

## Release scope

v0.31 is a **platform consolidation + RSA model-enrichment** milestone. It centralizes product/format/upstream provenance and makes RSA model output available as ordinary namespaced virtual channels inside a measured telemetry session.

Key additions:

- canonical `runlab.product_manifest` for product/catalog/workbook/library/study/sync-contract versions;
- explicit upstream-reference records for `RacingSystemsAnalysis` and `nhratechservices`;
- `release manifest` and `release audit` CLI workflows;
- `.nhrafit` format v5 and `.nhrastudy` format v2 embed upstream-reference provenance while older package versions remain readable;
- `runlab.model_enrichment` publishes `Model.*` and model-minus-measured `Residual.*` virtual channels without replacing raw measured channels or official timing;
- desktop **Attach RSA Model / Residual Channels…** workflow and Model Validation Quick Graph;
- persisted derived-analysis settings can rebuild RSA virtual channels when a workbook is reopened;
- canonical `PRODUCT_ARCHITECTURE.md` and rewritten long-term roadmap align Tech Services + workstation + RSA as equal product pillars.

## Automated regression

- `python -m pytest -q` → **164 passed**.
- `python -m compileall -q runlab desktop.py tests` → pass.

## Native import / corpus

- RacePak / MoTeC / MaxxECU native self-test → **3/3 PASS**.
- strict bundled corpus qualification → **10/10 PASS**.

## Official NHRA Run import regression

### U.S. Nationals

- source rows seen: **134**;
- canonical Runs imported: **123**;
- duplicate partial rows merged: **6**;
- identical re-import: **0 new / 123 updated**.

### PSM Indianapolis Test

- source rows/imported: **25/25**;
- identical re-import: **0 new / 25 updated**.

## Fresh catalog

- schema version **7**;
- `assets` present;
- retired `remote_assets` absent;
- retired `reconciliation_reviews` absent.

## Release-consistency audit

`python -m runlab.cli release audit --root .`:

- **0 errors**;
- **2 warnings**, both intentional upstream-provenance warnings;
- `RacingSystemsAnalysis` SHA: **unverified for this release**;
- `nhratechservices` SHA: **unverified for this release**.

The GitHub connector disabled itself during the audit and no moving `main` revision was guessed.

Current portable/persistent versions from `PRODUCT_MANIFEST.json`:

- catalog schema: **7**;
- workbook: **7**;
- analysis library: **2**;
- simulation-study package: **2**;
- fit-study package: **5**;
- Tech Services sync contract: **4**.

## RSA enrichment smoke test

`python -m runlab.cli enrich --file examples/demo_run_1.csv --qpro examples/qpro_reference/PROSTOCK.dat --engine smooth ...`

produced:

- **17** `Model.*` virtual channels;
- **4** `Residual.*` channels;
- **2784** model-time rows;
- explicit model fingerprint SHA-256;
- model grid sample rate ≈ **400 Hz**.

Measured canonical channel roles and raw rectangular telemetry columns remain unchanged. Residual sign is explicitly **model minus measured**. Regression testing also verifies that when the measured Run and model come from the identical simulation, the speed residual collapses to numerical/interpolation tolerance rather than showing a false rollout/ET-clock offset.

## Desktop runtime limitation

PySide6/pyqtgraph are unavailable in this validation container. Desktop source compiles, but the new Qt action/Quick Graph/workbook-rebuild workflow is not interactively exercised here. A real Windows Qt launch/smoke pipeline remains a high-priority pre-1.0 item.

## Release conclusion

v0.31 is suitable to freeze as the architecture-consolidation / RSA-Enrich milestone. The next development cycle should prioritize real Tech Services binding when the repository is reachable, Windows UI runtime validation, and daily-workstation usability/performance rather than automatically continuing deeper inverse-fit statistics.

## Exact-ZIP clean-room verification

The release ZIP was extracted into a fresh directory and validated against the packaged source:

- `python -m pytest -q` → **164 passed**;
- native self-test → **3/3 PASS**;
- packaged `release audit` → **0 errors / 2 explicit upstream-SHA warnings**;
- packaged RSA enrichment smoke → **17 Model.* + 4 Residual.* channels / 2784 rows**;
- ZIP contains **181 files** and **0** `__pycache__`, `.pytest_cache`, `.pyc` or `.pyo` entries.
