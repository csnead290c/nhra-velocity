# Desktop UI Roadmap — v0.19+

## Current model

The left-side **NHRA Tech Services Runs** browser represents the mirrored server catalog. It is run-centric, not file-centric.

Current controls:

- search Events/Drivers/Runs;
- open a Run and all telemetry Assets already attached to it;
- inspect the Run's permanent Asset manifest;
- cache a Run/Event offline;
- create an AnalysisCase from a selected Run;
- add baseline/comparison/reference Runs to an existing case;
- browse cases and reopen member Runs;
- cache all Run Assets used by a case;
- inspect official timing/weather/source provenance;
- inspect/edit local time mappings and analysis metadata;
- use the **Case Timeline / Sync** dock to fit Asset→Run and Run→Case anchors;
- create source-aware case markers that remain tied to their original clock domain;
- create versioned Run model snapshots, with case-scoped model storage available for future multi-run fitting.

Direct **Open Log** remains a scratch workspace and does not create permanent catalog identity.

## After the real Tech Services API is bound

Add:

- Refresh / Sync catalog button with status and last-sync time;
- selective Event/Run offline download manager;
- cache progress/cancel/retry;
- clear-cache controls that explicitly leave server data untouched;
- server upload shortcut only if the production API intentionally supports raw Asset upload from the desktop;
- approved push-back of derived analyses/models/annotations with clear permission state.

## Multi-source workspace

The shared AnalysisCase timeline and synchronization editor are now in place. Next, add synchronized media/IDR playback panels that consume the existing Asset→Run→Case mappings, plus richer marker navigation and side-by-side comparison controls. Case-only evidence should join the same workspace without becoming a fake Run Asset.

## Avoid

Do not add:

- filename/path-based Run matching;
- archive browsing as a production data source;
- automatic re-parenting of server Assets;
- silent upload of scratch files;
- any UI that makes the local cache appear authoritative.
