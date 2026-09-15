# NHRA Velocity v0.38 Development Validation

Validated build: **0.38.0-dev.4**

## Scope

This validation covers the NHRA Tech Services read-only login/metadata integration, the authoritative Run-first local telemetry attachment bridge, and the new canonical-weather hydration path using the existing Tech Services `parity.php?action=runsWithWeather` GET endpoint.

## Results

- **211/211 automated tests passed** (`PYTHONPATH=. pytest -q`).
- **3/3 bundled native import/plot pipelines passed**:
  - RacePak/DataLink `.rpk`
  - MoTeC `.ld`
  - MaxxECU `.MaxxECU-log`
- Python source compilation passed for `desktop.py` and `runlab/*.py`.
- Release audit passed with **0 errors / 0 warnings** when pinned to the audited upstream revisions:
  - RacingSystemsAnalysis `1556ac70684908038fe47a9fe54e2f506cc4e71c`
  - nhratechservices `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`

## Tech Services integration checks

- Site application-data integration remains read-only. The only POST in the desktop boundary is the existing first-party login exchange; no Event, Entry, Run, linkage, or Asset record is created/modified on Tech Services.
- Run synchronization now prefers the verified `runsWithWeather` GET so official timing can carry the nearest canonical site weather sample.
- Weather field names are translated into Velocity's canonical environment schema while server timestamp, join delta, canonical source kind/detail, and sample provenance remain attached as evidence metadata.
- If the weather-join GET is unavailable or malformed, synchronization falls back to the existing timing-only `action=runs` GET and reports the fallback rather than failing the event.
- The audited read API still does not expose the database `parity_runs.event_entry_id` relationship. Velocity continues to leave Entry→Run ownership unresolved rather than duplicating the website's administrative matching logic.
- The existing Tech Master linkage write/admin actions (`backfillRunLinks`, `manualLink`, etc.) are not called by Velocity.

## Run-first local telemetry bridge checks

- A local telemetry attachment requires an explicit canonical `run_id`; it fails closed without one.
- The selected Run is never inferred from filename, driver name, car number, timestamp, or folder path.
- Attached bytes are copied into Velocity's SHA-256-addressed managed local object store.
- The local Asset is explicitly marked `attachment_mode=local_working_copy` and `server_persistence=false`.
- Official catalog timing/weather remain authoritative over telemetry/user session values.
- Full official timing remains available in metadata for fields outside the compact `TimingData` object (for example RT/DQ/MOV).
- Normalized 330-ft timing remains fixed as `ft330 -> three_thirty_ft_s`.

## Known validation limitation

PySide6/pyqtgraph are not installed in this Linux build container, so the updated synchronization dialog and Run Browser attachment UI were syntax-compiled but not interactively exercised here. A real Windows Qt smoke test is still required before calling the desktop UI path production-qualified.
