# NHRA Tech Data v0.24 — Validation Report

## Release scope

v0.24 extends the portable analysis library with historical rule-generated events and alarm-state evaluation. The rule layer is derived engineering state and reuses the existing safe canonical-role condition engine; catalog schema and Tech Services authority remain unchanged.

## Automated tests

- **123/123 tests passed** from the release candidate source tree.
- New rule tests cover canonical-role portability, minimum-duration filtering, rising/falling edges, cursor alarm state, and missing-channel validation.
- `desktop.py` and all `runlab/*.py` modules compile successfully.

## Native/corpus regression

- Native RacePak/MoTeC/MaxxECU pipeline self-test: **3/3 PASS**.
- Recursive telemetry qualification: **10/10 candidate files PASS**.

## Rule-engine smoke on bundled RacePak data

- A saved rule referenced canonical `engine_rpm`, not the RacePak source spelling.
- Condition: `engine_rpm > 7500`, trigger `interval`, minimum duration 0.05 s, severity `warning`.
- Historical event count: **1**.
- First event: **2.9000 s → 7.5000 s** (duration **4.6000 s**).
- Headless `library events` exported the same rule results to CSV.

## Official NHRA Run import regression

### U.S. Nationals
- Source rows: **134**
- Canonical imported Runs: **123**
- Partial duplicates merged: **6**
- Identical re-import created **0 new Runs**.

### Indianapolis PSM Test
- Source rows: **25**
- Canonical imported Runs: **25**
- Identical re-import created **0 new Runs**.

## Fresh catalog schema

- Schema version: **7**
- `assets` present: **True**
- legacy `remote_assets` present: **False**
- legacy `reconciliation_reviews` present: **False**

No schema-v8 migration was introduced. Workbook format remains v6. `.nhralib` format advances to library version 2 and remains backward-readable for v1 libraries.

## Desktop/runtime limitation

PySide6/pyqtgraph are not installed in this validation container. Qt UI code is compile-tested, while event extraction/alarm-state logic is exercised headlessly through tests and CLI. Interactive desktop rendering remains to be checked on a Windows/PySide6 workstation.
