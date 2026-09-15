# Analysis Case Timeline — v0.20

## Principle

Synchronization is a composition of two independent mappings:

```text
raw Asset clock  →  authoritative Run clock  →  Analysis Case clock
```

The raw evidence is immutable. Synchronization changes coordinates used for analysis and display; it never rewrites source timestamps or changes Run/Asset ownership.

## Asset → Run

`TimeMapping` remains one-to-one with a Run Asset. The affine mapping is:

```text
run_time = asset_scale × asset_time + asset_offset
```

It stores method, confidence, uncertainty and synchronization anchors. One anchor solves offset; two or more anchors can solve constant clock-rate drift.

Typical anchors include launch flash/audio, ignition event, shift, impact spike, parachute event, or another signal visible in both sources.

## Run → Case

Each `AnalysisCaseRun` has its own rigid time alignment:

```text
case_time = run_time + run_offset
```

This is separate from Asset synchronization. A primary incident Run might use its launch as case `t=0`, while a historical baseline Run can also be launch-aligned to `t=0`; alternatively, an investigation can set impact or another event to a convenient case timestamp.

The same Run can belong to two cases with different Run→Case offsets because the mapping describes the engineering comparison, not the canonical Run itself. Canonical Run seconds are never stretched to make anchors fit; multiple anchors instead produce an alignment uncertainty.

## Composition

For an Asset attached to a case member Run:

```text
run  = a × asset + b
case = run + d

case = a × asset + (b + d)
```

`runlab.case_timeline` exposes this composed mapping while preserving both stored stages. Uncertainty is propagated in time units and the conservative combined confidence is the lower available confidence.

## Source-aware case markers

`AnalysisCaseMarker` records the original time domain and timestamp:

- `case` — analyst-defined directly in case time;
- `run` — tied to a member Run timestamp;
- `asset` — tied to a raw Asset timestamp.

Markers are resolved dynamically when listed. If a video or IDR mapping is refined, an impact marker stored at raw Asset time stays at the original frame/sample time and its derived case timestamp moves appropriately.

This is important for incident reconstruction because it avoids silently baking provisional synchronization into the evidence record.

## Desktop workflow

The **Case Timeline / Sync** dock shows:

- each case member Run and its Run→Case equation;
- every Run Asset and its Asset→Run equation;
- mapping method and uncertainty;
- resolved case markers.

Current controls allow an engineer to:

1. select a Run and enter `run_time = case_time` anchors;
2. select an Asset and enter `asset_time = run_time` anchors;
3. add a marker in the selected source's natural time domain;
4. refine a mapping and immediately see marker case times update.

v0.20 adds that UI layer as **Synchronized Case Review**. One Case-time cursor now resolves every source position through this mapping layer. Cached video/audio can seek to the resolved Asset time, telemetry/IDR-compatible numeric sources are previewed against Case time, and markers/frame steps move the same cursor. The review layer does not maintain its own hidden offsets.

## Headless inspection

The catalog CLI can inspect the same state without Qt:

```bash
python -m runlab.cli catalog cases
python -m runlab.cli catalog case-bundle --case-id <case_id>
python -m runlab.cli catalog case-timeline --case-id <case_id>
python -m runlab.cli catalog case-playback --case-id <case_id> --case-time 3.250
```

These commands are read-only. They are useful for automated qualification and for validating a future Tech Services adapter against the local case model.
