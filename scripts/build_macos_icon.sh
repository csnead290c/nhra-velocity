#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ICONSET="$ROOT/assets/nhra-velocity.iconset"
OUT="$ROOT/assets/nhra-velocity.icns"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: build_macos_icon.sh requires macOS (iconutil)." >&2
  exit 2
fi
for f in \
  icon_16x16.png icon_16x16@2x.png \
  icon_32x32.png icon_32x32@2x.png \
  icon_128x128.png icon_128x128@2x.png \
  icon_256x256.png icon_256x256@2x.png \
  icon_512x512.png icon_512x512@2x.png; do
  [[ -f "$ICONSET/$f" ]] || { echo "ERROR: missing $ICONSET/$f" >&2; exit 3; }
done
rm -f "$OUT"
iconutil -c icns "$ICONSET" -o "$OUT"
echo "Created $OUT"
