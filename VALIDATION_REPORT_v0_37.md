# NHRA Tech Data v0.37 — Validation Report

## Release scope

v0.37 is an interactive-performance and everyday-waveform-workflow milestone. It is directly motivated by the first real Windows trial of v0.36: the desktop launched successfully and the user opened/rendered both MoTeC `.ld` and RacePak `.rpk` files, but waveform interaction was noticeably laggy. No RSA/Quarter Pro physics, import calibration, official timing/weather authority, or Tech Services Run/Asset ownership rule is changed by this release.

## Root-cause finding

The v0.36 cursor hot path repeated expensive work for every pointer event. With snap/readout enabled, each event could rebuild channel X/Y mapping, scan the full X array for the nearest sample, sort X/Y again for interpolation, sample Cursor/A/B independently for every displayed channel, and recreate QTableWidget items. The waveform pointer proxy allowed up to 60 events/s. This made GUI-thread latency scale unnecessarily with channel length and displayed-channel count.

## Corrective work

- Added a bounded `DisplaySeriesCache` shared by each waveform display.
- Cached format-neutral X/Y mapping, prepared interpolation views and snap grids.
- Replaced O(n) nearest-sample scanning with binary search.
- Batched Cursor/A/B interpolation per channel.
- Coalesced cursor readout painting to about 30 Hz and reused table items.
- Reduced pointer tracking to 30 Hz and suppress duplicate snapped positions.
- Enabled pyqtgraph view clipping and automatic peak downsampling.
- Applied the same strategy to Values/Gauge cursor-driven displays.
- Removed duplicate full waveform redraw paths on active-session/alignment changes.

## Real-data cursor benchmark

Source: `S1_#2626_20260908_103002.ld` from the 2026 Indianapolis PSM test archive. Seven channels were sampled across 240 cursor positions using Cursor+A+B values per channel.

- v0.36-style repeated mapping/sort/sample path: **2.8370 s total**, **11.821 ms/cursor frame**.
- v0.37 cached/batched path: **0.01088 s total**, **0.04535 ms/cursor frame**.
- Data-side cursor hot-path reduction: approximately **260.7×** in this controlled headless benchmark.

This does not imply a 260× end-to-end GUI speedup; Windows/Qt painting, graphics-driver behavior and widget layout still contribute latency. It does show that the avoidable Python/data work identified from the Windows trial has been removed. Machine-readable results are stored in `validation/PERFORMANCE_BENCHMARK_v0_37.json`.

## Workflow additions

The simple workspace now exposes Main Run and Reference selection directly in the toolbar, Channel Explorer has persistent Favorites, single-channel stacked plots omit redundant legends, multi-channel drops rebuild once, and A/B cursors can be placed with Shift/Ctrl click. These changes target routine pass-to-pass analysis rather than adding new specialist analysis windows.

## Automated regression

- `PYTHONPATH=. pytest -q` → **187 passed**.
- `python -m compileall -q .` → **PASS**.
- `PYTHONPATH=. python -m runlab.cli selftest` → **3/3 PASS** (RacePak, MoTeC, MaxxECU native demo pipelines).
- New cache-focused regression → **4/4 passed** and verifies X/Y reuse, batched interpolation, nearest-sample behavior and one-time repair of non-monotonic/duplicate X values.

## Windows validation status

The prior v0.36 build has now been manually exercised on Windows and confirmed to launch and render real `.ld` and `.rpk` telemetry. That trial identified the interaction-performance issue addressed here. The **v0.37 binary itself still requires the follow-up Windows smoke trial** to verify the new Qt toolbar interactions and perceived pan/zoom/cursor responsiveness.

## Provenance

Persistent format versions remain catalog 7, workbook 8, analysis library 2, simulation study 2, fit study 5 and Tech Services sync contract 4. Read-only upstream pins remain RacingSystemsAnalysis `1556ac70684908038fe47a9fe54e2f506cc4e71c` and nhratechservices `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`.

## Release conclusion

v0.37 is suitable as the next Windows development trial. The next decision should be based on that real interaction test: if cursor/pan/zoom responsiveness is now acceptable, development should move to deeper daily-workflow functionality (vehicle/setup/channel templates, richer compare-session controls, reporting/publishing and lazy/background loading). If the Qt renderer remains materially laggy, profile paint/range-change behavior on Windows before adding more UI.
