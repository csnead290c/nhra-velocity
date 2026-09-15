# NHRA Tech Data v0.18 — Analysis Cases & Multi-Run Workspaces

v0.18 generalizes the v0.17 incident foundation into a reusable engineering workspace without weakening the Tech Services Run/Asset source-of-truth model.

## AnalysisCase

- Catalog schema advances to **v6**.
- New `analysis_cases` table represents a persistent engineering workspace with `case_type`, title, status, summary, optional primary Run, optional future remote identity/revision, and sync state.
- Supported case types are intentionally open-ended. The desktop currently offers Incident, Performance / Reconstruction, Parity, Development, Aerodynamics, and General Engineering.
- A case can exist without a primary Run, although the desktop's current create-from-Run flow supplies one.

## Multi-run membership

- New `analysis_case_runs` many-to-many relationship lets one case include multiple authoritative Runs.
- Each included Run has an explicit role such as `primary`, `baseline`, `comparison`, or `reference`.
- Changing the primary Run demotes the prior primary to `reference`; it never re-parents or alters any Run Asset.
- The same canonical Run may participate in multiple analysis cases.

## Evidence

- New `analysis_case_evidence` supports two evidence forms:
  - a link to an existing authoritative Run Asset; or
  - case-only local evidence such as inspection photos, reports, notes, CAD exports, or other material that does not naturally belong to one race pass.
- Linked Run Assets remain owned by their Tech Services Run. The case stores a reference, not a copy or new ownership relationship.
- Standalone local case evidence can be stored in the existing SHA-256 content-addressed object store and retains filename/hash/size/MIME/provenance metadata.

## Model snapshots

- `ModelSnapshot` ownership is generalized: a snapshot may belong to a single Run, an AnalysisCase, or both.
- Case-scoped snapshots no longer require an artificial single-Run owner, which is required for future multi-run inverse fitting and shared vehicle-model estimation.
- Existing v0.17 Run model snapshots migrate in place and remain attached to their original Run.

## Incident compatibility / migration

- `create_incident_case()` remains as a compatibility wrapper but now creates an AnalysisCase with `case_type='incident'` and the supplied Run as primary.
- Existing v0.17 `incident_cases` rows are copied into `analysis_cases` during schema migration while the legacy table is retained untouched for rollback/audit safety.
- No existing IncidentCase or Run ModelSnapshot data is discarded.

## Desktop

- **New Incident Case** becomes **New Analysis Case** in the Tech Services Run browser.
- New **Analysis Cases** dock lists cases and their member Runs.
- Case creation selects a case type and starts from a primary authoritative Run.
- A selected Tech Services Run can be added to an existing case as Comparison, Baseline, Reference, or Primary.
- Case Runs can be reopened directly from the case browser.
- **Cache Case** caches the authoritative Run Assets used by the case through the normal Tech Services transport/cache path.

## Provider-neutral analysis bundle

- `analysis_case_bundle()` serializes case metadata, Run roles/remote IDs, evidence hashes, and case-scoped ModelSnapshots without local filesystem paths.
- This is deliberately **not** presented as a guessed nhratechservices.com HTTP contract.
- The production adapter should translate the local AnalysisCase model into the website's existing incident/session concepts only after the backend API/auth/permissions are fully inspected.

## Source-of-truth invariant

v0.18 does **not** reintroduce archive matching, filename heuristics, Run inference, or desktop re-parenting of permanent files. Tech Services remains authoritative for Event → Run → Asset ownership.

## Validation target

- automated catalog/analysis regression suite — **92/92 passing**;
- v0.17 → v0.18 schema migration coverage;
- Python compile check;
- native RacePak/MoTeC/MaxxECU self-test;
- bundled corpus qualification — **10/10 passing**;
- clean-room ZIP test run.
