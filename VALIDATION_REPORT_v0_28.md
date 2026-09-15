# NHRA Tech Data v0.28 — Validation Report

## Release scope

v0.28 adds **Joint Reconstruction Studies** on top of the v0.27 evidence-aware inverse fitter. Shared vehicle unknowns can be estimated across multiple measured Runs while each Run keeps its own evidence-selection policy, authoritative source Run reference/role, and explicit allowlist of tightly regularized local nuisance corrections.

Portable `.nhrafit` format v2 preserves the complete joint-study definition, base/optimized vehicle, Run policies, parameter estimates, correlation/identifiability diagnostics, raw residual evidence, Quarter Pro reference residuals, and fit-quality decomposition by Run/source/named distance window. `.nhrafit` v1 remains readable.

## Automated regression

- `python -m pytest -q` → **149 passed**.
- `python -m compileall -q runlab desktop.py tests` → pass.

## Native import pipeline

`python -m runlab.cli selftest` → **3/3 PASS**:

- RacePak native demo PASS;
- MoTeC native demo PASS;
- MaxxECU native demo PASS.

The known MoTeC fixture warning remains expected: the header declares 99 channels while the linked list contains six, so the linked-list count is used.

## Corpus qualification

`python -m runlab.cli qualify examples --recursive --strict` → **10/10 PASS**.

## Official NHRA Run import regression

### U.S. Nationals (`event-runs-20260902(1).csv`)

- source rows seen: **134**;
- canonical Runs imported: **123**;
- duplicate partial rows merged: **6**;
- first import: **123 created**;
- identical second import: **0 created / 123 updated**.

### PSM Indianapolis Test (`event-runs-20260908.csv`)

- source rows seen/imported: **25/25**;
- first import: **25 created**;
- identical second import: **0 created / 25 updated**.

## Fresh catalog schema

- schema version: **7**;
- `assets` table present;
- retired `remote_assets` table absent;
- retired `reconciliation_reviews` table absent.

v0.28 does not change the authoritative Tech Services Run/Asset model or add a second evidence authority.

## Joint reconstruction validation

A controlled two-Run recovery was generated from the smooth RSA/Quarter Pro-derived vehicle model with the true shared power scale withheld at **0.9000**.

- Run A trusted only `speed_mph` from **330–660 ft**;
- Run B trusted only `speed_mph` from **660–1320 ft**;
- no RPM, driveshaft RPM, longitudinal G, official timing, or local nuisance corrections were included;
- fitted shared power scale: **0.903569** (absolute error ≈ **0.003569**);
- `.nhrafit` format version: **2**;
- Run A objective fraction: ≈ **78.1%**;
- Run B objective fraction: ≈ **21.9%**;
- named-window quality summaries correctly identify `330-660` and `660-1320`.

This validates that separate Run evidence policies can constrain one shared vehicle parameter set while the release package records where the remaining fit error resides.

## Upstream reference repositories

Two public repositories are mandatory external references and are documented in `REFERENCE_REPOSITORIES.md`:

- `https://github.com/csnead290c/RacingSystemsAnalysis` — physics/source-fidelity reference;
- `https://github.com/csnead290c/nhratechservices` — production identity/auth/data/API reference.

**Pinned commit SHAs are unverified for this release.** During v0.28 validation the connected GitHub tool disabled itself, public GitHub page retrieval failed, and direct `git ls-remote` could not resolve `github.com` from the container. No SHA was guessed and no moving `main` snapshot is claimed.

## Desktop runtime limitation

The validation environment does not provide PySide6/pyqtgraph, so the Qt desktop is source/compile tested but not interactively launched here. Headless analysis, import, inverse fitting, study packaging and CLI paths are exercised directly.

## Release conclusion

The v0.28 source tree is suitable to freeze as the Joint Reconstruction Study milestone. The next RSA-focused increment should deepen **multi-Run identifiability/uncertainty** (sensitivity/profile-likelihood/posterior work) rather than treating the least-squares covariance estimate as sufficient for weakly constrained parameters.

## Exact-ZIP clean-room verification

The packaged ZIP was extracted into a fresh directory and tested independently:

- `python -m pytest -q` → **149 passed**;
- `python -m runlab.cli selftest` → **3/3 PASS**;
- packaged `fit-study` CLI on the controlled two-Run recovery → fitted shared power **0.903569**, `.nhrafit` format **v2**.

No Python bytecode or pytest cache directories are intentionally included in the release archive.
