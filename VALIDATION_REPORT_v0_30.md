# NHRA Tech Data v0.30 — Validation Report

## Release scope

v0.30 adds **Run Influence** analysis to Joint Reconstruction Studies. Each measured Run can be omitted in turn, the remaining dataset is fully refit, and movement of the shared vehicle parameters is quantified. This reveals whether a joint reconstruction is broadly supported or disproportionately driven by one pass.

`.nhrafit` advances to format v4 to persist Run-influence results. v1–v3 packages remain readable.

## Automated regression

- `python -m pytest -q` → **155 passed**.
- `python -m compileall -q runlab desktop.py tests` → pass.

## Native import / corpus

- RacePak / MoTeC / MaxxECU native self-test → **3/3 PASS**.
- strict bundled corpus qualification → **10/10 PASS**.

## Official NHRA Run import regression

### U.S. Nationals
- source rows seen: **134**;
- canonical Runs: **123**;
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

## Controlled Run-influence validation

Two synthetic measured Runs intentionally conflict:

- Low-power Run generated at power scale **0.80**;
- High-power Run generated at power scale **1.10**;
- both use only physical-distance `speed_mph` evidence from **330–1320 ft**;
- no Run-specific nuisance corrections are permitted.

Full two-Run joint fit:

- shared power estimate: **0.942066**.

Leave-one-Run-out results:

- omit **Low power** → fitted power **1.104062**, shift **+0.161996**, engineering-bound-span shift ≈ **14.73%**, classification **`high_influence`**;
- omit **High power** → fitted power **0.803180**, shift **−0.138886**, engineering-bound-span shift ≈ **12.63%**, classification **`high_influence`**.

The shifts move in the expected opposite directions, demonstrating that the diagnostic identifies dependence on conflicting individual passes rather than simply repeating the full-data fit.

## Persistence / UI / CLI

- `.nhrafit` format **v4** stores `run_influence`;
- v1–v3 packages remain backward-readable;
- CLI: `fit-study --leave-one-run-out`;
- Inference Center: **Run Influence (Leave-One-Out)…**;
- retained Run-specific nuisance warm starts/overrides are index-remapped after omission;
- Run influence is derived analysis only and does not alter authoritative Tech Services Runs/Assets.

## External reference repositories

Two upstream repositories remain mandatory references under `REFERENCE_REPOSITORIES.md`:

- `https://github.com/csnead290c/RacingSystemsAnalysis` — physics/source-fidelity reference;
- `https://github.com/csnead290c/nhratechservices` — production identity/auth/data/API reference.

Pinned SHAs remain **unverified for this release** because the GitHub connector disabled itself, public GitHub retrieval failed, and the container could not resolve `github.com`. No SHA or moving branch state was guessed.

## Desktop runtime limitation

PySide6/pyqtgraph are unavailable in the validation container. Qt source compiles; the underlying influence engine and CLI are exercised directly.

## Release conclusion

v0.30 is suitable to freeze as the Run Influence milestone. The next uncertainty work should add omitted-Run predictive scoring, adaptive/two-parameter profile contours, and Monte Carlo/posterior uncertainty where the underlying probability assumptions are defensible.

## Exact-ZIP clean-room verification

The release ZIP was extracted into a fresh directory and validated in split commands after a combined validation shell exceeded its runtime budget:

- `python -m pytest -q` → **155 passed**;
- native self-test → **3/3 PASS**;
- packaged `fit-study --leave-one-run-out` → `.nhrafit` **v4**;
- packaged influence result reproduced **high_influence** for both controlled Runs, with maximum bound-span shifts ≈ **14.73%** and **12.63%**;
- archive contains **0** Python/pytest cache entries.

The combined-command timeout was a validation-harness runtime limit, not an application/test failure.
