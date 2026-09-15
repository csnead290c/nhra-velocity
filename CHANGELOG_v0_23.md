# Changelog — v0.23

## Portable analysis definition library

- Added versioned `DefinitionLibrary` with constants, calculated channels, gates, segments, metrics, conditional rules and saved reports.
- Portable expressions can resolve canonical channel roles across logger/vendor naming differences.
- Added explicit dependency graph, missing-input validation and calculated-channel cycle detection.
- Added standalone `.nhralib` JSON import/export and workbook-embedded analysis library (workbook version 6).
- Added active-Run capture for existing calculated-channel/gate definitions.

## Reports and trends

- Saved reports evaluate multiple metrics/segments across Main/Reference/Overlay Runs.
- Official segment templates resolve against each Run's own timing data.
- Added conditional rules/status/severity.
- Added CSV, JSON and XLSX report export.
- Added Saved KPI Trend display driven by the same report definitions.

## Desktop

- Added Analysis Definition Library menu/actions for import/export, constants, saved metrics, saved segments, conditional rules and saved reports.
- Added Saved Analysis Report and Saved KPI Trend worksheet displays.

## Headless / automation

- Added `library starter`, `library inspect`, `library validate`, `library apply` and `library report` commands.
- Headless library/report execution uses the same calculation engine as the desktop.

## Persistence and authority

- Catalog schema remains **v7**.
- Definitions/reports are derived engineering state; raw telemetry and Tech Services Run/Asset ownership remain unchanged.
