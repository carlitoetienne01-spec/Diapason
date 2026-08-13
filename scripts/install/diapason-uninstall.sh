#!/usr/bin/env bash
# diapason-uninstall.sh — clean removal of Diapason from $HOME.
#
# Removes:
#   ~/.diapason/
#   ~/.local/bin/diapason
#   ~/.local/bin/diapason-uninstall
#
# Does NOT remove: ollama, uv, or the Rust toolchain.

set -euo pipefail

DIAPASON_HOME="${DIAPASON_HOME:-${OPENJARVIS_HOME:-${JARVIS_HOME:-$HOME/.diapason}}}"

# Resolve and validate the exact install root before recursive deletion.
parent_dir="$(dirname "$DIAPASON_HOME")"
base_name="$(basename "$DIAPASON_HOME")"
resolved_parent="$(cd "$parent_dir" 2>/dev/null && pwd -P)" || {
    echo "Refusing uninstall: cannot resolve $DIAPASON_HOME" >&2
    exit 1
}
DIAPASON_HOME="$resolved_parent/$base_name"
if [[ -z "$DIAPASON_HOME" || "$DIAPASON_HOME" == "/" || "$DIAPASON_HOME" == "$HOME" ]]; then
    echo "Refusing unsafe uninstall target: $DIAPASON_HOME" >&2
    exit 1
fi
if [[ "$base_name" != ".diapason" && ! -f "$DIAPASON_HOME/src/pyproject.toml" ]]; then
    echo "Refusing unrecognized Diapason install root: $DIAPASON_HOME" >&2
    exit 1
fi

if [[ -f "$DIAPASON_HOME/.state/bg.pid" ]]; then
    pid=$(cat "$DIAPASON_HOME/.state/bg.pid" 2>/dev/null || echo "")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        echo "Stopping background work (pid=$pid)..."
        kill "$pid" 2>/dev/null || true
    fi
fi

if command -v ollama >/dev/null 2>&1; then
    ollama stop >/dev/null 2>&1 || true
fi

if [[ -d "$DIAPASON_HOME" ]]; then
    rm -rf "$DIAPASON_HOME"
    echo "Removed $DIAPASON_HOME"
fi

for f in "$HOME/.local/bin/diapason" "$HOME/.local/bin/diapason-uninstall"; do
    if [[ -L "$f" ]] || [[ -f "$f" ]]; then
        rm -f "$f"
        echo "Removed $f"
    fi
done

cat <<EOF

Diapason removed.

Left intact (may be used by other tools):
  - Ollama       (uninstall: brew uninstall ollama  /  rm -f /usr/local/bin/ollama)
  - uv           (uninstall: rm -rf ~/.local/share/uv ~/.cargo/bin/uv)
  - Rust toolchain (uninstall: rustup self uninstall)
EOF
