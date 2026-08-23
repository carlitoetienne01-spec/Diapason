"""Installer une application à la demande — Homebrew d'abord, l'App Store en repli.

Demandé le 23 août 2026 : « quand je lui demande d'installer une application,
il doit pouvoir l'installer ». La machine a Homebrew ; le canal est donc :

1. Déjà installée ? On le dit, et on l'ouvre — installer un doublon n'aide
   personne.
2. Le cask Homebrew existe ? L'installation part en ARRIÈRE-PLAN — elle dure
   des minutes, aucun outil ne doit retenir la conversation si longtemps — et
   une notification macOS annonce la fin, succès ou échec.
3. Sinon, la page de recherche de l'App Store s'ouvre sur le nom demandé :
   Apple exige de toute façon le mot de passe de l'utilisateur pour Obtenir.

L'outil déclare requires_confirmation : installer du logiciel sur une phrase
peut-être mal transcrite mérite un clic dans la cloche. La règle de Carlito
visait la suppression ; installer change aussi la machine, la prudence est la
même. Le nom demandé passe en argv, jamais interpolé dans un shell.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any
from urllib.parse import quote_plus

from diapason.core.registry import ToolRegistry
from diapason.tools._stubs import BaseTool, ToolResult, ToolSpec

_BREW = "/opt/homebrew/bin/brew"


def _brew() -> str | None:
    if shutil.which("brew"):
        return "brew"
    import os

    return _BREW if os.path.exists(_BREW) else None


def _chercher_cask(nom: str) -> str | None:
    """Le cask exact pour ce nom parlé, ou None. Jamais un à-peu-près.

    « zoom » rend aussi gzdoom et photozoom-pro : seul un nom qui correspond
    une fois les tirets pliés est retenu — installer le mauvais logiciel est
    pire que renvoyer vers l'App Store.
    """
    brew = _brew()
    if brew is None:
        return None
    try:
        r = subprocess.run(
            [brew, "search", "--cask", nom],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    voulu = re.sub(r"[^a-z0-9]", "", nom.casefold())
    for ligne in (r.stdout or "").split("\n"):
        candidat = ligne.strip()
        if not candidat or candidat.startswith("==>") or "@" in candidat:
            continue
        if re.sub(r"[^a-z0-9]", "", candidat.casefold()) == voulu:
            return candidat
    return None


@ToolRegistry.register("app_install")
class AppInstallTool(BaseTool):
    """Install an application by name — Homebrew cask, or the App Store page."""

    tool_id = "app_install"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="app_install",
            description=(
                "Install an application the user asks for — « installe VLC », "
                "« télécharge Discord ». Already installed → says so and opens "
                "it. Known to Homebrew → installs in the background and "
                "notifies when done. Otherwise → opens the App Store search "
                "page for it. Requires the user's approval."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "description": "Application name."},
                },
                "required": ["name"],
            },
            category="system",
            requires_confirmation=True,
            timeout_seconds=45.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        nom = str(params.get("name") or "").strip()
        if not nom:
            return ToolResult(
                tool_name="app_install",
                content="Il manque le nom de l'application.",
                success=False,
            )

        # 1 · déjà là ? On ouvre au lieu de réinstaller.
        from diapason.desktop.app_index import APP_INDEX

        deja = APP_INDEX.lookup(nom)
        if deja is not None:
            subprocess.run(
                ["open", "-a", deja], capture_output=True, timeout=15, check=False
            )
            return ToolResult(
                tool_name="app_install",
                content=f"« {deja} » est déjà installée — je l'ai ouverte.",
                success=True,
            )

        # 2 · Homebrew, en arrière-plan, avec notification de fin.
        cask = _chercher_cask(nom)
        brew = _brew()
        if cask and brew:
            fini_ok = (
                f'display notification "{cask} est installée." '
                'with title "Diapason" subtitle "Installation terminée"'
            )
            fini_ko = (
                f'display notification "L\'installation de {cask} a échoué." '
                'with title "Diapason" subtitle "Installation"'
            )
            commande = (
                f"{brew} install --cask {cask} "
                f"&& osascript -e '{fini_ok}' || osascript -e '{fini_ko}'"
            )
            try:
                subprocess.Popen(
                    ["/bin/sh", "-c", commande],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as exc:
                return ToolResult(
                    tool_name="app_install",
                    content=f"Homebrew n'a pas démarré : {exc}",
                    success=False,
                )
            return ToolResult(
                tool_name="app_install",
                content=(
                    f"Installation de « {cask} » lancée en arrière-plan via "
                    "Homebrew — une notification annoncera la fin, d'ici "
                    "quelques minutes."
                ),
                success=True,
            )

        # 3 · l'App Store, page de recherche ouverte sur le nom.
        try:
            subprocess.run(
                [
                    "open",
                    "macappstore://search.itunes.apple.com/WebObjects/MZSearch.woa"
                    f"/wa/search?q={quote_plus(nom)}",
                ],
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(
                tool_name="app_install",
                content=f"L'App Store n'a pas répondu : {exc}",
                success=False,
            )
        return ToolResult(
            tool_name="app_install",
            content=(
                f"« {nom} » n'est pas dans Homebrew — j'ai ouvert la recherche "
                "App Store : clique Obtenir pour l'installer."
            ),
            success=True,
        )


__all__ = ["AppInstallTool"]
