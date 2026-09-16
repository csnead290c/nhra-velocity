# NHRA Velocity v0.38 development

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
