# Changelog — v0.25

## Protected desktop foundation

- Added `runlab.auth` with PKCE material generation, identities/roles/scopes, short-lived token sessions, bounded offline entitlement state and fail-closed provider boundary.
- Added secure `KeyringCredentialStore`; refresh/offline credentials have no plaintext persistence fallback.
- Added `AuthorizedTechServicesTransport` scopes for Run catalog reads, Asset fetches and analysis write-back.
- Frozen/distributed builds require authentication by default; source development remains unlocked until the real Tech Services provider is bound.
- Added Account/access UI scaffolding and `simulation.use` feature entitlement checks.
- Added optional SHA-256/RFC3161 Authenticode signing/verification stage to the Windows build script.

## RSA / Quarter Pro Simulation Studies

- Added `runlab.simulation_study`.
- Multi-axis absolute/delta/scale sweeps support power, mass, aero, traction, final drive, tire and indexed gear/shift parameters.
- Supports both the source-faithful Quarter Pro reference solver and smooth optimizer-oriented solver.
- Reports official-style incrementals/traps, baseline deltas and selected solver diagnostics.
- Added observed-vs-predicted multi-Run timing validation helpers and study-level inverse-fit entry point.
- Added `.nhrastudy` packages with complete baseline vehicle/dyno, environment, source Run, software version and results.
- Added desktop Simulation Study Center and headless `study template|sweep|validate` commands.
- Workbook format advances to v7 to retain simulation-study packages/definitions; local catalog schema remains v7.

## Validation

- Added auth/security/transport/simulation-study tests.
- Production HTTP/auth endpoints remain deliberately unbound until the real Tech Services backend can be inspected.
