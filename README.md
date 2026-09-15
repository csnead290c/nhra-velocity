# NHRA Tech Data — Development v0.38

NHRA Tech Data is a native desktop engineering workstation for NHRA telemetry, vehicle-performance analysis, synchronized evidence, and future incident reconstruction.



## v0.37.1 Windows waveform-render hotfix

The first Windows trial of v0.37 exposed a pyqtgraph compatibility regression (`GraphicsLayoutWidget` missing `autoRangeEnabled`) before the waveform could render. v0.37.1 removes the pyqtgraph implicit clip/downsample constructor flags that triggered that path and continues to use NHRA Tech Data's own peak-preserving `prepare_plot_series()` decimation. All v0.37 cursor-cache and workflow improvements remain enabled.

## v0.37 interactive performance + everyday waveform workflow

v0.37 is the first workstation-performance pass driven by a real Windows trial of v0.36. The v0.36 application successfully launched and opened/rendered both MoTeC `.ld` and RacePak `.rpk` telemetry, but cursor interaction felt noticeably laggy. Profiling found that each hover event rebuilt X/Y mappings, scanned the full snap grid, sorted every displayed channel again for interpolation, sampled Cursor/A/B independently, and recreated the cursor-value table. v0.37 replaces that path with a bounded display-series cache, binary-search cursor snapping, batched Cursor/A/B interpolation, coalesced ~30 Hz readout painting, item reuse, and pyqtgraph view clipping/peak downsampling.

The simple workspace also becomes more usable without opening extra docks: the toolbar now exposes the active **Run** and **Reference** session, enabling straightforward two-file comparison; Channel Explorer gains persistent cross-project **Favorites**; multi-channel drag/drop refreshes once instead of once per channel; redundant legends disappear from single-channel stacked traces; and `Shift+click` / `Ctrl+click` place A/B cursors directly. The authority model is unchanged: these are display/workflow improvements only.

## v0.36 scalable import registry + named Compare Sets

v0.36 turns telemetry-file support into a declarative registry instead of an expanding chain of extension guesses. RacePak/DataLink, MoTeC, MaxxECU, VBOX VBO, TunerStudio/MegaSquirt text logs, Excel telemetry tables, generic delimited files and ZIP containers have explicit direct/interchange paths. Common proprietary families such as MDF4, AiM, FuelTech, Holley, HP Tuners, VBOX VBB, AEM, ECUMaster, Emtron, Cosworth/Pi, iRacing, Syvecs and raw CAN captures are recognized and fail closed with decoder/bridge guidance rather than being guessed as CSV. `python -m runlab.cli formats` exposes the same registry used by the desktop and qualification harness.

The workstation also gains persistent **Named Compare Sets**. A set records participating loaded Runs, Main/Reference/Overlay roles and view-only time offsets; it can be saved in the workbook, reapplied later, and the Reference Run can be stepped forward/backward while Main stays fixed. Compare Set state is display state only: it never changes evidence timestamps or invents Tech Services Run→Asset ownership. Workbook format advances to **v8** to persist the named sets while older workbooks remain readable.


## v0.33 native logger reliability + focused waveform workspace

v0.33 prioritizes the basic engineering workflow before adding more analysis surfaces. Native MoTeC M1 `.ld` import now handles the real 16-bit advisory channel count used by current files, always releases mapped buffers on decode failures, walks the channel linked list as the authority, and skips isolated unsupported diagnostic encodings without discarding an otherwise valid run. Native RacePak/DataLink `.rpk` import now supports the current `CAN_Device` serialization in addition to the older `ScaledBuffer` family, including extended DataLink strings, native timers, used-sample counts, explicit units, and the linear hardware/sensor calibration chain present in current NHRA files.

The desktop also defaults to a **Simple Workspace**: the primary waveform owns the worksheet center, Channel Explorer is the only application dock shown initially, secondary analysis panels stay available through menus/Ctrl+K, and `Ctrl+1` / `Ctrl+2` / `Ctrl+3` switch between Simple, Investigation, and Full Engineering workspaces. The primary cursor is visible on every plot and follows the waveform pointer/click position while updating the value readout. A/B cursors, navigator, event navigation, bookmarks, and regions remain available under the waveform's **More** menu instead of occupying permanent screen space.

## v0.32 verified Tech Services metadata boundary

v0.32 audits the live `nhratechservices` source read-only and binds the protected reads that actually exist: Bearer-authenticated identity, Tech Master Events, Event Entries, and normalized NHRA parity Runs. The older website `run_history` remains explicitly classified as simulator history. The database already contains an Entry→Run foreign key, but the current parity Run response does not expose it, and no permanent Run→Asset attachment/download API is present. The workstation therefore exposes verified metadata reads while the full Event → Entry → Run → Asset sync contract stays fail-closed—no driver-name, car-number, filename, or folder guessing. See `TECH_SERVICES_API_AUDIT_v0_32.md`.

## v0.31 platform consolidation + RSA model enrichment

v0.31 consolidates product/version/format provenance into a machine-readable release manifest and adds an ATLAS-style RSA enrichment layer. A measured Run can carry namespaced `Model.*` and explicit model-minus-measured `Residual.*` virtual channels on the RSA model Run-time grid without replacing raw logger channels or official timing. The same channels are available to normal workstation browsing/plotting/report logic and can be rebuilt from workbook-derived-analysis provenance. New `.nhrafit` v5 and `.nhrastudy` v2 packages also embed upstream-reference provenance. See `PRODUCT_ARCHITECTURE.md` and `MODEL_ENRICHMENT.md`.

## v0.30 Run influence

v0.30 adds leave-one-Run-out influence analysis to Joint Reconstruction Studies. Each measured Run is omitted in turn, the remaining Runs are fully refit with their original evidence/nuisance policies, and the movement of every shared vehicle parameter is reported. `.nhrafit` format v4 persists these influence results alongside profile-objective scans and residual decomposition. See `RUN_INFLUENCE.md`.

## v0.29 practical identifiability

v0.29 adds on-demand profile-objective scans to Joint Reconstruction Studies. A selected shared parameter is forced away from its optimum while every other allowed shared/nuisance parameter is re-optimized, exposing whether the available Runs actually constrain that parameter or whether correlated freedom can compensate. `.nhrafit` format v3 stores the completed profiles and remains backward-readable from v1/v2. See `PRACTICAL_IDENTIFIABILITY.md`.

## v0.28 joint reconstruction studies

v0.28 generalizes evidence-aware inverse fitting into a repeatable multi-Run **Joint Reconstruction Study**. Shared vehicle unknowns are solved across several measured Runs while each Run can carry its own evidence policy, Tech Services Run identity/role and tightly bounded local nuisance allowances. Portable `.nhrafit` packages preserve the complete study definition, optimized vehicle, parameter estimates, correlation/identifiability diagnostics, raw residual evidence and per-Run/source/window fit-quality decomposition.

The desktop Inference Center exposes Run participation, timing/telemetry inclusion and optional local power/traction/rollout corrections. The CLI `fit-study` command runs the same engine headlessly. See `FIT_EVIDENCE_POLICY.md`, `REFERENCE_REPOSITORIES.md`, and the v0.28 validation report.

## v0.27 fit-evidence policy + downtrack inverse fitting

v0.27 makes the RSA/Quarter Pro inverse solver explicitly **evidence-aware**. A fit can now choose whether telemetry is compared in Run time or physical distance downtrack, select trusted downtrack windows, independently include/exclude speed, engine RPM, driveshaft RPM and longitudinal G, independently weight official ET/trap observations, and set engineering uncertainty scales. Residuals are retained as model-minus-measured values normalized by the configured uncertainty and weighting.

The desktop **Inference Center** exposes the same policy. A selected policy is stored with inference provenance and captured into ModelSnapshots together with selected unknowns and nuisance terms. Headless `fit` run JSON may carry the same evidence policy and can export the exact residual/evidence table. The default policy remains backward compatible with prior time-domain fits. See `FIT_EVIDENCE_POLICY.md`.

## v0.26 NHRA strip analysis + RSA model residuals

v0.26 makes **distance downtrack** a first-class engineering comparison coordinate and places the RSA/Quarter Pro model directly inside the normal analysis workstation. The new **NHRA Strip / Model Residuals** display overlays measured and modeled speed/RPM/driveshaft/G versus distance, shows model-minus-measured residuals, marks official timing beams and portable rule events, and reports official timing/trap residuals.

A headless `strip` command exposes the same analysis for scripting/export. Beam-to-beam section residuals decompose total model error into Launch→60, 60→330, 330→660, 660→1000 and 1000→1320 contributions. The implementation intentionally does **not** time-warp measured data to make the model appear better; launch/rollout coordinate uncertainty remains visible.

## v0.25 protected desktop + RSA simulation studies

v0.25 deliberately advances two long-term pillars together: **NHRA-controlled desktop access** and **RSA/Quarter Pro vehicle simulation**.

The security boundary now assumes the desktop will reuse the existing NHRA Tech Services identity in the system browser through an Authorization Code + PKCE style flow. The desktop never needs the website password or browser cookies. `runlab.auth` provides identity/scopes, PKCE state, short-lived sessions, secure OS credential-vault persistence, bounded offline-entitlement support, and a fail-closed unbound provider. `AuthorizedTechServicesTransport` separately gates Run catalog reads, Asset downloads and derived-analysis writes. Frozen/distributed builds require authorization by default; source development remains runnable until the real Tech Services auth adapter is mapped. See `SECURITY_ARCHITECTURE.md`.

On the engineering side, `runlab.simulation_study` makes the RSA/Quarter Pro code a repeatable study system rather than a one-off compare-run dialog. Multi-axis scenario sweeps can vary power, weight, aero, traction, final drive, tire, individual gears/shift RPMs and other model variables with either the source-faithful reference solver or smooth optimizer solver. Results carry official-style incrementals/traps and deltas versus baseline; a selected case can become a normal generated comparison session. Portable `.nhrastudy` packages retain the exact vehicle model/dyno, environment, solver/study definition, software version, source Run identity and result table. See `SIMULATION_STUDIES.md`.


## v0.24 rule-generated events and historical alarms

v0.24 adds portable **Event / Alarm Rules** to the same Analysis Definition Library introduced in v0.23. Rules use the existing safe condition language and canonical channel roles, so the same definition can evaluate across RacePak/MoTeC/FuelTech-style naming differences after normal channel mapping. Historical evaluation produces explicit rising, falling, or interval events with severity, minimum-duration filtering, timestamps and duration.

The desktop Events display now includes saved rule-generated events and a new **Alarm Status** display evaluates interval rules at the shared Run-time cursor. Headless `library events` uses the exact same engine for batch/event extraction. The event engine prepares portable calculated channels/constants once per Run even when many rules are evaluated.

This is deliberately a historical/load-time rules engine first. It creates the reusable semantics needed for future live telemetry alarms without pretending that a live transport/reconnect pipeline exists yet. Raw source data and Tech Services Run/Asset ownership remain unchanged.

## v0.23 portable definitions and saved reports

v0.23 turns the workstation primitives into reusable engineering workflows. A versioned **Analysis Definition Library** can now carry setup constants, calculated channels, gates, segment templates, KPI definitions, conditional rules and saved reports across Runs/loggers. Definitions may use canonical roles such as `engine_rpm` instead of one vendor's channel spelling, and the library exposes an explicit dependency graph/cycle/missing-input validation step before execution.

Saved reports evaluate every Run against its own official timing boundaries, can flag conditional results, export CSV/JSON/XLSX, and feed a Run-by-Run KPI trend display. `.nhratech` workbook format v6 embeds the current analysis library; standalone `.nhralib` files allow deliberate reuse between workbooks. Headless `library` commands use the same engine for batch validation/reporting.

v0.21 established Channel Explorer/gates/segments/KPIs/PSD/load maps; v0.22 added richer displays. v0.23 deliberately reuses those same headless layers rather than creating a separate reporting dialect.

See `WORKSTATION_PARITY_REQUIREMENTS.md` for the benchmark matrix and long-term minimum capability target.

**NHRA Tech Services remains the permanent system of record** for Events, Entries, Runs, official timing/weather, and every permanent file attached to a Run. v0.26 builds on the reusable **AnalysisCase** timeline with one shared review cursor that can drive media, telemetry/IDR-style numeric evidence, markers, and the active telemetry session together.

An AnalysisCase can group a primary Run plus any number of baseline, comparison, or reference Runs without changing permanent Run/Asset ownership. Incident analysis is now one case type alongside performance/reconstruction, parity, development, aero, and general engineering work.

The production flow remains:

1. A Run exists in NHRA Tech Services.
2. Permanent engineering files are attached to that Run on the website.
3. The desktop mirrors the Event → Run → Asset manifest.
4. Engineers create AnalysisCases that reference those canonical Runs and Assets.
5. Relevant immutable Asset bytes are cached locally and verified against SHA-256.
6. Case-only material that does not belong to one pass (inspection photos, reports, notes, etc.) can be stored as local case evidence.
7. Each Asset clock is mapped into its authoritative Run clock; each member Run can then be aligned onto the shared Case clock.
8. Source-aware case markers (impact, launch, shift, chute, failure, etc.) resolve through those mappings and follow later synchronization refinements.
9. Derived models/results remain versioned and can later be mapped back to the website's existing incident/session APIs after that backend contract is fully inspected.

A filename has **no identity role** for permanent Run ownership. `anything_the_team_named_it.rpk` belongs to the correct Run because Tech Services says that Asset belongs to that Run.

There is no Box connection, repository-manifest workflow, file-to-run matcher, or reconciliation UI in v0.26.

## Current Tech Services integration status

The local schema and authorization boundary are ready, and v0.32 now contains a source-verified read-only HTTP client for the website's real Bearer-token API. The audited site still lacks the telemetry workstation's Event → Entry → Run → Asset catalog/download endpoints and a safe native-desktop login handoff, so those pieces remain fail-closed. The app does not reinterpret the site's simulation `run_history`, guess object URLs, infer Run ownership from filenames, or call the website password endpoint from the end-user desktop.

For development only, **Data → Apply Tech Services Snapshot (Development)…** accepts contract-v4 JSON containing Events, nested Runs, and nested permanent Assets. This exercises the exact local mirror/cache semantics without pretending that the final network API is known.

See `ARCHITECTURE.md`, `DATA_MODEL.md`, `ANALYSIS_CASES.md`, and `SYNC_CONTRACT_v4.md`.

## Desktop workflow

- **NHRA Tech Services Runs** lists only mirrored server Runs.
- **Analysis Cases** lists local engineering workspaces and their primary/baseline/comparison/reference Runs.
- **New Analysis Case** creates an Incident, Performance / Reconstruction, Parity, Development, Aerodynamics, or General Engineering workspace from a selected Run.
- A selected authoritative Run can be added to an existing case without altering the Run or any Asset ownership.
- **Cache Case** downloads/caches all authoritative Run Assets referenced by that case through the normal Tech Services transport.
- **Case Timeline / Sync** shows each Run→Case and Asset→Run mapping, supports manual synchronization anchors, and displays source-aware case markers.
- **Synchronized Case Review** adds one movable Case-time cursor, marker/frame stepping, 0.25×–2× review playback, source-position readout, Qt video/audio seeking for cached media, and a synchronized case-time preview/readout for telemetry/IDR-compatible numeric files.
- Double-click/Open Run loads every telemetry Asset attached to that Run.
- **Run Assets** shows server authority, remote Asset ID, cache state, vendor, and time mapping.
- Direct **Open Log…** remains available for ad-hoc/scratch analysis, but opening a random local file does not create a permanent catalog Run or attach it to a Tech Services Run.
- Run-scoped and case-scoped ModelSnapshots remain supported for single-pass and multi-run inverse fitting.
- **Simulation Study Center** performs repeatable multi-axis RSA/Quarter Pro sweeps and can add selected simulated cases directly to Compare Sessions.
- **Account** surfaces the Tech Services protection/entitlement state; live sign-in remains fail-closed until the real backend adapter is bound.

## Launch

### Windows

1. Run `setup_windows.bat` once.
2. Run `run_windows.bat`.

For a self-contained executable, run `build_windows_exe.bat` on Windows with Python installed. Frozen builds require Tech Services authorization by default. The build script can Authenticode-sign the executable when the NHRA signing certificate/timestamp environment variables are configured; development packaging can explicitly opt out of auth with `NHRA_TECH_DEV_UNAUTHENTICATED=1`.

### macOS / Linux

```bash
./setup_mac_linux.sh
./run_mac_linux.sh
```

## Local state

By default the local mirror, analysis state, logs, and object cache live in the application data directory. Set `NHRA_TECH_DATA_HOME` to redirect the local state tree for testing or managed deployments.

Cached immutable objects live under `library/objects/<sha256>`. The server's Asset ID and Run relationship remain authoritative; local paths are machine-specific cache details only.

## Supported analysis foundation

The workstation retains the telemetry/analysis work built through v0.12–v0.26, including:

- RacePak, MoTeC, MaxxECU and generic text import paths with fail-closed binary handling;
- waveform, values, cursor-driven gauge/status views, advanced scatter, weighted/cumulative histograms, FFT/PSD/spectrogram, filters, rolling statistics, envelopes and run deltas;
- channel explorer metadata/aliases, safe reusable data gates, official drag segments and KPI reports;
- portable analysis libraries with constants, calculated channels, gates, segments, metrics, conditional rules and saved reports;
- dependency/cycle/missing-input validation, CSV/JSON/XLSX report export and saved KPI trends;
- portable rule-generated events/alarms with rising/falling/interval triggers, severity, minimum duration and cursor-state review;
- 2-D load/heat/occupancy maps and normalized Run-progress views;
- canonical channel mapping and unit handling;
- cursor/region statistics, annotations and bookmarks;
- sensor-health/data-integrity tools;
- official timing/weather authority;
- vehicle setup/knowledge provenance;
- delivered-power reconstruction, multi-run inverse fitting, scenario generation and Quarter Pro reference modeling;
- reproducible RSA Simulation Studies with multi-axis forward sweeps, baseline deltas, observed-vs-predicted validation and `.nhrastudy` provenance packages;
- desktop authentication/entitlement foundations designed to reuse the Tech Services login, plus operation-specific Run/Asset/analysis scopes;
- versioned ModelSnapshots and longitudinal EngineeringValues;
- AnalysisCase workspaces that can group multiple Runs, incident/performance evidence, and case-scoped model snapshots;
- two-stage Asset→Run→Case time mappings for synchronized telemetry/video/audio/IDR analysis;
- one shared Case-time review cursor with media seeking, marker navigation, frame stepping and numeric evidence sampling;
- source-aware case timeline markers that dynamically resolve after synchronization changes.

Raw server assets remain immutable. Calculated channels and derived analyses are separate from the source file.

## Architecture rule to preserve

**Do not add a second file-discovery or run-matching system.** If a file should belong to a Run, that relationship is created in NHRA Tech Services. The desktop consumes that authoritative relationship.
