"""Les onglets du navigateur de l'utilisateur — lister, activer. Pas fermer.

Atlas, panier « Ensuite », 24 août 2026. L'état du bureau lit déjà le TITRE
de l'onglet actif ; il manquait « retrouve mon onglet Gmail » — lister et
mettre devant. La fermeture est volontairement ABSENTE de ce périmètre :
fermer un onglet est irréversible (formulaire, brouillon), et les index se
décalent à chaque fermeture — le geste sûr viendra, gated, s'il manque.

Mêmes remparts qu'etat_bureau : LISTE BLANCHE de navigateurs (un « tell
application » vers une app non installée ouvre à la COMPILATION une boîte
« Où se trouve X ? » qu'aucun try ne rattrape), présence constatée par
pgrep avant tout tell, dialectes Safari (« name of current tab ») et
Chromium (« title of active tab ») écrits en toutes lettres.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any, Optional

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_SEP = "␟"  # symbole « unit separator » : introuvable dans un titre


def _run(cmd: list[str], *, timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


# Deux dialectes AppleScript. Les scripts sont des CONSTANTES — jamais l'app
# interpolée depuis une valeur libre.
_LISTER = {
    "Safari": (
        'set sortie to ""\n'
        'tell application "Safari"\n'
        "  set nf to 0\n"
        "  repeat with f in windows\n"
        "    set nf to nf + 1\n"
        "    set nt to 0\n"
        "    repeat with t in tabs of f\n"
        "      set nt to nt + 1\n"
        '      set sortie to sortie & nf & "␟" & nt & "␟" & (name of t) & "␟" & (URL of t) & linefeed\n'  # noqa: E501 - ligne d'AppleScript, pas ligne de Python
        "    end repeat\n"
        "  end repeat\n"
        "end tell\n"
        "return sortie"
    ),
    "Brave Browser": (
        'set sortie to ""\n'
        'tell application "Brave Browser"\n'
        "  set nf to 0\n"
        "  repeat with f in windows\n"
        "    set nf to nf + 1\n"
        "    set nt to 0\n"
        "    repeat with t in tabs of f\n"
        "      set nt to nt + 1\n"
        '      set sortie to sortie & nf & "␟" & nt & "␟" & (title of t) & "␟" & (URL of t) & linefeed\n'  # noqa: E501
        "    end repeat\n"
        "  end repeat\n"
        "end tell\n"
        "return sortie"
    ),
}

_ACTIVER = {
    "Safari": (
        'tell application "Safari"\n'
        "  set w to window {nf}\n"
        "  set current tab of w to tab {nt} of w\n"
        "  set index of w to 1\n"
        "  activate\n"
        "  return name of current tab of front window\n"
        "end tell"
    ),
    "Brave Browser": (
        'tell application "Brave Browser"\n'
        "  set w to window {nf}\n"
        "  set active tab index of w to {nt}\n"
        "  set index of w to 1\n"
        "  activate\n"
        "  return title of active tab of front window\n"
        "end tell"
    ),
}


def navigateur_en_marche(runner=None) -> Optional[str]:
    """Le premier navigateur connu dont le processus tourne — None sinon."""
    for nav in _LISTER:
        if (runner or _run)(["pgrep", "-x", nav]).returncode == 0:
            return nav
    return None


def interpreter_onglets(sortie: str) -> list[dict]:
    """[{fenetre, onglet, titre, url}] depuis les lignes du script."""
    onglets = []
    for ligne in (sortie or "").splitlines():
        morceaux = ligne.split(_SEP)
        if len(morceaux) != 4:
            continue
        try:
            onglets.append(
                {
                    "fenetre": int(morceaux[0]),
                    "onglet": int(morceaux[1]),
                    "titre": morceaux[2].strip(),
                    "url": morceaux[3].strip(),
                }
            )
        except ValueError:
            continue
    return onglets


@ToolRegistry.register("browser_tabs")
class BrowserTabsTool(BaseTool):
    """Les onglets ouverts : les voir, en mettre un devant."""

    tool_id = "browser_tabs"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_tabs",
            description=(
                "List the user's open browser tabs (Safari or Brave), or "
                "bring one to front: « retrouve mon onglet Gmail », « va sur "
                "l'onglet YouTube ». action=list returns window/tab indexes "
                "with titles and URLs; action=activate takes the window and "
                "tab indexes FROM THAT SAME list. It cannot close tabs."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "activate"],
                        "description": "list the tabs, or activate one.",
                    },
                    "window": {
                        "type": "integer",
                        "description": "Window index from list (activate).",
                    },
                    "tab": {
                        "type": "integer",
                        "description": "Tab index from list (activate).",
                    },
                },
                "required": ["action"],
            },
            category="system",
            # Lire, et un geste visible et réversible (l'onglet d'avant est à
            # un clic) : pas de cloche.
            requires_confirmation=False,
            timeout_seconds=20.0,
            metadata={"risk": "read_only", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        if sys.platform != "darwin":
            return ToolResult(
                tool_name="browser_tabs",
                content="browser_tabs is only implemented on macOS.",
                success=False,
            )
        action = str(params.get("action") or "").strip().lower()
        nav = navigateur_en_marche()
        if nav is None:
            return ToolResult(
                tool_name="browser_tabs",
                content=(
                    "No known browser is running (Safari, Brave). To open "
                    "one, call open_anything."
                ),
                success=False,
                metadata={"persistence": "unchanged"},
            )
        try:
            if action == "list":
                fait = _run(["osascript", "-e", _LISTER[nav]], timeout=15.0)
                if fait.returncode != 0:
                    return self._echec(nav, fait.stderr)
                onglets = interpreter_onglets(fait.stdout)
                lignes = [
                    f"[{o['fenetre']}.{o['onglet']}] {o['titre'][:80]}"
                    for o in onglets[:40]
                ]
                suite = f" (+{len(onglets) - 40} autres)" if len(onglets) > 40 else ""
                return ToolResult(
                    tool_name="browser_tabs",
                    content=(
                        f"{len(onglets)} onglet(s) dans {nav} :\n"
                        + "\n".join(lignes)
                        + suite
                    ),
                    success=True,
                    metadata={
                        "browser": nav,
                        "tabs": onglets,
                        "persistence": "unchanged",
                    },
                )
            if action == "activate":
                try:
                    nf, nt = int(params.get("window")), int(params.get("tab"))
                except (TypeError, ValueError):
                    return ToolResult(
                        tool_name="browser_tabs",
                        content=(
                            "activate needs window and tab indexes — call "
                            "action=list first and use ITS indexes."
                        ),
                        success=False,
                    )
                script = _ACTIVER[nav].replace("{nf}", str(nf)).replace("{nt}", str(nt))
                fait = _run(["osascript", "-e", script], timeout=15.0)
                if fait.returncode != 0:
                    return self._echec(nav, fait.stderr)
                # Constater : le titre rendu est celui de l'onglet DEVENU actif.
                titre = " ".join(fait.stdout.split())[:100]
                return ToolResult(
                    tool_name="browser_tabs",
                    content=f"Onglet devant toi dans {nav} : {titre}",
                    success=True,
                    metadata={
                        "browser": nav,
                        "active": titre,
                        "persistence": "unchanged",
                    },
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(tool_name="browser_tabs", content=str(exc), success=False)
        return ToolResult(
            tool_name="browser_tabs",
            content="Unknown action: list or activate.",
            success=False,
        )

    def _echec(self, nav: str, stderr: str) -> ToolResult:
        return ToolResult(
            tool_name="browser_tabs",
            content=(
                f"{nav} did not answer: {(stderr or '').strip()[:120]}. "
                "Grant Automation for the browser in System Settings → "
                "Privacy & Security → Automation if prompted."
            ),
            success=False,
        )


__all__ = [
    "BrowserTabsTool",
    "interpreter_onglets",
    "navigateur_en_marche",
]
