# NHRA Velocity v0.38 Development Validation

Validated build: **0.38.0-dev.24**

### dev.24 Windows smoke-gate hotfix
- Fixed the smoke scenario to count the real `WaveformDisplay._plots` collection.
- The prior `wave.plots` access raised `AttributeError` only when the real Qt smoke scenario ran on Windows.
- Smoke failures now print their exception and traceback directly in the updater console in addition to the log file.
- Source suite: 301 passed, 1 skipped.
- Native decoder self-tests: 3/3 passed.
- Strict release audit: 0 errors / 0 warnings after manifest update.


## Scope

This validation covers the dev.23 RacePak corpus-evidence safety redesign on top of the dev.22 mining foundation, dev.21 Box corpus-audit/import-discovery hardening, dev.20 Compare Workspace / portable worksheet-template work, and the existing v0.38 data-log, Run-workspace, analysis, persistence, packaging, and reliability foundation.

## Results


## dev.23 RacePak evidence-safety validation

- Complete source suite: **300 passed, 1 skipped** across two batches in the Linux packaging environment.
- RacePak / MoTeC / MaxxECU native self-tests: **3/3 passed**.
- Strict release-consistency audit: **0 errors / 0 warnings** with the pinned upstream SHAs supplied.
- Numeric RacePak channel-id history is now regression-locked as **suggestion only**. Even three or more consistent semantic configurations cannot rename an unknown DDF channel by id alone.
- Exact automatic source-name recovery is limited to a complete DDF descriptor-table SHA-256 that was learned from a real DDF fully matched to a sibling RCG. Changing only a descriptor sample rate changes the fingerprint and blocks recovery.
- Conflicting source definitions observed for the same exact descriptor fingerprint fail closed and leave the DDF generic.
- Corpus-derived source identity still leaves the Common Channel map time-only until the engineer explicitly maps engineering roles.
- DDF structure-only parsing now reads only the header/descriptor table from file paths, allowing large corpus fingerprint scans without loading full payloads.
- The current Linux packaging environment does not contain PySide6, so the real desktop `--smoke-test` cannot run here; the Windows updater and Windows/macOS CI packaging lanes remain the authoritative Qt smoke gates.

## dev.22 empirical RacePak channel-id validation

> **Superseded by dev.23:** dev.22 allowed conflict-free numeric ID history to rename a configless DDF. dev.23 intentionally removes that authority; ID history is suggestion-only.

- Full automated suite: **297 passed, 1 skipped** in the Linux packaging environment.
- Added regression coverage proving repeated race files from one identical RacePak configuration count as one semantic vote rather than manufacturing consensus confidence.
- Three distinct conflict-free configuration signatures are required before a numeric `_CONNECT4_COMMAND` id is safe for automatic source-label fallback. Two-source agreement remains visible but is not auto-applied.
- Conflicting source names fail closed. Conflicting non-empty units also block fallback.
- A configless DDF can use a verified installed corpus definition to recover a source name/unit while retaining the RacePak numeric id and evidence count as channel metadata.
- Corpus-derived source naming does **not** assign any VELOCITY Common Channel; regression coverage explicitly requires the configless run's canonical map to remain time-only until the engineer maps a role.
- Exact RCG/RPK config and context profiles remain higher authority than the empirical library.
- Native decoder/plot self-test remains **3/3 passed** for RacePak, MoTeC, and MaxxECU.

## dev.13 analysis/workflow hardening

- Non-Qt automated suite: **241/241 passed** in two batches; the additional offscreen Qt smoke module is skipped in this Linux validation environment when PySide6 is unavailable.
- Focused dev.13 contract/smoke coverage passed where runtime dependencies were available, covering statistics toggles, channel removal, reference-to-live-cursor analysis semantics and repeated launch re-zero.
- `python -m compileall -q desktop.py runlab` passed.
- Manual re-zero now clears display-only alignment and persists the effective snapped logger sample, preventing the apparent first-use offset seen in dev.12.
- Legacy A/B analysis consumers used by Region Statistics and reference-limited Spectrum now follow the visible Reference→Cursor region.


- Full automated suite completed **238/238 tests** (99 + 139 in two groups to stay below the execution wall-clock limit).
- `python -m py_compile desktop.py` passed.
- New dev.12 regression coverage verifies:
  - compact per-band current/reference/delta values are scheduled for refresh on every cursor/reference move even when the detailed table is hidden;
  - a managed Run attachment can be reopened from a fresh catalog instance and actually decoded through its original filename/extension, not merely found as a database row;
  - compact Run scope prioritizes the current event or most recently completed event ahead of future database rows;
  - selecting a Run with local attached data schedules an automatic reopen after a short debounce.
- New source-level regression coverage verifies:
  - left-drag-anywhere waveform cursor ownership through `VelocityWaveformViewBox`;
  - Widget-with-children shortcut binding for `R`, `+`, and `-`;
  - reference cursor capture/visibility/range-window behavior;
  - compact per-band waveform headers replacing the always-visible detailed value table;
  - document-style worksheet tabs, worksheet `+` control and `Ctrl+Enter` focus mode;
  - compact Run-browser action layout that no longer forces an oversized left dock.
- Existing launch-zero, Run/data-log persistence, Tech Services metadata, import, analysis, reconstruction, fit-study, display-cache and workbook regressions all remained green.

## Waveform interaction regression

The dev.11 Waveform interaction intentionally follows the verified ATLAS model where practical:

- hover does not change engineering state;
- click positions the live cursor;
- left-drag anywhere in a waveform scrubs the live cursor;
- middle-drag retains X-axis pan;
- mouse-wheel and keyboard zoom operate on X only;
- `R` adds/removes a red reference cursor at the current cursor position;
- a shaded window identifies the live↔reference analysis range;
- `+` / `-` zoom around the live cursor when it is visible;
- `Ctrl+Z` returns to the previous view;
- `Ctrl+Alt+Z` fits the drag run.

## Workbook / desktop usability regression

- Primary waveform remains the worksheet center.
- Live channel values move into compact plot-band headers so graph area is not consumed by an always-visible table.
- Detailed channel values/statistics remain opt-in under **More → Detailed channel table**.
- Worksheet tabs use document-style presentation and expose a compact `+` control.
- `Ctrl+Enter` toggles **Focus Analysis**, temporarily hiding application side docks for full-width waveform review.
- Run-browser primary/secondary actions are split into compact rows and the normal simple-workspace dock targets are narrower.

## Authority / persistence invariants

No source evidence, official NHRA timing, canonical weather, or Tech Services Run identity is rewritten by these UI changes. Manual launch zero remains an analysis coordinate override. Local data-log attachments remain explicit managed Velocity associations to an authoritative Run and are not uploaded or inferred from filenames.

## dev.12 persistence root cause

The earlier persistence regression only proved that the Run→Asset row and managed SHA-256 object survived a catalog reopen. It did not prove that the managed bytes could be decoded again. The object store uses extensionless hash filenames by design; native decoder routing is deliberately extension-aware/fail-closed. dev.12 adds filename-preserving aliases for read/decode while keeping the underlying content-addressed object authoritative and hash-verifiable.

## dev.14 reliability-gate validation

- Source regression includes release-pipeline contract checks for the packaged desktop smoke path, installer version plumbing, and workflow gates.
- Windows development and tagged-release workflows now validate both the frozen and installed desktop with `--smoke-test`; these are intended to catch startup/Qt/PyInstaller regressions that source-only tests cannot detect.
- The packaged smoke scenario exercises MainWindow construction, pyqtgraph rendering, live/reference cursor statistics, and representative Analysis displays without network access.
- A broader Qt-only test constructs the normal daily Analysis display set with realistic main/reference sessions; it runs on Windows build agents where PySide6 is installed.


## dev.16 context-safe Common Channel profile validation

- Full automated suite: **260 passed, 1 Qt-only test skipped** in the Linux packaging environment.
- Exact per-data-log Common Channel and unit overrides now persist in `telemetry_sessions.settings_json`; catalog schema migration v9 is exercised by catalog regression coverage.
- Reusable Common Channel profiles are limited to **Driver + Category + Logger** or **Vehicle + Category + Logger**. No vendor-global learned mapping is offered or auto-applied.
- Profile matching uses stable Tech Services catalog driver/vehicle ids when available and includes category + logger vendor in the profile identity.
- A profile is applied **all-or-none**. Missing sources or dimensional conflicts cause the entire reusable profile to fail closed rather than partially overriding a new logger configuration.
- Regression coverage verifies that the same vendor/source name does not cross drivers, categories, or vendors; context-free scratch logs cannot create an auto-applied profile; changed logger configurations reject stale profiles.
- Exact attached-data settings are stored independently of reusable profiles so one data set may intentionally select a different Engine Speed source than another.
- Native decoder/plot self-test: **3/3 passed** for bundled RacePak, MoTeC and MaxxECU pipelines.
- Strict release audit with verified RSA/Tech Services SHAs: **0 errors / 0 warnings**.

## dev.15 Common Channel / Math validation

- Full automated source suite: **257 passed, 1 Qt-only test skipped** in the Linux packaging environment before final documentation/version updates.
- Added focused regression coverage for Common Channel labels, explicit assign/unassign behavior, vendor-scoped learned mappings, dimensional-safety rejection, friendly-label resolution, portable `@common_role` calculations across differently named vendor data sets, display-alias references, reusable math templates, rolling engineering functions, remap-driven recalculation, dependency ordering/cycle rejection, and Analysis Library interoperability.
- Native decoder/plot self-test: **3/3 passed** for bundled RacePak, MoTeC and MaxxECU pipelines.
- `python -m compileall -q desktop.py runlab tests` passed.
- Strict release audit with the pinned RSA/Tech Services SHAs reports **0 errors / 0 warnings**. The manifest remains pinned to those verified upstream revisions.
- Workbook loading explicitly suppresses global learned Common Channel preferences, restores workbook-specific mappings first, then reapplies math definitions. This preserves saved-project determinism.
- Math dependency reapplication removes stale calculated results, evaluates definitions in dependency order, and rejects cycles so a remap cannot silently produce a dependent channel from an old intermediate value.

## dev.17 RacePak DDF config-profile validation

- Full automated suite: **265 passed, 1 Qt-only test skipped** in the Linux packaging environment before final version/documentation-only edits.
- Added regression coverage proving an explicit `.rcg` can name/unit a DDF through `load_telemetry(..., racepak_config_path=...)`.
- Driver+Category profiles are context-isolated: another driver in the same category does not inherit the config. Vehicle+Category profiles intentionally win over the broader Driver+Category profile when both are present.
- Selected configuration files are copied into Velocity-managed app data and remain usable after the original source file is deleted.
- Exact telemetry-session bindings take precedence over reusable profiles and are hash-verified before use.
- DDF/config mismatch handling remains fail-closed for duplicate `_CONNECT4_COMMAND` ids and sample-rate mismatches; partial channel-id coverage is surfaced as a data warning rather than silently guessed.
- The existing Common Channel layer remains independent, so a RacePak config can define a channel name without automatically declaring that signal to be the engineering Engine Speed/Driveshaft Speed source.

## dev.18 branding / setup-readiness validation

- Full automated suite: **269 passed, 1 Qt-only test skipped** in the Linux packaging environment before final version/documentation-only edits.
- Added release-pipeline coverage proving the branded `.ico`/PNG/SVG assets exist, PyInstaller embeds the icon/assets, Inno Setup uses the branded setup icon, and the desktop-shortcut task is selected by default for normal installations.
- Added reusable RacePak profile-manager regression coverage for listing/deleting profiles by persisted key and surfacing stale managed configurations as invalid instead of silently dropping them.
- Python compilation passed. RacePak/MoTeC/MaxxECU native self-tests remain **3/3 passed**. Strict release audit with pinned RSA/Tech Services SHAs remains **0 errors / 0 warnings**.
- The next Windows updater additionally runs the complete suite, native decoder self-test, strict release audit and the real Qt desktop smoke scenario before pushing `develop`.


## dev.19 macOS portability validation

- Core CI matrix now targets **Windows + macOS + Linux** on Python 3.13.
- Dedicated macOS workflow builds the real PyInstaller `.app` bundle and runs the same network-free `--smoke-test` used by packaged Windows validation.
- Added platform-contract regression coverage for stable platform ids, macOS Keychain/app-bundle capability reporting, Windows installer preservation, and `~/Library/Application Support/NHRA Velocity` app-data behavior.
- macOS packaging includes the production VELOCITY iconset and bundle id `com.nhra.velocity`. Development artifacts remain explicitly unsigned until Developer ID/notarization gates exist.


## dev.20 Compare / template / grouped-axis validation

- Full automated suite: **283 passed, 1 Qt-only test skipped** in the Linux packaging environment before final version/documentation-only edits.
- Portable worksheet-template regression proves mapped Common Channels resolve across differently named logger sources while unmapped raw source references require an exact match and surface missing inputs instead of guessing.
- Template scope regression verifies Vehicle+Category is more specific than Category, Category does not leak across classes, and global templates remain explicit user-selected reusable layouts rather than automatic behavior.
- Compare Workspace Manager keeps alignment as display-only state and validates one Main plus one Reference for an active multi-Run comparison. Existing Compare Set serialization remains the persistence layer.
- Grouped Channels shares a plot band only for the same explicit axis-group name and exact display unit; this prevents accidental mixed-unit axes.
- `python -m compileall -q desktop.py runlab tests` passed.


## dev.21 Box corpus / import-discovery validation

- Full automated suite: **294 passed, 1 Qt-only test skipped** in the Linux development environment.
- `python -m py_compile desktop.py runlab/import_registry.py runlab/importers.py runlab/qualification.py runlab/cli.py` passed.
- Native RacePak / MoTeC / MaxxECU pipeline self-test: **3/3 passed**. Strict release audit with the pinned RSA/Tech Services reference SHAs: **0 errors / 0 warnings**.
- Regression coverage proves the default Qt file filter is generated from the import registry and includes `*.MaxxECU-Zip-log`, `.rpk.bin`, and `.ld.bin` without relying on a second hand-maintained extension list.
- Support/configuration assets (`.rcg`, `.ldx`, `.hefi`, `.ftm`, `.mff`, `.bigTune/.big`) are recognized but excluded from data-log qualification and return explicit format-specific guidance instead of falling through to generic text parsing.
- `.daq` no longer routes as AEM by extension alone; current NHRA Power Grid recordings remain recognized/fail-closed until a signature-qualified decoder exists. `.dqi` is recognized as the Power Grid/ReView log family.
- Corpus qualification now records decoder-independent integrity indicators for non-increasing time, duplicate columns, mostly-nonfinite numeric channels, and recordings dominated by constant numeric channels.
- All-extension inventory output intentionally includes unrecognized suffixes, preventing unsupported families from disappearing merely because they are absent from the registry.
- The read-only Box metadata survey is documented in `BOX_DATA_FORMAT_AUDIT_2026-09-17.md`. Byte-level validation of proprietary Box files remains a local/Box-synced audit step because the Box connector's advertised raw-download action returned `Tool get_download_url not found` during this validation.


## dev.27 corpus-audit source-availability validation

- Full automated suite: **308 passed, 1 skipped**.
- Added regression coverage proving cloud/on-demand source failures are classified as source availability problems rather than decoder failures.
- Added regression coverage proving non-PKZIP `*.MaxxECU-Zip-log` samples are surfaced as format variants with header evidence instead of being silently reinterpreted.
- Added regression coverage proving an empty RacePak census cannot overwrite a previously useful installed evidence library and that scan roots are preserved in the report.


## dev.28 recovery durability / corpus-root validation

- Complete automated source suite: **311 passed, 1 skipped**.
- Added a headless regression contract that verifies every `runlab.project_io` helper referenced by `desktop.py` is explicitly imported, preventing the background autosave `NameError` found in the real Windows log.
- The packaged desktop smoke scenario now forces a real recovery snapshot write/read and rejects a build whose recovery file is absent or empty. This gate will run on the user Windows machine and in packaged desktop CI where Qt is available.
- Data-audit regression verifies the audit wrapper does **not** pass `--install`; RacePak evidence must be reviewed before runtime installation.
- The audit wrapper now performs a native-logger preflight and warns/halts by default when fewer than 10 strong/native logger files are found, which specifically catches accidental broad folders such as generic Documents trees.
- Native RacePak/MoTeC/MaxxECU self-test: **3/3 passed**.
- Strict release audit with verified RSA/Tech Services SHAs: **0 errors / 0 warnings**.
- Local Linux packaging environment does not contain PySide6, so the revised Qt desktop recovery smoke is intentionally proven again by the Windows updater before push.
