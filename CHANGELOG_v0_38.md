# NHRA Velocity v0.38 development

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
