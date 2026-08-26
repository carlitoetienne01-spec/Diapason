"""Detect how Diapason was installed so we can show the right upgrade
command (and run the right upgrade command for ``diapason self-update``).

Three install paths are supported today:

- **PyPI** (``pip install diapason``). The package lives somewhere
  inside ``site-packages``. Upgrade with ``pip install --upgrade diapason``.
- **uv tool** (``uv tool install diapason``). Lives in a uv-managed
  isolated venv under ``~/.local/share/uv/tools/``. Upgrade with
  ``uv tool upgrade diapason``.
- **Editable git checkout** (``uv sync`` / ``pip install -e .`` from a
  cloned repo). The package's ``__file__`` is inside a working tree
  with a ``.git`` directory at the repo root. Upgrade with
  ``git pull && make setup`` from the checkout — **not** a bare
  ``uv sync``, which prunes every extra it does not name and would leave
  the install broken in silence. On Windows, where make is absent, run the
  sync line from ``deploy/windows/install.ps1`` instead.

We detect by inspecting ``diapason.__file__``. If we can't tell with
confidence we fall back to the PyPI command — that's the most common
case and the worst outcome is a no-op for a user who has nothing to
pull from PyPI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class InstallInfo:
    """How Diapason was installed."""

    kind: str  # "pypi" | "uv-tool" | "editable-git" | "unknown"
    upgrade_command: str
    repo_root: Optional[Path] = None  # only set for editable-git


def detect_install() -> InstallInfo:
    """Return an :class:`InstallInfo` for the running interpreter.

    Cheap: just walks the parent directories of ``diapason.__file__``
    once and checks for marker directories. No subprocess calls.
    """
    try:
        import diapason

        pkg_file = Path(diapason.__file__).resolve()
    except Exception:
        return InstallInfo(
            kind="unknown",
            upgrade_command="pip install --upgrade diapason",
        )

    parts = [p.lower() for p in pkg_file.parts]

    if "uv" in parts and "tools" in parts:
        return InstallInfo(
            kind="uv-tool",
            upgrade_command="uv tool upgrade diapason",
        )

    # Editable install: a ``.git`` dir within a few parents of the
    # package source. Walk up at most ~8 levels — enough for typical
    # ``<repo>/src/diapason/__init__.py`` layouts plus headroom, but
    # not so deep we wander into home or root.
    candidate = pkg_file.parent
    for _ in range(8):
        if (candidate / ".git").exists() and (candidate / "pyproject.toml").exists():
            return InstallInfo(
                kind="editable-git",
                # `make setup`, JAMAIS un `uv sync` nu. La commande nue
                # ÉLAGUE tout extra qu'elle ne nomme pas : elle emporterait
                # fastapi, uvicorn, faster-whisper, l'extension native — et
                # la mise à jour laisserait une installation cassée sans un
                # mot. Le piège a mordu deux fois sur la machine de
                # développement (24 et 25 août 2026) ; l'inscrire dans la
                # commande que Diapason CONSEILLE lui-même l'aurait fait
                # mordre chez tout le monde.
                #
                # `make setup` porte la liste complète des extras, en un seul
                # endroit. Sans make — Windows — la cible équivalente est
                # rappelée par le message ci-dessous.
                upgrade_command=f"cd {candidate} && git pull && make setup",
                repo_root=candidate,
            )
        if candidate.parent == candidate:
            break
        candidate = candidate.parent

    if "site-packages" in parts:
        return InstallInfo(
            kind="pypi",
            upgrade_command="pip install --upgrade diapason",
        )

    return InstallInfo(
        kind="unknown",
        upgrade_command="pip install --upgrade diapason",
    )
