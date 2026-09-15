# Analysis Cases — v0.19

## Purpose

An `AnalysisCase` is the persistent engineering workspace above individual race passes. It is the shared foundation for incident reconstruction, multi-run vehicle modeling, parity studies, development work, aero studies, and other investigations.

The key separation is:

```text
Tech Services authoritative data
Event → Run → Asset

Local engineering workspace
AnalysisCase ↔ Runs
             ↳ linked Run Assets
             ↳ case-only evidence
             ↳ annotations / synchronization / derived models
             ↳ ModelSnapshots
```

A case never changes which Run owns a permanent Asset.

## Case types

Current desktop choices:

- `incident`
- `performance`
- `parity`
- `development`
- `aero`
- `engineering`

The database does not hard-code this list so additional technical workflows can be added without another schema change.

## Run roles

A case can include any number of canonical Runs. Membership is many-to-many, because one Run may be relevant to several engineering investigations.

Common roles:

- `primary` — focal pass or incident;
- `baseline` — clean/reference configuration used as the principal comparator;
- `comparison` — directly compared pass;
- `reference` — supporting historical or contextual pass.

Only one Run is marked `primary` by the current catalog API. Changing primary does not remove the previous Run; it becomes a reference.

## Evidence

### Linked Run evidence

A case may reference an Asset that already belongs to an authoritative Tech Services Run. The case records only the relationship and case-specific label/type/metadata. Asset identity, hash, revision, and Run ownership continue to come from the mirrored Asset record.

### Standalone case evidence

Some material does not naturally belong to a single pass: chassis inspection photos, reports, component measurements, CAD exports, meeting notes, or analysis documents. v0.19 supports local case evidence for this purpose.

Standalone evidence is hashed and, by default, copied into the content-addressed local object store. A future Tech Services adapter can map this to the site's existing incident/session storage if that backend supports it.

## ModelSnapshot scope

A Run-specific model remains valid and continues to use `run_id`.

A multi-run shared fit uses `analysis_case_id` and can leave `run_id` empty. This is the intended storage model for future cases such as:

```text
Case: Pro Stock vehicle reconstruction
  Runs: Q1, Q2, Q3, E1
  Shared unknowns:
    engine torque curve
    CdA
    rolling resistance
    drivetrain efficiency
    effective tire radius
  Per-run knowns:
    weather
    official timing
    mass
    gearing
    shift timing
  Snapshot:
    solver/model version
    fixed values and bounds
    fitted outputs
    residuals by Run
    quality/confidence/identifiability
```

The snapshot is append-only. Re-running a newer model produces another snapshot rather than rewriting the old result.

## Incident workflow

Incident analysis is now a specialized case workflow, not a separate silo:

1. create an Incident case from the incident Run;
2. add clean/baseline/reference Runs as needed;
3. cache the relevant Run Assets;
4. link telemetry/video/IDR/audio Assets to the case as useful evidence;
5. add case-only inspection material;
6. synchronize each Asset to its own Run clock, then align Runs/case events as needed;
7. store derived reconstruction/model snapshots and approved conclusions with provenance.

## Tech Services integration

The local AnalysisCase schema is intentionally transport-neutral. The v0.19 desktop does not invent new PHP routes or database writes on `nhratechservices.com`.

`analysis_case_bundle()` provides a path-free, provider-neutral serialization that can later be translated into the real website/backend contract. Event → Run → Asset synchronization remains contract v4 until the production backend adapter is bound.

## v0.19 shared timeline

A case now has an explicit time coordinate without replacing any canonical Run clock.

- Asset-local time is mapped to its owning Run through `TimeMapping` and may correct source clock drift.
- Each member Run is translated into Case time by `AnalysisCaseRun` using a physical-time-preserving offset (`scale=1`).
- `AnalysisCaseMarker` retains whether its source timestamp came from Case, Run, or Asset time and resolves dynamically through the current mappings.
- The desktop **Case Timeline / Sync** dock edits anchors and shows the resulting equations, methods, uncertainty, and case markers.

See `CASE_TIMELINE.md` for the synchronization math and workflow.
