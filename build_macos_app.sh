#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: build_macos_app.sh must run on macOS." >&2
  exit 2
fi

python3 -m pip install -r requirements-build-macos.txt
./scripts/build_macos_icon.sh

FULL_VERSION="${NHRA_VELOCITY_VERSION:-$(python3 -c 'from runlab.version import __version__; print(__version__)')}"
SHORT_VERSION="${FULL_VERSION%%-*}"
BUILD_VERSION="$(python3 - <<'PYVER'
import re
from runlab.version import __version__
v=__version__
core=v.split('-',1)[0]
m=re.search(r'(?:dev|alpha|beta|rc)[.-]?(\d+)',v,re.I)
print(core + ('.' + m.group(1) if m else '.0'))
PYVER
)"
APP_NAME="NHRA Velocity"
BUNDLE_ID="com.nhra.velocity"

python3 -m PyInstaller --noconfirm --clean --windowed \
  --name "$APP_NAME" \
  --icon "assets/nhra-velocity.icns" \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --collect-all pyqtgraph \
  --add-data "assets:assets" \
  --add-data "examples:examples" \
  --add-data "README.md:." \
  --add-data "IMPORT_SUPPORT.md:." \
  --add-data "VALIDATION_REPORT.md:." \
  --add-data "ARCHITECTURE.md:." \
  --add-data "DATA_MODEL.md:." \
  --add-data "LONG_TERM_ROADMAP.md:." \
  --add-data "PRODUCT_AUDIT_v0_38.md:." \
  --add-data "MACOS_PLAN.md:." \
  desktop.py

APP="dist/$APP_NAME.app"
PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName $APP_NAME" "$PLIST" || true
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $SHORT_VERSION" "$PLIST" || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $SHORT_VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $BUILD_VERSION" "$PLIST" || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $BUILD_VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$PLIST" 2>/dev/null || true

if [[ -n "${NHRA_MACOS_CODESIGN_IDENTITY:-}" ]]; then
  echo "Signing $APP with ${NHRA_MACOS_CODESIGN_IDENTITY}..."
  codesign --force --deep --options runtime --timestamp \
    --sign "$NHRA_MACOS_CODESIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
else
  echo "NOTE: NHRA_MACOS_CODESIGN_IDENTITY is not set; development .app is unsigned."
fi

echo "Build complete: $APP"
