# NHRA Velocity v0.38 development

## v0.38.0-dev.24

- Fixed the Windows desktop smoke gate to inspect the actual `WaveformDisplay._plots` collection instead of a nonexistent `plots` attribute.
- Smoke-test failures now print the real exception and traceback to the updater console as well as the diagnostic log.
- This is a validation-gate hotfix; no RacePak corpus-evidence authority rules were loosened.


## v0.38.0-dev.23 — RacePak Evidence Safety / Exact Descriptor Recovery

- Reworked the dev.22 empirical RacePak channel-id feature around a stricter rule: **numeric `_CONNECT4_COMMAND` history is evidence only and never automatically renames an unknown DDF channel**, regardless of how many known configurations agree. This directly avoids over-assuming that a slot/id has one global meaning across cars.
- Added exact DDF **descriptor-table fingerprint** recovery. VELOCITY may recover source names/units automatically only when the complete raw DDF descriptor SHA-256 exactly matches a previously configured DDF whose recorded ids/rates fully match a sibling RCG. Any conflicting definition observed for that exact fingerprint disables automatic recovery.
- Configless DDF channels now retain `RacePak Channel <id>` when only id history is available. Historical names/units/config counts/conflicts are preserved as suggestion metadata for engineering review instead of changing the visible source identity.
- The authority order is now exact per-log config → Vehicle/Category profile → Driver/Category profile → sibling RCG → exact known DDF descriptor fingerprint → id-history suggestion → generic id label. Corpus evidence never assigns Common Channels.
- Added DDF header-only structure parsing so corpus fingerprint scans can inspect thousands of DDF descriptor tables without loading entire multi-megabyte payloads into memory.
- The audit now also writes `racepak_descriptor_profiles.csv`. Quick/Full corpus scans install a v2 evidence library and remove the legacy dev.22 v1 default-path library so the superseded ID-only fallback cannot remain active accidentally.
- Added regressions proving: repeated configs do not inflate evidence; conflicting ids remain conflicts; strong id-only history still leaves a DDF generic; an exact configured descriptor fingerprint can recover source names; changing only the sample-rate descriptor blocks that recovery; and conflicting definitions for the same exact fingerprint fail closed.

## v0.38.0-dev.22 — Empirical RacePak Channel-ID Library

> **Superseded by dev.23:** dev.22 allowed conflict-free numeric ID history to rename a configless DDF. dev.23 intentionally removes that authority; ID history is suggestion-only.

- Added a conservative **RacePak `_CONNECT4_COMMAND` channel-id census** that mines known `.rcg` and `.rpk` definitions from the user's real data corpus. Evidence is counted by distinct configuration signature so one team with hundreds of repeated runs cannot manufacture false confidence.
- Added conflict-aware consensus levels: **verified** (3+ distinct configurations, conflict-free), **supported** (2), **single-source**, and **conflict**. Only verified, conflict-free IDs are eligible for automatic fallback naming.
- Configless raw `.ddf` files can now use the installed empirical library to recover source-channel names/units for verified IDs while retaining the numeric RacePak ID as provenance. Exact per-log config, Vehicle/Category profile, Driver/Category profile, and sibling RCG remain higher authority.
- The empirical ID library **never assigns VELOCITY Common Channels automatically**. It may tell us that RacePak ID `X` has been consistently called `ENGINE RPM`; the engineer still decides whether that signal is the Common Channel **Engine Speed** for the specific data set.
- Conflicting IDs fail closed and remain `RacePak Channel <id>`. Unit disagreements also prevent automatic fallback. Two-source agreements are reported for review but are not auto-applied.
- Extended the one-click corpus audit so the same Quick/Full run also writes `racepak_channel_ids.csv/json` and installs the verified subset as the lowest-authority DDF source-label fallback. Quick scans every RCG plus a deterministic representative RPK spread; Full scans every RCG and every RPK.
- Large RPK definition mining uses memory mapping to avoid loading tens-of-megabyte run files fully into RAM.

## v0.38.0-dev.21 — Box Corpus Audit + Import Discovery Hardening

- Replaced the desktop's hand-maintained **Open / Attach data log** filters with a filter generated from the same import registry that routes decoders. Supported native extensions can no longer be added to the decoder layer and accidentally omitted from the default file picker; current Box `*.MaxxECU-Zip-log` files are the concrete regression case.
- Added explicit **support-asset** classification for files that travel with a data set but are not run recordings: RacePak `.rcg`, MoTeC `.ldx`, Holley `.hefi`, FuelTech `.ftm`, MSD Power Grid `.mff`, and BigStuff `.bigTune/.big`. These are excluded from recursive data-log qualification and fail closed with format-specific guidance when selected as a Run log.
- Corrected `.daq` discovery so the actual NHRA corpus is not mislabeled as AEM-only. The current `Race Data` tree contains 802 `7730_*`/Power Grid `.daq` recordings; they are now recognized as a pending MSD Power Grid / ambiguous DAQ family rather than guessed through a generic parser. Added explicit recognition for Power Grid/ReView `.dqi`.
- Added a read-only **corpus qualifier + extension inventory** that can scan a local/Box-synced data tree, report recognized and unknown extensions, deterministically sample each format for a quick smoke pass, optionally skip expensive hashing for a full sweep, and flag suspicious successful decodes such as duplicate columns, broken time, mostly-empty numeric channels, or recordings dominated by flat channels.
- Added `scripts\Audit-NHRA-Velocity-Data.cmd` for a one-click Windows audit. It provides Quick (five files per format) and Full modes and writes qualification + all-extension CSV/JSON reports to a timestamped Desktop folder without modifying source data.
- Documented the 2026-09-17 read-only Box inventory. The largest currently identified native decoder gaps are MSD Power Grid `.daq` (802 scoped files), FuelTech `.ftml` (21), and Power Grid/ReView `.dqi` (one example elsewhere in Box). Raw proprietary Box bytes could not be batch-tested in-session because the connector's advertised binary-download action currently errors, so the Windows corpus audit is the byte-level completion step.

## v0.38.0-dev.20 — Compare Workspace + Portable Worksheet Templates

- Added **Compare Workspace Manager…** (`Ctrl+Shift+R`) as one place to assign Main / Reference / Overlay / Available roles, edit display-only time alignment, auto-align comparison Runs to Main, load existing Compare Sets, and save the live setup as a named Compare Set. Validation requires exactly one Main Run and one Reference whenever multiple Runs are displayed.
- Added portable **Worksheet Templates** with save/apply/manage workflows (`Ctrl+Alt+T` to apply). Templates store Common Channel identities when a plotted parameter is explicitly mapped, so a layout built from RacePak `ENGINE RPM` can resolve to a different explicitly mapped Engine Speed source on another logger. Unmapped raw source channels remain exact references and are never fuzzy matched.
- Worksheet templates may be scoped explicitly to **All vehicles/categories**, **Category**, or **Vehicle + Category**. Applying a template outside its scope is blocked; unavailable exact/common references are reported rather than silently substituted.
- Templates capture dock/display structure, waveform properties, statistics options, trace styles, and the worksheet X-axis mode. Existing workbook persistence remains unchanged.
- Added **Grouped Channels** waveform mode and a per-trace **Axis group** property. Traces share a band only when the engineer gives them the same group name and they also have the same display unit; incompatible units cannot be silently forced onto one scale.
- Existing `Stacked Channels`, `Stacked Units`, and `Overlay` behavior is preserved. Axis-group metadata is ordinary worksheet display state and is included in portable templates/workbooks.
- Daily-workflow regression coverage now tests portable Common Channel resolution across differently named data sets, exact raw-channel failure behavior, contextual template scoping, and the Compare/Template/Grouped-Axis desktop contracts.

## v0.38.0-dev.19 — macOS Portability Guardrails

- Added `MACOS_PLAN.md` with a staged first-class macOS path: portability guardrails, real-hardware engineering beta, Developer ID/notarized distribution, cross-platform updater, and vendor-bridge classification. The intent is one analysis engine/workbook format rather than a Mac fork.
- Added `runlab.platform_support` so packaging/update/native-integration capability decisions are explicit and testable instead of scattered OS checks. macOS is defined around Keychain, `.app` packaging, and no Windows-DLL assumptions.
- Added `macos-latest` to the normal core CI matrix so every future feature is exercised on Windows, macOS and Linux at source-test level.
- Added a dedicated **macOS Development Build** workflow that installs the desktop stack, runs the full suite/native self-tests, builds `NHRA Velocity.app`, launches the real packaged `--smoke-test`, inspects bundle metadata, and uploads an unsigned engineering `.app` ZIP artifact.
- Added `build_macos_app.sh`, `requirements-build-macos.txt`, `setup_macos.sh`, `run_macos.sh`, native `.icns` generation, and a complete macOS `.iconset` derived from the VELOCITY brand assets.
- The first macOS artifact is intentionally unsigned/unnotarized development output. Production DMG/PKG distribution will not be represented as complete until Developer ID signing, hardened runtime, notarization and Gatekeeper verification are CI-gated.
- Current Windows install/update behavior remains unchanged; the existing updater continues to fail clearly outside Windows until the signed macOS distribution/update path is implemented.

## v0.38.0-dev.18 — Branding, Setup Readiness and RacePak Profile Management

- Added a production NHRA Velocity brand asset set under `assets/`: Windows multi-resolution `.ico`, raster app icons, transparent mark/logo PNGs, and SVG mark/lockup files. The compact Windows icon uses a charcoal tile for legibility; transparent logo/mark assets remain available for in-app/documentation use.
- The desktop now loads the bundled Velocity application icon in source and frozen builds, and Help now includes an About dialog showing product identity/version.
- Windows PyInstaller builds now embed the Velocity `.ico` and bundle the brand assets. Inno Setup now uses the branded setup icon.
- Normal installer setup now selects **Create a desktop shortcut** by default. The development updater also repairs/creates `NHRA Velocity Dev.lnk` and assigns the branded icon, so the next update guarantees a usable desktop shortcut.
- Added **Data → Data Log Setup / Readiness…** (`Ctrl+Alt+D`) as a single trackside readiness view for Run authority, managed attachment status, RacePak definition source, Common Channel coverage, math-channel count, launch-zero mode, timing/weather availability, and data warnings. The dialog links directly to Common Channel, Math Channel, and RacePak setup actions.
- Added **Data → RacePak Configuration Profiles…** to inspect reusable Driver+Category / Vehicle+Category profiles, see managed config/channel/status metadata, replace the current context profile, and delete a reusable profile without disturbing exact configurations already pinned to historical DDFs.
- Added profile-management API coverage that surfaces stale/missing managed configurations instead of silently hiding them.
- Corrected the Keyboard Shortcuts help text to describe the current Ref-to-Cursor statistics model and the new Data Log Setup shortcut.

## v0.38.0-dev.17 — Contextual RacePak DDF Config Profiles

- Added managed RacePak DDF configuration profiles so a selected `.rcg` or prior `.rpk` definition can be assigned explicitly to **Driver + Category** or **Vehicle + Category**. There is intentionally no RacePak-vendor-global config rule.
- Added **Data → RacePak DDF Configuration…** and Command Palette access. The dialog shows exact-data-log and reusable-profile authority, validates `_CONNECT4_COMMAND` ids/sample rates against the active DDF, and makes the save scope explicit.
- Selected RacePak configs are copied into Velocity app-data using SHA-256 content addressing. Profiles therefore do not depend on a user's Downloads/USB/card folder continuing to exist.
- When a DDF is attached to an authoritative Tech Services Run, Velocity automatically resolves the applicable config using conservative precedence: **exact data-log config → Vehicle/Category profile → Driver/Category profile → sibling RCG discovery → raw DDF channel IDs**.
- Every attached DDF that successfully uses a config is pinned to the exact managed config fingerprint in its telemetry-session settings. Future edits to the reusable driver/category profile cannot silently reinterpret historical runs.
- Common Channel mappings are kept separate from RacePak config identity. Applying a config supplies source-channel names/units; the engineer still explicitly decides which source is Engine Speed, Driveshaft Speed, etc. Exact Common Channel selections remain higher authority.
- Config changes can translate existing exact Common Channel selections only when the same stable RacePak `_CONNECT4_COMMAND` id exists in both decodes; Velocity does not guess based on similar names.
- DDF parsing now records config SHA/path provenance and warns when a selected config leaves recorded channel ids unmatched. Duplicate ids and sample-rate mismatches continue to fail closed.
- `load_telemetry()` now accepts an explicit `racepak_config_path` for deterministic DDF processing.

## v0.38.0-dev.16 — Context-Safe Common Channel Profiles

- Reworked learned Common Channel behavior around a conservative authority hierarchy: **exact data-log assignment → explicit context profile → importer auto-detection**. An engineer can deliberately choose a different Engine Speed source for one data set without a reusable profile silently changing it back on reopen.
- Added durable per-asset Common Channel and unit settings to the local telemetry-session catalog. For data logs attached to authoritative Tech Services Runs, exact channel selections now survive application restart independently of reusable profiles or workbook state. Catalog schema advances to v9 with an in-place `telemetry_sessions.settings_json` migration.
- Replaced the dev.15 vendor/source-name auto-learning model with narrowly scoped reusable profiles. Supported scopes are **Driver + Category + Logger** and **Vehicle + Category + Logger**. There is intentionally no vendor-global RPM/speed mapping option.
- Context profiles use stable catalog driver/vehicle ids when available, with category and logger vendor as part of the key. Tech Services Run authority now hydrates those stable ids into the decoded data-log context before profile selection.
- Reusable profiles apply **all-or-none**: every mapped source must still exist and be dimensionally compatible. If the logger configuration changed, Velocity applies none of the profile instead of mixing a partial stale profile with new guesses.
- The Common Channel Mapping, Assign Common Channel, and Channel Properties dialogs now make scope explicit. **This data log only** is always available and never deletes or mutates an existing profile; saving a reusable profile is an explicit choice.
- Legacy dev.15 vendor-global learned records are retained in the preference file for audit/migration but are no longer auto-applied.

## v0.38.0-dev.15 — Common Channels + Math Channel Builder

- Split channel naming into two explicit concepts: **Display Alias** is cosmetic/run-local, while **Common Channel** is the stable engineering identity used by comparisons, Quick Graphs, reports, RSA workflows and portable calculations. Friendly roles include Engine Speed, Driveshaft Speed, Vehicle Speed, Throttle Position, pressures, temperatures, acceleration, GPS and more.
- Added **Data → Common Channel Mapping…** (`Ctrl+Alt+M`) with a full-data-set mapping table, expected/source units, dimensional conflict checks, auto-detect, clear/unassign, and vendor-scoped learned mappings. Once an engineer teaches Velocity that a vendor source name means Engine Speed (or another common role), later logs from the same vendor/source name can inherit that mapping automatically when dimensionally safe.
- Added per-channel **Assign Common Channel…** and clarified the existing rename feature as **Display Alias…** so a pretty label can never silently change engineering meaning. Waveform headers and Channel Explorer now prefer the friendly Common Channel label where appropriate.
- Rebuilt **Math Channel Builder…** (`Ctrl+M`) around portable engineering references. Formulas can use stable references such as `@engine_rpm / @driveshaft_rpm`, raw/display-alias backtick references, double-click insertion, function buttons, live validation/preview, engineering-unit assignment and reusable templates.
- Added rolling Min/Max/Std functions and common rate units (`rpm/s`, `mph/s`, `psi/s`, `%/s`) to the safe math engine. Math channels may depend on other math channels; recalculation now topologically orders dependencies and rejects cycles instead of accidentally using stale calculated values.
- Common-channel formulas now work inside the existing portable Analysis Library as well, avoiding a second incompatible math dialect. Friendly names such as `Engine Speed` also resolve interactively while persisted formulas keep stable machine-facing keys.
- Remapping a Common Channel automatically recalculates dependent math channels. Editing/renaming a math channel is validated on a private Run copy before mutation; dependent backtick formulas and active waveform references follow a successful rename, while source evidence can never be overwritten by a math output.
- Workbook loading now restores saved channel/unit mappings before recalculating math channels, preserving deterministic portable formulas rather than allowing global learned preferences to contaminate a saved workbook.
- Packaged desktop smoke testing now exercises a portable Common Channel math calculation in addition to the existing waveform/reference/statistics path.

## v0.38.0-dev.14 — reliability gate and product audit

- Added `PRODUCT_AUDIT_v0_38.md` with a current-state scorecard, immediate product rules, phased execution plan, and explicit 1.0 acceptance test.
- Added `--smoke-test` to the actual desktop entry point. The smoke path is network-free, bypasses account prompts only for the test process, constructs the real MainWindow, renders a representative waveform, enables reference/statistics, and constructs common analysis displays.
- Windows development and release workflows now smoke-test both the frozen PyInstaller executable and the silently installed Inno Setup application. A packaged Qt startup failure now blocks the artifact/release.
- Fixed the Inno Setup version variable mismatch: installer metadata now consumes `NHRA_VELOCITY_VERSION`, the same variable emitted by CI/release workflows.
- Expanded Windows Qt smoke coverage so ordinary Analysis displays are constructed/refreshed with realistic main/reference sessions.

## v0.38.0-dev.13.1 — Windows startup hardening

- Installs native/Python fault capture before `MainWindow` construction so `pythonw.exe` startup failures cannot vanish silently.
- Wraps main-window construction and authentication startup in durable logging/error reporting.
- The Windows dev launcher is replaced by a hidden, blocking WSH/CMD handoff so the application process is not orphaned by a short-lived terminal launcher.
- Normal desktop launch remains console-free while launch/update diagnostics are written to the Velocity local app-data folder.

## v0.38.0-dev.13 — statistics, channel control, analysis consistency, exact re-zero

- Added ATLAS-style **reference-to-live-cursor statistics** directly to waveform band headers. The new **Stats** menu exposes Delta, Minimum, Maximum, Mean and Standard Deviation, with `E/M/X/N/Q` shortcuts and a one-click clear action.
- Statistics use the same red Reference cursor (`R`) and live engineering cursor as the waveform, so the shaded reference region, header statistics, Cursor Region Statistics display and reference-limited spectrum analysis all share one analysis window.
- Added practical channel removal/reordering: right-click a waveform band, **More → Remove channel**, or right-click a Channel Explorer item to remove it from the active waveform.
- Reworked Region Statistics and reference-limited FFT/PSD from the legacy A/B cursor pair to the visible Reference→Cursor model.
- Hardened manual launch re-zero: the selected displayed cursor position is first converted back to logger time, snapped to the effective logger sample, persisted as that exact sample, and any display-only alignment is cleared. Reference/B cursor positions are translated so they remain on the same physical samples.
- Added focused UI/source contract coverage for waveform statistics, channel management, quick-analysis construction and repeat manual re-zero.

## v0.38.0-dev.12 — live cursor readout + durable Run data + event scope fix

- Fixed the compact waveform headers so **current value, reference value and delta update continuously with cursor/reference motion** even when the optional detailed table is hidden. dev.11 incorrectly returned early from the coalesced readout path when the table was hidden, so cursor lines moved while displayed values remained stale until another action forced a redraw.
- Strengthened local Run-data persistence beyond the database link. Velocity's content-addressed object store intentionally names managed files by SHA-256, but that removed source extensions required for fail-closed native decoder dispatch on reopen. Managed Assets now expose a filename-preserving hard-link alias (copy fallback), so `.ld`, `.rpk`, `.dlz`, `.MaxxECU-log`, CSV and other supported files remain decodable after restart while retaining verified/deduplicated storage.
- Updated workbook and synchronized-review reopen paths to use the decoder-safe managed Asset path, repairing older workbooks/catalog rows that remember an extensionless content-addressed path.
- Selecting a Tech Services Run with an attached locally managed data log now **auto-reopens the attached data after a short debounce**. This makes the attachment behave as part of the Run while avoiding repeated decode work as the user rapidly arrows/searches through the Run list.
- Fixed the compact Run-browser event scope. **Current / last completed** now selects an event underway today when applicable; otherwise it selects the most recently completed event. Future events can no longer win simply because the catalog sorts `start_date DESC`. Search and All events still span the full synchronized catalog.
- Added regression coverage that actually reopens and decodes a managed data log from its catalog attachment, plus explicit guards for live header refresh, event prioritization and attached-data auto-reopen behavior.

## v0.38.0-dev.11 — ATLAS-style waveform interaction + workbook shell

- Reworked the Waveform left-button interaction so **click or left-drag anywhere in the plot moves the engineering cursor**. The user no longer has to hit the one-pixel cursor line to scrub a run. Middle-drag remains available for X-axis panning.
- Fixed keyboard handling by binding Waveform shortcuts with `WidgetWithChildrenShortcut`, so focus inside pyqtgraph no longer makes **R / + / -** appear to stop working.
- Implemented the ATLAS-style **Reference Cursor** behavior: `R` adds a red reference at the current cursor position, `R` again removes it, and a subtle shaded window shows the analysis range between the live and reference cursors. The normal legend/readout shows reference values and deltas only while the reference is active.
- Restored `+` / `-` X-axis zoom and added `Ctrl+Z` previous-view plus `Ctrl+Alt+Z` fit-run behavior. Keyboard zoom is centered on the live cursor when it is inside the visible range.
- Replaced the always-visible waveform value table with **compact per-band headers** embedded directly in each waveform plot. Each band shows channel name, current value/unit and, when active, reference value + delta. The detailed table is still available under **More → Detailed channel table**.
- Narrowed stacked Waveform Y axes to numeric/unit scales; channel names and live values now live in the plot header rather than consuming vertical axis-label space.
- Tightened the Run browser so its action buttons no longer force an oversized left dock. Primary and secondary actions are split into compact rows and the default dock target is narrower.
- Improved the workbook shell with compact document-style worksheet tabs, a `+` worksheet button and **Ctrl+Enter Focus Analysis** mode that temporarily hides side docks for a full-width waveform review.
- Refined the application stylesheet for denser headers, tabs, toolbars, splitters and tables while retaining the existing dark trackside theme.

## v0.38.0-dev.10 — trackside waveform + Run-browser usability

- Changed the waveform cursor to the established ATLAS-style interaction: **click to position**, **drag the vertical cursor line to scrub**, and arrow keys for sample-precise movement. Merely hovering over a graph no longer moves the engineering cursor. Shift-click and Ctrl-click continue to place A/B cursors.
- Mouse-wheel and normal plot navigation now operate on the **X axis only** in Waveform displays. Y remains auto-scaled (or explicitly set in Trace Properties), preventing accidental vertical rescaling while reviewing a pass.
- Reworked the waveform live-value table into a denser readout: smaller rows, up to seven immediately visible channels, and only Channel / Unit / Cursor / Ref / Δ shown by default. Min / Max / Mean / Std remain available under **More → Readout columns**.
- Renamed the everyday source-file workflow from *telemetry* to **data log** throughout the primary UI. The application title is now **NHRA Velocity — Data Analysis**. Internal telemetry/data-model terminology remains unchanged where technically appropriate.
- Simplified the NHRA Tech Services Run browser: opaque `tech-services:<UUID>` values are no longer displayed as Run names; rows use Run number / car number / lane / time context instead, and a dedicated **Data** column makes attached Run data obvious.
- The Run browser now defaults to **Latest event** for a compact trackside view, with **All events** one click away. Entering a search automatically spans all synchronized events.
- Strengthened the local Run-data association UX. Selecting a canonical Run reactivates its already-loaded data log, locally managed Run data is visibly marked, and attachment metadata explicitly records local persistence. Added regression coverage proving the canonical Run → managed data-log link survives closing and reopening the local catalog.
- Removed a duplicate `add_channel` method declaration found during the usability cleanup.

## v0.38.0-dev.9 — manual launch re-zero + Run-browser polish

- Added an explicit waveform **Zero** control. Place the cursor at the true launch point and choose **Set Cursor as Launch (T=0)**; every Time/Distance-from-Launch view, drag-run fit window and official beam overlay then uses the corrected launch anchor without modifying raw logger samples or NHRA official timing.
- Added **Use Auto-Detected Launch** to remove a manual zero and return to the detector. The waveform visibly shows **Zero: Auto** versus **Zero: Manual** so the review state is never hidden.
- Manual launch zero is persisted in `.nhratech` workbooks and, for a catalog-attached telemetry Asset, in the local Asset→Run time mapping with an explicit zero-time anchor. Reopening the Run restores the engineering correction.
- The Run browser now exposes **Sync Tech Services** directly and renames the local-only button to **Refresh View**, avoiding the previous ambiguity between a local repaint and a server synchronization.
- Catalog-attached telemetry sessions now use the canonical driver/round as the toolbar label instead of exposing an opaque managed-storage/Asset filename when one source is attached.
- Added launch-zero regression coverage and kept the raw logger clock immutable.

## v0.38.0-dev.8 — staged background sync + account/access UX

- Reworked NHRA Tech Services season synchronization so it no longer blocks the desktop while every event is downloaded. Velocity now prioritizes the current event, or the most recently completed event when between races, refreshes the Run browser as soon as that first event is ready, and continues the rest of the season in a background Qt worker.
- Added live status-bar progress for background season hydration instead of a long modal wait cursor. The existing manual sync action remains read-only and can still include Tech Master entries plus official timing/canonical weather.
- On an authenticated first launch with an empty local catalog, Velocity automatically begins the useful-first current/latest-event sync rather than presenting an unexplained empty Run browser.
- Account actions now reflect actual state: signed-out users see **Sign in**; signed-in users see **Sign out**; the Account item identifies the active Tech Services identity.
- Source/development builds now enforce NHRA Tech Services authentication by default, matching packaged builds now that the production website auth adapter is bound. Controlled CI/development can still opt out explicitly with `NHRA_TECH_DEV_UNAUTHENTICATED=1`.
- Added event-priority regression coverage; full automated suite passes at 223 tests.

## v0.38.0-dev.7 — Windows Tech Services sign-in fix

- Fixed Windows Credential Manager failure (`CredWrite`, WinError 1783) seen after a valid Tech Services login, especially for owner/admin accounts with large capability sets.
- Tech Services credential persistence now stores only the minimum restorable secret: the seven-day access token and its expiry. Identity, role and capabilities are refreshed from the server on restore rather than duplicated in the Windows credential blob.
- Added an explicit Windows credential-size guard so an oversized vault payload produces a useful error instead of the cryptic OS error.
- A credential-vault write failure no longer masquerades as a bad login. If the server authenticated successfully, Velocity keeps the in-memory session active and explains that the user may need to sign in again next launch.
- Password handling is unchanged: the password is never persisted. No plaintext credential fallback was added.

## RacePak raw DDF import

- Added direct decoding of RacePak `.DDF` logger files so supported raw recordings no longer require DataLink conversion to `.RPK` before analysis.
- Qualified the decoder against real RacePak data and retained fail-closed configuration/channel naming behavior when the logger definition is unavailable.

## NHRA Tech Services identity and read-only data integration

- Bound the existing `nhratechservices.com` first-party login endpoint with no server/repository changes. Passwords are used only for the HTTPS credential exchange and are never persisted; the returned seven-day Bearer token is stored only in the OS credential vault.
- Refreshes the account's live server capabilities and maps them conservatively to NHRA Velocity desktop entitlements.
- Added read-only synchronization of Tech Master Events, Event Entries and official parity timing Runs into the local Velocity catalog.
- Preserves the server's current contract boundary: Velocity does **not** infer Event Entry → Run ownership while `event_entry_id` is absent from the parity response, and it does not invent a Run → telemetry Asset endpoint.
- Tech Services application data remains GET-only in this integration; no website records are created, edited or deleted.


## Canonical Tech Services weather hydration

- Velocity now prefers the existing read-only `parity.php?action=runsWithWeather` endpoint when synchronizing official Runs, so the local Run mirror carries the nearest canonical Tech Services weather snapshot in addition to official timing.
- Site weather fields are translated into Velocity's canonical environment names while retaining the server timestamp, join delta, source kind/detail, and sample provenance as evidence metadata.
- If the weather-join endpoint is unavailable, sync fails over to the existing timing-only `action=runs` GET and reports the fallback instead of failing the whole event. No Tech Services writes are introduced.
- The audited website still does not expose `parity_runs.event_entry_id` in a read response, so Entry→Run ownership remains unresolved rather than guessed.

## Authoritative Run-first local telemetry bridge

- Added an explicit **Attach Local Telemetry…** workflow from the synchronized NHRA Tech Services Run browser. The engineer selects the canonical Run first; Velocity never chooses the Run from a filename, driver name, car number, or folder.
- Attached telemetry is copied into Velocity's SHA-256-addressed managed local object store and linked to the selected local mirror Run as a clearly labeled **Local working attachment**. This association is workstation state only and is never uploaded to or presented as a permanent Tech Services Asset.
- Opening a Run now hydrates every attached telemetry session with the authoritative catalog Run context. Official timing and weather win over logger/user session values, while the complete official timing record remains available in metadata for RT/DQ/MOV-style fields outside the compact `TimingData` model.
- Fixed Tech Services 330-ft normalization so `ft330` maps to the canonical `three_thirty_ft_s` field instead of being stranded under an unrecognized key.
- Run Assets now distinguish **Tech Services**, **Local working attachment**, and scratch/development authority plus remote/cached/managed-local state.
- Direct **Open Log…** remains scratch-only; the new Run-first attachment action is the only local path that creates an explicit Run association.


## Usability simplification / progressive disclosure (dev.6)

- Simplified the permanent toolbar to the ordinary trackside path: Open, Save, Fit Run, active Run, X-axis mode, and optional Compare/Reference. Class-profile and Quick Graph controls remain available from menus/commands instead of occupying permanent width.
- Compare Reference controls are hidden until Compare is enabled.
- The default **Simple Workspace** now keeps the authoritative Run browser, Run Workspace and Channel Explorer available while hiding investigation/diagnostic tooling. Run Browser and Channel Explorer share one left-side tab group instead of consuming two panes.
- Channel Explorer now defaults to **Essentials**: favorites plus the class-relevant standard channels for the active Run. **All channels** is one selector away, and entering a search always searches the complete logger channel catalog.
- Applying a standard class layout now creates one useful core waveform (up to eight class-relevant channels) instead of automatically filling the worksheet with multiple waveform panels.
- Applying a class layout no longer generates a Pro Stock report as a side effect; standardized reports remain an explicit Run Workspace action.
- Automatic first-view channel selection prefers the authoritative Run class profile when available, while preserving existing user-customized waveform selections.
- Collapsed the Run Workspace from five top-level tabs to three: **Summary**, **Data**, and **Engineering**. Report fingerprints/version/source details remain available as tooltips instead of crowding the everyday table.
- Advanced class-layout/report actions moved under a single **More** menu in the Run Workspace.

## Run-first engineering workspace (dev.5)

- Added a dedicated **Run Workspace** centered on the authoritative NHRA Tech Services Run rather than on a logger filename/session.
- One view now combines official timing, canonical weather, attached telemetry evidence, class-specific RSA defaults, engineering values, standardized reports and model snapshots.
- Applying a class layout from an authoritative Run uses the synchronized NHRA category as the profile seed; filename-based Run/category inference is still prohibited.
- Added catalog schema v8 `run_reports`: standardized derived reports are immutable/fingerprinted Run metadata with optional source-Asset provenance. Re-running an identical report is idempotent.
- Pro Stock shift reports generated from an authoritative Run are now persisted to the catalog, not only to workbook memory.
- The Run Workspace compares the latest Pro Stock shift report against the nearest prior report for the same canonical driver/category and flags shift RPM/time deltas that exceed report thresholds.
- Corrected Tech Services timing translation for 60 ft and 1000 ft values and added canonical 1000-ft MPH support to `TimingData`.
- Re-opening an already-loaded catalog telemetry Asset now activates the existing session instead of duplicating it.
- Application identity is now `NHRA.Velocity`; historical source/release records retain their original names.
