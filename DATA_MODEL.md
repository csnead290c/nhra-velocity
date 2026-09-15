# NHRA Tech Data — canonical data model v0.23

## Event

Authoritative NHRA race/test event mirrored from Tech Services. Carries local ID plus server `remote_id`, season, event code, dates, track and location.

## Driver / Vehicle / Entry

Supporting identities associated with a Run through an event Entry. Server identities may be mirrored when provided.

## Run

The permanent engineering record for one pass/test/incident timeline. A production Run originates in NHRA Tech Services and carries a server `remote_id`.

Key data include category, car number, driver/vehicle/entry, round/session, lane, timestamp, official timing, official weather and source provenance.

**A file never determines Run identity.** The server's Run→Asset relationship determines which files belong to the Run.

## Asset

A permanent server file attached to one Run. Types can include telemetry, video, audio, IDR, photo, document and other.

Important fields:

- local `id` — stable mirror/workbook reference;
- `run_id` — authoritative mirrored Run relationship;
- `remote_id` — Tech Services Asset ID;
- `revision` — server revision/version token when available;
- `source_kind` — `tech_services` for production assets; `local_dev` only for development/scratch catalog tests;
- `asset_type`;
- `filename` — descriptive only, never identity;
- `sha256` — authoritative content hash when supplied by server;
- `size_bytes`, MIME type, vendor;
- `remote_uri` — optional stable opaque server object reference if the real API uses one; temporary/signed download URLs are never persisted;
- `uploaded_at`;
- local cache path/storage state;
- metadata JSON.

A Tech Services Asset cannot be re-parented to another Run by the desktop.

## Local asset cache

The local object cache stores immutable downloaded bytes by SHA-256. It is expendable. Clearing the cache does not change the Run or Asset on Tech Services.

## TelemetrySession

Decoded telemetry metadata associated with a telemetry Asset: vendor, display name and channel summary. Raw numeric arrays remain outside SQLite and are regenerated from cached source bytes when needed.

## TimeMapping

Maps an Asset-local clock into canonical Run Time with scale + offset, method, confidence, uncertainty and optional synchronization anchors.

## EngineeringValue

Append-only scalar/JSON engineering observation tied to a Run. Includes unit, provenance, confidence/bounds, method and optional ModelSnapshot ID.

Examples: `vehicle.weight_lb`, `model.peak_hp`, future `incident.delta_v_resultant_mps`.

## ModelSnapshot

Versioned vehicle-model state. A snapshot may be owned by one Run, by one AnalysisCase, or by both. Run-scoped snapshots preserve the existing single-pass workflow. Case-scoped snapshots support future multi-run inverse fitting where shared parameters cannot honestly be attributed to only one pass. Reprocessing under a newer model creates another snapshot rather than rewriting history.

## AnalysisCase

Persistent engineering workspace above one or more canonical Runs. Fields include case type, title, status, summary, optional primary Run, optional future remote identity/revision, sync state and timestamps.

Incident analysis is an AnalysisCase with `case_type='incident'`; other examples include `performance`, `parity`, `development`, `aero`, and `engineering`.

## AnalysisCaseRun

Many-to-many membership between AnalysisCase and Run. Each relationship carries an explicit role (`primary`, `baseline`, `comparison`, `reference`, or future workflow-specific role), order and notes. In v0.21 it also owns the Run→Case alignment: a physical-time-preserving offset plus method, confidence, uncertainty and synchronization anchors. A scale field is retained in storage for compatibility/future migration, but v0.21 requires it to remain 1.0. The same canonical Run may participate in multiple cases with different case-time offsets.

## AnalysisCaseEvidence

Case-specific evidence reference. It can either point to an existing authoritative Run Asset or represent standalone local case evidence such as inspection photos/reports that do not belong to one race pass. Linked Run Assets remain owned by their Run; the case only references them. Standalone evidence retains SHA-256, size, MIME type, storage/provenance and metadata.

## AnalysisCaseMarker

A source-aware case event/interval such as launch, shift, impact, chute deployment, failure, or analyst note. The marker retains its original time domain (`case`, `run`, or `asset`) and source timestamp. Its displayed Case time is resolved through the current mappings, so synchronization refinements do not orphan or silently freeze derived timestamps.

## Annotation

Legacy/general Run-time marker or interval, optionally associated with one Asset. AnalysisCaseMarker is the preferred structure for cross-source/cross-Run incident and engineering work.

## Legacy IncidentCase

The v0.17 `incident_cases` table is retained only for migration/rollback safety. New incident work uses AnalysisCase. Existing rows are copied forward to `analysis_cases` during schema v7 migration without deleting the legacy source rows.

## RemoteEntity / SyncCursor

Synchronization bookkeeping. `RemoteEntity` maps Tech Services Event/Run/Asset IDs and revisions to local mirror IDs. `SyncCursor` tracks catalog/change-feed continuation.

These are not remote-file discovery records and do not perform matching.

## Workbook

`.nhratech` stores the engineer's view state: open sessions, compare roles, worksheets, displays, cursor state, layout and analysis settings. It references canonical Run/Asset IDs where applicable but does not own source data. Future workbook revisions may remember the active AnalysisCase, but the case itself lives in the catalog rather than in the view file.


## Synchronized review state (derived, not persisted)

The v0.21 shared review cursor is intentionally not a new database authority. `CasePlaybackFrame` is derived on demand from AnalysisCaseRun alignment, TimeMapping, Asset metadata/cache state, and AnalysisCaseMarker rows. Each source state reports the Case, Run and Asset timestamps plus optional duration/frame index and synchronization uncertainty. This keeps playback deterministic without adding a second evidence store.

## Workstation definitions (derived, not new catalog authority)

v0.23 retains and extends channel aliases, safe data gates, segment/KPI definitions, frequency-analysis settings and load-map definitions as engineering-analysis state. They do not change Run/Asset identity and do not require a schema-v8 migration. Workbook format v6 can embed a versioned `DefinitionLibrary`, and standalone `.nhralib` JSON files provide deliberate reuse. Libraries contain constants, calculated channels, gates, segments, metrics, conditional rules and reports with dependency validation. They remain derived engineering state and never modify raw source data or Run/Asset ownership.



## Portable EventRuleDefinition (derived/workbook state)

v0.24 library format v2 may include rule-generated event/alarm definitions. Each rule has a portable boolean expression, event type, severity, trigger mode (`interval`, `rising`, or `falling`), minimum duration and description. These are derived analysis definitions stored in the workbook/`.nhralib`; they are not catalog entities and do not modify authoritative Run/Asset records.


## AuthSession / entitlement state (security state, not catalog identity)

v0.25 introduces an in-memory authenticated identity/session boundary for the desktop. Identity carries stable user ID, roles and scopes; access tokens are short-lived and are never workbook/catalog data. Refresh/offline credentials may be persisted only in the OS credential vault. A future signed offline grant is bounded by an explicit expiry. None of these values become Run/Asset metadata.

## SimulationStudyDefinition / SimulationStudyPackage (derived engineering state)

A `SimulationStudyDefinition` stores the forward-study solver and parameter axes. A `.nhrastudy` `SimulationStudyPackage` adds the exact baseline vehicle/dyno, environment, source Run identity, software version, creation time and result rows. Workbook format v7 can retain study packages/definitions for repeatable local engineering work. These remain derived model evidence; the server's Event/Run/Asset schema stays authoritative and local catalog schema remains v7.


## StripAnalysisResult (derived, not persisted)

v0.26 adds a derived downtrack analysis object containing a distance grid, observed channel samples, modeled RSA channel samples, model-minus-measured residual arrays, official timing/trap residuals and projected strip events. It is reproducible from Run telemetry + official timing + a versioned vehicle/model definition and is not a new catalog authority.


## FitEvidencePolicy / FitDistanceWindow (derived inverse-model definition)

A `FitEvidencePolicy` is a portable derived-analysis definition attached to an inverse-fit invocation, not authoritative Run data. It defines telemetry domain (`time` or `distance`), official timing weights, telemetry-channel weights, engineering uncertainty scales, maximum residual samples, distance-grid step, and optional weighted `FitDistanceWindow` ranges.

When an inference result is promoted to a ModelSnapshot, the snapshot input bundle records the evidence policy together with selected unknowns and nuisance terms. This allows later review of exactly which measurements could influence the fit. Catalog schema remains v7.
