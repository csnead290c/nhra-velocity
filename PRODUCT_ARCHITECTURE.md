# NHRA Velocity — Product Architecture v0.38


## v0.37 interaction-performance layer

Interactive display work is now treated as a separate performance layer over immutable telemetry. Channel/time mapping and interpolation views may be cached inside a worksheet, but the cache is invalidated whenever the Run/session mapping changes and it never modifies source arrays. Cursor movement is a hot path: sampling, snapping and GUI readout updates are bounded so large native logs remain usable on ordinary trackside Windows hardware. Toolbar Run/Reference selection and Channel Favorites reduce the number of dock/menu operations needed during routine pass-to-pass analysis.

## v0.36 scalable ingestion + reusable comparison

The workstation now separates file-family recognition, decoder availability and qualification status through a declarative import registry. It also promotes ad-hoc comparison session state into persistent Named Compare Sets. Both changes stay below the authority boundary: source telemetry remains immutable, alignment is display-only, and only Tech Services can define permanent Run/Asset identity.

## v0.33 interaction and native-data boundary

This milestone deliberately moves the product toward a telemetry-first workstation: the central waveform and native logger import path are P0 capabilities; specialist analysis surfaces are secondary and discoverable rather than always visible. Current RacePak `CAN_Device` and MoTeC M1 files are decoded locally without a Box/runtime dependency, and raw source bytes remain unchanged.
## North-star product

NHRA Velocity is one engineering platform with three equal pillars:

1. **NHRA Tech Services** — authoritative identity, Events, Entries, Runs, official timing/weather, permanent Assets, users, permissions, shared cases and approved published results.
2. **Analysis Workstation** — ATLAS/i2-class daily telemetry, comparison, math, reporting, synchronized evidence, alarms, automation and future live/replay workflows.
3. **RSA Engineering Engine** — Racing Systems Analysis / Quarter Pro source fidelity, inverse reconstruction, forward simulation, model enrichment, uncertainty and digital-twin workflows.

The product target is not a visual clone of any commercial viewer. ATLAS, MoTeC i2/i2 Pro, Cosworth Pi Toolbox, Bosch WinDarab and AiM RaceStudio define the minimum mature workstation capability. NHRA-specific data authority, drag-racing workflows, RSA modeling and incident reconstruction extend that baseline.

## System boundary

```text
NHRA Tech Services (authoritative)
    Event → Entry → Run → Asset
    timing / weather / identity / permissions
                 │
                 ▼
NHRA Velocity Desktop
    local mirror + immutable verified cache
    workbooks / displays / reports / cases
                 │
          ┌──────┴────────┐
          ▼               ▼
Analysis workstation   RSA engineering engine
measured channels      fitted vehicle / simulation
          │               │
          └──────┬────────┘
                 ▼
      Model.* / Residual.* virtual channels
                 │
                 ▼
 same plots / gates / KPIs / alarms / reports
```

## Authority rules

- Tech Services owns permanent Event, Run and Asset identity.
- A filename never determines Run ownership.
- Raw server Assets are immutable; the local object store is an expendable SHA-256 verified cache.
- Scratch files opened directly in the desktop never become authoritative Runs automatically.
- Official timing/weather remain authoritative and are not overwritten by logger metadata or model output.
- Display-only alignment never rewrites evidence time.
- RSA outputs are derived engineering evidence with model/version/provenance, not source telemetry.
- Production endpoints, auth claims, storage semantics and database tables are never invented before verifying `nhratechservices`.
- Fundamental physics/source-fidelity changes are reviewed against a pinned `RacingSystemsAnalysis` revision whenever the repository is reachable.

## ATLAS-style platform mapping

| Platform responsibility | NHRA implementation target |
| --- | --- |
| Analyse | Desktop workbooks, displays, compare sets, reports, synchronized review |
| Store | NHRA Tech Services authoritative Runs/Assets/cases/results |
| Enrich | RSA model, reconstruction, Model.* and Residual.* virtual channels |
| Stream | Future live telemetry/replay transport using the same channel abstractions |
| Integrate | Headless CLI today; stable SDK/API/automation boundary long term |

## Current v0.33 integration step

v0.33 keeps the v0.31 **RSA enrichment layer** and adds the first source-verified NHRA Tech Services metadata boundary. The audited website uses Bearer tokens for protected API routes, and the workstation now binds real Tech Master Event/Entry reads plus normalized parity Run reads through a hardened GET-only client. The database already has `parity_runs.event_entry_id`, but the current Run API omits that field, and no permanent Run→Asset manifest/download endpoint is exposed. Full canonical sync therefore remains fail-closed until the server exposes those exact links; the desktop does not infer them.

Representative channels include `Model.Speed`, `Model.Engine RPM`, `Model.Driveshaft RPM`, `Model.Longitudinal G`, `Model.Engine Power`, `Model.Engine Torque`, `Model.Tire Slip Ratio`, `Model.Aero Drag`, and corresponding `Residual.*` channels where measured evidence exists.

The same channels are visible to the Channel Explorer, waveforms, portable definitions, reports and future alarm/live systems. This is the bridge between the RSA digital twin and the ordinary ATLAS/i2-style workstation.

## Required upstream references

- `https://github.com/csnead290c/RacingSystemsAnalysis` — physics/source-fidelity authority.
- `https://github.com/csnead290c/nhratechservices` — production identity/auth/data/API authority.

Every release manifest has a place for both commit SHAs. If a repository cannot be reached, its SHA is recorded as `unverified`; the build must not silently assume moving `main`.

## Version 1.0 exit criteria

A credible 1.0 requires all of the following:

- existing Tech Services identity works in the desktop with server-side authorization;
- authoritative Run/Asset catalog and verified downloads are bound to the real backend;
- professional saved-workbook analysis covers normal ATLAS/i2-class daily workflows;
- measured and RSA model/residual channels coexist naturally throughout the workstation;
- multi-Run reconstruction and reproducible forward studies are case-aware and publishable;
- synchronized telemetry/video/IDR evidence is usable offline at the track;
- large/high-rate files use lazy/background loading rather than full-memory assumptions;
- a real Windows validation pipeline launches and exercises the packaged Qt application;
- approved results/reports can be published back to Tech Services with provenance and audit history.
