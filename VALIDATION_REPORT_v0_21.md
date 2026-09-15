# NHRA Tech Data v0.21 — Validation Report

Validation date: 2026-09-13

## Release objective

v0.21 starts the **Analysis Workstation Parity** program identified by the ATLAS/i2/WinDarab/RaceStudio benchmark audit. The release intentionally adds shared Qt-independent workstation primitives before deeper specialized incident calculations.

Primary additions:

- richer Channel Explorer metadata and user aliases;
- safe reusable data gates/conditions;
- official drag segments and reusable KPI metrics;
- multi-Run segment/KPI reporting using each Run's own official timing boundaries;
- Welch PSD and spectrogram analysis;
- 2-D load/heat/occupancy maps;
- display-only Normalized Run % axis;
- CLI/headless analysis entry points for channels, gates, metrics, PSD and load maps.

The authoritative Event → Run → Asset architecture is unchanged. Catalog schema remains **v7**.

## Automated tests

Final source-tree command:

```text
python -m pytest -q
```

Result:

```text
111 passed in 10.20s
```

The new workstation tests cover:

- alias and channel-role discovery;
- safe boolean gate evaluation;
- official drag segment generation;
- per-Run official timing boundaries in comparison KPI reports;
- normalized Run-progress axis behavior;
- PSD and spectrogram frequency recovery;
- binned mean/count load maps.

## Workstation smoke validation

A headless smoke test against `examples/demo_run_1.csv` and the bundled RacePak native demo produced:

```text
run demo_run_1
channels 7
gate_true 216 of 380
normalized_axis_minmax -2.432432 100.0 points 380
metric_rows 6 segments Launch → 1320 ft | Launch → 60 ft | 60 ft → 330 ft | 330 ft → 660 ft | 660 ft → 1000 ft | 1000 ft → 1320 ft
heatmap_shape (20, 20) used 380
psd_bins 33 sample_rate_hz 20.0
PASS
```

Negative normalized progress is expected for pre-launch samples; the finish is 100%. This is a view coordinate only and does not alter physical Run time.

Additional CLI smoke commands succeeded for:

- `analyze channels`;
- `analyze metrics`;
- `analyze psd`;
- `analyze loadmap`.

## Native telemetry pipeline

`python -m runlab.cli selftest`:

- RacePak: **PASS** — 160 finite plot points on each default trace;
- MoTeC: **PASS** — 401/201 finite points depending on channel; known header/list-count warning retained;
- MaxxECU: **PASS** — 250 finite plot points on each default trace.

Result: **3/3 native demo pipelines passed**.

## Corpus qualification

`python -m runlab.cli qualify examples --recursive --strict`:

- 10 candidate files;
- **10 pass**;
- 0 require attention.

This includes bundled generic telemetry, native RacePak/MoTeC/MaxxECU examples, and Quarter Pro/reference CSV artifacts.

## Official NHRA Run import regressions

### 2026 U.S. Nationals

Source: `/mnt/data/event-runs-20260902(1).csv`

First import:

- 134 rows seen;
- 123 canonical Runs imported/created;
- 6 duplicate partial rows merged;
- 19 drivers created;
- 19 entries created;
- 5 rows skipped because required Time/Driver/Class fields were blank.

Identical second import:

- 0 new Runs;
- 123 existing Runs updated;
- 0 new drivers/entries.

Catalog stats after validation: 1 event, **123 Runs**, schema v7.

### PSM Indianapolis Test

Source: `/mnt/data/event-runs-20260908.csv`

First import:

- 25 rows seen;
- **25 Runs imported/created**;
- 0 duplicates merged;
- 6 drivers created;
- 6 entries created;
- no warnings.

Identical second import:

- 0 new Runs;
- 25 existing Runs updated.

## Fresh catalog/schema check

A new catalog initializes at **schema v7**. Current tables include the authoritative `assets` model plus AnalysisCase/Run/evidence/marker structures.

The retired v0.16 discovery/reconciliation tables are absent in a fresh database:

```text
remote_assets_table False
reconciliation_reviews_table False
```

v0.21 adds analysis definitions and displays without introducing a competing evidence authority.

## Compilation/runtime environment

`python -m compileall -q runlab desktop.py`: **PASS**.

This Linux validation container does not contain the desktop GUI dependencies:

```text
PySide6: unavailable
pyqtgraph: unavailable
```

Therefore the new Qt displays are syntax/compile tested here but were not interactively launched in this container. Headless analysis code is directly exercised by tests and CLI smoke validation.

## Product benchmark baseline

`WORKSTATION_PARITY_REQUIREMENTS.md` records the capability baseline reviewed against current official documentation for McLaren Applied ATLAS, MoTeC i2/i2 Pro, Bosch WinDarab, AiM RaceStudio and the broader professional motorsport-analysis category. It distinguishes Implemented, Foundation, Planned and intentionally Out-of-scope capabilities and is intended to guide subsequent workstation releases.

## Release conclusion

v0.21 is suitable as the next development milestone. It begins workstation-parity work without changing the trusted Run/Asset/Case authority model or physical synchronization model.

## Packaged clean-room verification

The release tree was cleaned of `__pycache__`, `.pyc` and `.pytest_cache` entries, zipped, extracted into a new directory, and validated from the extracted package rather than the working tree.

Clean-room results:

```text
111 passed in 10.88s
3/3 native demo pipelines passed
compileall PASS
```

This verifies that the release archive contains the files required by the automated/headless workflows.
