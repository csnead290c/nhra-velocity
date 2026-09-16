# NHRA Velocity v0.38 Development Validation

Validated build: **0.38.0-dev.14**

## Scope

This validation covers the dev.14 packaged-Windows reliability gate and product audit on top of the dev.13.1 startup hardening, dev.13 analysis/statistics consistency work, durable Run-data reopen, ATLAS-style waveform interaction, staged/background Tech Services sync, protected account flow, manual launch re-zero, Run-first workspace, and native logger support.

## Results

## dev.13 analysis/workflow hardening

- Non-Qt automated suite: **241/241 passed** in two batches; the additional offscreen Qt smoke module is skipped in this Linux validation environment when PySide6 is unavailable.
- Focused dev.13 contract/smoke coverage passed where runtime dependencies were available, covering statistics toggles, channel removal, reference-to-live-cursor analysis semantics and repeated launch re-zero.
- `python -m compileall -q desktop.py runlab` passed.
- Manual re-zero now clears display-only alignment and persists the effective snapped logger sample, preventing the apparent first-use offset seen in dev.12.
- Legacy A/B analysis consumers used by Region Statistics and reference-limited Spectrum now follow the visible Reference→Cursor region.


- Full automated suite completed **238/238 tests** (99 + 139 in two groups to stay below the execution wall-clock limit).
- `python -m py_compile desktop.py` passed.
- New dev.12 regression coverage verifies:
  - compact per-band current/reference/delta values are scheduled for refresh on every cursor/reference move even when the detailed table is hidden;
  - a managed Run attachment can be reopened from a fresh catalog instance and actually decoded through its original filename/extension, not merely found as a database row;
  - compact Run scope prioritizes the current event or most recently completed event ahead of future database rows;
  - selecting a Run with local attached data schedules an automatic reopen after a short debounce.
- New source-level regression coverage verifies:
  - left-drag-anywhere waveform cursor ownership through `VelocityWaveformViewBox`;
  - Widget-with-children shortcut binding for `R`, `+`, and `-`;
  - reference cursor capture/visibility/range-window behavior;
  - compact per-band waveform headers replacing the always-visible detailed value table;
  - document-style worksheet tabs, worksheet `+` control and `Ctrl+Enter` focus mode;
  - compact Run-browser action layout that no longer forces an oversized left dock.
- Existing launch-zero, Run/data-log persistence, Tech Services metadata, import, analysis, reconstruction, fit-study, display-cache and workbook regressions all remained green.

## Waveform interaction regression

The dev.11 Waveform interaction intentionally follows the verified ATLAS model where practical:

- hover does not change engineering state;
- click positions the live cursor;
- left-drag anywhere in a waveform scrubs the live cursor;
- middle-drag retains X-axis pan;
- mouse-wheel and keyboard zoom operate on X only;
- `R` adds/removes a red reference cursor at the current cursor position;
- a shaded window identifies the live↔reference analysis range;
- `+` / `-` zoom around the live cursor when it is visible;
- `Ctrl+Z` returns to the previous view;
- `Ctrl+Alt+Z` fits the drag run.

## Workbook / desktop usability regression

- Primary waveform remains the worksheet center.
- Live channel values move into compact plot-band headers so graph area is not consumed by an always-visible table.
- Detailed channel values/statistics remain opt-in under **More → Detailed channel table**.
- Worksheet tabs use document-style presentation and expose a compact `+` control.
- `Ctrl+Enter` toggles **Focus Analysis**, temporarily hiding application side docks for full-width waveform review.
- Run-browser primary/secondary actions are split into compact rows and the normal simple-workspace dock targets are narrower.

## Authority / persistence invariants

No source evidence, official NHRA timing, canonical weather, or Tech Services Run identity is rewritten by these UI changes. Manual launch zero remains an analysis coordinate override. Local data-log attachments remain explicit managed Velocity associations to an authoritative Run and are not uploaded or inferred from filenames.

## dev.12 persistence root cause

The earlier persistence regression only proved that the Run→Asset row and managed SHA-256 object survived a catalog reopen. It did not prove that the managed bytes could be decoded again. The object store uses extensionless hash filenames by design; native decoder routing is deliberately extension-aware/fail-closed. dev.12 adds filename-preserving aliases for read/decode while keeping the underlying content-addressed object authoritative and hash-verifiable.

## dev.14 reliability-gate validation

- Source regression includes release-pipeline contract checks for the packaged desktop smoke path, installer version plumbing, and workflow gates.
- Windows development and tagged-release workflows now validate both the frozen and installed desktop with `--smoke-test`; these are intended to catch startup/Qt/PyInstaller regressions that source-only tests cannot detect.
- The packaged smoke scenario exercises MainWindow construction, pyqtgraph rendering, live/reference cursor statistics, and representative Analysis displays without network access.
- A broader Qt-only test constructs the normal daily Analysis display set with realistic main/reference sessions; it runs on Windows build agents where PySide6 is installed.
