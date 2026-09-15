# NHRA Tech Data v0.36 — Changelog

## Import architecture

- Added a declarative telemetry format registry that separates recognition, decoder availability, and qualification status.
- Restored/implemented direct interchange paths documented in the v0.35 hardening audit: Racelogic VBOX `.vbo`, TunerStudio/MegaSquirt text `.msl`/`.mlg`, and Excel `.xlsx`/`.xlsm` telemetry tables.
- Expanded fail-closed recognition for MDF, AiM, FuelTech, Holley, HP Tuners, VBOX VBB, AEM, ECUMaster, Emtron, Cosworth/Pi, iRacing, Syvecs, MegaSquirt FRD, CAN captures, and legacy spreadsheets.
- Added `python -m runlab.cli formats` and registry/probe metadata to corpus qualification records.
- Expanded common canonical roles for GPS/spatial, lateral/vertical acceleration, battery voltage, brake pressure, steering angle, and yaw rate.
- Restored MaxxECU packaged-log recognition (`.MaxxECU-Zip-log`) and now uses package `LogRate` metadata as the physical logger clock instead of incorrectly mapping event timers such as `Time after launch`.

## Compare workflow

- Added headless Named Compare Set models with persistent membership, reference selection, global/per-display view alignment, and per-display Run selection.
- Added desktop actions to save/apply/delete named Compare Sets and step the Reference Run while holding Main fixed.
- Named Compare Sets persist in `.nhratech` workbook format v8. Older workbooks remain readable.
- Compare state remains display-only and never changes source timestamps or Tech Services Run→Asset authority.

## Provenance

- Product version advanced to `0.36.0-development`.
- Read-only upstream references pinned for this milestone: RacingSystemsAnalysis `1556ac70684908038fe47a9fe54e2f506cc4e71c`; nhratechservices `77eb280fe94825f93f2cdfdd3ab2568851aa6a19`.
