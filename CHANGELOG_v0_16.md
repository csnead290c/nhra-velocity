# NHRA Tech Data v0.16 — Remote Evidence Reconciliation

v0.16 makes the archive-intelligence work from v0.15 usable as an engineering review workflow while deliberately postponing any guessed production API integration.

## Remote Evidence Browser

- Added a desktop **Remote Evidence Browser / Reconciliation** surface.
- Browse indexed remote evidence by provider, filename/path, link state, selected-event season, and duplicate-hash status.
- Repository source objects remain untouched; this browser operates on metadata already indexed into the local catalog.
- Duplicate copy count is exposed without treating filename/path as content identity.

## Event-scoped batch reconciliation

- Added `runlab.remote_evidence`.
- Batch-ranks remote repository items against official Runs for a selected event.
- Preserves best score, runner-up score, score margin, evidence-strength class, proposed driver/round/time, and reasons.
- Explicit contradictory season hints are filtered by default; sparse legacy items with no season hint remain eligible.
- Status policy distinguishes `strong`, `moderate`, `review`, `conflict`, and `unmatched` suggestions.
- Close top-two candidates are surfaced as conflicts instead of pretending the top row is certain.
- No suggestion auto-links evidence.

## Durable review decisions

- Catalog schema v4 adds `reconciliation_reviews`.
- Accepted/rejected decisions store reviewer, note and timestamp and survive later matcher refreshes.
- Explicit acceptance links the RemoteAsset metadata to the canonical Run.
- Rejection does not double as an unlink operation; already-linked evidence cannot be silently detached by rejecting a refreshed proposal.

## Tech Services adapter boundary

- Added `TechServicesTransport` protocol and capability model.
- Added `UnboundTechServicesTransport`, which intentionally fails closed for network operations.
- No `nhratechservices.com` URL, route, token scheme, or write permission is guessed in v0.16.
- Existing local JSON official snapshots and repository manifests remain the development/qualification interchange until the real backend source/API is available.

## CLI

New catalog actions:

- `browse-remote`
- `reconcile-remote`
- `reviews`
- `accept-remote`
- `reject-remote`

## Validation

- 87/87 regression tests pass.
- New tests cover duplicate-aware browsing, metadata-only strong reconciliation, no-auto-link behavior, durable acceptance, rejection safeguards, ambiguous-candidate conflicts, schema v4 and fail-closed unbound transport.
- Against the real 2026 U.S. Nationals official export (123 canonical runs after import/coalescing), archive-style metadata for Matt Smith E2, Gaige Herrera Q4 and Richard Gadson Q3 each resolved to the correct official driver/round at the metadata-only ceiling of 0.89 with runner-up margins of approximately 0.23–0.31.
