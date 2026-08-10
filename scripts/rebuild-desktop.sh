#!/usr/bin/env bash
# Rebuild the OpenJarvis macOS/desktop Tauri app (global hotkeys live here).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"
echo "→ npm install"
npm install
echo "→ tauri build (this compiles Rust + Vite)"
npm run tauri:build
echo
echo "Done. Bundle under:"
echo "  $ROOT/frontend/src-tauri/target/release/bundle/"
echo "Install/replace the .app, then restart OpenJarvis Desktop."
