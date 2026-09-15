# v0.13 — run-centric platform foundation

## Major architectural change

- introduced a local SQLite **Run Catalog**; canonical Run records are now separate from the workbook/layout file
- `.nhratech` is now described in the UI/documentation as a **Workbook**
- workbook format v5 stores catalog run/asset/session references while retaining a compatibility shadow for older development workspaces

## Local catalog

- Event, Driver, Vehicle, Entry and Run records
- generic evidence Assets for telemetry/video/audio/IDR/photo/document/other
- TelemetrySession records and channel summaries
- TimeMapping records (`Run Time = Asset Time × scale + offset`)
- EngineeringValue history
- versioned ModelSnapshot records
- Annotation and IncidentCase tables
- pending synchronization journal
- remote ID/sync-state fields ready for a future Tech Services API

## Offline evidence

- SHA-256 content-addressed managed object library
- external vs managed storage state
- hash verification after ingest
- duplicate logger imports resolve by content hash to the existing local run/asset
- per-run and per-event **Keep Offline** workflows implemented in the core catalog (not only the Qt UI)

## Desktop

- new **Run Browser / Local Catalog** dock
- new **Assets / Evidence** dock
- create local NHRA runs before server sync exists
- attach video/audio/IDR/photos/documents now, even before their analysis modules are implemented
- link the active telemetry session to a selected canonical run
- edit per-asset Run-Time offset/clock-scale synchronization metadata
- create Incident Cases from the Run Browser
- capture vehicle Model Snapshots from the active run
- Engineering History table for queryable values such as `model.peak_hp`

## Historical engineering groundwork

- model snapshots preserve application/model version, inputs, outputs and quality metadata
- peak HP and other scalar model inputs can be written as append-only engineering observations
- first descriptive season-to-season trend engine added (does not yet perform comparability/causal normalization)

## Future sync contract

- API-safe run/asset payload generator excludes machine-local paths
- event offline manifest
- CLI catalog inspection (`python -m runlab.cli catalog ...`)

## Testing

- regression coverage expanded for catalog schema, hash deduplication, managed evidence verification, run/event offline caching, telemetry relinking, time drift mapping, model history, sync payloads, incident cases and season trends
- 72 automated regression tests passing in the release candidate
