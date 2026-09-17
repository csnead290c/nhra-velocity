# Telemetry import support

## Qualified/direct paths in v0.38

| Source | Input | Status | Notes |
| --- | --- | --- | --- |
| RacePak / DataLink | `.rpk` | Direct | Supports the legacy `ScaledBuffer` serialization and the current `CAN_Device` family. Exercised against real NHRA files from 2019 and 2026; current files validated native timers, used-sample counts, explicit units and hardware/sensor linear calibration. |
| RacePak raw logger | `.ddf` | Direct | Decodes the SD-card/logger recording directly, without DataLink conversion. A matching `.rcg` or prior `.rpk` supplies names/units. Velocity can save that definition as an explicit Driver+Category or Vehicle+Category profile, then pins the exact config fingerprint to each attached DDF for reproducible reopen. Without a config, stable channel IDs are preserved and semantics are not guessed. |
| RacePak / downloaded wrapper | `.rpk.bin` and similarly identifiable names | Direct | Content/filename probe routes to the RacePak decoder instead of text parsing. |
| MoTeC i2 / M1 | `.ld` | Direct | Walks the channel metadata linked list as the authority, preserves native channel timebases and can skip isolated unsupported diagnostic/state encodings without discarding the run. Exercised against a real 2026 PSM M1 log with 180 decodable native channels. |
| MaxxECU | `.MaxxECU-log`, `.maxxlog` | Direct | Vendor-native format is delimited text. |
| MaxxECU | supported zip log packages | Direct | Primary log is extracted to a temporary directory. |
| Racelogic VBOX | `.vbo` | Direct | Parses the documented sectioned, space-delimited VBOX format. Raw clock/GPS columns are preserved; an elapsed logger clock and conventional decimal-degree GPS channels are added. |
| EFI Analytics / TunerStudio | `.msl`, text `.mlg` | Direct | Opens normal TunerStudio/MegaSquirt delimited logs. Binary `.mlg` remains fail-closed until a binary decoder is qualified. |
| Excel telemetry table | `.xlsx`, `.xlsm` | Direct interchange | Searches the workbook sheets, applies the same header/unit/channel logic as delimited files, and selects the most telemetry-like sheet. |
| Generic / vendor export | `.csv`, `.tsv`, `.txt`, `.log` | Direct | Auto-detects delimiter/header and normalizes known engineering channels. |
| Telemetry archive | `.zip` | Direct container | Finds a primary recognized telemetry member and preserves a matching MoTeC `.ldx` sidecar. |

## Recognized but not silently decoded

These families are intentionally visible to folder import and the file picker so the application can identify them and give a useful decoder/bridge message instead of either ignoring the file or guessing that it is CSV.

| Source | Input | v0.38 behavior / planned path |
| --- | --- | --- |
| FuelTech Vision / PowerFT | `.ftlog`, `.ftml` | Recognized and rejected with a specific message until native decoding is validated. CSV and MoTeC `.ld` exports are supported. |
| ASAM MDF | `.mf4`, `.mdf` | Recognized. High-priority standard decoder target; should preserve mixed-rate channels, conversion metadata and events. |
| AiM RaceStudio | `.xrk`, `.xrz`, `.drk` | Recognized. Preferred Windows path is the official AiM data-access DLL behind an isolated adapter. |
| Holley EFI V6 | `.dl`, `.dlz` | Direct native import. V6 RTC + engine RPM qualified against paired NHRA Pro Stock Holley/RacePak data; unqualified slots remain numeric. V5 sparse/V3 fail closed. |
| HP Tuners VCM Scanner | `.hpl` | Recognized. Native decoder not yet qualified. |
| Racelogic VBOX | `.vbb` | Recognized. Newer binary VBOX decoder not yet qualified; text `.vbo` is direct. |
| AEM | `.daq`, `.itlog` | Recognized. AQ-1 / Infinity native decoders not yet qualified. |
| ECUMaster EMU Black V3 | `.emublog3` | Recognized. Native decoder not yet qualified. |
| Emtron EmVision | `.elf`, `.elo` | Recognized. Native ECU/PC and display-log decoders not yet qualified. |
| Cosworth / Pi | `.pds` | Recognized. Native Pi logged-data decoder/bridge not yet qualified. |
| iRacing | `.ibt` | Recognized. Native IBT decoder not yet qualified. |
| Syvecs SView | `.sd` | Recognized. Native SView decoder not yet qualified; CSV interchange is direct. |
| MegaSquirt raw logger | `.frd` | Recognized. Requires the matching ECU/firmware definition; not guessed without it. |
| CAN/network captures | `.asc`, `.blf`, `.pcap`, `.pcapng` | Recognized. Future bus-log adapter will pair the raw frames with DBC/A2L/other signal definitions. |
| Legacy spreadsheet | `.xls`, `.ods` | Recognized. Save/export as `.xlsx` or CSV until optional legacy/OpenDocument readers are packaged. |
| Unknown binary | any | Rejected before the generic text parser. |

## Import architecture rules

Native breadth must never come at the cost of engineering trust. Every importer follows the same rules:

1. **Recognized is not the same as decoded.** A format is only advertised as Direct after a real or authoritative fixture reaches the normal waveform pipeline.
2. **Binary decoding is fail-closed.** Unknown/proprietary binary data is never sent to pandas as text just to see what happens.
3. **Raw source channels are immutable.** Unit conversion and canonical roles create derived channels; they do not overwrite source samples.
4. **Native clocks are preserved.** Mixed-rate formats should retain one timebase per source channel rather than being expanded to a giant synthetic table.
5. **Units have provenance.** Native metadata wins, then explicit user override, then conservative label inference.
6. **File/decoder provenance is recorded.** The selected decoder and probe reason travel with the Run.
7. **A decoder is not qualified by parsing alone.** It must produce finite waveform data through the same viewer contract used by the desktop.
8. **Sidecars are explicit.** Examples include MoTeC `.ldx` today and future DBC/A2L/configuration definitions; missing sidecars never trigger silent guesses.

## What “opened successfully” means

The importer does not consider parsing alone to be success. A run must also pass the viewer contract:

1. at least one source/native channel contains at least two finite numeric samples;
2. at least one default waveform channel can be selected;
3. that channel can produce finite X/Y points;
4. native-rate channels retain their logger clock;
5. rectangular data uses validated time when available and Sample Index as a viewing fallback when it is not.

Sample Index fallback is only a viewer convenience. Derivative, integration, delivered-power reconstruction and other time-dependent physics tools still require a valid physical timebase.

## Quick verification

From the desktop application choose **File → Open Bundled Native Demos**. The build includes generated RacePak, MoTeC and MaxxECU files. They are synthetic importer/viewer fixtures, not vehicle-performance reference data.

For command-line diagnostics:

```bash
python -m runlab.cli inspect path\to\run.rpk path\to\run.ld
```

The report shows the selected decoder, probe reason, canonical mappings, timebase, default traces, finite plot-point counts and warnings.

## Renderer-readiness check

After decoding, default waveform traces pass through the same final display-preparation layer used by the desktop waveform: non-finite samples are removed, reset/duplicate/non-monotonic clocks are reduced to a safe increasing segment, and very large traces are peak-preserving min/max decimated for display. **Data Integrity** reports whether each default trace survives this final renderer contract. Raw logger data is never modified by these display repairs.

The desktop waveform itself reports the number of curves and points rendered. A `NO CURVES` or `RENDER ERROR` status is therefore distinguishable from a decoder failure.

The bundled pipeline diagnostic is also available without Qt:

```bash
python -m runlab.cli selftest
```
