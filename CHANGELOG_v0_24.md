# Changelog — v0.24

## Rule-generated events / alarms

- Added portable `EventRuleDefinition` to `DefinitionLibrary` (library format v2; v1 files remain readable).
- Event conditions use the same safe canonical-role expression resolver as portable gates.
- Added interval, rising-edge and falling-edge trigger modes, severity, event type and minimum-duration filtering.
- Added headless historical event extraction and cursor-time alarm-state evaluation.
- Multiple rules prepare/apply the portable library once per Run rather than recomputing calculated channels for every rule.

## Desktop

- Existing Events display now includes saved rule-generated events.
- Added **Alarm Status** display driven by the shared Run-time cursor.
- Added **Event / Alarm Rule…** to the Analysis Definition Library workflow.

## CLI / automation

- Added `library events --library ... --file ...` with CSV/JSON export support.

## Persistence / authority

- Catalog schema remains **v7**.
- Workbook format remains **v6**; its embedded DefinitionLibrary can now include event rules.
- Raw telemetry and Tech Services Run/Asset authority remain unchanged.
