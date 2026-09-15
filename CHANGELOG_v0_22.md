# Changelog — v0.22

## Display depth

- Added `runlab.display_analysis` as a Qt-independent display-analysis layer.
- Added **Gauge / Status** display with Numeric, Bar, Dial and Bit modes driven by the shared worksheet cursor.
- Gauge displays support automatic or explicit engineering ranges plus configurable bit thresholds.
- Advanced **Scatter / XY** now supports optional third-channel Z colour, saved data-gate filtering and linear regression with slope/intercept/R² readout.
- Histogram display now supports Samples, % Samples, Time [s] and % Time modes plus cumulative distributions and saved gates.
- Time-weighted distributions integrate actual sample-to-sample dwell and do not invent time beyond the recording.

## Headless analysis

- Added deterministic X/Y/Z alignment on the sparsest overlapping source clock to avoid visual upsampling/fake precision.
- Gated multi-channel displays require an explicit rectangular analysis grid rather than silently interpolating mixed-rate clocks inside a condition.
- Added reusable linear-regression, distribution and cursor-sampling primitives.
- Added CLI actions `analyze scatter`, `analyze histogram` and `analyze sample`.

## Persistence / architecture

- Workbook display specifications now retain gauge settings, scatter Z/gate/regression state, and histogram weighting/cumulative/gate state.
- Catalog schema remains **v7**.
- Event → Run → permanent Asset authority and Asset→Run→Case synchronization are unchanged.
