# NHRA Tech Data v0.18 Validation Report

## Scope

v0.18 validates the AnalysisCase / multi-Run workspace architecture while preserving the v0.17 Tech Services source-of-truth rule: permanent Event → Run → Asset ownership remains authoritative and the desktop does not infer, re-parent, or duplicate server-owned Assets.

## Automated regression suite

- **92 / 92 tests passed** with `python -m pytest -q`.
- Catalog schema is **v6**.
- Explicit migration coverage verifies legacy v0.17 IncidentCase rows are copied into AnalysisCase without deleting the legacy row.
- Existing v0.17 Run-scoped ModelSnapshots migrate without changing their Run ownership.
- AnalysisCase tests cover multi-Run membership, primary/baseline/comparison/reference roles, primary switching, linked Run evidence, standalone content-addressed evidence, case-scoped ModelSnapshots, provider-neutral path-safe bundles, offline manifests, and case-wide asset caching.
- Linking a Run Asset as case evidence automatically includes its owning Run as a case `reference` when needed; Asset ownership itself is unchanged.

## Python compile validation

`python -m compileall -q runlab desktop.py tests` completed successfully.

The container does not include PySide6 or pyqtgraph, so the Qt desktop could not be launched interactively here. `desktop.py` compiles successfully and the non-Qt catalog/service layer is covered by the automated tests.

## Native telemetry pipeline self-test

`python -m runlab.cli selftest`:

- **RacePak: PASS** — validated native time channel, 5 default plotted traces.
- **MoTeC: PASS** — native channel time, 6 linked channels. The sample declares 99 channels in its header but contains 6 in the linked list; the decoder deliberately uses the linked-list count and reports the discrepancy as a warning.
- **MaxxECU: PASS** — validated native time channel, 4 default plotted traces.

**Result: 3 / 3 native demo pipelines passed.**

## Bundled corpus qualification

`python -m runlab.cli qualify examples --recursive`:

- **10 candidates**
- **10 pass**
- **0 need attention**

The set includes native RacePak, MoTeC and MaxxECU samples plus generic/reference CSV data used by the simulation and legacy-comparison work.

Machine-readable qualification outputs are in the validation package as `qualification.json` and `qualification.csv`.

## Official NHRA run import — 2026 U.S. Nationals PSM

Source: `event-runs-20260902(1).csv`

- source rows seen: **134**
- canonical rows imported: **123**
- duplicate/partial rows merged: **6**
- incomplete rows skipped: **5**
- canonical Runs created on first import: **123**
- Drivers created: **19**
- Entries created: **19**
- categories represented: **PRO STOCK MOTORCYCLE**
- rounds represented: **Q1–Q5 and E1–E4**

A second import of the identical authoritative file produced:

- Runs created: **0**
- Runs updated/reconciled: **123**
- new Drivers: **0**
- new Entries: **0**

This confirms the official-import path remains idempotent through the schema-v6 changes.

## Official NHRA run import — Indianapolis PSM test

Source: `event-runs-20260908.csv`

- source rows seen: **25**
- rows imported: **25**
- duplicate rows merged: **0**
- Runs created: **25**
- Drivers created: **6**
- Entries created: **6**
- warnings: **0**

## AnalysisCase architecture validated

v0.18 now supports the intended shared engineering workspace:

```text
Event → Run → Asset        authoritative Tech Services history
          ↑
          │ referenced by
          │
AnalysisCase ↔ Runs        engineering workspace
             ├─ linked Run Assets
             ├─ standalone case evidence
             └─ case-scoped ModelSnapshots
```

One case can therefore represent an incident reconstruction, a multi-run vehicle model, a parity study, development work, aero analysis, or another engineering investigation without changing the canonical Run/Asset records.

## Tech Services network boundary

The real `nhratechservices.com` production transport remains intentionally **unbound** in this package. The GitHub connector was not reliably available during this implementation pass, so v0.18 does not invent PHP routes, authentication behavior, database writes, or Asset-upload semantics that were not verified from the actual backend.

`analysis_case_bundle()` is provider-neutral local serialization only. A future production adapter should translate it into the existing Tech Services incident/session model after the backend implementation and permissions are inspected read-only.

## Overall result

**PASS for the v0.18 development milestone.**

The core data model is now suitable for both the incident workflow and the broader multi-run/inverse-model engineering application. The next development step should focus on synchronized multi-source case analysis and binding the production Tech Services transport only after the website backend contract is verified.
