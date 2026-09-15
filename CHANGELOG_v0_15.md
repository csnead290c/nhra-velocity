# NHRA Tech Data v0.15 — Archive Intelligence & Sync Core

v0.15 continues the run-centric refactor by treating NHRA's historical evidence repository and the future Tech Services API as durable data sources rather than file-open conveniences. The release is deliberately conservative: repository discovery is metadata-only, official synchronization is authoritative but transport-neutral, and run matching remains advisory.

## Historical repository intelligence

- Added a provider-neutral `remote_assets` catalog table. A Box/object-store/API item can be indexed by provider ID, source path, filename, size, repository hash and modification metadata without copying or modifying the source file.
- Added repository-manifest ingestion with idempotent provider + remote-ID identity.
- Added duplicate discovery by repository hash. This is important because the read-only Box survey showed repeated historical files in multiple archive locations with identical hashes, while other files reuse similar names with different content.
- Added archive/path evidence extraction for season, Q/E/T round, category candidates and car-number hints.
- Driver-name support is evaluated against the complete archive path rather than trusting one assumed folder depth.
- Added metadata-only official-run candidate ranking for remote evidence that has not been downloaded yet.

## Better telemetry → official-run reconciliation

- Existing timing/incremental agreement remains the dominant match evidence.
- Local telemetry now also benefits from immutable source-path/filename evidence stored with its catalog asset.
- Driver, round and category path cues can distinguish old logger files whose embedded timeslip metadata is absent.
- Metadata-only matches are intentionally capped below automatic-certainty territory. Nothing is silently linked.
- Match dialog now shows an explicit evidence-strength label in addition to numerical score and reasoning.

## Tech Services synchronization core

- Added sync contract v3.
- Added provider-neutral remote entity mapping and sync cursors.
- Added `apply_official_snapshot()` for authoritative Event/Run snapshots.
- Remote event/run IDs and revisions are persisted separately from local IDs.
- Applying the same snapshot repeatedly is idempotent.
- Official timing/weather remain authoritative; local telemetry/assets/model snapshots are not discarded when a remote record refreshes.
- Added pending-change bundle generation over the existing offline sync journal.
- Desktop Data menu can apply a local Tech Services JSON snapshot for development/qualification before the authenticated API transport exists.

## Corpus qualification

- Added `python -m runlab.cli qualify ...` for batch qualification of files or directories.
- Reports SHA-256, vendor/decoder, plotability, row/channel counts, native channel counts, canonical mappings, duration/sample-rate information, warnings and decode errors.
- Can emit JSON and CSV reports and run in strict CI mode.
- Bundled native RacePak, MoTeC and MaxxECU fixtures all pass the qualification pipeline.

## Read-only Box survey used in development

The connected NHRA `Race Data` archive was searched read-only. The search returned more than 1,000 `.rpk` items spanning multiple seasons, classes and incident folders. The observed structure contains useful identity evidence such as year/category/driver/event folders and Q/E round tokens in filenames. It also contains duplicate copies identified by repository SHA-1, proving that filename/path identity alone is not sufficient.

The Box connector's raw-binary download action was unavailable during this development session, so v0.15 **does not** claim that the native RacePak decoder has suddenly been qualified against all of those archive files. The new batch qualifier is specifically designed to perform that work once raw read-only retrieval is available.

## Catalog migration

- Local catalog schema is now v3.
- v0.14/v2 catalogs migrate in place; existing events, runs, assets and engineering history are retained.
- New tables: `remote_assets`, `remote_entities`, and `sync_cursors`.

## Validation

- 83 core regression tests pass.
- Python source and desktop entry point compile cleanly.
- Qt runtime/UI interaction still requires the Windows environment with PySide6/pyqtgraph installed.
