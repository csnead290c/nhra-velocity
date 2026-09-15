# NHRA Tech Data v0.23 — Validation Report

## Release scope

v0.23 adds the portable analysis definition/report layer on top of the v0.21/v0.22 workstation primitives. Definitions remain derived engineering state; the catalog schema and Tech Services Run/Asset authority are unchanged.

## Automated tests

- **119/119 tests passed** from the release candidate source tree.
- The new portable-library tests cover canonical-role portability across differently named logger channels, dependency/cycle and missing-input validation, per-Run official segment resolution, library round-trip, and CSV/JSON/XLSX report export.
- `desktop.py` and every `runlab/*.py` module compile successfully.

## Native telemetry pipeline self-test

- RacePak: **PASS** — 160 finite plot points on each default trace.
- MoTeC: **PASS** — 401/201-point mixed-rate default traces; the known 99-declared/6-linked channel warning remains explicit.
- MaxxECU: **PASS** — 250 finite plot points on each default trace.
- Result: **3/3 native demo pipelines passed**.

## Corpus qualification

- `python -m runlab.cli qualify examples --recursive --strict`: **10/10 candidate files passed**.
- Qualification CSV/JSON were regenerated from this source tree.

## Official NHRA Run import regression

### U.S. Nationals source (`event-runs-20260902(1).csv`)

- Source rows: **134**
- Canonical imported Runs: **123**
- Partial duplicate rows merged: **6**
- Drivers / entries created: **19 / 19**
- Identical re-import created **0 new Runs**.

### Indianapolis PSM Test (`event-runs-20260908.csv`)

- Source rows: **25**
- Canonical imported Runs: **25**
- Identical re-import created **0 new Runs**.

## Portable library/report smoke test

A single library was applied to two synthetic Runs with different source names:

- Run A: `Engine RPM` / `G Meter`
- Run B: `RPM` / `Accel`
- Both were addressed through canonical roles `engine_rpm` and `longitudinal_g`.
- Both library validations returned **valid=true**.
- A unit-bearing `RPM_LIMIT` constant and calculated `RPM Margin` channel materialized on both Runs.
- The saved `Peak G` report used each Run's own official 60→330 boundaries (1.0→2.0 s and 1.3→3.2 s respectively).
- Conditional status/severity were generated from the same saved rule.
- CSV and XLSX exports were produced successfully; XLSX size: **5499 bytes**.

## Fresh catalog schema

- Schema version: **7**
- `assets` table present: **True**
- legacy `remote_assets` table present: **False**
- legacy `reconciliation_reviews` table present: **False**
- Fresh SQLite table count: **20**

No schema-v8 migration was introduced. Workbook format v6 embeds the portable `DefinitionLibrary`; standalone `.nhralib` JSON is the deliberate sharing format.

## Desktop/runtime limitation of this validation environment

PySide6/pyqtgraph are not installed in this container. The Qt desktop is therefore source/bytecode compile-tested but not interactively launched here. The report/library calculations used by those displays are exercised headlessly by the automated tests and CLI smoke validation.
