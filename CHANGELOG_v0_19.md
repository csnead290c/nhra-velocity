# NHRA Tech Data v0.19 — Shared Case Timeline

v0.19 turns the v0.18 AnalysisCase foundation into an auditable multi-source synchronization system suitable for incident reconstruction and cross-Run engineering comparisons.

## Catalog schema v7

- `analysis_case_runs` now stores a Run→Case physical-time alignment: scale fixed at 1.0, plus offset, method, confidence, uncertainty and anchor list.
- New `analysis_case_markers` stores source-aware case events/intervals whose source domain can be case, Run, or Asset time.
- v0.18/schema-v6 case memberships migrate with identity alignment (`scale=1`, `offset=0`, method `run_time`).
- Existing Event/Run/Asset and AnalysisCase ownership is unchanged.

## Two-stage synchronization

- Existing Asset→Run `TimeMapping` remains authoritative for the analysis coordinate transform of one Asset.
- New Run→Case alignment is independent and case-specific.
- `runlab.case_timeline` fits Run→Case anchors and composes the two mappings without modifying raw source time.
- Direct Asset↔Case conversion is available through the catalog and composition helpers.
- Asset clock offset/drift is supported through an auditable affine fit; Run→Case uses offset only so physical time is never warped.

## Source-aware markers

- Case markers retain their original source timestamp and domain.
- Asset-domain markers dynamically resolve through Asset→Run→Case mappings.
- Run-domain markers dynamically resolve through Run→Case alignment.
- Refining synchronization therefore updates derived Case time while preserving the original evidence coordinate.

## Desktop

- New **Case Timeline / Sync** dock.
- Run alignment editor accepts `run_time = case_time` anchors.
- Asset mapping editor accepts `asset_time = run_time` anchors.
- Case markers can be created directly from a selected Run/Asset or in case time.
- Mapping equations, methods and uncertainty are visible alongside each source.

## Analysis bundle

- Provider-neutral AnalysisCase bundle advances to version 2.
- Member Run time mappings and resolved case markers are included.
- This remains local serialization, not an invented Tech Services HTTP contract.

## Validation target

- catalog + timeline regression suite — **98/98 passing**;
- schema-v6 → v7 migration;
- Asset→Run→Case composition and inverse mapping;
- dynamic marker remapping after synchronization refinement;
- Python compile check;
- native decoder/corpus qualification — **3/3 native and 10/10 corpus passing**;
- official run-import regression;
- clean-room ZIP execution.
