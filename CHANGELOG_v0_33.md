# NHRA Tech Data v0.33 — Native Logger Reliability + Focused Waveform Workspace

## MoTeC `.ld`

- Fixed M1 header parsing so the advisory channel count is read using the 16-bit field used by the real 2026 files tested during this release.
- Made the channel metadata linked list authoritative instead of rejecting a file because its advisory header count does not match the linked records.
- Added fail-soft handling for isolated, structurally valid diagnostic/state channels whose sample encoding is not yet decoded. Those channels are identified in run warnings while the rest of the run remains usable.
- Guaranteed release of the parser `memoryview` before the memory-mapped file is closed, eliminating the secondary `cannot close exported pointers exist` error that could hide the real decode failure.
- Qualified the parser against the exact 6.2 MB PSM `.ld` file that reproduced the reported v0.32 failure. It yields 180 decodable native channels and one explicitly skipped unsupported synchronization diagnostic channel.

## RacePak / DataLink `.rpk`

- Added the current `CAN_Device` serialization alongside the previously supported `ScaledBuffer` family.
- Added extended DataLink length-prefixed string decoding used by current files.
- Decode current buffer capacity, used-sample counts and native sample timing instead of assuming every allocated buffer is populated.
- Added current DataLink hardware and sensor linear calibration parsing, including `_HW_A/_HW_B`, `_X_MIN/_X_MAX`, `_Y_MIN/_Y_MAX` and explicit `_UNIT` metadata.
- Added structural pairing/validation between current channel definitions and serialized buffers, with conservative fail-closed fallback matching rather than silently relabeling unmatched buffers.
- Qualified current-family import against four real NHRA `.rpk` files spanning 2019 and 2026. Three 2026 files contain 43, 57 and 62 recorded channels respectively.
- Historical device-specific engineering transforms remain a qualification item; a file opening structurally is not treated as proof that every old sensor/logger combination has fully characterized scaling.

## Canonical channel mapping

- Channel auto-mapping now uses native engineering units when available instead of relying on text alone.
- Measured channels are strongly preferred over state/status/limit/target/diagnostic channels.
- Engine, driveshaft and clutch RPM roles are separated more aggressively.
- Fixes cases such as `Engine.Speed.Limit.State` outranking the actual `Engine.Speed` measurement.

## Waveform / desktop usability

- The primary waveform now owns the worksheet center instead of living in another dock over an empty central surface.
- The default application workspace is **Simple**: central waveform plus Channel Explorer. Investigation and Full Engineering layouts remain one shortcut away (`Ctrl+2` and `Ctrl+3`; `Ctrl+1` returns to Simple).
- The permanent top toolbar is reduced to the frequent workflow: Open, Save, New Worksheet, Command Palette, Quick Graph, X-axis and Compare.
- Specialist analysis displays remain available from menus and `Ctrl+K` instead of occupying permanent toolbar space.
- The waveform itself is now a cursor surface: mouse hover moves the visible live cursor and updates the parameter/value readout; left-click places it.
- A/B cursors, event navigation, bookmarks, regions, full-run navigator, snap controls and display properties were moved under **More** and are hidden by default.
- Dock children and docks have zero minimum-size constraints, all dock areas enabled and movable/floatable/closable features normalized so workspace splitters can actually resize them.

## Regression additions

- Added a synthetic modern `CAN_Device` RacePak fixture covering extended strings, used counts, empty buffers, native timing and two-stage linear calibration.
- Added mapping regression coverage proving measured RPM roles beat state/limit lookalikes.
- Real native-log qualification results are recorded by hash in `validation/REAL_NATIVE_LOG_VALIDATION_v0_33.json`; the proprietary source logs are not distributed.
