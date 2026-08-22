#!/usr/bin/env bash
# diapason-wrapper.sh — symlinked to ~/.local/bin/diapason.
# Activates the managed venv and execs the real diapason CLI.

DIAPASON_HOME="${DIAPASON_HOME:-${OPENJARVIS_HOME:-${JARVIS_HOME:-$HOME/.diapason}}}"
VENV="$DIAPASON_HOME/.venv"

if [[ ! -d "$VENV" ]]; then
    echo "diapason: venv not found at $VENV" >&2
    echo "Re-run the installer: curl -fsSL https://carlitoetienne01-spec.github.io/Diapason/install.sh | bash" >&2
    exit 1
fi

exec "$VENV/bin/diapason" "$@"
