# NHRA Tech Data v0.12 — development changelog

v0.12 continues the telemetry-workstation path.  The emphasis is signal analysis, repeatable comparison, sensor/data health, display preferences and persistence—not adding more hidden assumptions to the vehicle solver.

## Analysis workstation

- Added `runlab.signal_analysis` with validated uniform-time preparation, zero-phase Butterworth low/high/band-pass filters, FFT spectrum analysis, rolling mean and rolling RMS.
- Added persistent calculated-channel functions `lowpass()`, `highpass()`, `bandpass()`, `rollingmean()` and `rollingrms()` in the restricted math evaluator.
- Added conservative expression-dimension inference.  Clearly incompatible assigned output units are rejected; expressions whose dimension cannot be proven are left unknown rather than guessed.
- Added **FFT / Spectrum** display with window selection, frequency limit, linear/log amplitude and optional A-B-window analysis.
- Added **Multi-Run Envelope** display.  Main/Reference/Overlay runs are aligned, compatible units are converted, and min/max/mean/std are calculated only over common data overlap.
- Added **Run Comparison Summary** display for official timing plus selected telemetry quantities at timing locations.
- Added **Sensor Health** display for recording quality: finite coverage, sample rate, clock problems, flat-line behavior and extreme sample-step outliers.

## Waveform / preferences

- Added cross-project channel display preferences keyed by canonical engineering role when available, otherwise by normalized source name.
- Waveform **Trace Properties** can save/clear global defaults for display unit, line width, color and manual Y range.
- Added fuller **Waveform Display Properties** for layout, compare visibility, event markers, cursor readout, navigator, legends, cursor snapping and render point budget.
- Added **Duplicate Worksheet** and a command palette (`Ctrl+K`) for common workstation actions.
- Run Comparison Summary now persists its selected reference session.

## Derived engineering data

- Delivered-power reconstruction is now attached through a dedicated derived-analysis layer.
- Reconstructed HP/torque no longer replace an existing measured/logger canonical power or torque mapping.
- The reconstruction recipe is stored with the session and regenerated on project reopen rather than persisting a second opaque copy of derived arrays.
- Project format advances to version 4 and also preserves global X mode, compare enabled state and primary/A/B cursor positions.

## Persistence / performance

- Cross-project preference reads use an mtime-aware cache instead of rereading the preference file during each waveform refresh.
- New analysis-display state is stored in worksheet display configuration and rebuilt before Qt docking geometry is restored.
- Existing atomic project write and crash-recovery behavior remains in place.

## Validation

- 61 core regression tests pass in the development tree before release packaging.
- Bundled RacePak, MoTeC LD and MaxxECU import→plot self-tests pass 3/3.
- Real development RacePak files remain plotable after the new analysis/persistence changes.

## Still open

- The actual Qt/PySide6 desktop shell cannot be runtime-launched in the isolated build container because PySide6/pyqtgraph are unavailable there.  Core/display-data code is tested headlessly, but Windows interaction testing remains required.
- Native FuelTech `.ftlog/.ftml` remains fail-closed pending a validated decoder and representative files.
- MoTeC `.ld` still needs a production corpus of genuine NHRA files checked side-by-side against i2.
- Undo/redo, richer report export, order analysis, lazy/memory-mapped very-large-log storage and background/cancellable workers remain future work.
