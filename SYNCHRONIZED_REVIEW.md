# Synchronized Case Review — v0.20

## Objective

The review cursor represents **Analysis Case time**. It is not a video clock, logger clock or hidden desktop offset.

For each source:

```text
Case time -> Run time -> Asset time
```

The mappings are the inverses of the already-auditable Asset→Run and Run→Case synchronization stages.

## Source state

At a given Case timestamp the review engine reports, for every Run Asset:

- owning Run and case role;
- resolved Run time;
- resolved Asset-local time when the Asset is mapped;
- source type (video, audio, telemetry, IDR, other);
- local cache availability;
- optional duration and frame rate;
- approximate frame index;
- in/out-of-source-range status;
- synchronization method and uncertainty.

No filename matching or Run inference occurs.

## Media

Cached video/audio can be opened by Qt Multimedia. The desktop seeks the selected media source to the Asset timestamp derived from the Case cursor. The application never edits or transcoded the permanent source as part of synchronization.

The current review UI displays one selected media source at a time while still calculating positions for every source. Additional tiled/multi-camera views can reuse the same review frame without creating another synchronization model.

## Numeric / IDR evidence

Any telemetry or IDR export that can already be decoded into `TelemetryRun` can participate immediately. The review panel:

1. maps its source time into Case time for plotting;
2. moves one vertical Case cursor through that preview;
3. reports nearest numeric samples at the corresponding Asset time.

Native IDR binary formats that are not yet decoded fail closed. Adding a native decoder later does not change the synchronization architecture.

## Playback

Playback is a derived UI clock. A monotonic timer advances Case time at 0.25×, 0.5×, 1× or 2×. Media playback is corrected back toward the authoritative Case-derived position if it drifts materially.

Frame stepping uses Asset frame-rate metadata when available; otherwise it uses a conservative 10 ms step. Marker navigation jumps to the previous/next resolved AnalysisCaseMarker.

## Offline behavior

A mirrored server Asset that has not been cached is reported as remote, not viewable. The review dock can request the normal Tech Services cache path; downloaded bytes still pass through the existing SHA-256 verification and content-addressed object store.
