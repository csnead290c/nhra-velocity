# NHRA Velocity v0.38 Development Validation

Validated build: **0.38.0-dev.7**

## Scope

This validation covers the Windows Tech Services sign-in persistence fix on top of the v0.38 simplified Run-first engineering workspace, catalog schema v8 standardized Run reports, authoritative Tech Services timing/weather hydration, and direct logger support. No changes were made to the `nhratechservices` repository or server data.

## Results

- The previous dev.6 baseline completed **221/221 automated tests**.
- The dev.7 authentication/Tech Services delta completed **20/20 focused regression tests** (`test_auth`, `test_tech_services_auth`, `test_tech_services_http`, `test_tech_services_metadata`, `test_authorized_transport`).
- A full-suite rerun was attempted in this constrained environment but exceeded the execution window before reporting a failure; no failed test was observed before timeout.
- `python -m compileall -q .` passed.
- **3/3 bundled native import/plot pipelines passed**:
  - RacePak/DataLink `.rpk`
  - MoTeC `.ld`
  - MaxxECU `.MaxxECU-log`
- Release/provenance audit passed with the pinned upstream references:
  - RacingSystemsAnalysis `1556ac70684908038fe47a9fe54e2f506cc4e71c`
  - nhratechservices `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`
- Release audit findings: **0 errors / 0 warnings**.


## Windows Tech Services sign-in regression

Focused validation covers:

- provider-specific compact credential payloads that omit persisted identity/capability duplication;
- secure restore of the cached seven-day access token followed by live identity/capability refresh;
- payload size staying below the Windows generic Credential Manager blob limit in the qualified test case;
- no password field in the persisted payload;
- authorization/capability behavior remaining unchanged after restore;
- continued fail-closed behavior with no plaintext credential fallback.

The desktop sign-in path also now distinguishes server authentication from credential-vault persistence: a vault write problem does not report a false bad-login failure or discard the already-authenticated in-memory session.

## Usability / progressive-disclosure validation

Automated source-level regression checks cover:

- permanent toolbar limited to Open / Save / Fit Run / active Run / X-axis / optional Compare;
- Compare Reference controls hidden until Compare is enabled;
- default Simple Workspace limited to Run Browser, Run Workspace and Channel Explorer rather than exposing every engineering dock;
- Run Browser and Channel Explorer sharing one left-side tab group;
- Channel Explorer defaulting to class-relevant **Essentials**, with **All channels** one selector away;
- text search bypassing the Essentials filter so a search always spans the complete logger channel catalog;
- standard class layout producing one core waveform rather than multiple automatic panels;
- class-layout application remaining separate from standardized-report generation;
- automatic default waveform selection preferring the authoritative class profile when available;
- Run Workspace reduced to Summary / Data / Engineering while retaining provenance in tooltips/advanced detail.

## Run Workspace / authority validation

Automated tests continue to cover:

- canonical category → class profile resolution without Run ownership inference from filenames;
- Pro Stock standardized RSA seed visibility;
- immutable/idempotent fingerprinted `run_reports` persistence;
- report source-Asset validation;
- expected-report/pending-report state;
- latest-vs-previous same-driver Pro Stock shift comparison and alert generation;
- Tech Services 60 ft, 330 ft, 1000 ft and 1000 MPH timing-name translation into the canonical timing model;
- existing catalog upgrade behavior through schema v8.

## Authority / safety boundary

- Tech Services Events/Runs/timing/weather remain authoritative.
- Local telemetry is associated only after the user selects the canonical Run.
- No filename-to-Run matching was added.
- Raw Assets remain immutable evidence.
- Standardized reports are derived local metadata and do not overwrite official timing/weather or telemetry.
- The desktop still does not infer Event Entry → Run linkage while the server read API does not expose `event_entry_id`.
- The current Tech Services integration remains read-only for application data.

## Remaining external validation

This build still requires a real Windows Qt/pyqtgraph smoke test for the simplified toolbar, dock/tab arrangement, Essentials channel browser, and compact Run Workspace. The automated environment validates Python/data behavior and static UI contracts but does not prove Windows widget layout/painting.
