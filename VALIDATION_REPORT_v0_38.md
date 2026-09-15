# NHRA Velocity v0.38 Development Validation

Validated build: **0.38.0-dev.3**

## Scope

This validation covers the existing NHRA Tech Services read-only login/metadata integration plus the new authoritative Run-first local telemetry attachment bridge.

## Results

- **210/210 automated tests passed** (`PYTHONPATH=. pytest -q`).
- **3/3 bundled native import/plot pipelines passed**:
  - RacePak/DataLink `.rpk`
  - MoTeC `.ld`
  - MaxxECU `.MaxxECU-log`
- Python source compilation passed for `desktop.py` and `runlab/*.py`.
- Release audit passed with **0 errors / 0 warnings** when pinned to the audited upstream revisions:
  - RacingSystemsAnalysis `1556ac70684908038fe47a9fe54e2f506cc4e71c`
  - nhratechservices `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`

## Run-first local telemetry bridge checks

- A local telemetry attachment requires an explicit canonical `run_id`; it fails closed without one.
- The selected Run is never inferred from filename, driver name, car number, timestamp, or folder path.
- Attached bytes are copied into Velocity's SHA-256-addressed managed local object store.
- The local Asset is explicitly marked `attachment_mode=local_working_copy` and `server_persistence=false`.
- Official catalog timing/weather remain authoritative over telemetry/user session values.
- Full official timing remains available in metadata for fields outside the compact `TimingData` object (for example RT/DQ/MOV).
- Existing Tech Services synchronization remains GET-only for application data.
- Fixed normalized 330-ft timing mapping: `ft330 -> three_thirty_ft_s`.

## Known validation limitation

PySide6/pyqtgraph are not installed in this Linux build container, so the new Run Browser button/dialog was syntax-compiled but not interactively exercised here. A real Windows Qt smoke test is still required before calling the desktop UI path production-qualified.
