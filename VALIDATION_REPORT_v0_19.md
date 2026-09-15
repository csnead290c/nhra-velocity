# NHRA Tech Data v0.19 Validation Report

## Scope

v0.19 validates the shared AnalysisCase timeline used to synchronize telemetry, video, IDR/audio and comparison Runs while preserving the Tech Services source-of-truth rule: permanent Event → Run → Asset ownership remains authoritative and raw evidence timestamps are never rewritten.

## Automated regression suite

- **98 / 98 tests passed** with `python -m pytest -q`.
- Catalog schema is **v7**.
- v0.18/schema-v6 `AnalysisCaseRun` memberships migrate to identity case alignment (`scale=1`, `offset=0`, method `run_time`).
- Existing v0.17 incident/model migrations remain covered.
- Multi-Run AnalysisCase, case evidence, case-scoped ModelSnapshot and case-wide caching regressions remain green.
- Asset→Run→Case composition and inverse conversion are tested.
- Source-aware markers are tested in case, Run and Asset clock domains.
- Refining an Asset synchronization mapping changes the marker's resolved Case time while preserving its original raw source timestamp.
- Run→Case fitting is explicitly tested to **preserve physical seconds** rather than stretching a Run; disagreement between multiple anchors becomes alignment uncertainty.
- Provider-neutral AnalysisCase bundle v2 includes Run alignment and resolved timeline markers.

## Python compile validation

`python -m compileall -q runlab desktop.py tests` completed successfully.

The validation container does not include PySide6 or pyqtgraph. The Qt desktop therefore could not be launched interactively here, but `desktop.py` compiles and the catalog/timeline/service behavior behind the new **Case Timeline / Sync** dock is covered by automated tests.

## Native telemetry pipeline self-test

`python -m runlab.cli selftest`:

- **RacePak: PASS** — validated native time channel and default trace extraction.
- **MoTeC: PASS** — native channel time. The sample header declares 99 channels while the linked list contains 6; the decoder deliberately uses the linked-list count and emits the existing warning.
- **MaxxECU: PASS** — validated native time channel and default trace extraction.

**Result: 3 / 3 native demo pipelines passed.**

## Bundled corpus qualification

`python -m runlab.cli qualify examples --recursive`:

- **10 candidates**
- **10 pass**
- **0 need attention**

This includes native RacePak, MoTeC and MaxxECU samples plus generic/reference CSV datasets used by simulation and legacy-comparison work.

## Official NHRA run import — 2026 U.S. Nationals PSM

Source: `event-runs-20260902(1).csv`

First import:

- source rows seen: **134**
- canonical rows imported: **123**
- duplicate/partial rows merged: **6**
- incomplete rows skipped: **5**
- Runs created: **123**
- Drivers created: **19**
- Entries created: **19**

Identical re-import:

- Runs created: **0**
- Runs updated/reconciled: **123**
- new Drivers: **0**
- new Entries: **0**

The official import remains idempotent through schema v7.

## Official NHRA run import — Indianapolis PSM test

Source: `event-runs-20260908.csv`

- source rows seen: **25**
- rows imported: **25**
- duplicate rows merged: **0**
- Runs created: **25**
- Drivers created: **6**
- Entries created: **6**
- warnings: **0**

## Timeline architecture validated

The persistent synchronization chain is now:

```text
Asset clock -- affine TimeMapping --> Run time -- rigid offset --> Analysis Case time
```

Asset→Run can correct source clock rate drift. Run→Case does not time-warp canonical physical seconds; it applies only an offset. Multiple Run/Case anchors quantify alignment disagreement as uncertainty.

`AnalysisCaseMarker` stores its original source time domain and timestamp. Resolved Case time is calculated dynamically, which is important for incident analysis because synchronization can be refined without silently replacing the evidence coordinate used to identify an impact/frame/sample.

## Desktop / CLI surfaces

The source includes the new **Case Timeline / Sync** desktop dock with:

- Run→Case alignment anchor entry;
- Asset→Run synchronization anchor entry;
- visible mapping equations/method/uncertainty;
- source-aware case marker creation and display.

Read-only/headless inspection is also available through:

- `catalog cases`
- `catalog case-bundle --case-id ...`
- `catalog case-timeline --case-id ...`

## Tech Services network boundary

The real `nhratechservices.com` production transport remains intentionally **unbound**. The GitHub connector was not reliably available during this implementation pass, so v0.19 does not invent PHP routes, authentication behavior, database writes, or Asset-upload semantics that were not verified from the actual backend.

The case bundle is provider-neutral local serialization only. The future production adapter should translate it into the existing Tech Services incident/session model after the backend implementation and permissions are inspected read-only.

## Overall result

**PASS for the v0.19 development milestone.**

The application now has the data and time-coordinate foundation needed for the next layer: synchronized video/audio/IDR playback, a shared movable Case-time cursor, and multi-source event navigation on top of the same mappings.
