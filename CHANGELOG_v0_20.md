# Changelog — v0.20

## Synchronized Case Review

- Added `runlab.case_playback`, a headless shared-cursor review engine for AnalysisCases.
- One Case-time cursor resolves every case member Asset to Run time and, when mapped, Asset-local time.
- Added optional media duration and frame-rate metadata handling for review extents and frame stepping.
- Added active/previous/next marker resolution at any Case time.
- Added a pure `CasePlaybackController` for stepping, marker navigation, clamping and UI-independent playback state.
- Added synchronized nearest-sample readout for telemetry/IDR-compatible numeric sources.

## Desktop

- Added **Synchronized Case Review** dock.
- Case-time slider/spinbox, play/pause, 0.25×/0.5×/1×/2× playback, previous/next marker, and frame stepping.
- Source table shows Run time, Asset time, cache state and synchronization uncertainty for every case source.
- Cached video/audio assets seek through Qt Multimedia using the stored Asset→Run→Case mappings.
- Telemetry/IDR-compatible numeric sources receive a case-time plot preview plus nearest-sample readout.
- Moving the Case cursor also drives the active catalog telemetry session to the corresponding raw source time where possible.
- Remote Tech Services assets remain visibly remote until the normal SHA-256-verified cache exists.

## CLI

- Added `catalog case-playback --case-id ... --case-time ...` for headless inspection of synchronized review state.

## Persistence

- Catalog schema remains **v7**. Playback state is derived; no new evidence authority or hidden synchronization table was added.
