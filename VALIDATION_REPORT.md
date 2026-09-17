# NHRA Velocity — Current Development Validation

Validated build: **0.38.0-dev.18**

This is the release-facing validation summary. Detailed v0.38 history and regression notes are maintained in `VALIDATION_REPORT_v0_38.md`.

## Automated validation

- Full source suite: **269 passed, 1 Qt-only test skipped** in the Linux packaging environment before final version/documentation-only edits.
- Python compilation: **PASS**.
- Native import/plot self-test: **3/3 PASS** for bundled RacePak, MoTeC and MaxxECU pipelines.
- Strict release-consistency audit with pinned RSA and Tech Services reference SHAs: **0 errors / 0 warnings**.

## Windows reliability gate

The development and tagged-release workflows run the same core checks on Windows, then:

1. build the PyInstaller executable;
2. launch the frozen executable with the network-free desktop smoke scenario;
3. build the Inno Setup installer;
4. silently install the package;
5. launch the installed executable with the same real Qt/pyqtgraph smoke path.

The smoke scenario constructs the real MainWindow, waveform, cursor/reference statistics, portable math and representative Analysis displays. A packaged startup/runtime regression therefore blocks the artifact rather than being discovered only by an engineer after installation.

## dev.18 focus

- bundled NHRA Velocity application/installer/shortcut branding assets;
- desktop shortcut enabled by default for normal installer use and repaired by the development updater;
- Data Log Setup / Readiness view for trackside configuration state;
- RacePak Driver+Category / Vehicle+Category profile management;
- exact historical DDF config bindings remain immutable higher-authority evidence;
- Common Channel semantics remain explicitly separate from RacePak source-channel names.

## Authority invariants

- Tech Services owns permanent Run identity and official timing/weather authority.
- Local data-log attachment is explicit; filenames never infer Run ownership.
- RacePak config definitions identify source channels but do not choose engineering Common Channels.
- Exact data-log choices override reusable context profiles.
- Manual launch zero is an analysis coordinate decision and never rewrites raw logger samples or official timing.
