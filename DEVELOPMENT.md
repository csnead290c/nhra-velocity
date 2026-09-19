# NHRA Velocity development workflow

NHRA Velocity is maintained as a long-lived engineering application, not as a sequence of disposable ZIP builds. Git history, release tags, automated validation, reproducible Windows builds and provenance are part of the product.

## Branch model

- `main` — production/releasable code only. Every production version is tagged `vMAJOR.MINOR.PATCH`.
- `develop` — integration branch for the next version. It may contain qualified work that is not yet released.
- `feature/<topic>` — short-lived focused development from `develop`; merge back through review once tests pass.
- `hotfix/<topic>` — urgent production correction from `main`; merge to `main`, tag a patch release, then merge the same fix back into `develop`.
- `release/<version>` — optional stabilization branch when a release needs extended Windows/track validation while feature work continues on `develop`.

Do not maintain long-lived parallel product forks. Experimental work belongs in branches and should either merge or be retired.

## Commit policy

Prefer small, explainable commits with conventional prefixes (`feat:`, `fix:`, `perf:`, `test:`, `docs:`, `build:`, `refactor:`). Never commit team/customer race data, credentials, signing keys, database dumps or downloaded Box files. The `.gitignore` intentionally blocks common motorsports logger formats outside the synthetic `examples/` corpus.

## Local development environment

Windows development uses a repo-local `.venv`: `setup_windows.bat` creates it and installs `requirements-desktop.txt`, `run_windows.bat` launches the desktop through it, and `test_windows.bat` runs the suite from it. Setup is idempotent — rerun it any time dependencies change.

Source runs enforce NHRA Tech Services sign-in by default. `NHRA_TECH_DEV_UNAUTHENTICATED=1` is a **local development/test-only** opt-out; it must not be set for distributed builds or shared machines. Test and tooling runs should also set `NHRA_VELOCITY_HOME` to an isolated directory so they never touch real user state.

## Validation before merge

Run:

```text
PYTHONPATH=. pytest -q
python -m compileall -q .
PYTHONPATH=. python -m runlab.cli selftest
PYTHONPATH=. python -m runlab.cli release audit --root .
```

Native-format support must additionally be qualified against real read-only corpus files outside the repository. Store only hashes, structural findings and non-sensitive validation summaries in Git.

## Versioning

`runlab/version.py` is the single source of truth. Development builds use semantic prerelease versions such as `0.39.0-dev.1`; stable releases use `0.39.0` and tag `v0.39.0`.

Portable/persistent data formats are versioned independently in `runlab/product_manifest.py`. A product release does not automatically imply a catalog/workbook/model package migration.
