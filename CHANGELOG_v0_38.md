# NHRA Velocity v0.38 development

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
