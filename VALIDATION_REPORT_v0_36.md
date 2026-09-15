# NHRA Tech Data v0.36 — Validation Report

## Release scope

v0.36 is the import-registry and Named Compare Set milestone. It reconstructs the documented v0.35 ingestion hardening on the verified v0.33 source base, then advances the workstation with persistent comparison-session state and real Indy-data regression. No RSA/Quarter Pro physics equations or Tech Services server authority rules were changed.

## Automated regression

- `python -m pytest -q` → **183 passed**.
- New v0.36 focused tests → **8/8 passed**.
- `python -m compileall -q .` → **PASS**.
- `python -m runlab.cli selftest` → **3/3 PASS** (RacePak, MoTeC, MaxxECU bundled pipelines).

## Real Indianapolis PSM data qualification

Five representative files from the Project's `20260908 Indianapolis Test.zip` were run through the normal qualification/viewer contract and all **5/5 passed**:

| File | Decoder | Rows | Numeric channels | Duration | Result |
| --- | --- | ---: | ---: | ---: | --- |
| `S1_#2626_20260908_114627.ld` | MoTeC | 12,549 | 180 | 62.74 s | PASS |
| `S1_#11093_20260908_144541.ld` | MoTeC | 13,720 | 198 | 68.595 s | PASS |
| `Indy 2026 AngT1data_596.MaxxECU-Zip-log` | MaxxECU | 8,742 | 103 | 87.41 s | PASS |
| `Indy 2026 Matt Q5data_472.MaxxECU-Zip-log` | MaxxECU | 8,462 | 97 | 84.61 s | PASS |
| `S1_#2626_20260908_143834.csv` | Delimited | 12,052 | 175 | 60.255 s | PASS |

The real MaxxECU packages exposed a useful regression issue during validation: package files were still decodable but had fallen out of folder-recognition coverage, and `Time after launch` could be selected as the logger timebase. v0.36 fixes both. For packaged MaxxECU logs, `fileinfo*.LogMetaData` `LogRate` is now the physical logger-clock authority; the raw event timer remains untouched as a normal source channel.

The two real MoTeC files each explicitly warn that one structurally valid `Engine.Synchronisation.Position` channel uses an unsupported encoding and is skipped; the remainder of the log remains plotable. This matches the intended fail-soft-per-channel / fail-closed-file behavior. Machine-readable results are in `validation/INDY_REAL_LOG_QUALIFICATION_v0_36.json`.

A recursive qualification attempt across the entire 82.8 MB Indy archive exceeded the validation harness's 120-second command budget before completion. This was not counted as either a pass or failure; representative current-format files were therefore qualified explicitly as listed above.

## Import registry / qualification behavior

The registry now distinguishes `direct`, `interchange`, `container`, `bridge`, and `pending` states. Recognized proprietary binary files are rejected with family-specific guidance before they can fall through to a generic text parser. `qualify` records the registry key/status plus the actual selected decoder and probe reason.

Current direct/interchange coverage in this milestone includes RacePak/DataLink, MoTeC i2/M1, MaxxECU including packaged logs, Racelogic VBOX VBO, TunerStudio/MegaSquirt text logs, Excel telemetry tables, generic delimited files, and telemetry ZIP containers. MDF/AiM and other recognized proprietary families remain deliberately non-qualified until the appropriate library/vendor bridge and representative real files are available.

## Named Compare Sets / persistence

The new headless Compare Set tests verify reference stepping, per-display Run selection, global and per-display alignment, serialization round-trip, and Compare Set library active-set round-trip. Desktop integration saves current Main/Reference/Overlay membership, applies named sets without attaching or matching files, and rotates the Reference among loaded comparison Runs while Main remains fixed.

Workbook format advances from **v7 → v8** for Named Compare Set persistence. Missing `compare_sets` is treated as an empty library, so existing workbooks remain readable.

## Release provenance

Read-only GitHub verification on 2026-09-15 pinned:

- RacingSystemsAnalysis: `1556ac70684908038fe47a9fe54e2f506cc4e71c`
- nhratechservices: `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`

With those SHAs supplied, `python -m runlab.cli release audit --strict` → **PASS, 0 errors / 0 warnings**.

## Desktop/runtime limitation

PySide6 and pyqtgraph are not installed in this Linux validation container. The desktop source compiles, but the new Compare Set menu/dialog interaction and Windows Qt packaging still require a real target-machine smoke test. Headless compare-state logic and all non-GUI importer paths are regression-tested here.

## Release conclusion

v0.36 is suitable to freeze as the scalable-import / Named Compare Set development milestone. The next highest-value work remains MDF4 and AiM adapter qualification, broader real-file corpus coverage (FuelTech/Holley/HP Tuners/VBOX VBB), reusable vehicle/setup/channel templates, lazy/background loading for large logs, and Windows packaged-application interaction tests.
