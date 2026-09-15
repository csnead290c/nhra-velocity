# RSA Model Enrichment — v0.31

## Purpose

RSA simulation and reconstruction are part of the ordinary engineering workstation, not a separate application. `runlab.model_enrichment` publishes model-derived channels into an in-memory measured Run while keeping raw telemetry and official NHRA timing authoritative.

## Clock semantics

- `Model.*` channels use the RSA simulation's **physical Run-time** axis aligned to the workstation launch convention (the last near-zero-speed sample before the pass excursion).
- The NHRA ET clock remains separate and continues to govern official increment/trap validation.
- No logger source channel is rewritten or resampled merely to host a model channel.
- `Residual.*` channels are calculated only through an explicit interpolation of the measured canonical channel onto the model Run-time grid.
- Residual sign is always **model minus measured**.

## Stable virtual roles

Examples:

- `Model.Speed` → `model_speed_mph`
- `Model.Engine RPM` → `model_engine_rpm`
- `Model.Driveshaft RPM` → `model_driveshaft_rpm`
- `Model.Longitudinal G` → `model_longitudinal_g`
- `Residual.Speed` → `residual_speed_mph`
- `Residual.Engine RPM` → `residual_engine_rpm`

These roles are visible through the normal channel resolver so portable definitions can consume them without vendor-specific names.

## Provenance

Every enrichment stores:

- NHRA Tech Data software version;
- model engine (`reference` or `smooth`);
- optional ModelSnapshot ID;
- vehicle/environment/model fingerprint SHA-256;
- model clock semantics;
- residual sign convention.

Workbook derived-analysis state stores the engine/settings and rebuilds the enrichment from the retained vehicle model when the workbook is reopened.

## Long-term direction

The provider boundary should grow beyond one RSA implementation. Other validated models may eventually publish their own namespaced virtual parameters through the same interface. Historical, live and replay analysis should consume the same resulting channel abstraction.
