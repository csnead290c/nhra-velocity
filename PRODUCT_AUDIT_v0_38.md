# NHRA Velocity — Product Audit v0.38

Date: 2026-09-16
Baseline: v0.38.0-dev.18

## Executive finding

Velocity is no longer a prototype decoder with a plotting window. It already has the foundations of the intended product: an authoritative NHRA Run model, a professional desktop workbook, a broad analysis library, multi-vendor ingestion, RSA reconstruction/simulation primitives, cases, synchronized evidence, CI, Windows packaging and release/update scaffolding.

The primary risk has changed. **Breadth is now ahead of trackside reliability and workflow cohesion.** The next development phase should resist adding isolated analysis windows unless they close a documented daily-workflow gap. The highest-value work is to make the core Run → Data Log → Waveform → Compare → Analysis → Save/Share path fast, predictable and difficult to break.

The product north star remains three equal pillars:

1. **Tech Services authority** — Event → Entry → Run → Asset, official timing/weather, permissions, shared cases and approved results.
2. **Professional analysis workstation** — ATLAS/i2-class daily data review, compare, math, reports, evidence and reusable workbooks.
3. **RSA engineering engine** — source-faithful Quarter Pro/RSA modeling, inverse reconstruction, forward studies and Model/Residual channels inside normal analysis.

## Current-state scorecard

| Area | Status | What is already real | Main gap before 1.0 |
| --- | --- | --- | --- |
| Tech Services identity / metadata | Strong development foundation | Real site login, capability refresh, Events/Entries/Runs, official timing and canonical weather, staged/background sync | Permanent server Run→Asset contract, protected Asset download/upload, server-side cases/results |
| Run / local data lifecycle | Usable bridge | Explicit Run-first local data attachment, managed SHA-256 object store, filename-preserving decode alias, reopen/persistence, manual zero mapping | Promote local bridge to real server Assets once backend contract exists; richer attachment/history UI |
| Waveform / daily review | Rapidly maturing | Stacked channels, click/drag cursor, reference cursor, X zoom, manual zero, statistics, channel removal, official beam overlays, channel explorer | More interaction QA, better trace properties, reusable layouts/templates, polished compare ergonomics |
| Workbook / desktop shell | Good foundation | Dockable displays, saved workbooks, worksheets, autosave/recovery, focus mode, cases, compare sets | Stronger workspace/template manager, consistent display prerequisites, publish-quality layout/report flow |
| Analysis displays | Broad but uneven | Values/gauges, stats, scatter, histogram, spectrum, maps, KPIs, deltas, envelope, alarms, sensor health, strip/model displays | Systematic GUI/runtime validation and prerequisite handling; reduce “menu exists but context is missing” failures |
| Compare workflow | Functional foundation | Reference/overlay roles, named Compare Sets, per-display Run selection, reference stepping, alignment | ATLAS/i2-class session manager, faster A/B/reference selection, compare-aware values/statistics/reporting everywhere |
| Import / decode | Strong architecture, mixed qualification | Registry, fail-closed recognition, RacePak direct DDF, MoTeC, MaxxECU, Holley paths, generic text/Excel/VBOX/TunerStudio | Qualified real-world corpus for more vendors; MDF4/AiM SDK and prioritized logger families |
| RSA / digital twin | Powerful engine, not yet seamless | Vehicle inputs, delivered-power reconstruction, inverse fitting, joint studies, simulation studies, Model/Residual channels | One coherent Vehicle Model Builder and tighter Model/Residual integration into ordinary workbook/report workflows |
| Cases / synchronized evidence | Advanced foundation | AnalysisCases, Asset→Run→Case time mapping, case cursor, video/audio seeking, markers | Production Asset backend, stronger media UX, IDR-native reconstruction and publishable evidence packages |
| Performance / large data | Early | Display-series cache, decimation/performance work from v0.37 | Chunked/lazy decode, background jobs, cancellation, deterministic derived-data cache |
| Windows production / release | Good scaffolding, needs stronger gate | PyInstaller, Inno Setup, CI, release workflow, update manifest, crash logging, dev auto-update | Frozen/installed GUI launch smoke gate, packaged interaction tests, signing/update rollout on real target PCs |
| Live / replay / automation | Early | Headless primitives and portable analysis definitions provide the right boundary | Live transport, ring buffer/reconnect, stable plugin/SDK/job API |

## Immediate product rules

1. **Trackside core comes before feature count.** Opening a Run, reopening its attached data, cursor/zoom/zero, compare and workbook restore must be boringly reliable.
2. **One interaction model.** Reference + live cursor is the normal analysis interval. A/B or legacy cursor concepts may exist internally only when the UI explicitly exposes them.
3. **One Run identity model.** A filename never discovers or owns a Run. Tech Services owns permanent identity; the local bridge is explicit and visible.
4. **One analysis surface.** Model.* / Residual.* / calculated / measured channels should behave as peers in the same plots, statistics, reports and comparisons.
5. **Fail visibly.** Unsupported analysis, decoder or server capability must explain what is missing instead of silently doing nothing.
6. **Every packaged platform build proves it can launch.** Source tests are not enough for a packaged Qt desktop application. Windows remains the production target; macOS development builds now carry the same smoke-test expectation.

## Execution plan

### Phase 0 — Reliability gate (now → v0.39)

- frozen and installed Windows GUI smoke tests in CI;
- packaged macOS `.app` build + GUI smoke test in CI, with production distribution held until Developer ID signing/notarization;
- startup/crash logging before Qt window construction;
- automated construction/refresh smoke coverage for every ordinary Analysis display;
- explicit action prerequisites and useful failure messages;
- attachment/reopen, workbook restore, launch-zero and compare regression scenarios;
- installer/version/update-manifest consistency checks;
- trackside performance instrumentation for sync/open/render latency.

**Exit condition:** no known P0 defect in the Run → Data Log → Waveform → Compare → Save/Reopen path, and packaged Windows startup is a CI release gate.

### Phase 1 — Daily workstation completeness (v0.39 → v0.45)

- stronger session/Compare Set manager and faster reference selection;
- Common Channel mapping + context-scoped driver/category or vehicle/category profiles, with exact data-log overrides (foundation delivered in dev.15/dev.16);
- reusable channel groups, class/vehicle/team mapping profiles and worksheet templates;
- mature Math Channel Builder + reusable formulas (portable @Common Channel foundation delivered in dev.15);
- trace properties and axis grouping/scaling workflow;
- compare-aware statistics/value strips everywhere;
- report builder/publishing layout with PDF/HTML/XLSX provenance;
- keyboard/mouse behavior aligned intentionally with mature motorsport tools where useful.

**Exit condition:** an engineer can use Velocity instead of a conventional logger viewer for normal event review without fighting the UI.

### Phase 2 — Authoritative Assets and shared knowledge

Dependent on verified Tech Services backend support:

- permanent Run→Asset manifest/download API;
- secure Asset upload/attachment path;
- bounded offline cache policy;
- shared AnalysisCases, reports, ModelSnapshots/studies and audit history;
- incremental sync based on server revision/change state rather than season rescans.

**Exit condition:** local working attachments are no longer the normal production path.

### Phase 3 — RSA unified engineering workflow

- Vehicle Model Builder built from the useful Quarter Pro/RSA concepts, not a legacy UI copy;
- guided evidence sufficiency/identifiability before fitting;
- multi-run inverse fitting as a normal case/workbook operation;
- Model.* and Residual.* channels created, versioned and compared like measured channels;
- setup/ratio/power/shift studies launched directly from a validated model and written back as reproducible scenarios;
- holdout/predictive validation and uncertainty surfaced in reports.

**Exit condition:** the same workstation naturally answers both “what happened?” and “what would happen if we changed X?”

### Phase 4 — Scale, incidents and live workflows

- lazy/chunked high-rate data and background job scheduler;
- native IDR decode, impact pulse/ΔV and incident evidence package;
- GPS/spatial/lane-map analysis and multi-camera review;
- live/replay transport using the same Run/channel/display abstractions;
- stable plugin/SDK/job boundary.

## dev.15/dev.16 execution note — common engineering vocabulary

The first Phase 1 foundation is now implemented. Velocity distinguishes **Display Alias** (cosmetic text) from **Common Channel** (engineering identity). Common Channel mappings are vendor-independent inputs to worksheets, comparisons, reports, RSA and portable math; reusable mappings can be explicitly taught only in narrow Driver+Category+Logger or Vehicle+Category+Logger profiles, while exact data-log choices remain higher authority and persist per attached Asset. The Math Channel Builder consumes those identities through `@common_role` references so one formula survives logger naming changes. The next step is to lift those learned mappings/templates from one workstation preference file into shareable vehicle/class/team profiles and the broader Analysis Definition Library.

## Version 1.0 acceptance test

A credible 1.0 is not defined by the number of menu items. It is the point where a Windows engineer can:

1. sign in and immediately see the current/last completed event;
2. open an authoritative Run and its permanent Asset(s), or work offline from a verified cache;
3. review/compare data with professional cursor, zoom, statistics, math and workbook behavior;
4. save/reopen the same workspace without losing Run relationships, zero/alignment or derived analysis;
5. build/validate an RSA vehicle model from one or more Runs and use it for forward studies;
6. publish a reproducible case/report with source hashes, official timing/weather, software/model versions and uncertainty;
7. do all of the above on real NHRA Windows hardware with installer/update/crash behavior validated by automated and target-PC testing.

## dev.17/dev.18 execution note — RacePak definitions + trackside setup coherence

RacePak raw-DDF configuration profiles now allow a trusted `.rcg` **or prior good `.rpk`** to provide stable channel-id/name/unit definitions for future Driver+Category or Vehicle+Category DDFs while pinning the exact config fingerprint to each historical attached data log. dev.18 adds profile management and a Data Log Setup / Readiness view so RacePak definition, Common Channel mapping, math channels, launch zero, attachment authority and data warnings can be checked in one place before analysis. Branding/Windows shortcut integration is also moved into the packaged build rather than treated as external installer polish.


## dev.19 execution note — macOS without a second product

macOS is now an explicit future target rather than an afterthought. Core CI runs on Windows, macOS and Linux, and the dedicated macOS build lane packages the real `NHRA Velocity.app` and executes the network-free desktop smoke scenario. The application continues to share one Run/catalog/workbook/math/RSA code path; platform-specific behavior is limited to packaging, credential vault integration, updater handoff and optional vendor-native bridges. Production macOS distribution remains intentionally incomplete until Developer ID signing, hardened runtime, notarization and Gatekeeper verification are automated. See `MACOS_PLAN.md`.
