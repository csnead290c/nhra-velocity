# NHRA Tech Data — Functionality & Import Gap Audit v0.35

## Decision

v0.35 should **not** be frozen yet. The core telemetry/analysis/RSA foundation is strong, but two things should become explicit release gates before the product is treated as a daily engineering workstation:

1. a scalable import/qualification architecture with broad motorsport logger coverage; and
2. completion of the highest-value daily-workflow gaps that still force an engineer back into ATLAS/i2/Toolbox/DataLink for routine work.

The goal is not to claim every proprietary binary format. The goal is that every common motorsport file is either **opened natively**, **opened through a documented vendor SDK/standard adapter**, or **recognized with a precise next-step message**. Unknown binary files must never be guessed as CSV.

---

## 1. Current strengths

The workstation already has a substantial professional-analysis base:

- native RacePak/DataLink, MoTeC LD and MaxxECU import;
- direct Racelogic VBOX VBO and TunerStudio/MegaSquirt text-log import added in the v0.35 hardening pass;
- generic delimited import with explicit unit provenance and canonical mappings;
- mixed-rate channel support for native logs;
- waveform, cursor/reference cursor, statistics, linked displays and ATLAS-familiar shortcuts;
- comparison, scatter, histograms, FFT/PSD/spectrogram, filters, maps, event/alarm rules and reports;
- official drag timing/weather authority and automatic drag markers;
- RSA/Quarter Pro source-faithful simulation, smooth simulation, inverse fitting, joint reconstruction, identifiability and run-influence analysis;
- synchronized AnalysisCase evidence infrastructure;
- fail-closed binary import and immutable raw source channels.

The primary risk is no longer “can the app analyze data?” It is **coverage, workflow polish, scale, and authoritative production integration**.

---

## 2. Import coverage model

### Status definitions

- **Native qualified** — decoded inside NHRA Tech Data and exercised through the normal waveform pipeline with a real/authoritative fixture.
- **Standard direct** — open documented interchange/text standard directly, preserving raw data and metadata where practical.
- **SDK-backed target** — proprietary format where the vendor exposes an official supported API/DLL. Prefer the official bridge over reverse engineering.
- **Recognized / decoder pending** — identify the family and fail closed with a useful message.
- **Unknown binary** — reject; do not guess.

### Current v0.35

| Family | Extension(s) | Status |
| --- | --- | --- |
| RacePak/DataLink | `.rpk`, identifiable `.rpk.bin` | Native qualified |
| MoTeC i2/M1 | `.ld` (+ `.ldx`) | Native qualified |
| MaxxECU | `.MaxxECU-log`, `.maxxlog` | Native qualified/direct text |
| Racelogic VBOX | `.vbo` | Standard direct |
| MegaSquirt/TunerStudio | `.msl`, text `.mlg` | Standard direct |
| Generic exports | `.csv`, `.tsv`, `.txt`, `.log` | Standard direct |
| ZIP package | `.zip` | Direct container |
| FuelTech | `.ftlog`, `.ftml` | Recognized / decoder pending; CSV and MoTeC LD export available |
| ASAM MDF | `.mf4`, `.mdf` | Recognized / high-priority standard decoder |
| AiM RaceStudio | `.xrk`, `.xrz`, `.drk` | Recognized / official SDK target |
| Holley EFI | `.dl`, `.dlz` | Recognized / decoder pending |
| HP Tuners | `.hpl` | Recognized / decoder pending |
| Racelogic VBOX | `.vbb` | Recognized / decoder pending |
| AEM | `.daq`, `.itlog` | Recognized / decoder pending |
| ECUMaster | `.emublog3` | Recognized / decoder pending |
| MegaSquirt raw logger | `.frd` | Recognized / definition-aware decoder pending |
| Raw CAN/network | `.asc`, `.blf`, `.pcap`, `.pcapng` | Recognized / DBC/A2L-aware decoder pending |

### Next families to add to recognized coverage

- Emtron EmVision: `.elf`, `.elo`;
- Cosworth/Pi logged data: `.pds`;
- iRacing telemetry: `.ibt`;
- Syvecs SView: `.sd` (CSV is already a supported exchange path);
- Haltech native NSP/ESP log family once the exact current extensions/contract are verified from authoritative documentation or sample files;
- Link PCLink native log family once exact extension/contract is verified;
- Bosch WinDarab native files through a documented API/adapter if licensing/deployment permits; MDF4 is already the preferred open interchange route.

---

## 3. Import work priority

### P0 — build next

1. **ASAM MDF3/MDF4 (`.mdf`/`.mf4`)**
   - extremely high leverage across automotive data systems;
   - preserve channel-native clocks, conversion formulas, groups, events and attachments;
   - package a proven MDF library only after licensing/deployment review and real-file qualification.

2. **AiM XRK/XRZ/DRK via the official Windows DLL**
   - isolate the DLL behind a small adapter so the rest of the application sees normal `TelemetryRun`/`ChannelSeries` objects;
   - do not redistribute vendor binaries unless allowed.

3. **FuelTech FTLOG/FTML**
   - keep current `.ld`/CSV export path as fallback;
   - obtain representative native files from several firmware/software generations before declaring direct support.

4. **Holley DL/DLZ**
   - DLZ container handling plus DL decoder;
   - qualify Sniper/Terminator/Dominator variants separately if their structures differ.

5. **Raw CAN (`.asc`, `.blf`) + DBC**
   - raw frame timeline and bus metadata first;
   - optional DBC decode into engineering channels;
   - preserve undecoded frames as evidence.

6. **HP Tuners HPL / VCM Scanner**
   - current VCM Scanner has changed the log format over time, so decoder capability must be versioned and corpus-tested.

### P1

- VBOX binary `.vbb`;
- AEM AQ-1 `.daq` and Infinity `.itlog`;
- ECUMaster `.emublog3`;
- Emtron `.elf`/`.elo`;
- Cosworth/Pi `.pds` and iRacing `.ibt`;
- Syvecs `.sd`;
- Haltech / Link once authoritative native format details or vendor APIs are available.

### P2 engineering interchange

- Excel `.xlsx`/`.xlsm` direct table import;
- MATLAB `.mat`;
- HDF5 `.h5`/`.hdf5`;
- Parquet/Arrow for high-performance analysis exchange;
- TDMS where test-cell / lab data makes it useful;
- GPX/GeoJSON/KML as track/GPS evidence rather than primary engine telemetry.

---

## 4. Decoder qualification gate

Every format advertised as Native Qualified should have at least:

1. one real file from each materially different format generation;
2. source/vendor/version identification where available;
3. channel names, units, sample counts and clocks checked against the vendor software;
4. at least one mixed-rate or nontrivial case where the format supports it;
5. all raw channels retained;
6. a deterministic source hash;
7. explicit warnings for skipped/unsupported channels;
8. waveform-pipeline validation;
9. parser corruption/truncation tests;
10. a frozen corpus fixture or cryptographic/metadata manifest when the real file cannot be redistributed.

A parser that merely “doesn't crash” is not a qualified telemetry decoder.

---

## 5. Daily engineering functionality still missing or incomplete

### P0 before a credible 1.0

#### A. Compare/session workflow
- true Compare Set/session manager with many Runs, reference Run and per-display selection;
- quick next/previous Run and compare-run stepping;
- saved alignment per display without changing evidence time;
- Run metadata/setup differences visible beside comparison plots.

#### B. Vehicle/setup/channel templates
- vehicle/class templates;
- channel groups/favorites and aliases reusable across logger families;
- structured setup sheets so gearing, weight, tire, aero, clutch, tune/setup notes and changes are correlated to Runs;
- canonical-role confidence and user confirmation for ambiguous mappings.

#### C. Report/publishing workflow
- engineer-quality report layout with reference deltas and conditional formatting;
- PDF + HTML publishing in addition to current data exports;
- evidence provenance block: file hashes, decoder version, model version, timing/weather authority, user/time, warnings and uncertainty.

#### D. Large/high-rate data
- lazy/chunked decode instead of requiring the full file in RAM;
- background import/calculation jobs with progress, cancel and retry;
- deterministic caches for expensive calculated channels/models;
- downsample only for display, never source analysis.

#### E. Production Tech Services integration
- real safe desktop login using the actual server contract;
- authoritative Event → Entry → Run → Asset relationship;
- protected Asset download/cache and offline entitlement;
- durable shared AnalysisCases, model snapshots, studies and approved reports;
- audit history and controlled write-back.

#### F. Target-hardware validation
- automated Windows install/build/launch smoke test;
- Qt interaction test coverage for open/drag/zoom/cursor/workbook save/restore;
- high-DPI/multi-monitor and trackside offline testing.

### P1 — high-value motorsport capability

#### G. GPS/spatial analysis
- strip/lane map, GPS trace and channel-vs-position displays;
- GPS quality/accuracy status;
- automatic coordinate/time alignment between VBOX/video/logger evidence.

#### H. Video/evidence
- multi-camera tiled review;
- hardware-accelerated seek where possible;
- telemetry overlay export to video;
- frame-accurate synchronization metadata.

#### I. IDR/incident reconstruction
- native NHRA IDR decode;
- coordinate transforms, impact pulse, ΔV and event windows;
- explicit uncertainty and sensor-saturation handling;
- incident evidence package/report.

#### J. Live/replay
- live transports feed the same channel/session model as files;
- reconnect/recovery + ring buffer;
- live-to-historical transition;
- same math/gates/events/alarms/models in live and replay.

#### K. Automation/SDK
- stable headless batch API;
- plugin/provider interface for decoders, math, model channels and reports;
- user-installed decoder plugins can be sandboxed/versioned rather than patched into core import code.

---

## 6. Canonical channel model gaps

v0.35 now adds common canonical roles for lateral/vertical acceleration, GPS latitude/longitude, heading, altitude, yaw rate, battery voltage, brake pressure and steering angle. The next canonical layer should cover common drag/motorsport channels without hiding raw logger naming:

- ignition timing / timing retard;
- manifold absolute pressure versus boost distinction;
- fuel/oil pressure;
- coolant/oil/intake/fuel temperature;
- fuel flow / injector duty / fuel pump or rail pressure;
- per-cylinder EGT, lambda and cylinder-pressure channels;
- clutch position/pressure, converter slip and input/output RPM;
- individual wheel speeds;
- suspension travel/velocity and ride-height channels;
- shock potentiometers/loads/wheelie-bar load where present;
- launch/shift/limiter/traction-state channels;
- ECU/calibration version and logger configuration metadata.

These should be **roles and aliases**, not destructive renames. Source channel names remain visible and immutable.

---

## 7. Recommendation for v0.35 → v0.36

Do not spend the next cycle adding another dozen analysis windows. The best return is:

1. finish the scalable import registry and qualification harness;
2. land MDF4 and AiM SDK-backed import first;
3. obtain/qualify FuelTech + Holley + HP Tuners + VBOX VBB samples;
4. build the real Compare Set/session manager;
5. add reusable vehicle/channel/setup templates;
6. begin lazy/background data loading;
7. validate the actual Windows packaged application;
8. then freeze the next release.

That sequence attacks the remaining reasons an engineer would still need to leave NHRA Tech Data during normal analysis.
