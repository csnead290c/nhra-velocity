# NHRA Velocity Architecture — v0.38


## Progressive-disclosure UI boundary

NHRA Velocity should expose the smallest useful surface for ordinary Run review and reveal specialist tools only when requested. The default desktop path is authoritative Run selection → telemetry → core class channels → fit/compare. Advanced displays, RSA studies, report internals, evidence synchronization and diagnostic/audit tooling remain available but must not consume permanent screen space merely because they exist. Class profiles choose sensible defaults; they do not lock the user into a fixed layout.


## v0.37 display performance boundary

The desktop may cache format-neutral X/Y display views, sorted interpolation views and cursor snap grids within a worksheet. Those caches are disposable and are cleared on session/Run mapping changes. They do not become evidence, alter raw samples, or change Tech Services authority. GUI readout updates are coalesced independently from the shared cursor signal so synchronized displays remain responsive without forcing full-rate table repainting.

## v0.36 import and comparison state

Telemetry recognition/decoder status is now centralized in `runlab.import_registry`; proprietary binary families fail closed before generic text parsing. Named Compare Sets are workbook-owned display state, not data authority: they persist loaded-session membership, Main/Reference/Overlay roles and view-only offsets without changing source clocks or Tech Services Run→Asset ownership. Workbook format v8 carries this state as an optional field so v0.36 remains backward-readable from older workbooks.

## v0.33 workstation focus

The default worksheet now treats the primary waveform as the central analysis surface rather than a dock. Optional displays remain dockable/floating, while application-level panels use explicit Simple / Investigation / Full workspace presets. Native telemetry import remains fail-closed structurally, but the RacePak and MoTeC decoders now cover the current real-world binary families qualified in `VALIDATION_REPORT_v0_33.md`.
## 1. System boundary

NHRA Tech Services is the permanent system of record. The desktop is an engineering client and local analysis/cache layer.

```text
nhratechservices.com / database / object storage
        │
        │ authoritative Event → Entry → Run → Asset relationships
        │ official timing + weather + remote IDs/revisions/hashes
        ▼
NHRA Velocity desktop local mirror
        │
        ├─ SQLite metadata mirror
        ├─ SHA-256 immutable asset cache
        ├─ decoded telemetry sessions / time mappings
        ├─ AnalysisCases ↔ canonical Runs / evidence
        ├─ workbooks / displays / annotations
        └─ derived models / engineering analysis
```

The desktop does not discover files in Box or any other archive and then infer their Run. It never uses filename/path heuristics to assign a permanent Asset to a Run.

## 2. Canonical identity

The server owns identity for Event, Entry, Run, and Asset. Local IDs are stable implementation IDs used by SQLite and workbooks; `remote_id` maps each mirrored object back to Tech Services.

A Run owns its permanent Asset list. An Asset's filename is metadata only. The Run/Asset foreign-key relationship supplied by Tech Services is authoritative.

`remote_entities` retains server→local identity/revision mappings and `sync_cursors` supports incremental catalog pulls. These are synchronization mechanics, not evidence-matching concepts.

## 3. Local catalog schema v7

Core objects:

- Event
- Driver
- Vehicle
- Entry
- Run
- Asset
- TelemetrySession
- TimeMapping
- EngineeringValue
- ModelSnapshot
- AnalysisCase
- AnalysisCaseRun
- AnalysisCaseEvidence
- AnalysisCaseMarker
- Annotation
- legacy IncidentCase (migration only)
- RemoteEntity
- SyncCursor

Schema v6 generalizes incident work into reusable multi-Run AnalysisCases and allows ModelSnapshots to be Run-scoped or case-scoped. Existing v0.17 IncidentCase rows and Run ModelSnapshots migrate forward without deletion.

A fresh v0.33 catalog still uses schema v7 and does **not** create repository-discovery or reconciliation tables. v0.23 extends portable workstation definitions/reporting without changing persistent catalog schema. Older migrated SQLite files may physically retain legacy tables after migration, but current runtime code does not use those discovery concepts.

## 4. Server asset lifecycle

A production Asset is first created on Tech Services and already belongs to a Run before the desktop sees it.

`upsert_server_asset()` mirrors that record. The desktop may update its mirrored filename/type/vendor/hash/revision metadata as newer server snapshots arrive, but it cannot re-parent a Tech Services Asset to another Run.

If the authoritative SHA-256 changes for an existing remote Asset revision, any old local cached bytes and decoded telemetry session are invalidated before the new bytes are used.

## 5. Local caching

`LocalObjectStore` is a content-addressed cache, not a primary repository.

When a server Asset is requested:

1. `TechServicesTransport.fetch_asset(remote_asset_id)` returns the bytes.
2. The desktop computes SHA-256.
3. If the server supplied a SHA-256, the download must match it exactly.
4. The object is stored under its SHA-256 path.
5. The local Asset record points to that cached object.

Deleting a cache entry must never delete or change the permanent server Asset.

## 6. Scratch sessions and explicit local working attachments

Engineers can still open a local telemetry file directly for quick analysis. That session is **scratch state**. Direct **Open Log…** does not create an official Run, attach the file to a Run, upload it, or infer ownership.

When an authoritative Tech Services Run has already been synchronized, the engineer may instead select that exact Run and invoke **Attach Local Telemetry…**. That explicit action:

- requires a user-selected canonical Run ID;
- never derives Run identity from filename, driver, car number, timestamps, or folder structure;
- copies the bytes into Velocity's local content-addressed object store;
- creates a local working Asset association to the selected Run so the workstation can persist analysis/time mappings;
- inherits official timing/weather from the canonical Run without overwriting them from logger metadata;
- performs **no Tech Services write** and does not claim the local association is a permanent server Asset.

This is a bridge for the current read-only website contract. If the file needs to become part of permanent run history, Tech Services remains the system of record. When a verified server Run→Asset endpoint exists, server Asset identity can replace the local working association without changing the canonical Run identity.

## 7. Tech Services contract v4

Development snapshots use a nested authoritative shape:

```text
Event
  └─ Run
       ├─ official timing/weather
       └─ Assets[]
```

Each Asset contains at minimum a server `remote_id` and filename; type, SHA-256, size, MIME type, vendor, revision, upload time, metadata, and a stable opaque object reference may also be present. Temporary or signed download URLs are transport capabilities and are never persisted as Asset identity.

Omitting the `assets` field in a Run snapshot leaves the current mirrored manifest unchanged. v0.25 does not infer deletion semantics until the real backend contract is inspected.

See `SYNC_CONTRACT_v4.md`.

## 8. Transport boundary

`runlab.transport.TechServicesTransport` currently defines only the capabilities the desktop truly needs:

- pull catalog snapshot/change feed;
- fetch one permanent Asset by server Asset ID;
- push permitted derived-analysis bundles in the future.

Asset upload is modeled as a capability but is not assumed. The current `UnboundTechServicesTransport` fails closed for every network operation.

Once the real source repository/API is available, the adapter should wrap the existing website/backend rather than force the backend to implement a client-invented API.

`analysis_case_bundle()` is deliberately a provider-neutral local serialization, not a new server route contract. The production adapter must map it to the website's actual incident/session model after that backend is fully inspected.

## 9. Data authority

Official timing/weather from Tech Services remain authoritative. Logger metadata can assist analysis but cannot silently overwrite official values. The current verified metadata bridge prefers `parity.php?action=runsWithWeather`, translating its nearest canonical weather sample into Velocity environment fields while retaining the server weather timestamp, join delta, and provenance metadata; if that GET surface is unavailable the client falls back to timing-only Run sync.

Raw server Asset bytes remain immutable. User math, filters, reconstructions, annotations, time mappings, engineering values and model snapshots are distinct derived state with provenance.

## 10. Workbooks

`.nhratech` remains a view/workspace artifact. It stores open sessions, worksheet/display layout, cursor state, compare roles, notes and analysis settings. Where a session came from Tech Services, the workbook references local mirror Run/Asset IDs so the bytes can be re-cached from the server if needed.

## 11. AnalysisCase and multi-source analysis

A Run remains the canonical clock/ownership container for telemetry, IDR, video, audio and other permanent Run Assets. An AnalysisCase sits above one or more Runs and defines the engineering question being investigated.

Typical structure:

```text
AnalysisCase
  ├─ primary Run
  ├─ baseline Run(s)
  ├─ comparison/reference Run(s)
  ├─ links to relevant Run Assets
  ├─ standalone inspection/report evidence
  └─ case-scoped ModelSnapshots / future derived results
```

This lets incident work, parity studies and multi-run vehicle reconstruction share the same evidence/synchronization architecture without weakening server Run/Asset authority. Synchronization is explicitly two-stage:

```text
Asset time --(TimeMapping)--> Run time --(AnalysisCaseRun alignment)--> Case time
```

Asset→Run is affine (`scale × time + offset`) so logger/media clock drift can be corrected. Run→Case preserves physical seconds (`scale=1`) and applies only an offset; disagreement among multiple alignment anchors is reported as uncertainty rather than time-warping a pass. Both stages retain method, confidence, uncertainty and anchors, and raw Asset timestamps are never rewritten. `AnalysisCaseMarker` can be anchored in case, Run, or Asset time and is resolved dynamically into case time, so a refined video/IDR mapping updates the marker position without changing its original source timestamp.

## 12. Physics/model architecture

Two vehicle-performance engines remain separate:

- smooth optimizer engine for inverse fitting;
- source-faithful Quarter Pro-derived reference engine for high-fidelity compatibility/reference checks.

ModelSnapshots are append-only and retain software/model version. They may be tied to a canonical Run for single-pass work or to an AnalysisCase for shared multi-run estimates. Historical values are not silently recomputed under newer models.


## 13. Synchronized case review

`runlab.case_playback` is a headless review layer over the existing timeline. The Case clock is the single review cursor. For every Run Asset it resolves the corresponding Run time and, when an Asset→Run mapping exists, the source Asset time. Media duration/frame-rate metadata are optional hints used only for viewing bounds and frame stepping.

The desktop **Synchronized Case Review** dock consumes this same logic. Cached video/audio assets can be sought through Qt Multimedia. Telemetry and IDR-compatible numeric exports are previewed on Case time and sampled at the resolved source timestamp. Remote Assets are never presented as locally viewable until their normal SHA-256-verified cache exists.

Review playback is derived UI state. It does not mutate raw Assets, Run ownership, synchronization anchors, or the authoritative Tech Services record.

## 14. Analysis workstation layer

v0.21 adds a Qt-independent analysis layer above decoded `TelemetryRun` data. `runlab.workstation`, `runlab.signal_analysis`, `runlab.heatmap`, and `runlab.display_data` are intentionally reusable by desktop displays, CLI/batch processing, and future live sessions.

The workstation layer owns derived definitions and views, not source identity. It provides:

- channel discovery with unit, dimension, canonical role, source kind, sample rate and user alias;
- safe vector data gates/conditions without arbitrary Python execution;
- official drag segments in time, distance and normalized-progress coordinates;
- reusable KPI/statistical metrics across Runs and segments;
- FFT, Welch PSD and spectrogram analysis through a common validated timebase;
- 2-D binned load/heat/occupancy maps;
- display-only normalized Run progress.

Mixed-rate native channels are not silently interpolated for boolean gates. Operations that require a common grid must do so explicitly. Comparison reports regenerate official time segments independently for each Run so one Run's incremental timestamps are never reused as another Run's boundaries.

Channel aliases and saved gates currently live with analysis/workbook metadata rather than becoming authoritative catalog identity. Future shareable definition libraries should preserve this separation. See `WORKSTATION_PARITY_REQUIREMENTS.md`.

## 15. Display-depth layer

v0.22 extends the workstation layer with `runlab.display_analysis`. Rich Qt displays consume the same headless functions used by CLI/tests:

- `paired_channel_data()` aligns X/Y/Z on the sparsest overlapping logger clock and avoids fake precision;
- a gated multi-channel display requires an explicit common rectangular grid so boolean filtering never hides cross-clock interpolation;
- `linear_regression()` provides slope/intercept/correlation/R² for advanced XY work;
- `channel_distribution()` supports sample count/percent and dwell-time seconds/percent, plus cumulative distributions;
- `sample_channel_at()` provides deterministic cursor sampling for numeric, bar, dial and bit/status displays.

Display configuration is workbook/view state. These additions do not mutate raw telemetry, Run/Asset authority, canonical synchronization, or catalog schema.



## 16. Portable definition/report layer

v0.23 adds `runlab.definition_library` above the existing workstation primitives. It is derived engineering state and does **not** introduce catalog authority or schema v8.

A versioned `DefinitionLibrary` can contain:

- named setup/analysis constants;
- portable calculated-channel definitions;
- reusable data gates;
- manual or official per-Run segment templates;
- KPI/statistic definitions;
- conditional rules with explicit severity;
- saved multi-metric report definitions.

Portable expressions may resolve source channel names, user aliases or canonical roles. Canonical roles are preferred for cross-vendor reuse. Library validation exposes missing channels/library references and calculated-channel dependency cycles before execution. Applying a library materializes only derived constants/calculated channels/gates on a decoded Run; raw data remains immutable.

Official segment templates resolve independently for every Run, preventing one pass's timing boundaries from being reused on another pass. Saved reports and KPI trends consume the same headless engine as CLI/batch work. CSV, JSON and XLSX report exports contain derived results only and never alter Tech Services source assets.

Workbook format v6 may embed an analysis library; `.nhralib` is a portable JSON representation for deliberate sharing. Neither is a substitute for authoritative Run/Asset identity.


## 17. Rule-generated event / alarm layer

v0.24 extends the portable `DefinitionLibrary` with `EventRuleDefinition`. Historical event extraction lives in `runlab.rule_events` and consumes the same canonical-role/constant/calculated-channel condition language as gates. A rule can emit a true interval, rising edge, or falling edge and carries severity, event type and an optional minimum true duration.

Rule evaluation is derived state. The engine deep-copies the decoded Run, applies portable constants/calculated channels once, evaluates all saved rules on the explicit rectangular analysis clock, and returns event records without rewriting raw telemetry. The desktop Events and Alarm Status displays and the headless CLI use the same engine.

This layer is intentionally transport-neutral. Future live telemetry may evaluate the same rules incrementally, but v0.24 does not claim a live stream/reconnect implementation.


## 18. Desktop authentication / authorization boundary

`runlab.auth` and `runlab.security` reuse the existing Tech Services identity rather than inventing a second account system. Because the audited website does not yet expose an Authorization Code + PKCE bridge, the current first-party adapter performs the existing HTTPS email/password login exchange, immediately discards the password, refreshes server capabilities, and persists only the seven-day Bearer token in the OS credential vault. The provider boundary deliberately remains compatible with a future browser/device PKCE handoff.

`AuthorizedTechServicesTransport` applies least-privilege scopes before provider calls (`runs.read`, `assets.read`, `analysis.write`). Feature-level checks such as `simulation.use` use the same identity/entitlement model. Frozen builds require authorization by default and fail closed when no validated online/offline session exists. Source development remains available until the real provider adapter is bound. See `SECURITY_ARCHITECTURE.md`.

The local object cache is still an integrity cache, not application-level encrypted storage. Endpoint disk encryption remains required until/unless an explicit encrypted-cache layer is added.

## 19. RSA / Quarter Pro Simulation Study layer

`runlab.simulation_study` sits above the existing forward/reference and inverse engines. A `SimulationStudyDefinition` captures solver plus one or more absolute/delta/scale parameter axes. Sweeps return official-style timing/trap outputs, deltas from the unchanged baseline and selected solver diagnostics. Study cases can be materialized as normal generated `TelemetryRun` sessions so all workstation plots/gates/KPIs/event rules/reports can consume simulated and measured data through the same abstractions.

A `SimulationStudyPackage` (`.nhrastudy`) additionally freezes the complete baseline VehicleConfig/dyno, Environment, source Run identity, software version, UTC timestamp and result rows. This is derived engineering evidence, not a new authoritative Run/Asset identity. Long term, an AnalysisCase should reference these packages/results alongside its versioned fitted ModelSnapshot. See `SIMULATION_STUDIES.md`.


## 20. Strip / model-residual layer

`runlab.strip_analysis` is a derived spatial-analysis layer. It never changes Run time, source timestamps, official timing, Asset ownership or the RSA vehicle model. Measured channels are projected onto distance from launch using the existing validated speed/time mapping; modeled channels are sampled from the RSA/Quarter Pro simulation trace. Official timing and trap residuals remain based on the model's proper timing-system calculation, not on instantaneous spatial samples.

This separation is deliberate: **spatial channel residuals** answer where the model diverges from measured telemetry, while **official timing residuals** answer whether the model reproduces the NHRA timing system. Beam-to-beam section residuals decompose timing error without forcing a graphical alignment.


## 21. Fit Evidence Policy / inverse-model residual architecture

`runlab.inverse.FitEvidencePolicy` controls what evidence is permitted to influence an inverse solution without changing the underlying Run or telemetry. Official timing and telemetry remain independent evidence families. Telemetry can be evaluated in Run time or projected to physical downtrack distance using the same strip-analysis coordinate system introduced in v0.26.

A policy may enable/disable and weight individual official timing fields, enable/disable telemetry channels, define engineering uncertainty scales, select one or more weighted distance windows, and bound residual sample count. Residual rows retain source, observed/predicted value, raw residual, normalized residual, and time/distance coordinate. A zero weight excludes evidence rather than hiding it after optimization.

The Inference Center persists the selected policy, unknowns, and nuisance terms into Run analysis metadata; `capture_model_snapshot()` freezes that fit context into the versioned ModelSnapshot. This keeps inverse conclusions auditable and makes it possible to distinguish “matched the timeslip” from “matched how the vehicle traveled downtrack.” No catalog schema change is required.


## 22. Joint reconstruction studies

`runlab.fit_study` wraps the inverse engine in a reproducible multi-Run study definition. Shared unknowns describe the common vehicle model. Each `FitRun` separately records its Tech Services Run reference/role, environment, official timing, evidence-selection policy and allowed local nuisance corrections. Local corrections are regularized and must never be mistaken for shared vehicle properties.

`.nhrafit` format v2 stores the base/optimized vehicle, Run policies, estimates, covariance/correlation diagnostics, smooth-engine and Quarter Pro reference residual evidence, and objective decomposition by Run/source/window. The package contains derived analysis and references to authoritative Runs; it does not duplicate raw Run Assets.

The two public repositories in `REFERENCE_REPOSITORIES.md` are independent upstream references: RacingSystemsAnalysis governs physics/source-fidelity review and nhratechservices governs production identity/auth/data integration. Release audits should pin both commit SHAs whenever reachable.


## 23. Practical identifiability

`runlab.fit_uncertainty` profiles selected shared fit parameters by forcing each value across a bounded grid and re-optimizing the remaining allowed shared and Run-specific freedom. This supplements local covariance/correlation with a nonlinear practical-identifiability check. The robust soft-L1 objective is retained; reported threshold intervals are engineering diagnostics and are not labeled exact posterior confidence intervals. Completed scans are stored in `.nhrafit` v3.


## 24. Run influence

`runlab.fit_uncertainty.leave_one_run_out_influence` refits the joint model after omitting each Run. Shared-parameter movement is normalized to engineering bounds (and local standard error where useful), exposing dependence on individual passes. Retained Run-specific nuisance starts/overrides are index-remapped so the influence test changes evidence rather than parameter bookkeeping. Results persist in `.nhrafit` v4.


## 25. RSA model enrichment

`runlab.model_enrichment` publishes RSA-derived `Model.*` virtual channels and explicit model-minus-measured `Residual.*` channels into a measured `TelemetryRun` without modifying raw source columns, canonical measured roles, official timing or server Asset ownership. Model channels retain their own Run-time grid and are classified separately in the channel catalog. Stable virtual canonical roles such as `model_speed_mph` and `residual_speed_mph` allow portable definitions to reference them. Workbook-derived-analysis metadata can rebuild the enrichment deterministically from the retained vehicle model/environment/engine settings.

Product/version/portable-format constants are centralized in `runlab.product_manifest`; `runlab.release_audit` detects release-document drift and records both mandatory upstream repositories as verified pinned SHAs or explicit `unverified` warnings. New `.nhrafit` v5 and `.nhrastudy` v2 artifacts embed the same upstream-reference records. See `PRODUCT_ARCHITECTURE.md` and `MODEL_ENRICHMENT.md`.

## v0.38 Run Workspace and derived-report boundary

The canonical Run is the desktop coordination object. Official timing/weather remains authoritative server-derived context; telemetry Assets remain immutable evidence; worksheet/session state remains display state. The Run Workspace merely composes those layers. It does not infer Run ownership from filenames.

Catalog schema v8 adds `run_reports` for standardized derived engineering products such as the Pro Stock shift report. Reports are keyed by deterministic fingerprints and append rather than overwrite so historical analyses remain auditable. A report may reference the telemetry Asset used to generate it, but the report does not change that Asset or the authoritative Run. Class/RSA profile defaults are explicit seed values with provenance and remain overridable by measured/user/fitted engineering values.
