# NHRA Velocity — Long-Term Roadmap v0.38

> **2026-09-16 product audit:** the immediate priority is the Reliability Gate in `PRODUCT_AUDIT_v0_38.md`. Breadth is now ahead of workflow cohesion; new isolated analysis windows should not outrank packaged-Windows reliability, Run/data persistence, compare/workbook ergonomics, or verified server contracts.

## Product invariant

The platform has three equal pillars: **Tech Services authority**, **ATLAS/i2-class analysis workstation**, and **RSA engineering/digital twin**. Development should not allow one pillar to crowd out the other two.

## Priority A — Consolidate and verify architecture

- keep `PRODUCT_ARCHITECTURE.md` and the machine-readable release manifest canonical;
- run the release-consistency audit before every frozen archive;
- pin and record both mandatory upstream SHAs whenever reachable;
- build a real Windows Qt launch/smoke-test pipeline in addition to headless regression tests.

## Priority B — Bind the real Tech Services platform

- ✅ inspect pinned `nhratechservices` source read-only and record the audited revision;
- map the verified Bearer-token user/login/role model into a safe native-desktop sign-in flow; the current website does not expose PKCE/refresh endpoints;
- ✅ bind the verified Tech Master Event/Entry and normalized parity Run read APIs;
- expose the existing `parity_runs.event_entry_id` relationship through a protected read API;
- add/verify permanent Run→Asset attachment/storage semantics; the audited current source has no telemetry Asset catalog/download endpoint yet;
- bind canonical catalog pull, Asset download, permissions and bounded offline access;
- make shared AnalysisCases, published ModelSnapshots/studies and approved reports durable server knowledge;
- add server audit history for protected downloads and write-back.

No production endpoint or schema is invented before the upstream contract is verified.

## Priority C — Finish ATLAS/i2-class daily usability

- stronger Compare Set/session manager and per-display Run selection;
- reference/dual cursors, linked display selection and graphical view-only alignment;
- structured setup sheets, channel groups/favorites and vehicle/class templates;
- richer report layout, reference deltas, color scales and PDF/HTML publishing;
- GPS/lane mapping and richer NHRA strip spatial displays;
- tiled multi-camera review and telemetry-over-video export;
- MATLAB plus Parquet/Arrow interoperability;
- plugin/SDK boundary using the same headless primitives as the desktop.

## Priority D — RSA as the Enrich layer

- keep source-faithful Quarter Pro behavior separate from the smooth optimization engine;
- maintain a pinned RacingSystemsAnalysis source-fidelity matrix and regression fixtures;
- expose fitted/simulated `Model.*` channels and explicit `Residual.*` channels throughout normal analysis;
- convert useful legacy RSA worksheets into a modern Vehicle Model Builder rather than copying their UI;
- capture authoritative original Quarter Pro executable outputs for black-box parity validation;
- make Joint Reconstruction and Simulation Studies AnalysisCase-aware and publishable;
- continue predictive holdout validation, two-parameter profiles and probabilistic uncertainty only after core integration work is stable.

## Priority E — Data performance, live and automation

- chunked/memory-mapped high-rate decoding and lazy calculation;
- background jobs with progress/cancel/retry and deterministic caches;
- live transport that produces the same session/channel objects as historical files;
- reconnect/recovery, ring buffer and live-to-historical transition;
- evaluate the same portable math/gates/events/model providers in live and replay modes;
- stable batch/job API and later server-side automation where appropriate.

## Priority F — NHRA differentiators

- longitudinal parity/platform/season intelligence from authoritative Run history;
- IDR-native decoding, coordinate transforms, impact pulse/ΔV and incident reconstruction;
- case-level model/evidence reporting with source hashes, software/model versions and uncertainty;
- design-of-experiments/setup optimization on top of validated RSA models.

## Version 1.0 definition

1. Tech Services login/authorization and authoritative Run/Asset sync are real, not development snapshots.
2. A Windows engineer can use the desktop every day for normal ATLAS/i2-class analysis with reliable saved workbooks.
3. RSA model/residual channels are integrated into ordinary analysis, not isolated simulation dialogs.
4. Multi-Run reconstruction and forward studies are reproducible, case-aware and publishable.
5. Track-side offline use, synchronized evidence and protected distribution are production-ready.
6. Large data and Qt runtime behavior are validated on real target hardware.
