# NHRA Tech Data v0.22 — Validation Report

Validation date: 2026-09-13

## Release objective

v0.22 is the second **Analysis Workstation Parity** increment. It adds richer everyday analysis displays while keeping the Event → Run → Asset authority model, immutable evidence rules and schema-v7 catalog unchanged.

Primary additions:

- Gauge / Status display: Numeric, Bar, Dial and Bit modes;
- advanced XY scatter with optional Z-channel colouring;
- saved-gate filtering for scatter and histogram displays;
- linear regression with slope/intercept/correlation/R²;
- sample-count/percent and physical dwell-time histogram modes;
- cumulative histogram modes;
- headless scatter/regression, histogram/distribution and cursor-sampling primitives;
- CLI actions `analyze scatter`, `analyze histogram`, and `analyze sample`;
- workbook persistence for the new display settings.

## Automated tests

```text
115 passed in 10.87s
```

Four new headless display-analysis tests cover:

- paired X/Y/Z alignment and linear regression;
- gated multi-channel analysis without hidden mixed-clock interpolation;
- cursor sampling and percent-of-samples distributions;
- physical dwell-time weighting and cumulative percent-time distributions.

## Display-analysis smoke checks

### Advanced scatter

Bundled `demo_run_1.csv`, engine RPM vs speed with longitudinal-G colour and linear regression:

```text
points: 380
aligned: true
slope: 0.0721219306477095
intercept: -488.49453745049976
R²: 0.5432484172620662
correlation: 0.7370538767702571
Z range: 0.0208038927 to 2.7246484195
```

### Time-weighted histogram

Engine RPM, 20 bins, percent-of-time mode:

```text
source_points: 380
used_points: 380
total_time_s: 7.58
```

The time total is the actual first-to-last recorded time span. The final sample is not assigned an invented extra dwell interval.

### Cursor sample

Engine RPM at Run time 3.0 s:

```text
value: 8953.4500425 rpm
in_range: true
```

## Native telemetry pipeline

`python -m runlab.cli selftest`:

- RacePak: **PASS**;
- MoTeC: **PASS**;
- MaxxECU: **PASS**.

Result: **3/3 native demo pipelines passed**.

## Corpus qualification

`python -m runlab.cli qualify examples --recursive --strict`:

- 10 candidate files;
- **10 pass**;
- 0 require attention.

## Official NHRA Run import regressions

### 2026 U.S. Nationals

First import:

- 134 rows seen;
- 123 canonical Runs imported/created;
- 6 duplicate partial rows merged;
- 19 drivers and 19 entries created;
- 5 incomplete rows skipped with explicit warnings.

Identical re-import:

- 0 new Runs;
- 123 existing Runs updated;
- 0 new drivers/entries.

### PSM Indianapolis Test

First import:

- 25 rows seen;
- **25 Runs imported/created**;
- 0 duplicates;
- 6 drivers and 6 entries created;
- no warnings.

Identical re-import:

- 0 new Runs;
- 25 existing Runs updated.

## Schema / authority check

Fresh catalog:

```text
schema_version 7
assets True
analysis_cases True
remote_assets False
reconciliation_reviews False
```

No repository-discovery or file-to-run reconciliation authority was reintroduced.

## Compilation / GUI environment

`python -m compileall -q runlab desktop.py`: **PASS**.

The validation container does not have PySide6 or pyqtgraph installed, so Qt widgets are syntax/compile tested here rather than interactively launched. Their analysis logic is exercised independently by tests and CLI commands.

## Release conclusion

v0.22 is suitable as the next development milestone. It materially improves ATLAS/i2-class display depth while continuing to keep source clocks, permanent evidence ownership and canonical synchronization explicit and auditable.

## Packaged clean-room verification

A release archive was extracted into a new directory and tested from the extracted package:

```text
115 passed in 11.06s
Result: 3/3 native demo pipelines passed.
```

The final release is cleaned of `__pycache__`, `.pyc` and `.pytest_cache` entries before packaging.
