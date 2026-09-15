# NHRA Tech Data v0.37 — Changelog

## Interactive performance

- Added `DisplaySeriesCache` for reusable X/Y mapping, interpolation views and cursor snap grids.
- Cursor snapping now uses binary search on a cached grid instead of scanning the full channel on each hover event.
- Cursor/A/B values are sampled together from one cached interpolation view instead of independently rebuilding/sorting data three times per channel.
- Waveform readout repaint is coalesced to approximately 30 Hz and existing table cells are reused instead of recreated.
- Pointer tracking is capped at 30 Hz; duplicate snapped cursor positions no longer emit redundant cursor work.
- pyqtgraph traces now use view clipping plus automatic peak downsampling in addition to the existing peak-preserving source preparation.
- Values and Gauge displays use the same cached/coalesced cursor strategy; Gauge auto-range is cached per display state.
- Active-session changes no longer force the main waveform through duplicate `changed` + `activeChanged` full redraws.
- Compare alignment updates no longer explicitly redraw waveforms a second time after the store change signal.
- Multi-channel drag/drop performs one waveform rebuild after the complete drop rather than one rebuild per channel.

## Daily waveform workflow

- Added an always-visible toolbar **Run** selector for the active/Main session.
- Added a toolbar **Reference** selector beside Compare; enabling Compare can automatically choose the first other loaded session as Reference.
- Channel Explorer supports persistent cross-project **Favorites**, grouped at the top.
- Single-channel stacked plots suppress redundant legend boxes while compare/overlay/unit-group legends remain available.
- Waveform click shortcuts: normal click sets Cursor, `Shift+click` sets A, `Ctrl+click` sets B.

## Validation / provenance

- Product version advanced to `0.37.0-development`; persistent format versions are unchanged.
- v0.36 received its first real Windows GUI trial: application launch, MoTeC `.ld` open/render and RacePak `.rpk` open/render succeeded; interaction lag observed in that trial triggered this performance pass.
- A real 2026 Indianapolis MoTeC file was used for the cursor hot-path benchmark.
- Upstream reference pins remain RacingSystemsAnalysis `1556ac70684908038fe47a9fe54e2f506cc4e71c` and nhratechservices `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`.
