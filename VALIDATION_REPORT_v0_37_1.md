# NHRA Tech Data v0.37.1 — Validation Report

## Release scope

v0.37.1 is a focused Windows waveform-render hotfix for v0.37. The first v0.37 Windows trial successfully opened the RacePak file and populated the Channel Explorer, but the waveform failed before drawing with `AttributeError: GraphicsLayoutWidget object has no attribute autoRangeEnabled`.

## Root cause and correction

The regression came from re-enabling pyqtgraph `clipToView` and automatic downsampling flags on `PlotDataItem` construction. The Windows pyqtgraph runtime entered an auto-range query before the item had a compatible ViewBox parent. These flags are now removed from both the main waveform and navigator. NHRA Tech Data's existing `prepare_plot_series()` stage still repairs non-finite/non-monotonic clocks and performs peak-preserving source decimation before Qt rendering; the main display remains capped at 50,000 points per trace by default and the navigator at 10,000.

The v0.37 data-side performance work remains unchanged: cached X/Y mapping and interpolation, binary-search snapping, batched Cursor/A/B sampling, ~30 Hz coalesced readout painting, reduced redraws, and direct Run/Reference workflow.

## Regression coverage

- `PYTHONPATH=. pytest -q` → **189 passed**.
- `python -m compileall -q .` → **PASS**.
- `PYTHONPATH=. python -m runlab.cli selftest` → **3/3 PASS** (RacePak, MoTeC, MaxxECU).
- Pinned release audit → **0 errors / 0 warnings**.
- A new compatibility regression fails if `clipToView=True`, `autoDownsample=True`, or the implicit peak-downsample constructor path is reintroduced in `desktop.py`, and separately verifies that the application's own bounded `prepare_plot_series()` path remains enabled.

## Runtime-validation limitation

PySide6/pyqtgraph are not available in this isolated Linux build environment and package installation is network-blocked, so the exact Windows Qt runtime still must be re-tried by the user. The fix is intentionally conservative and restores the renderer contract that was already proven on Windows in v0.36 while keeping the non-renderer performance improvements from v0.37.

## Provenance

Persistent format versions remain catalog 7, workbook 8, analysis library 2, simulation study 2, fit study 5 and Tech Services sync contract 4. Upstream pins remain RacingSystemsAnalysis `1556ac70684908038fe47a9fe54e2f506cc4e71c` and nhratechservices `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`.
