"""Faire parvenir un texte à l'utilisateur — la partie qui manquait.

``heartbeat/kinds.py`` calculait un drapeau ``delivered`` et rendait le texte à
son appelant. Personne ne l'envoyait nulle part. Une routine pouvait donc
tourner, réussir, consigner son résultat dans un journal, et n'atteindre
personne. C'est la raison pour laquelle Diapason n'a jamais parlé le premier :
non parce qu'il n'avait rien à dire, mais parce qu'il n'avait pas de bouche.

Le canal retenu est la notification macOS. Elle a trois qualités qu'aucun autre
n'a ici : elle survit à une application fermée, elle n'exige aucune permission
supplémentaire, et elle reste dans le centre de notifications quand personne
n'était devant l'écran — un briefing de sept heures du matin doit pouvoir
attendre son lecteur.

Écrire dans un fichier reste fait EN PLUS, toujours : une notification que
l'utilisateur balaie sans lire est perdue à jamais, alors qu'un journal se
relit. Les deux ne remplissent pas le même office.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

# osascript ne rend pas la main tant que le centre de notifications n'a pas
# accepté. Le borner évite qu'une routine de fond se fige indéfiniment.
DELAI_NOTIFICATION_S = 10.0

# AppleScript termine une chaîne au premier guillemet non échappé ; un titre de
# tâche contenant « " » couperait le message en deux et le reste passerait pour
# du code. La barre oblique inverse doit être traitée EN PREMIER, sinon on
# échapperait les barres qu'on vient d'ajouter.
_A_ECHAPPER = (("\\", "\\\\"), ('"', '\\"'))


def echapper_applescript(texte: str) -> str:
    """Rend une chaîne sûre à l'intérieur de guillemets AppleScript."""
    sortie = str(texte or "")
    for brut, remplace in _A_ECHAPPER:
        sortie = sortie.replace(brut, remplace)
    # Un saut de ligne littéral casse la commande : osascript -e prend une
    # ligne. Le corps d'une notification ne les affiche pas de toute façon.
    return sortie.replace("\r", " ").replace("\n", " ")


@dataclass(frozen=True, slots=True)
class Livraison:
    """Ce qui a été tenté, et ce qui a abouti."""

    notifiee: bool
    journalisee: bool
    detail: str = ""

    @property
    def ok(self) -> bool:
        """Vrai dès qu'UN canal a abouti — le journal suffit à ne rien perdre."""
        return self.notifiee or self.journalisee


def notifier_macos(
    titre: str,
    corps: str,
    *,
    sous_titre: str = "Diapason",
    lanceur: Sequence[str] | None = None,
) -> tuple[bool, str]:
    """Pose une notification dans le centre de notifications. Ne lève jamais."""
    script = (
        f'display notification "{echapper_applescript(corps)}" '
        f'with title "{echapper_applescript(titre)}" '
        f'subtitle "{echapper_applescript(sous_titre)}"'
    )
    commande = list(lanceur or ("osascript", "-e"))
    try:
        r = subprocess.run(
            [*commande, script],
            capture_output=True,
            text=True,
            timeout=DELAI_NOTIFICATION_S,
            check=False,
        )
    except FileNotFoundError:
        return False, "osascript introuvable (hors macOS ?)"
    except subprocess.TimeoutExpired:
        return False, "osascript n'a pas rendu la main"
    except Exception as exc:  # noqa: BLE001 - une livraison ratée ne tue rien
        return False, str(exc)[:120]
    if r.returncode != 0:
        return False, (r.stderr or "").strip()[:160] or f"code {r.returncode}"
    return True, ""


def journaliser(texte: str, *, chemin: Path | str | None = None, quand=None) -> bool:
    """Ajoute le texte au journal des briefings. Ne lève jamais.

    Une notification balayée sans être lue est perdue ; le journal, lui, se
    relit. C'est pourquoi il est écrit MÊME quand la notification a abouti.
    """
    if chemin is None:
        from diapason.core.paths import get_config_dir

        chemin = get_config_dir() / "briefings.md"
    chemin = Path(chemin).expanduser()
    horodatage = (quand or datetime.now()).strftime("%Y-%m-%d %H:%M")
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("a", encoding="utf-8") as f:
            f.write(f"\n## {horodatage}\n\n{texte.rstrip()}\n")
        return True
    except Exception:  # noqa: BLE001
        logger.warning("briefing non journalisé dans %s", chemin, exc_info=True)
        return False


def livrer(
    titre: str,
    corps: str,
    *,
    notifier: bool = True,
    chemin_journal: Path | str | None = None,
) -> Livraison:
    """Notifie ET journalise. Un canal qui tombe n'emporte pas l'autre."""
    notifiee, detail = (False, "notification désactivée")
    if notifier:
        notifiee, detail = notifier_macos(titre, corps)
        if not notifiee:
            logger.warning("notification non posée : %s", detail)
    journalisee = journaliser(corps, chemin=chemin_journal)
    return Livraison(notifiee=notifiee, journalisee=journalisee, detail=detail)


__all__ = [
    "DELAI_NOTIFICATION_S",
    "Livraison",
    "echapper_applescript",
    "journaliser",
    "livrer",
    "notifier_macos",
]
