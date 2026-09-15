# NHRA Tech Data v0.37.1 — Hotfix changelog

## Windows waveform render regression

The first Windows trial of v0.37 exposed an immediate pyqtgraph render failure while opening a real RacePak run:

`AttributeError: 'GraphicsLayoutWidget' object has no attribute 'autoRangeEnabled'`

The failure was introduced by the v0.37 renderer-performance pass. `clipToView=True` and `autoDownsample=True` were supplied while constructing `PlotDataItem` traces. On the Windows pyqtgraph runtime used for the trial, that path caused the item to query auto-range state before it had a compatible `ViewBox` parent.

### Fix

- Removed pyqtgraph's implicit `clipToView` / `autoDownsample` flags from waveform traces and the navigator.
- Retained NHRA Tech Data's own `prepare_plot_series()` pipeline, which already repairs the X clock and peak-preserving decimates each trace before it reaches Qt.
- The main waveform remains capped by the configurable `max_render_points` setting (50,000 points/trace by default).
- The navigator remains independently capped at 10,000 points.
- All v0.37 cursor-cache, 30 Hz coalescing, Run/Reference selector, Favorites and redraw-reduction work remains intact.
- Added a source regression test that fails if the unsafe pyqtgraph constructor flags are reintroduced.

No telemetry-decoder, RSA/Quarter Pro, timing/weather, workbook, catalog, Tech Services or evidence-authority behavior changes in this hotfix.
