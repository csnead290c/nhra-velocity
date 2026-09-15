# NHRA Tech Data v0.14 — Official Run Bridge

## Purpose

v0.14 is the first working bridge between the run-centric offline catalog and authoritative NHRA event data. It deliberately focuses on identity, authority and reconciliation before adding more visually exciting media features.

## Added

- Official NHRA event-run CSV importer for the current `event-runs-YYYYMMDD.csv` interchange format.
- Idempotent Event/Driver/Entry/Run upsert with deterministic official run keys.
- NHRA category-code normalization (including PSM → PRO STOCK MOTORCYCLE).
- SHA-256 source provenance for the official export and source-row tracking for each run.
- Duplicate/partial export-row coalescing: richer official timing is preserved and all contributing source rows are retained in provenance.
- Run schema v2 with `timing_provenance`, `weather_provenance` and `official_source_json`.
- In-place v0.13 → v0.14 SQLite migration preserving existing catalog data.
- Conservative telemetry-to-official run matcher using available incremental timing, ET/MPH, category and timestamp evidence.
- Run Browser actions for **Import Official CSV…** and **Match Active…**.
- Read-only **Canonical Run Record** dock showing run identity, official timing, weather and source/provenance independently from the currently open logger.
- CLI support: `catalog import-official` and `catalog match`.
- Sync contract v2 to carry the expanded canonical run record.

## Authority / safety changes

- Official timing is now explicitly authoritative. Telemetry or default metadata cannot silently overwrite it when a logger is opened, linked or synchronized into the local catalog.
- Default environment values are no longer persisted as if they were measured conditions unless the session has explicit environment provenance.
- Linking an active telemetry session to an official run reloads official timing (and official weather when available) into the active engineering knowledge state.
- Candidate matching never auto-links a run. The engineer reviews ranked evidence and makes the association.

## Validation

- Core suite: **77/77 tests passing**.
- Real interchange validation: the supplied `event-runs-20260908.csv` imports all **25** official rows cleanly, creating 25 canonical runs, 6 drivers and 6 entries. A second import updates the same 25 runs rather than duplicating them.
- Qt desktop code is syntax/bytecode checked in the packaging environment. Interactive Windows validation is still required because PySide6/pyqtgraph are not installed in the build container.

## Next

The next architectural step is a real Tech Services API adapter around the now-stable run/sync contract: event discovery, remote IDs, incremental pull/push, conflict rules and object-storage manifests. Once that identity/sync path is solid, universal media synchronization can build on permanent Run/Asset identities rather than temporary project-file assumptions.
