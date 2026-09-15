# NHRA Tech Data v0.32 — Validation Report

## Release scope

v0.32 is the first **source-verified NHRA Tech Services metadata-integration** milestone. It keeps the v0.31 workstation/RSA stack intact and binds only the production read APIs that were verified in the pinned `nhratechservices` source.

Key additions:

- hardened GET-only `TechServicesHttpClient` with HTTPS, same-origin, Bearer-token, timeout, response-size and safe-error controls;
- verified current-user and saved-simulation-history reads, with simulator `run_history` explicitly separated from NHRA event Runs;
- verified Tech Master Event and Event Entry reads;
- verified normalized parity Run reads with source-defined filters and pagination caps;
- pinned Tech Services source provenance at commit `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`;
- CLI integration actions for Event, Entry and parity Run metadata inspection;
- explicit refusal to infer Event Entry ownership for a Run when the server does not expose the relationship;
- canonical contract-v4 catalog/Asset transport remains fail-closed until permanent Run→Asset APIs exist.

## Source audit findings

The audited site exposes protected Tech Master Event/Entry reads and a separate normalized NHRA parity Run API. Migration v22 also defines `parity_runs.event_entry_id -> event_entries.id`.

The current parity Run GET query, however, does not select/return `event_entry_id`. The current source also does not expose a permanent telemetry/supporting-file Asset manifest/download API. v0.32 therefore does not heuristically join Runs to Entries and does not invent Asset URLs or storage semantics.

No GitHub, website, database, or Box writes were performed. No live authenticated production API request was made during package validation because no end-user Bearer token is embedded in the build; HTTP behavior is source-verified and exercised against a local test server.

## Automated regression

- `PYTHONPATH=. pytest -q` → **173 passed**.
- `python -m compileall -q runlab desktop.py` → **pass**.
- focused Tech Services HTTP tests → **9 passed**.

## Native import / plot pipeline

`PYTHONPATH=. python -m runlab.cli selftest`:

- RacePak native demo → **PASS**;
- MoTeC native demo → **PASS**;
- MaxxECU native demo → **PASS**;
- result → **3/3 native demo pipelines passed**.

The existing MoTeC fixture still reports its expected warning that the header declares 99 channels while the linked list contains 6; the linked-list count is used.

## Tech Services HTTP boundary coverage

Regression coverage now includes:

- production HTTPS enforcement and localhost-only HTTP development exception;
- rejection of URL-embedded credentials;
- Bearer header use without putting secrets in URLs;
- same-origin route/download behavior;
- current-user and saved-simulation reads;
- Tech Master Event list/detail calls;
- Tech Master Event Entry list/detail calls;
- normalized parity Run query/filter/pagination contract;
- explicit check that parity Runs are not silently assigned to Event Entries;
- contract-v4 validation for any explicitly configured future canonical catalog route;
- Asset ID URL quoting;
- JSON/Asset response-size limits;
- invalid-JSON and HTTP-error handling;
- read-only/no-analysis-write behavior.

## Release-consistency audit

`NHRA_TECH_SERVICES_REFERENCE_SHA=77eb280fe94825f93f2cdfdd3ab2568851aa6a19 PYTHONPATH=. python -m runlab.cli release audit --strict`:

- **0 errors**;
- **1 warning**;
- `nhratechservices` SHA: **verified/pinned**;
- `RacingSystemsAnalysis` SHA: **unverified for this release**.

The remaining warning is deliberate: this milestone did not re-audit RacingSystemsAnalysis because v0.32 changes the Tech Services boundary rather than the physics engine.

Current portable/persistent versions remain:

- catalog schema: **7**;
- workbook: **7**;
- analysis library: **2**;
- simulation-study package: **2**;
- fit-study package: **5**;
- Tech Services sync contract: **4**.

## Desktop runtime limitation

PySide6/pyqtgraph are not available in this validation container. Desktop source compiles and the headless layers are fully regression-tested, but interactive Qt runtime behavior is not exercised here. A real Windows Qt launch/smoke pipeline remains a pre-1.0 requirement.

## Release conclusion

v0.32 is suitable to freeze as the **verified Tech Services metadata boundary** milestone. The next backend-enabling work is now sharply defined: expose the existing Entry→Run link through the protected Run API, then add the permanent Run→Asset manifest/download contract. Once those are available, the existing local catalog/cache layer can bind canonical Event→Entry→Run→Asset sync without filename matching, Box, or a local authority rewrite.

## Exact-ZIP clean-room verification

The release archive was extracted into a fresh directory and validated against the packaged source:

- `PYTHONPATH=. pytest -q` → **173 passed**;
- native import/plot self-test → **3/3 PASS**;
- packaged release audit → **0 errors / 1 explicit RSA-SHA warning**;
- archive contains **186 files**;
- archive contains **0** `__pycache__`, `.pytest_cache`, `.pyc`, or `.pyo` entries.
