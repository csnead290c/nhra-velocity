# NHRA Velocity release and update strategy

## User experience

Normal users install **NHRA Velocity** once through a signed Windows installer and launch it from the Start menu/desktop like any other Windows application. They do not need Python, Git, or a source checkout.

The application may check a configured HTTPS `update.json` feed. When a newer release is available it presents release notes and lets the user install now or later. The application downloads the normal installer, verifies the exact byte count and SHA-256, optionally requires a valid Authenticode publisher signature, then launches the installer and exits. It never overwrites its running executable directly.

## GitHub responsibilities

The private source repository is the engineering system of record. GitHub Actions should run tests on every pull request/push and build Windows release artifacts from version tags. Production releases are immutable Git tags.

For anonymous in-app updating, a private source repository should **not** embed a GitHub personal-access token in the executable. Use one of these release-feed models:

1. **Preferred internal production model:** private source repo -> GitHub Actions signed build -> publish `update.json` + installer to the authenticated NHRA Tech Services distribution endpoint.
2. **Simple GitHub-only model:** private source repo -> GitHub Actions publishes signed binaries to a separate public binary-only GitHub Releases repository; source remains private.
3. **GitHub-account model:** private GitHub Releases can be consumed only when each application user authenticates to GitHub. This is acceptable for engineering/developer channels but is not the preferred normal-user experience.

The updater is intentionally feed-agnostic: the build/install pipeline can change without changing the validation/security contract.

## Release channels

- `stable` — production users; tagged releases only.
- `beta` — track/engineering validation builds; opt-in.
- `development` — developer/tester artifacts from `develop`; never silently delivered to stable users.

The user's selected update channel is application state, not telemetry/run metadata.

## Windows packaging

PyInstaller creates the application directory; Inno Setup wraps it in a normal per-user installer. Per-user installation avoids requiring local administrator rights for routine installs/updates. Production builds should Authenticode-sign both the executable and installer using an NHRA-controlled code-signing certificate held only in protected CI secrets or a managed signing service.

## Release checklist

1. Freeze feature work on `release/vX.Y.Z` if needed.
2. Update `runlab/version.py` to `X.Y.Z` and channel `stable`.
3. Update changelog/validation report/product manifest.
4. Run the full automated suite plus real Windows smoke tests and qualified real-file regression.
5. Merge to `main`.
6. Create signed tag `vX.Y.Z`.
7. CI builds/signs installer, generates `update.json` and SHA-256 checksums, and publishes the GitHub Release/distribution feed.
8. Verify install, update-from-previous-version, rollback/uninstall and fresh-machine launch.
9. Merge release/version changes back to `develop` and advance it to the next `-dev.1` version.

A release is not considered production merely because CI compiled it. Track-side Windows validation remains a release gate for UI/import changes.
