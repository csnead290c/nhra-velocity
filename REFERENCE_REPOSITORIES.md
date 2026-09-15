# External reference repositories

Two public repositories are first-class upstream references for NHRA Tech Data. They serve different purposes and neither should be treated as a generic code dump.

## RacingSystemsAnalysis

Repository: `https://github.com/csnead290c/RacingSystemsAnalysis`

Role:
- source/reference for Racing Systems Analysis / Quarter Pro physics, numerical behavior and engineering worksheets;
- source for simulation parameterization, forward-model behavior and validation targets;
- reference when changing inverse/forward vehicle-model equations, clutch/converter/tire/aero/traction behavior or solver assumptions.

Rules:
- inspect read-only;
- pin the exact commit SHA used for a release audit whenever the repository is reachable;
- preserve source-faithful behavior separately from the smooth optimizer implementation;
- do not copy an old UI merely because the historical source used it;
- record intentional deviations from the reference physics and validate them quantitatively.

## nhratechservices

Repository: `https://github.com/csnead290c/nhratechservices`

Role:
- source/reference for the production Tech Services website, server-facing Run/Event/Asset contracts, authentication and permissions;
- source for existing incident/session patterns and any derived-analysis write-back integration;
- authority for how the desktop should connect to the real website rather than inventing parallel endpoints or identity systems.

Rules:
- inspect read-only;
- pin the exact commit SHA used for a release audit whenever the repository is reachable;
- do not invent API paths, token endpoints, cookie/session behavior, database tables or storage semantics that have not been verified;
- the desktop must adapt to the site's authoritative identifiers and authorization model;
- Run/Asset ownership remains server-authoritative.

## Release provenance

A validation report should record, when available:

- RacingSystemsAnalysis commit SHA;
- nhratechservices commit SHA;
- NHRA Tech Data product/software version;
- Quarter Pro/RSA model implementation version used by fit/simulation artifacts.

If an upstream repository is unavailable during validation, the report must say **unverified for this release** rather than substituting an assumed `main` revision.


## Release manifest binding

When a read-only audit succeeds, release tooling records the pinned revisions through `NHRA_RSA_REFERENCE_SHA` and `NHRA_TECH_SERVICES_REFERENCE_SHA`. Absence of either value is reported as `unverified`; it is never interpreted as permission to assume the current `main` branch.


## v0.36 verified revisions

Read-only GitHub verification on 2026-09-15 resolved the current accessible default-branch heads used for release provenance:

- `RacingSystemsAnalysis`: `1556ac70684908038fe47a9fe54e2f506cc4e71c`
- `nhratechservices`: `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`

v0.36 changes no RSA physics equations and no Tech Services production contract; these revisions are pinned to make that boundary explicit.
