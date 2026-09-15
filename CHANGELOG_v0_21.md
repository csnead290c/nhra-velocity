# Changelog — v0.21

## Analysis Workstation Foundation

- Added `runlab.workstation` as a Qt-independent foundation for channel discovery, aliases, safe data gates, official drag segments and reusable KPI metrics.
- Channel catalog now exposes source kind, engineering dimension, unit, sample rate, canonical role and user alias.
- Added safe boolean gates with comparisons, `and/or/not`, arithmetic, `abs()`, `isfinite()` and `between()`; arbitrary Python execution remains prohibited.
- Added official NHRA drag segment generation for time, distance and normalized Run-progress analysis.
- Added reusable metrics: min, max, mean, median, standard deviation, RMS, range, start, end, delta, integral, slope, count and arbitrary percentiles.
- Multi-run drag KPI reports use each Run's own official timing boundaries rather than reusing Main-run timestamps.
- Added `runlab.heatmap` for occupancy/count and binned mean/median/min/max/std/sum load maps.

## Frequency analysis

- Added Welch power-spectral-density analysis.
- Added spectrogram/time-frequency analysis.
- FFT, PSD and spectrogram calculations share the same validated uniform-timebase layer.

## Desktop

- Renamed Parameter Browser to **Channel Explorer** and added Alias, Source, canonical Role, sample-rate and unit visibility/search.
- Added user-editable channel aliases.
- Added **Data Gate / Condition** definition workflow.
- Added **Load / Heat Map** display with optional saved-gate filtering.
- Added **Segment / KPI Report** across Main + Reference/Overlay sessions.
- Spectrum display now supports FFT amplitude, Welch PSD and Spectrogram modes.
- Added **Normalized Run %** as a display-only X axis; physical Run time remains unchanged.
- Workbooks now persist channel aliases, saved gates and the new display configuration.

## CLI / automation

- Added `analyze channels`, `analyze gate`, `analyze metrics`, `analyze psd` and `analyze loadmap` commands.
- These commands use the same headless primitives as the desktop.

## Product requirements

- Added `WORKSTATION_PARITY_REQUIREMENTS.md`, benchmarking the long-term workstation against ATLAS, MoTeC i2/i2 Pro, Bosch WinDarab, AiM RaceStudio and the broader professional motorsport-analysis category.
