# NHRA Tech Data v0.29 — Validation Report

## Release scope

v0.29 adds **Practical Identifiability** to Joint Reconstruction Studies. A selected shared vehicle parameter can be forced across a bounded grid while all remaining permitted shared and Run-specific nuisance freedom is re-optimized. This exposes whether the supplied Runs genuinely constrain that parameter or whether correlated parameters can compensate.

`.nhrafit` advances to format v3 to persist completed profile scans. v1/v2 packages remain readable.

## Automated regression

- `python -m pytest -q` → **152 passed**.
- `python -m compileall -q runlab desktop.py tests` → pass.

## Native import / telemetry corpus

- native self-test: **3/3 PASS** (RacePak, MoTeC, MaxxECU);
- strict bundled-corpus qualification: **10/10 PASS**.

## Official NHRA Run import regression

### U.S. Nationals

- source rows seen: **134**;
- canonical Runs imported: **123**;
- duplicate partial rows merged: **6**;
- identical second import: **0 new / 123 updated**.

### PSM Indianapolis Test

- source rows/imported: **25/25**;
- identical second import: **0 new / 25 updated**.

## Fresh catalog

- schema version: **7**;
- `assets` present;
- retired `remote_assets` absent;
- retired `reconciliation_reviews` absent.

## Joint-fit + profile-objective validation

The controlled v0.28 two-Run test was repeated. True shared power was withheld at **0.9000**. Run A trusted only speed from 330–660 ft; Run B trusted only speed from 660–1320 ft.

Joint fit:

- fitted shared power scale: **0.903569**;
- absolute error from truth: ≈ **0.003569**.

Power profile (`5` points, scan span fraction `0.05`):

- ~0.848569 → Δobjective ≈ **316.28**;
- ~0.876069 → Δobjective ≈ **100.11**;
- **0.903569 → Δobjective 0.00**;
- ~0.931069 → Δobjective ≈ **90.80**;
- ~0.958569 → Δobjective ≈ **287.17**.

The minimum occurs at the unconstrained joint-fit optimum and the scan is classified **`bounded_in_scan`**.

The default Δobjective threshold (3.84) is an engineering/practical-identifiability reference only. Because the inverse solver uses normalized engineering residuals with robust `soft_l1` loss, v0.29 does **not** label the resulting scan interval an exact posterior or exact 95% statistical confidence interval.

## Persistence / UI / CLI

- `.nhrafit` format **v3** stores completed profile scans;
- v1 and v2 packages remain backward-readable;
- `fit-study --profile ...` profiles selected shared parameters headlessly;
- Inference Center adds **Profile Shared Parameter…** after a completed joint fit;
- profile results remain derived analysis and never alter authoritative Tech Services Run/Asset ownership.

## External reference repositories

Mandatory upstream references are documented in `REFERENCE_REPOSITORIES.md`:

- `https://github.com/csnead290c/RacingSystemsAnalysis` — physics/source-fidelity reference;
- `https://github.com/csnead290c/nhratechservices` — production identity/auth/data/API reference.

**Pinned commit SHAs are unverified for this release.** The connected GitHub integration disabled itself during the audit, public page retrieval failed, and direct Git could not resolve `github.com` from the container. No commit SHA or `main` state was guessed.

## Desktop runtime limitation

PySide6/pyqtgraph are not available in this validation container. Qt code is source/compile tested; the profile engine, joint-fit packaging and CLI are exercised headlessly.

## Release conclusion

v0.29 is suitable to freeze as the Practical Identifiability milestone. The next uncertainty increment should add **Run influence / leave-one-Run-out analysis**, followed by adaptive/two-parameter profiles and Monte Carlo/posterior uncertainty where justified.

## Exact-ZIP clean-room verification

The release ZIP was extracted into a fresh directory and validated independently in split commands after a combined shell command exceeded its runtime budget:

- `python -m pytest -q` → **152 passed**;
- native self-test → **3/3 PASS**;
- packaged `fit-study --profile power_scale` → `.nhrafit` **v3**, shared power **0.903569**, profile status **`bounded_in_scan`**, profile minimum at the same fitted optimum;
- packaged archive contains **0** `__pycache__`, `.pytest_cache`, `.pyc` or `.pyo` entries.

The earlier combined-command timeout was a validation-harness runtime limit, not a test or application failure.
