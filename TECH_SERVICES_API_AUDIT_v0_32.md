# NHRA Tech Services API Audit — v0.32

## Audited source

- Repository: `https://github.com/csnead290c/nhratechservices`
- Branch observed: `main`
- Commit: `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`
- Tree: `29e46420b0f806b6f17f4a39755802054c2fd7ef`
- Audit mode: read-only. No repository, website, database, or Box content was modified.

## Verified authentication behavior

The shared PHP API helper reads an `Authorization: Bearer <token>` header. The website login API returns a signed Bearer token; protected routes apply authentication plus server-side capability checks. The audited source does not expose a native-desktop authorization-code/PKCE or refresh-token flow.

Verified identity/simulation routes:

- `GET /api/auth.php?action=me` — authenticated current-user lookup.
- `GET /api/runs.php?limit=N` — saved **simulation** `run_history` for the authenticated user.

The `runs.php` records are deliberately kept separate from NHRA event Runs. They are simulator history and do not establish Event, Entry, Run, or Asset ownership.

## Verified Tech Master Event / Entry reads

The current source has real Tech Master read APIs:

- `GET /api/tm-events.php?action=listEvents[&seasonId=N|seasonYear=YYYY][&limit=N]`
- `GET /api/tm-events.php?action=getEvent&id=N`
- `GET /api/tm-entries.php?action=listForEvent&eventInstanceId=N[&classIndex=...]`
- `GET /api/tm-entries.php?action=get&id=N`

Event instances and Event Entries carry stable database IDs plus UUIDs. The event response also carries `race_lookup`, which is a legitimate event-level bridge to parity/timing data. v0.32 binds these GETs exactly as implemented.

## Verified normalized NHRA Run reads

The parity API exposes:

`GET /api/parity.php?action=runs&raceLookup=YYYYMMDD`

with verified optional filters for category/class index, driver name, lane, round, DQ handling, bad-run inclusion, limit, and offset. The response contains normalized Run IDs/UUIDs, race lookup, timestamps, category/class, round/lane, driver/car number, incrementals, MPH, result flags, source reference, and creation time.

This is materially different from the simulator `run_history` API and is safe to expose to the workstation as NHRA timing/run metadata.

## The important bridge gap

Migration v22 adds a real nullable foreign key:

`parity_runs.event_entry_id -> event_entries.id`

However, at the audited commit, `parity.php?action=runs` does **not** select or return `event_entry_id`. That means the database knows how a normalized parity Run can belong to an Event Entry, but the read API does not currently expose that authoritative relationship.

v0.32 therefore does **not** infer Entry ownership from driver names, competition numbers, ordering, timestamps, filenames, or any other heuristic.

## Remaining Run -> Asset gap

Repository/API review still did not identify a read contract for permanent telemetry/supporting files attached to a selected Run, including:

- stable Asset ID and Run ownership;
- immutable revision/hash/size metadata;
- Asset-by-ID download;
- permanent attachment manifests;
- catalog revision/cursor semantics for workstation sync.

Therefore the full Event -> Entry -> Run -> Asset sync-contract-v4 transport remains fail-closed even though source-verified metadata reads are now available.

## v0.32 client boundary

`runlab.tech_services_http` now provides:

- HTTPS enforcement for non-local hosts;
- Bearer-token GET support without putting secrets in URLs;
- same-origin route and redirect enforcement;
- bounded JSON/Asset response sizes;
- safe HTTP/JSON error handling;
- verified current-user and simulation-history helpers;
- verified Tech Master Event and Event Entry read helpers;
- verified normalized parity Run read helper;
- explicit canonical catalog/Asset route hooks with **no invented defaults**;
- contract-v4 validation if/when a matching server route is explicitly configured;
- read-only enforcement for workstation write-back at this milestone.

The CLI exposes these source-verified reads through `tech-services` actions for development and integration testing.

## Configuration seam

- `NHRA_TECH_SERVICES_BASE_URL` (defaults to `https://nhratechservices.com`)
- `NHRA_TECH_SERVICES_TOKEN`
- `NHRA_TECH_SERVICES_CATALOG_PATH`
- `NHRA_TECH_SERVICES_ASSET_PATH_TEMPLATE` (must include `{asset_id}`)
- `NHRA_TECH_SERVICES_TIMEOUT_S`
- `NHRA_TECH_SERVICES_MAX_JSON_BYTES`
- `NHRA_TECH_SERVICES_MAX_ASSET_BYTES`

The canonical catalog and Asset path settings intentionally have **no defaults**.

## Recommended server additions

The shortest path to a real workstation sync is now small and concrete:

1. return `event_entry_id` (and preferably Event instance identity) from the parity Run read surface, or expose an equivalent dedicated Run endpoint;
2. add a permanent Run-Attachment/Asset manifest with stable IDs, filename/media metadata, byte size, revision, SHA-256, and authoritative Run ownership;
3. add authenticated Asset download by stable Asset ID;
4. expose a catalog revision/cursor so Event -> Entry -> Run -> Asset metadata can refresh incrementally;
5. retain server-side capability checks and audit logging.

The desktop mirror/cache layer already supports immutable SHA-256 verified local Assets and permanent Run ownership, so these server changes do not require a local data-model rewrite.


## v0.38 implementation addendum

The audited commit remains the current `main` commit as of September 15, 2026. NHRA Velocity now binds the existing `POST /api/auth.php?action=login` route as a first-party compatibility login, then validates/restores sessions through `GET /api/auth.php?action=me` and `GET /api/capabilities-endpoint.php`. The password is not persisted; only the server-issued Bearer token is eligible for OS credential-vault storage.

Velocity also provides a read-only metadata synchronization path that mirrors Tech Master Events and Event Entries plus `parity.php?action=runs` official timing records into the local catalog. It deliberately leaves `Run.entry_id` unset because the protected parity response still does not expose `event_entry_id`. No Tech Services application-data writes are performed, and permanent telemetry Asset synchronization remains disabled until a verified server contract exists.


## Local working attachment bridge (v0.38 development)

Until the website exposes a verified permanent Run→Asset manifest/upload/download contract, Velocity can explicitly associate a local telemetry file with a user-selected synchronized Run. The bytes are copied into local SHA-256-addressed managed storage and the association is marked `local_working_copy`. This does not call a Tech Services write endpoint, does not generate a remote Asset ID, and does not weaken the prohibition on filename/name/number matching. Permanent server Asset synchronization remains fail-closed.
