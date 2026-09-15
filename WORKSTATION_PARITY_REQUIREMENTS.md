# NHRA Tech Data — Analysis Workstation Parity Requirements

Baseline reviewed: 2026-09-13

## Product target

NHRA Tech Data is not intended to be a clone of one vendor viewer. The long-term target is:

> **ATLAS/i2-class telemetry analysis + authoritative NHRA Run/Asset data + drag-racing-specific engineering workflows + inverse/forward vehicle modeling + incident reconstruction.**

The mature products are used as a minimum capability benchmark. NHRA-specific functions should extend that baseline rather than replace basic workstation functionality.

## Current benchmark sources

Primary vendor documentation reviewed for this baseline:

- McLaren Applied ATLAS Viewer displays / functions / sessions / workbooks: https://docs.atlas.mclarenapplied.com/
- MoTeC i2 / i2 Pro feature matrix: https://www.motec.com.au/products/I2
- Bosch Motorsport WinDarab V7 product/features and current wiki: https://www.bosch-motorsport.com/products/software/data-analysis-tools/analysis-tool-windarab-v7/
- AiM RaceStudio 3 Analysis documentation: https://www.aim-sportline.com/docs/racestudio3/manual/html/analysis.html
- Cosworth Pi Toolbox documentation/product literature should remain in the recurring benchmark set as releases evolve.

The benchmark must be revisited periodically. It is a product requirements reference, not a claim of binary compatibility with any vendor software.

## Capability matrix

Status meanings:

- **Implemented** — present and exercised in the current source tree.
- **Foundation** — core architecture/primitives exist, but the mature workstation experience is incomplete.
- **Planned** — explicit long-term requirement.
- **Out of scope** — vendor/hardware-specific function that NHRA Tech Data should not reproduce.

| Capability | current status | Long-term requirement |
| --- | --- | --- |
| Dockable/floating workbook pages | Implemented | Mature layout templates, global/local display properties, page-level compare selection |
| Channel/parameter browser | Implemented | Groups, favorites, aliases, source/rate/unit/type metadata, drag/drop, user collections |
| Channel aliases | Implemented | Shareable vehicle/class alias libraries |
| Canonical channel roles | Implemented | Class/vehicle templates and auto-assignment review tooling |
| Time-series waveform | Implemented | Reference cursors, trace bands, advanced axis properties, per-parameter scales |
| Time / distance axes | Implemented | Improve distance reconstruction and GPS/downtrack fusion |
| Normalized run-progress axis | Implemented | Display-only normalization; never alter physical evidence time |
| Sample-index/logger-time views | Implemented | Retain for raw diagnostics |
| Multi-run overlay / compare set | Implemented | More explicit compare-set manager and per-display Run selection |
| View-only overlay alignment | Foundation | Graphical drag alignment / event alignment / stretch as display transform only |
| Values/cursor readout | Implemented | Multi-channel dashboard composition and reusable dashboard templates |
| A-B region statistics | Implemented | Percentiles, integral, dwell/time-above, event-to-event measures |
| Scatter / XY | Implemented | Z-colour and linear regression implemented; add reference curves and linked point/cursor selection |
| Histogram | Implemented | Sample/time and percent/cumulative modes implemented; add multi-run/multi-channel/suspension presets |
| FFT | Implemented | Multi-channel overlays and advanced window controls |
| PSD / Welch spectrum | Implemented | Frequency-band metrics and vibration presets |
| Spectrogram | Implemented | Linked time-frequency cursor and saved display settings |
| Load / heat / mixture map | Implemented | Cell annotations, configurable scales, lookup/reference surfaces, 3-D surface view |
| User math channels | Implemented + portable library | Dependency graph/cycle validation implemented; add lazy evaluation, richer functions and lookup tables |
| Data gates / conditions | Implemented + portable library | Apply consistently to every display and future live alarms |
| Channel/setup constants | Implemented foundation | Expand setup-sheet integration, unit/dimension inference and vehicle/class libraries |
| Official drag segments | Implemented + portable templates | Add event-to-event/rule-generated segment boundaries |
| Segment/KPI report | Implemented saved reports | Add richer table layout, sorting, reference deltas and visual color scales |
| Channel reports | Implemented foundation | Expand arbitrary channel grids and graph/table linked selection |
| Event markers / annotations | Implemented + portable rule events | Expand event-to-event regions, richer event metrics and Case-marker promotion |
| Alarms | Historical/load-time foundation | Add hysteresis/debounce actions, cached event indexes and future live evaluation |
| Strip map | Implemented foundation | 1-D drag-strip display with timing beams, events and measured/model residuals; add lane/GPS position and richer channel bands |
| GPS map | Planned | Map/lane trajectory with channel colourization when data exists |
| Track/segment map | Planned | General-purpose GPS use for non-drag testing without making it the primary NHRA model |
| Video/audio sync | Implemented foundation | Multi-camera tiled review, frame-accurate controls, video clips/snapshots |
| Telemetry-over-video export | Planned | Gauge/channel/event overlays and review exports without modifying originals |
| IDR synchronized review | Foundation | Native validated IDR decoders and coordinate/frame transforms |
| Image/document evidence | Foundation | Native evidence viewer, markup and report inclusion |
| Run setup sheet | Foundation | Structured vehicle/configuration values, comparisons and setup-derived constants |
| Data integrity / sensor health | Implemented | Cross-run sensor drift and anomaly trend tools |
| Weather/timing authority | Implemented | Tech Services remains authoritative |
| Run/Asset provenance and immutable cache | Implemented | Preserve audit chain across future server push-back |
| Live telemetry | Planned | Same sessions/channels/displays/math as historical analysis |
| Realtime replay | Planned | Ring buffer, reconnect/recovery, live-to-historical transition |
| High-rate lazy/background loading | Planned | Chunked/memory-mapped source access; avoid loading full high-rate recordings |
| Automation / batch processing | Foundation | Expand headless `analyze`, job definitions, regression suites and server-side tasks |
| Plugin / scripting API | Planned | Safe Python SDK plus stable data/display/report extension points |
| CSV export | Implemented for saved reports | Expand raw/normalized channel export with provenance |
| Excel export | Implemented for saved reports | Expand formatting, units/provenance and templates |
| MATLAB export | Planned | Numeric arrays + metadata/timebases |
| Parquet/Arrow export | Planned | Large-data engineering interoperability |
| PDF/HTML engineering reports | Planned | Reproducible case/run reports with source hashes and model versions |
| Team permissions / approval workflow | Desktop auth/entitlement foundation; server dependent | Reuse Tech Services identity, role/scope mapping, confidentiality, audit and approved-result publishing |
| RSA model / residual virtual channels | Implemented foundation | Treat model outputs as first-class derived channels everywhere; expand model providers, residual alignment and live enrichment |
| Multi-run inverse vehicle model | Strong foundation / differentiator | Evidence-aware time/downtrack fitting implemented; continue to AnalysisCase-owned shared fits, per-Run policies, posterior uncertainty and repeatable blind validation studies |
| Forward what-if simulation | Implemented study foundation / differentiator | Reproducible multi-axis sweeps, AnalysisCase ownership, optimization/design-of-experiments and server-approved publishing |
| Incident reconstruction | Foundation / differentiator | Delta-V, vectors, pulse analysis, trajectory and comparison to clean Runs |
| Longitudinal/parity intelligence | Foundation / differentiator | Event/season/platform trends using authoritative Run history |

## v0.21 workstation primitives

v0.21 begins the parity program with shared, UI-independent primitives rather than isolated widgets:

1. **Channel catalog / explorer**
   - source/native/calculated type;
   - unit and engineering dimension;
   - sample-rate metadata;
   - canonical role;
   - user alias;
   - query across all of the above.

2. **Safe data gates**
   - vector boolean expressions;
   - comparisons and boolean logic;
   - `abs`, `isfinite`, and `between` helpers;
   - no arbitrary Python execution;
   - no hidden interpolation across unrelated mixed-rate clocks.

3. **Official drag segments**
   - launch→finish plus 60/330/660/1000/1320 subsegments when timing exists;
   - time, distance and normalized-progress variants;
   - comparison reports use each Run's own official timestamps.

4. **Reusable metrics**
   - min/max/mean/median/std/RMS/range/start/end/delta/integral/slope/percentiles/count;
   - headless report generation across Runs and segments.

5. **Frequency analysis**
   - amplitude FFT;
   - Welch PSD;
   - time-frequency spectrogram.

6. **Binned maps**
   - count/occupancy and mean/median/min/max/std/sum Z statistics;
   - reusable for mixture, EGT, lambda, slip, boost and other load-map workflows.

7. **Headless analysis interface**
   - `analyze channels`;
   - `analyze gate`;
   - `analyze metrics`;
   - `analyze psd`;
   - `analyze loadmap`.


## v0.22 display-depth increment

The second parity increment adds:

1. **Gauge / status display** — numeric, bar, dial and bit views driven by the shared worksheet cursor with explicit/automatic ranges.
2. **Advanced XY** — optional third-channel colour, saved gate filtering and linear regression with slope/intercept/R².
3. **Engineering distributions** — sample-count/percent or physical dwell-time seconds/percent, cumulative mode, and saved-gate filtering. Time weighting integrates actual sample-to-sample dwell only and does not invent an interval beyond the recording.
4. **Headless parity** — `analyze scatter`, `analyze histogram` and `analyze sample` use the same functions as the desktop displays.

These remain display/analysis state. No catalog schema or evidence authority changes are introduced.

## v0.23 definition/report increment

v0.23 adds a versioned portable `DefinitionLibrary` with constants, canonical-role math, gates, official/manual segments, metrics, conditional rules and saved reports. It validates dependencies/cycles/missing inputs before execution; saved reports use each Run's own official timing boundaries, export CSV/JSON/XLSX and feed a saved KPI trend display. Workbook v6 embeds the current library and `.nhralib` supports explicit reuse. Headless `library inspect|validate|apply|report|starter` uses the same engine.

## Architectural rules

The parity effort must not weaken these existing rules:

- Tech Services owns Event → Run → permanent Asset identity.
- Raw Assets remain immutable.
- Display alignment must never silently rewrite authoritative Run/Case time.
- Math/gates/reports are derived state with explicit definitions and provenance.
- Unknown or unsupported native binary data fails closed.
- Live and historical data should eventually use the same channel/display/math abstractions.
- Batch/automation APIs should call the same analysis primitives used by the desktop.

## Next parity increments

Recommended next sequence after v0.23:

1. **Strip/GPS map** — NHRA downtrack map first, general GPS map second.
2. **Report/display depth** — 3-D surfaces, linked report/graph selection, richer report layouts and video/gauge export.
3. **Performance/loading** — chunked lazy loading and background calculation for large/high-rate files.
4. **Live architecture** — streamed sessions, alarms, reconnect/recovery and replay on the same display engine.
5. **SDK/plugins** — stable headless Python API and custom analysis/display extension boundary.
8. **Specialized engineering** — deeper IDR/incident calculations and the multi-run digital twin on top of the mature workstation.


## v0.24 event/alarm increment

v0.24 adds portable historical event/alarm rules to DefinitionLibrary v2. Rules share canonical-role expression resolution, support interval/rising/falling triggers, severity and minimum duration, feed the Events and Alarm Status displays, and run headlessly through `library events`. Live transport/reconnect/alarm actions remain future work.


## v0.25 protected desktop / simulation-study increment

v0.25 adds two cross-cutting foundations rather than another isolated display:

1. **Protected native desktop** — external-browser PKCE architecture, user roles/scopes, OS credential-vault persistence without plaintext fallback, bounded offline-entitlement model, per-operation transport scopes and fail-closed frozen-build policy. The actual site endpoints/claim names remain deliberately unbound until the Tech Services backend can be inspected.
2. **RSA Simulation Studies** — reusable multi-axis forward sweeps on the source-faithful Quarter Pro port or smooth engine, baseline timing/trap deltas, observed-vs-predicted validation, generated compare sessions and complete `.nhrastudy` provenance packages.

These two areas are strategic differentiators: workstation parity remains important, but the product must not drift into becoming only a telemetry viewer.


## v0.26 drag-specific strip/model increment

- **Implemented:** NHRA strip/downtrack display with official 60/330/660/1000/1320 markers.
- **Implemented:** measured-vs-RSA channel overlays and model-minus-measured residual traces.
- **Implemented:** official ET/trap residual table and beam-to-beam section-error decomposition.
- **Implemented:** portable rule events projected onto physical downtrack distance.
- **Implemented:** headless strip-analysis/export command.
- **Implemented in v0.27:** direct inverse-fit evidence weighting from selected strip sections/downtrack windows, with selectable telemetry channels and independent official ET/trap constraints.
- **Still planned:** GPS/lane displacement, multiple spatial coordinate sources with uncertainty, track-grade correction, richer per-Run policies, and posterior uncertainty.


## v0.27 evidence-aware inverse-model increment

- **Implemented:** time-domain or physical-distance telemetry residuals in the inverse solver.
- **Implemented:** trusted weighted downtrack windows (for example 330–1320 ft) to exclude launch/shake or isolate specific vehicle behavior.
- **Implemented:** independent inclusion/weighting of speed, engine RPM, driveshaft RPM and longitudinal G.
- **Implemented:** independent official ET and trap-speed weights while preserving timing-system semantics.
- **Implemented:** explicit engineering uncertainty scales and normalized residual output.
- **Implemented:** Inference Center controls plus ModelSnapshot provenance for evidence policy/unknowns/nuisance terms.
- **Implemented:** headless fit configuration and residual CSV export.
- **Still planned:** per-Run policy editor for joint fits, section/event-relative weighting, robust loss/outlier controls, profile likelihood/Bayesian posterior analysis, and automated blind-recovery validation suites.


## v0.28 joint reconstruction increment

- **Implemented:** one shared vehicle fit across multiple measured Runs.
- **Implemented:** independent evidence policy per Run, including different trusted downtrack windows.
- **Implemented:** explicit per-Run nuisance allowlists for bounded power, traction and rollout differences.
- **Implemented:** portable `.nhrafit` study packages with Run references/roles and model provenance.
- **Implemented:** residual objective decomposition by Run, source and named distance window.
- **Implemented:** parameter-level identifiability/correlation diagnostics in the study package.
- **Next:** profile-likelihood/sensitivity analysis and richer posterior uncertainty for weakly identified shared parameters.


## v0.29 practical-identifiability increment

- **Implemented:** on-demand nonlinear profile-objective scan for shared joint-fit parameters.
- **Implemented:** re-optimization of all remaining permitted shared/nuisance freedom at each forced profile value.
- **Implemented:** practical bounded/one-sided/flat-in-scan classification.
- **Implemented:** `.nhrafit` v3 persistence of profile rows and interpretation metadata; v1/v2 remain readable.
- **Implemented:** CLI and Inference Center profile workflows.
- **Next:** adaptive/two-parameter profiles, leave-one-Run-out influence and Monte Carlo/posterior uncertainty.


## v0.30 Run-influence increment

- **Implemented:** leave-one-Run-out full refit across Joint Reconstruction Studies.
- **Implemented:** per-parameter shift, engineering-bound-span fraction and optional local-SE shift.
- **Implemented:** low/moderate/high Run-influence classification and dominant shared parameter.
- **Implemented:** correct remapping of retained Run-specific nuisance parameters after omission.
- **Implemented:** CLI and Inference Center workflows.
- **Implemented:** `.nhrafit` v4 persistence; v1–v3 remain readable.
- **Next:** omitted-Run predictive scoring, adaptive/two-parameter profiles and Monte Carlo/posterior uncertainty.
