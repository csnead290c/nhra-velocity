# NHRA Velocity macOS Plan

## Goal

NHRA Velocity should become a first-class macOS engineering workstation without creating a second codebase or weakening the Windows trackside workflow. The Qt/PySide6 application, Run/catalog model, logger decoders, Common Channel layer, math engine, RSA model engine, and Tech Services integration stay shared. Only packaging, OS integration, updater/signing, and a small amount of UX convention should vary by platform.

## Product rules

1. **One analysis engine.** Windows and macOS must read the same workbook/catalog formats and produce the same calculations for the same evidence.
2. **No macOS fork.** Platform behavior belongs behind narrow helpers or build scripts, not copied application logic.
3. **Fail closed on unsupported vendor bridges.** A Windows-only vendor DLL may remain Windows-only; macOS must identify that limitation rather than guessing or silently changing data.
4. **Secure credentials stay native.** Windows uses Credential Manager through `keyring`; macOS uses Keychain through the same credential-store boundary. No plaintext fallback.
5. **Trackside offline behavior must match.** Local Runs, managed data logs, Common Channel mappings, math channels, RacePak config profiles, and saved workbooks must work identically without network access.
6. **Packaged builds are the gate.** Source tests alone are insufficient. Both Windows and macOS packaged apps must launch the real Qt/pyqtgraph smoke scenario in CI.

## Current readiness

Already portable:

- Python 3.13 core analysis and catalog code.
- PySide6 / Qt workstation UI.
- pyqtgraph waveform rendering.
- RacePak RPK/DDF/RCG parsing implemented in Python.
- MoTeC LD and MaxxECU native parsing implemented in Python.
- Common Channel / Math Channel / RSA calculations.
- SQLite catalog and content-addressed local object store.
- App-data path already resolves to `~/Library/Application Support/NHRA Velocity` on macOS.
- OS credential persistence uses `keyring`, which maps to macOS Keychain.
- Folder-opening code already uses `open` on macOS.

Windows-specific today:

- Inno Setup installer and `.exe` packaging workflow.
- Development shortcut/launcher scripts.
- Authenticode verification/signing.
- Automatic update launch assumes a Windows installer.
- Some optional vendor-native integrations may require Windows DLLs.

## Execution phases

### Phase M0 — portability guardrails (dev.19)

- Add macOS to the core GitHub Actions test matrix.
- Add a dedicated macOS packaged-app workflow.
- Generate a native `.icns` from the VELOCITY iconset.
- Build `NHRA Velocity.app` with PyInstaller.
- Run the real packaged `--smoke-test` from inside the `.app` bundle.
- Upload an unsigned development `.app` ZIP artifact for engineering validation.
- Add platform-capability helpers/tests so Windows-only operations report clearly.

Acceptance: a GitHub-hosted macOS runner builds and smoke-tests the real app from the same commit as Windows.

### Phase M1 — usable engineering beta

- Validate Apple Silicon and Intel architecture requirements.
- Test RacePak RPK/DDF, MoTeC LD, MaxxECU, generic CSV/Excel, Common Channels, Math Channels, workbook save/reopen, and RSA workflows on real Mac hardware.
- Normalize custom shortcuts so macOS uses Command where appropriate while keeping engineering single-key waveform shortcuts unchanged.
- Validate drag/drop, file dialogs, menu placement, high-DPI/Retina rendering, multi-monitor behavior, and sleep/wake.
- Confirm Keychain session restore and Tech Services auth behavior.

Acceptance: an engineer can perform the normal Run → Data Log → Waveform → Compare → Save/Reopen workflow on macOS without a Windows machine.

### Phase M2 — signed distribution

- Enroll/confirm Apple Developer ID identity.
- Codesign the `.app` with hardened runtime.
- Notarize with Apple notary service and staple the ticket.
- Produce a signed/notarized DMG (or PKG only if operationally preferable).
- Add signature/notarization verification to CI/release gates.

Acceptance: a normal user can install and launch without bypassing Gatekeeper.

### Phase M3 — cross-platform updater

- Extend the update manifest from Windows-installer-only semantics to platform artifacts.
- Windows continues to verify SHA-256 + Authenticode.
- macOS verifies SHA-256 + Developer ID signature/notarization.
- Update UI downloads the correct platform artifact and hands off to a platform-specific installer/updater helper.
- Keep the app from replacing its own live bundle in place.

Acceptance: stable/beta channels update normally on both operating systems from one release manifest family.

### Phase M4 — vendor bridge parity

Classify each importer as:

- **Portable native parser:** same code on both platforms.
- **Portable interchange path:** CSV/Excel/export-based workflow works on both.
- **Windows-only vendor bridge:** explicitly unavailable on macOS until the vendor supplies a supported API/SDK.

Do not hold the entire macOS application hostage to a single Windows-only proprietary SDK.

## Architecture / packaging decisions

- macOS bundle id: `com.nhra.velocity`.
- User-facing app: `NHRA Velocity.app`.
- App support: `~/Library/Application Support/NHRA Velocity`.
- Logs remain under the Velocity application-support tree for parity with current diagnostics tooling.
- Initial development artifact is a ZIP of the `.app`; DMG becomes the production channel only after signing/notarization is in place.
- Universal2 is desirable but not assumed. We will validate the actual NHRA hardware mix before paying the complexity cost; Apple Silicon-native is likely the first real-hardware target, with Intel support retained if needed.

## Cross-platform acceptance suite

Every supported platform should eventually pass the same behavioral suite for:

- Tech Services sign-in/session restore.
- Current/latest-completed event sync.
- Run selection and attached data-log persistence.
- RacePak good-RPK → DDF definition reuse.
- Exact data-log Common Channel override and context-profile fallback.
- Portable math channels.
- Cursor/reference/statistics/zero behavior.
- Compare Set and workbook persistence.
- RSA model/residual calculations.
- Export/report operations.
- Crash logging and diagnostics collection.

The platform can differ in installer mechanics and native integrations; the engineering result must not.
