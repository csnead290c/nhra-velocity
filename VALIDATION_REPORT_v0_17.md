# NHRA Tech Data v0.17 Validation Report

## Scope

This release validates the source-of-truth correction introduced in v0.17: NHRA Tech Services owns the permanent Event/Run/Asset relationships and the desktop mirrors/caches those relationships without attempting file-to-Run matching.

## Automated test suite

Command:

```text
python -m pytest -q
```

Result: **83 passed**.

Coverage includes:

- fresh catalog schema v5 and migrations from earlier schema versions;
- Tech Services contract v4 snapshot replay/idempotency;
- authoritative nested Run -> Asset association;
- arbitrary filenames with no matching dependency;
- server Asset IDs/revisions and remote-entity bookkeeping;
- verified content-addressed Asset caching;
- prevention of desktop re-parenting of server-owned Assets;
- server revision/hash changes invalidating stale local cache state;
- already-cached Assets avoiding unnecessary re-fetch;
- fail-closed unbound Tech Services transport;
- telemetry import, calculations, modeling, comparison, project and workstation regressions.

## Compile validation

```text
python -m compileall -q runlab desktop.py tests
```

Result: **PASS**.

## Native telemetry self-test

```text
python -m runlab.cli selftest
```

Result: **3/3 PASS**.

- RacePak native demo: PASS
- MoTeC native demo: PASS
- MaxxECU native demo: PASS

The bundled MoTeC fixture retains its known synthetic header/list-count warning; the linked channel list is parsed and the self-test passes.

## Corpus qualification

```text
python -m runlab.cli qualify examples --recursive --strict
```

Result: **10 candidates / 10 pass**.

The qualification path exercises the same telemetry-loading/plotability path used by the workstation.

## Fresh-schema assertion

A fresh schema-v5 catalog was created and inspected directly:

- `assets` table: present
- legacy `remote_assets` table: absent
- legacy `reconciliation_reviews` table: absent
- reported schema version: **5**

## UI/runtime limitation of this environment

`PySide6` is not installed in the validation container (`ModuleNotFoundError`). The desktop source and Qt-facing code are therefore compile-validated and covered by non-interactive tests, but the GUI itself is not launched here. A Windows/macOS workstation smoke test remains appropriate for the packaged desktop environment.

## Backend integration status

The production `nhratechservices.com` adapter is intentionally **not yet bound** because the private Tech Services repository/API implementation is not currently accessible through the connected GitHub integration. v0.17 therefore validates the client contract and fail-closed transport boundary only. It does not claim that any guessed website endpoint or authentication flow works.
