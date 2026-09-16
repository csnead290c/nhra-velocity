# NHRA Velocity v0.38 Development Validation

Validated build: **0.38.0-dev.11**

## Scope

This validation covers the dev.11 ATLAS-style waveform interaction and workbook-shell usability pass on top of the staged/background Tech Services sync, protected account flow, manual launch re-zero, persistent Run-linked local data logs, Run-first workspace, and native logger support.

## Results

- Full automated suite completed **234/234 tests**.
- `python -m py_compile desktop.py` passed.
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
