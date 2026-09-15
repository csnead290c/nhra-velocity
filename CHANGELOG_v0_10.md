# NHRA Tech Data — v0.10 development changelog

v0.10 is an import/viewer reliability milestone. The priority is deliberately basic: opening a supported telemetry file must result in visible data without requiring the user to understand the application internals.

## Import pipeline

- Replaced extension-only dispatch with a probe → validate → decode → normalize → audit pipeline.
- Format selection and decoder selection now use the same result. This fixes files such as `*.rpk.bin` being recognized as RacePak and then accidentally sent to the generic text parser.
- Unknown binary files fail closed before pandas/CSV parsing.
- Import errors identify the decoder stage that failed.
- Successful imports must pass a plotability contract: at least one numeric channel must yield a usable X/Y series.
- ZIP archives can contain a primary `.ld`, `.rpk`, MaxxECU log or delimited export. Matching MoTeC `.ldx` sidecars are extracted beside the `.ld` before decoding.
- MaxxECU zip handling now uses a temporary extraction directory and does not require write access beside the source file.
- FuelTech `.ftlog` and `.ftml` are recognized explicitly but intentionally rejected until a native decoder is validated. They are never treated as CSV by guesswork.

## Viewer reliability

- Newly opened logs become the active Main session immediately.
- A newly opened session automatically populates the primary waveform with up to five useful channels, preferring engine RPM, driveshaft RPM, speed, longitudinal G, throttle and other canonical drag-racing channels.
- If a valid rectangular file has no trustworthy semantic time channel, it remains viewable on Sample Index rather than opening to a blank graph.
- Native-rate channels continue to use their own logger clocks.
- Headless waveform extraction is now in `runlab/display_data.py`, so CI exercises the exact X/Y data path used by the desktop waveform without requiring Qt.
- Added drag-and-drop of telemetry files onto the application.
- Added recursive **Open Log Folder…** for batch race/event data folders.
- Added **Open Bundled Native Demos** so the viewer can be verified independently of user files.
- Added **Import Support / Diagnostics** help inside the application.
- Added **Run Import / Plot Data Self-Test…**; the bundled RacePak, MoTeC and MaxxECU pipelines are decoded and checked for finite waveform points on the installed machine.
- Added rotating diagnostic logs plus a Help command that opens the log folder. Import exceptions include their full traceback in the log.

## Native verification fixtures

The distribution contains generated, non-vendor demo files used only to verify the import/viewer path:

- `examples/native_demo_racepak.rpk`
- `examples/native_demo_motec.ld`
- `examples/native_demo_maxxecu.MaxxECU-log`

Each decodes and produces default waveform points in automated tests. They are synthetic and are not performance-reference data.

Development validation also exercised the separate real Pro Stock and Top Fuel RacePak demo recordings. Those vendor files are not redistributed.

## Unit/data integrity

- Added RacePak/DataLink acceleration aliases including `g's`, preventing valid G-meter data from being rejected solely because of vendor unit spelling.
- Import audit now reports decoder/probe, plotability and default trace selection.
- CLI `inspect` now reports decoder, probe reason, canonical map, plotability, chosen default traces and actual finite plot-point counts.

## Regression status

- 44/44 automated core tests pass before release packaging.
- The Windows PyInstaller build now explicitly bundles native demo files and key validation/import documentation so self-test resources are present in the packaged application.
- Tests now include native-demo plot contracts, `.rpk.bin` dispatch, sample-index fallback, unknown-binary rejection, FuelTech fail-closed behavior and folder candidate filtering.

## Still open

- Actual Qt interaction cannot be executed in the isolated packaging container because PySide6/pyqtgraph are unavailable there. The final desktop package therefore still requires Windows-side interaction qualification.
- Native MoTeC needs a larger genuine NHRA `.ld/.ldx` corpus checked side-by-side against i2.
- Native FuelTech FTLOG/FTML remains a development item.
- Large-log lazy loading/min-max decimation/background import are still planned.
