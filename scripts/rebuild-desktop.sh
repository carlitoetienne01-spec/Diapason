#!/usr/bin/env bash
# Rebuild the Diapason macOS/desktop Tauri app (global hotkeys live here).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"
echo "→ npm install"
npm install
echo "→ tauri build (this compiles Rust + Vite)"
npm run tauri:build

# Spotlight indexes any .app it finds. Keep build leftovers invisible, then
# replace the single installed app — never open a second copy from target/.
TARGET="$ROOT/frontend/src-tauri/target"
mkdir -p "$TARGET"
touch "$TARGET/.metadata_never_index"

BUNDLE="$(find "$TARGET" -path '*/bundle/macos/Diapason.app' -maxdepth 8 2>/dev/null | head -1)"
if [ -z "$BUNDLE" ] || [ ! -x "$BUNDLE/Contents/MacOS/diapason-desktop" ]; then
  echo "Build finished but Diapason.app was not found under $TARGET" >&2
  exit 1
fi

echo "→ replace /Applications/Diapason.app (no second copy)"
osascript -e 'tell application "Diapason" to quit' 2>/dev/null || true
killall diapason-desktop 2>/dev/null || true
sleep 1
rm -rf /Applications/Diapason.app
ditto "$BUNDLE" /Applications/Diapason.app
xattr -cr /Applications/Diapason.app 2>/dev/null || true
rm -rf "$BUNDLE"

echo "→ open /Applications/Diapason.app"
open /Applications/Diapason.app
echo "Done. Only /Applications/Diapason.app should appear in Launchpad."
