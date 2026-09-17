# NHRA Velocity brand assets

Production application assets for the NHRA Velocity desktop workstation.

- `nhra-velocity.ico` — Windows executable/installer/shortcut icon.
- `nhra-velocity-16.png` ... `nhra-velocity-512.png` — raster application icons.
- `nhra-velocity.iconset/` — macOS source iconset used by `iconutil` to create the packaged `.icns`.
- `nhra-velocity-mark.svg` / `.png` — icon-only mark.
- `nhra-velocity-logo.svg` / `.png` — horizontal product lockup.

The compact install icon uses a solid charcoal tile for legibility in Windows. The logo/mark assets retain transparent backgrounds for use in the application UI and documentation.

The generated `nhra-velocity.icns` is a macOS build artifact and is intentionally not required in source control; `scripts/build_macos_icon.sh` creates it on a Mac from the committed iconset.
