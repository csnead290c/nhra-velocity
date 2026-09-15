# NHRA Velocity v0.38 Development Validation

Validated build: **0.38.0-dev.5**

## Scope

This validation covers the Run-first engineering workspace, catalog schema v8 standardized Run reports, class/RSA profile presentation, Pro Stock shift-report persistence/comparison, authoritative Tech Services timing/weather hydration, and the existing read-only Tech Services integration. No changes were made to the `nhratechservices` repository or server data.

## Results

- **217/217 automated tests passed** (`PYTHONPATH=. pytest -q`).
- `python -m compileall -q .` passed.
- **3/3 bundled native import/plot pipelines passed**:
  - RacePak/DataLink `.rpk`
  - MoTeC `.ld`
  - MaxxECU `.MaxxECU-log`
- Release/provenance audit passed with the pinned upstream references:
  - RacingSystemsAnalysis `1556ac70684908038fe47a9fe54e2f506cc4e71c`
  - nhratechservices `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`
- Release audit findings: **0 errors / 0 warnings**.

## Run Workspace validation

Automated tests cover:

- canonical category → class profile resolution without filename inference;
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

This build still requires a real Windows Qt/pyqtgraph smoke test for the new Run Workspace dock and its interactions. The automated environment validates Python/data behavior but does not prove Windows widget layout/painting.
