# NHRA Tech Data v0.26 — Validation Report

## Release scope

v0.26 connects the RSA / Quarter Pro simulation pillar directly to normal telemetry analysis through a drag-specific spatial layer:

- physical distance-from-launch analysis grid;
- measured-vs-modeled speed, engine RPM, driveshaft RPM and longitudinal-G traces;
- model-minus-measured residuals;
- official 60/330/660/1000/1320 ET residuals and 660/1320 trap-speed residuals;
- beam-to-beam timing-error decomposition;
- official beam and portable rule-event projection onto strip distance;
- desktop **NHRA Strip / Model Residuals** display;
- headless `strip` CLI/export path.

The layer is derived only. Catalog schema remains **v7**, Run/Asset authority remains with NHRA Tech Services, and no source timestamps are rewritten.

## Automated tests

- **141/141 tests passed** from the release source tree.
- `python -m compileall -q runlab desktop.py tests` passed.
- New strip-analysis tests cover measured/model channel residuals, official timing-residual sign convention, rule-event projection, missing-speed fail-soft behavior and beam-to-beam section residuals.

## Native / corpus regression

- RacePak / MoTeC / MaxxECU native pipeline self-test: **3/3 PASS**.
- Recursive telemetry corpus qualification: **10/10 PASS**.
- Qualification outputs are under `/mnt/data/v026_validation/` in the development environment.

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

## Strip / RSA validation

- `runlab.strip_analysis` projects measured telemetry and RSA model traces onto the same derived downtrack grid.
- Residual convention is **modeled − measured**.
- Official ET/trap residuals use the simulation timing-system outputs, not instantaneous spatial interpolation.
- Beam-to-beam residuals separate Launch→60, 60→330, 330→660, 660→1000 and 1000→1320 contributions.
- Portable rule events can be projected from Run time to strip distance.
- A bundled RacePak file was processed through the headless `strip` CLI with a Quarter Pro reference vehicle and exported to CSV successfully.
- A controlled generated-run/reference-engine smoke produced 132 finite speed-residual grid points and zero official timing residual for the identical baseline model.
- Launch/rollout coordinate disagreement is intentionally not hidden by time warping. Downtrack spatial residuals and official timing residuals remain separate evidence.

## Authentication / protection status

v0.25's protected-desktop architecture remains intact: frozen builds fail closed by default, authorization scopes gate Tech Services operations, and reusable credentials have no plaintext fallback. The live Tech Services website auth adapter is still intentionally unbound because the repository connector was unavailable during the v0.26 backend-auth recheck. No endpoint/session semantics were guessed.

## Platform note

Interactive Qt/PySide6 GUI execution is unavailable in this Linux validation container. Desktop source compiles successfully; the Strip/Model display uses the same headless `strip_analysis` functions covered by automated tests.

## Exact-package clean-room verification

The release ZIP was extracted into a new directory and exercised independently of the working tree:

- full automated suite: **141/141 PASS**;
- native importer self-test: **3/3 PASS**;
- headless RacePak + Quarter Pro `strip` analysis/export completed successfully;
- package contains no `__pycache__`, `.pyc`, or `.pytest_cache` entries.
