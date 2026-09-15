# NHRA Tech Data v0.11 changelog

v0.11 concentrates on waveform reliability and day-to-day telemetry analysis rather than adding more inverse-solver scope.

## Waveform/render reliability

- Added a format-neutral final plot-preparation stage before Qt/pyqtgraph rendering.
- Removes non-finite X/Y samples and repairs duplicate, reset or non-monotonic X clocks by retaining the longest valid increasing segment.
- Added peak-preserving min/max display decimation for large traces; raw logger data is unchanged.
- Disabled pyqtgraph's implicit clipping/downsampling on prepared traces so vendor clock quirks cannot silently produce empty curves.
- Each waveform now reports `N curves / N points`, `NO CURVES`, or `RENDER ERROR` directly in the display.
- Rendering exceptions are logged instead of disappearing inside the Qt event loop.
- Scatter interpolation uses the same monotonic plot-preparation contract.
- Data Integrity now checks final renderer readiness for the default waveform channels.
- Smart default Y-channel selection no longer wastes a trace slot on Time/clock columns.

## Analysis workflow

- Added persistent bookmarks and named A-B regions.
- Added previous/next event navigation; Alt+Left/Right jumps between events.
- User bookmarks/regions appear in the Events display and on waveform event markers.
- Added **A-B Region Statistics** display with start/end/delta/min/max/mean/median/std/RMS.
- Added **Reference Delta** display with unit-compatible aligned Reference-Main or Main-Reference traces and summary statistics.
- Reference Delta display configuration now restores correctly with a project.

## Reliability / recovery

- Added atomic JSON project writes using temporary-file + `os.replace()` commit semantics.
- Added 90-second crash-recovery snapshots and startup recovery prompt.
- Clean application shutdown removes the crash-recovery image so normal exits do not trigger false recovery prompts.
- Added **File → Recover Autosave…** for manual recovery.
- Added CLI `selftest` command for the same bundled RacePak/MoTeC/MaxxECU import/plot pipeline diagnostic available from the desktop Help menu.

## Validation

- Core suite: **52/52 passing** before release packaging.
- Bundled native data-pipeline self-test: **3/3 passing**.
- Real development RacePak Pro Stock and Top Fuel recordings remain plotable through the final importer/viewer contract.
