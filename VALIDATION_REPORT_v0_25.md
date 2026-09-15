# NHRA Tech Data v0.25 — Validation Report

## Release scope

v0.25 adds two first-class foundations without changing the authoritative Tech Services data model:

1. **Protected desktop access** designed to reuse NHRA Tech Services identity through a standards-based native-app authorization flow once the actual website backend contract is bound.
2. **RSA / Quarter Pro simulation studies** for reproducible multi-axis forward simulation, multi-run validation, scenario comparison, and future inverse-model workflows.

Catalog schema remains **v7**. Workbook format advances to **v7** to retain portable simulation-study packages. Raw Run/Asset authority remains with NHRA Tech Services.

## Automated tests

- **136/136 tests passed** from the release source tree.
- `python -m compileall -q runlab desktop.py tests` passed.
- Security coverage includes PKCE generation, scope enforcement, offline grants, secure credential-store behavior, transport authorization, frozen-build fail-closed policy, and unbound-provider behavior.
- Simulation coverage includes multi-axis sweeps, indexed gear/shift parameters, both solver families, observed-vs-simulated residuals, and `.nhrastudy` round-trip provenance.

## Native / corpus regression

- RacePak / MoTeC / MaxxECU native pipeline self-test: **3/3 PASS**.
- Recursive telemetry corpus qualification: **10/10 PASS**.
- Qualification outputs are under `/mnt/data/v025_validation/` in the development environment.

## Official NHRA Run import regression

### U.S. Nationals

- Source rows: **134**
- Canonical imported Runs: **123**
- Partial duplicate rows merged: **6**
- Incomplete rows skipped: **5**
- Identical re-import: **0 new Runs**, **123 updated**

### PSM Indianapolis Test

- Source rows: **25**
- Canonical imported Runs: **25**
- Identical re-import: **0 new Runs**, **25 updated**

### Fresh schema

- Schema version: **7**
- `assets`: present
- retired `remote_assets`: absent
- retired `reconciliation_reviews`: absent

## Security validation

- A frozen/distributed build requires authentication by default.
- Source/development execution remains usable without authentication while the real Tech Services provider adapter is being developed.
- `runs.read`, `assets.read`, and `analysis.write` are independently enforced at the Tech Services transport boundary.
- The optional `simulation.use` entitlement gates the Simulation Study Center when authentication enforcement is enabled.
- `KeyringCredentialStore` has **no plaintext fallback**; if an OS credential backend is unavailable it fails rather than storing reusable secrets in application files.
- `UnboundTechServicesAuthProvider` intentionally refuses to invent authorization URLs, token endpoints, claim names, or website-session semantics.
- Therefore **live Tech Services login is not claimed as operational in v0.25**. The desktop-side architecture is ready, but the real site authentication/API adapter must be bound after the actual backend contract is inspected.

## RSA / simulation validation

- `runlab.simulation_study` can execute Cartesian multi-axis scenario studies with either:
  - the source-faithful Quarter Pro-derived reference engine; or
  - the smooth optimization engine.
- Supported study variables include power scale, race weight, CdA/ClA, traction, final drive, tire size, driveline efficiency, per-gear ratios, and per-gear shift RPMs.
- A release smoke study was exported successfully to XLSX.
- `.nhrastudy` packages preserve the exact VehicleConfig / dyno curve, Environment, engine choice, axes, source Run identity, software version, and result rows.
- Generated scenarios can enter the ordinary Compare Sessions analysis path rather than living in a separate simulation-only UI.

## Packaging / platform notes

- The Windows build script supports optional Authenticode signing through `signtool` when signing-certificate and RFC3161 timestamp environment variables are supplied.
- Interactive Qt/PySide6 GUI execution remains unavailable in this Linux validation container; desktop source is compile-tested and its underlying logic is covered headlessly.
- Application login, authorization and code signing improve access control and integrity but do not make Python bytecode impossible to reverse-engineer. Higher-value solver IP can later be moved to compiled native modules and/or selected server-side services while preserving an offline-capable track workflow.

## Exact-package clean-room verification

The final release ZIP was extracted into a new directory and exercised independently of the working tree:

- full automated suite: **136/136 PASS**;
- native importer self-test: **3/3 PASS**;
- `study template` and a 2-axis Quarter Pro reference-engine `study sweep` completed successfully from the extracted package.

The final ZIP contains no `__pycache__`, `.pyc`, or `.pytest_cache` entries.
