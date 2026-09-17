# Box data-format audit — 2026-09-17

This is a **read-only** inventory of the NHRA Box `Race Data` tree used to drive VELOCITY import qualification. It records what is actually on file so import work is based on the corpus we have, not a hypothetical vendor list.

## Scope and caveat

- Box `Race Data` folder: metadata/search audit only; nothing was modified.
- Counts below are extension searches scoped to the `Race Data` tree unless stated otherwise.
- Generic CSV/Excel counts include non-logger documents stored under `Race Data`; they are inventory counts, not claims that every spreadsheet is a data log.
- Additional recognized native families searched with no scoped sample found include HP Tuners `.hpl`, VBOX `.vbb`, ECUMaster `.emublog3`, Emtron `.elf/.elo`, Cosworth/Pi `.pds`, iRacing `.ibt`, MegaSquirt raw `.frd`, and CAN captures `.asc/.blf/.pcap/.pcapng`.
- The Box connector currently exposes metadata/text search but its advertised raw-binary download action returns `Tool get_download_url not found`. Therefore proprietary Box binaries could not be batch-decoded inside this development session. VELOCITY now has a local corpus qualifier/inventory command so a Box-synced/local copy can complete the byte-level audit read-only.

## Corpus snapshot

| Family / extension | Box count | VELOCITY state after this audit | Notes |
| --- | ---: | --- | --- |
| RacePak `.rpk` | 1,288 | Direct | Current Pro Stock and other race data include large modern RPK files. |
| RacePak `.ddf` | 6,013 | Direct | Raw logger path is qualified; optional RCG/RPK config enrichment remains explicit. |
| RacePak `.rcg` | 416 | Support asset | Logger/channel configuration, not a run recording. |
| MoTeC `.ld` | 102 | Direct | Current PSM M1 corpus present. |
| MoTeC `.ldx` | 52 | Support asset | Companion metadata/index file; open the matching `.ld`. |
| MaxxECU `.MaxxECU-log` / `.maxxlog` / `.MaxxECU-Zip-log` | 52 | Direct | 2026 PSM test files include `.MaxxECU-Zip-log`. This extension exposed the file-picker drift bug. |
| Holley `.dl` | 100 | Direct | Qualified native Holley path. |
| Holley `.dlz` | 215 | Direct | Qualified native Holley path in current build. |
| Holley `.hefi` | 74 | Support asset | ECU configuration, not logged data. |
| MSD / generic `.daq` | 802 | **Decoder gap** | Corpus filenames are `7730_*` and live in PowerGrid contexts; do not label these AEM-only. Native Power Grid DAQ decoding is not yet qualified. |
| MSD Power Grid `.mff` | 22 | Support asset | Controller configuration/tune file, not logged data. |
| BigStuff `.bigTune` / `.big` | 4 | Support asset | Calibration/support files, not assumed to be run recordings. |
| MSD Power Grid `.dqi` | 0 in Race Data; 1 elsewhere in Box | **Decoder gap** | ReView data-log family recognized; native decoder not yet qualified. |
| FuelTech `.ftml` | 21 | **Decoder gap** | Native FuelTech data logs. CSV / MoTeC interchange remains usable. |
| FuelTech `.ftm` | 2 | Support asset | FTManager map/calibration, not a data log. |
| FuelTech `.ftlog` | 0 | Recognized/pending | No current scoped sample found. |
| VBOX `.vbo` | 43 | Direct | Text VBOX importer exists. |
| TunerStudio `.msl` / `.mlg` | 0 | Direct when applicable | No scoped sample found. |
| AEM `.itlog` | 0 | Recognized/pending | `.daq` is no longer assigned to AEM alone. |
| ASAM `.mf4` / `.mdf` | 0 | Recognized/pending | No scoped sample found. |
| AiM `.xrk` / `.xrz` / `.drk` | 0 | Recognized/pending | No scoped sample found. |
| CSV | 1,665 | Direct interchange | Count includes race reports and other non-logger CSVs. |
| Excel `.xlsx` / `.xlsm` | 848 | Direct interchange | Count includes administrative workbooks; content qualification decides whether a workbook is plotable data. |

## Findings that changed the code

1. **The file-picker bug was real.** The desktop had a hard-coded extension list that no longer matched the decoder registry. `*.MaxxECU-Zip-log` was a concrete Box example: the decoder could open it, but the default dialog hid it. Both Open and Attach dialogs now build their filters from the import registry, so decoder and picker support cannot silently drift apart.
2. **Power Grid `.daq` is the largest current decoder gap.** The scoped corpus has 802 files with `7730_*` naming. VELOCITY previously labeled `.daq` simply as AEM; the registry now treats `.daq` as an ambiguous DAQ binary and explicitly calls out the current MSD Power Grid corpus.
3. **FuelTech `.ftml` is a real historical/native-log gap.** Twenty-one native logs are on file. They remain fail-closed rather than being guessed as text.
4. **Support/configuration files are now separated from data logs.** `.hefi`, `.ftm`, `.mff`, `.rcg`, `.ldx`, and existing BigStuff calibration files are classified as support assets. They no longer pollute recursive data-log qualification, but selecting one produces a specific diagnostic instead of a vague parser failure.
5. **MoTeC exports include non-data companions.** Current 2026 PSM folders contain `.ld`, `.ldx`, and same-stem `.txt` ECU diagnostic output. The `.ld` is the primary recording; `.ldx` is support metadata; arbitrary `.txt` still goes through the generic tabular validation path and must become plotable before import is considered successful.

## Local byte-level qualification

The corpus qualifier now checks more than “parser did not throw.” For each recognized data-log candidate it records decoder/vendor, plotability, channel counts, duration/native rate, warnings, and generic integrity flags for duplicate columns, non-increasing time, mostly-nonfinite channels, and constant numeric channels.

Quick representative pass:

```bash
python -m runlab.cli qualify <folder> --recursive --sample-per-format 5 \
  --json-out qualification.json --csv-out qualification.csv \
  --inventory-json inventory.json --inventory-csv inventory.csv
```

Full pass: omit `--sample-per-format`. The extension inventory deliberately includes **unrecognized** file families so a missing registry entry cannot disappear from the audit just because VELOCITY does not know its suffix yet.

## Next decoder priorities from the actual Box corpus

1. MSD Power Grid `.daq` (802 scoped files).
2. FuelTech `.ftml` (21 scoped files).
3. MSD Power Grid `.dqi` (small current count, but same ecosystem and potentially useful as the PC/ReView form of Grid data).

Direct families should still be regression-tested against representative real files across years/versions, especially large current RacePak RPK, DDF+RCG, current MoTeC M1, MaxxECU ZIP logs, and Holley DL/DLZ.
