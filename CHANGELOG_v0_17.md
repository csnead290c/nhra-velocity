# NHRA Tech Data v0.17 — Tech Services Source-of-Truth Correction

v0.17 corrects the Run/Asset architecture so it matches the intended NHRA Tech Services workflow.

## Source of truth

- NHRA Tech Services is authoritative for Events, Entries, Runs, and the permanent files attached to each Run.
- A file is assigned to a Run when it is uploaded/added on the Tech Services website. The desktop does not infer that relationship.
- There is no production Box connection, archive browser, filename matcher, candidate reconciliation workflow, or automatic file-to-Run assignment.
- Filenames and original names remain useful descriptive metadata only. Asset identity comes from the server Asset ID/revision plus integrity metadata.

## Tech Services mirror and asset cache

- Catalog schema moves to **v5**.
- Server Assets now carry first-class `remote_id`, `revision`, `source_kind`, `uploaded_at`, authoritative SHA-256/size metadata, and cache state.
- Server-owned Assets cannot be re-parented to another Run by the desktop.
- Permanent Run/Asset relationships arrive directly in the Tech Services snapshot: `Event -> Run -> Assets`.
- Asset bytes are fetched by authoritative server Asset ID through the transport boundary.
- Cached bytes are verified against the authoritative SHA-256 (and size when supplied).
- A changed server Asset revision/hash invalidates stale local cached bytes and dependent telemetry/time-mapping state.
- The local content-addressed store is an expendable offline/performance cache, not another repository.
- Potentially temporary/signed download URLs are not persisted as Asset identity or transport configuration.

## Desktop workflow

- Run Browser is now explicitly an **NHRA Tech Services Runs** mirror.
- Run Assets show authority, cache state, Remote ID, and time-mapping information.
- Removed normal-workflow controls for matching, linking, attaching evidence, creating local permanent Runs, repository manifests, and remote-evidence reconciliation.
- `Open Log` remains available for scratch/ad-hoc engineering work but does **not** create a permanent catalog Run or Asset.
- Permanent model snapshots require a canonical Tech Services Run.
- Offline caching operates only on Assets already owned by a Tech Services Run.

## Sync/API boundary

- Sync contract advances to **v4** and represents permanent nested Run Assets directly.
- `TechServicesTransport` defines catalog pull, Asset fetch, and future explicitly permitted analysis push operations.
- `UnboundTechServicesTransport` fails closed until the real `nhratechservices.com` implementation is inspected and authenticated.
- No API URLs, authentication behavior, download routes, or write permissions are guessed.
- The legacy official timing CSV importer remains only as a development/validation bridge until the real Tech Services adapter is bound.

## Removed v0.16 concepts

The following v0.16 direction is intentionally retired from the runtime/product workflow:

- Remote Evidence Browser
- repository manifests
- Box/archive evidence hints
- automatic/heuristic Run matching
- candidate scores and reconciliation reviews
- filename/path-based permanent association

Older migrated SQLite files can physically retain legacy v0.16 tables; v0.17 code does not use them. Fresh v0.17 catalogs do not create them.

## Validation

- Full automated suite: **83 passed**.
- Python compile check: PASS.
- Native import self-test: **3/3 passed** (RacePak, MoTeC, MaxxECU).
- Bundled corpus qualification: **10/10 passed**.
- Dedicated transport/cache tests confirm server-owned Run/Asset association, hash verification, cache reuse, revision invalidation, and fail-closed unbound transport behavior.
