# NHRA Tech Data v0.27 — Validation Report

## Release scope

v0.27 makes the RSA / Quarter Pro inverse solver explicitly evidence-aware rather than treating every available observation as equally trustworthy.

- `FitEvidencePolicy` selects time-domain or physical-distance telemetry fitting.
- `FitDistanceWindow` supports trusted/weighted downtrack regions.
- Speed, engine RPM, driveshaft RPM and longitudinal G can be independently included, excluded and weighted.
- Official ET incrementals and official trap-speed observations can be independently weighted/excluded without replacing the simulator's timing-system semantics.
- Engineering uncertainty scales normalize heterogeneous residuals.
- Inference Center exposes the policy controls.
- ModelSnapshots freeze the policy, selected unknowns and nuisance terms.
- Headless `fit` JSON accepts the same policy and `--residual-output` exports the actual normalized evidence table.

The default policy remains backward compatible with the prior time-domain inverse workflow. Catalog schema remains **v7**.

## Automated tests

- **145/145 tests passed** from the release source tree.
- `python -m compileall -q runlab desktop.py tests` passed.
- New tests cover policy validation/round-trip, distance-window evidence selection, official-timing exclusion, nonlinear withheld-power recovery, and ModelSnapshot fit-context provenance.

## Native / corpus regression

- RacePak / MoTeC / MaxxECU native pipeline self-test: **3/3 PASS**.
- Recursive telemetry corpus qualification: **10/10 PASS**.

## Official NHRA Run import regression

### U.S. Nationals

- Source rows: **134**
- Canonical imported Runs: **123**
- Partial duplicate rows merged: **6**
- Incomplete rows skipped: **5**
- Identical re-import: **0 new Runs**, **123 updated**

### PSM Indianapolis Test

- Source rows: **25**
- Canonical imported Runs: **25**
- Identical re-import: **0 new Runs**, **25 updated**

### Fresh schema

- Schema version: **7**
- `assets`: present
- retired `remote_assets`: absent
- retired `reconciliation_reviews`: absent

## RSA / inverse-fit recovery validation

A controlled measured Run was generated from the Pro Stock reference vehicle with true power deliberately reduced to **0.9000**. That power scale was then withheld from the inverse solver.

The fit policy allowed **only measured speed from 330 through 1320 ft**:

- telemetry domain: `distance`
- trusted window: 330–1320 ft
- speed weight: 1.0
- engine RPM: excluded
- driveshaft RPM: excluded
- longitudinal G: excluded
- official timing/trap observations: absent
- residual samples: 50

The headless CLI recovered a shared `power_scale` of **0.899266**. The residual CSV contained exactly **50** `strip:speed_mph` rows and no hidden timing/RPM/G observations; its x-domain spans exactly 330–1320 ft.

This validates the intended behavior: selected downtrack evidence can identify a model parameter without allowing untrusted launch/other channels to leak into the objective.

## Residual / provenance behavior

- Residual sign convention remains **modeled − measured**.
- Optimization uses normalized residuals based on engineering uncertainty and evidence weight.
- Official timing/trap evidence remains separate from spatial telemetry evidence.
- ModelSnapshots retain the exact evidence policy, selected unknowns and nuisance terms with the model version.
- Raw Run/Asset data are never modified by fit policy choices.

## Authentication / protection status

v0.25's protected-desktop architecture remains intact: frozen builds fail closed by default, authorization scopes gate Tech Services operations, and reusable credentials have no plaintext fallback. The live Tech Services website auth adapter remains intentionally unbound because the GitHub connector became unavailable again during backend-auth inspection. No endpoint/session semantics were guessed.

## Platform note

Interactive Qt/PySide6 GUI execution is unavailable in this Linux validation container. Desktop source compiles successfully; the fit-evidence policy is exercised through the same headless inverse layer used by the Inference Center.

## Release packaging target

The final ZIP is validated after extraction in a clean directory. Exact-package results and SHA-256 are appended before release sealing.

## Exact-package clean-room verification

The release ZIP was extracted into a new directory and exercised independently of the working tree:

- full automated suite: **145/145 PASS**;
- native importer self-test: **3/3 PASS**;
- headless distance-domain withheld-power fit recovered **0.899266** from a true **0.9000** case;
- clean-room residual export contained exactly **50** `strip:speed_mph` observations spanning **330–1320 ft**;
- package contains no `__pycache__`, `.pyc`, or `.pytest_cache` entries.
