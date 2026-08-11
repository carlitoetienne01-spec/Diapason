"""Shared helper for resolving the diapason repo's HEAD commit."""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path


@functools.lru_cache(maxsize=1)
def diapason_commit() -> str:
    """Return the diapason repo's HEAD commit (cached, lru-1).

    Returns ``"unknown"`` if git is unavailable or the path isn't a repo.
    Used by DiapasonAgentBackend and DiapasonDirectBackend to populate the
    ``framework_commit`` field in their extended return dicts.
    """
    try:
        # Walk up to repo root: backends/ -> evals/ -> diapason/ -> src/ -> repo
        result = subprocess.run(
            [
                "git",
                "-C",
                str(Path(__file__).resolve().parents[4]),
                "rev-parse",
                "HEAD",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"
