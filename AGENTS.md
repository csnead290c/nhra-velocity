# NHRA Velocity — Permanent Development Rules

These rules apply to all contributors and agents working in this repository.

## Project purpose

- NHRA Velocity is an engineering workstation for NHRA Technical Services.
- Correctness, traceability, reliability, and engineering usefulness matter more than flashy UI or architectural elegance.

## Data model / identity

- Runs are the primary object.
- Telemetry/data files are explicitly associated with a selected Run.
- Never infer authoritative Run identity from filenames, folders, team naming conventions, timestamps alone, or other heuristics.
- Do not implement automatic filename/path based file-to-Run matching.
- The Tech Services/server Run-to-Asset relationship is authoritative when available.
- Local working attachments must remain explicitly identified as non-authoritative.
- Do not create phantom catalog Runs to paper over missing references.

## Importers

- Importers must remain fail-closed when a format is unknown or ambiguous.
- Preserve source data and provenance.
- Decoder correctness is more important than making unsupported files appear to work.
- Performance changes must preserve decoded results.

## Engineering / RSA

- Preserve existing Quarter Pro/RSA reference behavior and engineering equations unless a change is specifically validated.
- Do not silently substitute generic automotive assumptions for documented project behavior.

## Performance

- Measure performance problems before optimizing them.
- Prefer targeted fixes over broad rewrites.
- Do not refactor desktop.py merely because it is large.
- UI operations that may be expensive should eventually avoid blocking the GUI thread, but do not introduce concurrency casually.

## Security / auth

- Normal application authentication remains enabled by default.
- `NHRA_TECH_DEV_UNAUTHENTICATED=1` is for local development/testing only.
- Do not weaken production authentication behavior to simplify development.

## User data / state

- Tests and development utilities must not write to or alter the user's real NHRA Velocity application state.
- Honor `NHRA_VELOCITY_HOME` or equivalent isolation mechanisms.
- Never delete or overwrite real user recovery/session files during automated testing.
- Backward compatibility and recoverability matter when changing state locations.

## Git

- `main` = stable/release.
- `develop` = integration branch.
- Implementation occurs on feature branches from `develop`.
- Never commit directly to `main`.
- Do not merge the feature branch yourself.
- Keep commits focused and reversible.

## Testing

- Existing tests must remain green.
- Add regression tests for every confirmed bug fixed.
- Run the complete test suite before declaring work complete.
- Run the desktop smoke scenario after changes affecting desktop/runtime behavior.
- Report measured before/after performance for performance fixes.
