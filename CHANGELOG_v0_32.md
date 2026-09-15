# NHRA Tech Data v0.32 — Verified Tech Services Metadata Boundary

## Source-verified website integration

- Audited `csnead290c/nhratechservices` read-only at commit `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`.
- Confirmed the existing Bearer-token authentication and server-side capability model.
- Kept `api/runs.php` saved-simulation history explicitly separate from NHRA event/timing Runs.
- Verified and bound Tech Master Event and Event Entry GET APIs.
- Verified and bound normalized NHRA parity Run reads, including source-defined filters and pagination limits.
- Verified the database bridge `parity_runs.event_entry_id -> event_entries.id`.
- Confirmed the current parity Run GET response does not expose that bridge, so v0.32 refuses heuristic Entry->Run matching.
- Confirmed no permanent Run->Asset telemetry attachment/download API is present in the audited source.

## Hardened HTTP client

- Added `runlab.tech_services_http.TechServicesHttpClient`.
- Enforces HTTPS outside localhost development.
- Rejects URL-embedded credentials, cross-origin routes and cross-origin redirects.
- Supports Bearer authorization without putting secrets into URLs or reflected error text.
- Adds timeouts and configurable response-size limits.
- Adds safe JSON and HTTP error handling.
- Provides exact read helpers for identity, simulator history, Tech Master Events/Entries, and normalized parity Runs.

## Integration CLI

- `tech-services probe`
- `tech-services simulation-runs`
- `tech-services events` / `event`
- `tech-services entries` / `entry`
- `tech-services parity-runs`
- `tech-services catalog` remains available only when a canonical sync route is explicitly configured.

## Canonical sync seam

- `HttpTechServicesTransport` still accepts explicit sync-contract-v4 catalog and Asset routes.
- Those routes have no production defaults because the audited server does not yet expose the complete Entry->Run->Asset relationship.
- Existing SHA-256 verified cache, permanent Run->Asset ownership and revision invalidation remain unchanged.
- Analysis write-back and raw Asset upload stay disabled/read-only.

## Validation additions

- Added regression coverage for the verified Tech Master/Parity query contracts and argument validation.
- Added guards confirming normalized parity Run reads are not silently assigned to Event Entries.
- Existing TLS, same-origin, Bearer auth, catalog-v4 validation, Asset-ID quoting, size limits, JSON/HTTP errors and read-only tests remain in place.
