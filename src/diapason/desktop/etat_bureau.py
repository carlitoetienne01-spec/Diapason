"""L'état du bureau — ce qui tourne, ce qui est devant.

Demandé le 23 août 2026 : « si l'application est déjà ouverte, regarde,
et mets-la au premier plan » — un compagnon fluide perçoit l'état du Mac
avant d'agir et de parler. Ce module est cette perception : une lecture
System Events (l'app au premier plan + les apps visibles), un cache court
pour que la voix n'attende jamais, et une phrase française prête pour le
contexte du modèle.

Le cache a deux lectures : ``etat_du_bureau()`` rafraîchit si le cliché
est vieux (≈ 100 ms d'osascript), ``dernier_etat_connu()`` rend le cliché
tel quel sans jamais bloquer — c'est lui que le tour de parole consulte,
pendant qu'un rafraîchissement part en tâche de fond.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

TTL_S = 6.0
_APPS_MAX = 12

# Une seule passe AppleScript : le premier plan, puis les processus
# visibles, séparés par « | » — un séparateur qu'aucun nom d'app ne porte.
_SCRIPT = '''
tell application "System Events"
    set devant to first process whose frontmost is true
    set avant to name of devant
    set titre to ""
    -- Beaucoup de processus n'ont AUCUNE fenêtre (barre de menus, agents) :
    -- `front window` y lève -1728. Le try est obligatoire, pas défensif.
    try
        set titre to name of front window of devant
    end try
    set liste to name of every process whose background only is false
end tell
set AppleScript\'s text item delimiters to "|"
return avant & linefeed & (liste as text) & linefeed & titre
'''


@dataclass(frozen=True)
class EtatBureau:
    premier_plan: str
    en_marche: tuple[str, ...]
    quand: float
    # Ajoutés APRÈS `quand` et avec un défaut vide (24 août 2026) : quatre
    # constructions positionnelles à trois arguments existent dans les
    # tests, insérer avant les aurait toutes cassées.
    titre_fenetre: str = ""
    onglet: str = ""


_cache: Optional[EtatBureau] = None


def _executer(script: str) -> str:
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "osascript failed").strip())
    return r.stdout


# Les navigateurs dont on sait demander l'onglet actif. LISTE BLANCHE, et
# c'est structurel : un `tell application "X"` littéral pour une app NON
# INSTALLÉE ouvre, à la COMPILATION du script, une boîte « Où se trouve X ? »
# qu'aucun try ne rattrape. On ne demande donc l'onglet qu'à un navigateur
# connu ET déjà au premier plan (24 août 2026).
_ONGLET_PAR_NAVIGATEUR: dict[str, str] = {
    "Safari": 'tell application "Safari" to get name of current tab of front window',
    "Google Chrome": 'tell application "Google Chrome" to get title of active tab of front window',
    "Brave Browser": 'tell application "Brave Browser" to get title of active tab of front window',
    "Arc": 'tell application "Arc" to get title of active tab of front window',
    "Microsoft Edge": 'tell application "Microsoft Edge" to get title of active tab of front window',
}


def onglet_actif(
    app: str, runner: Optional[Callable[[str], str]] = None
) -> str:
    """Le titre de l'onglet actif d'un navigateur connu — "" sinon.

    Rien ne s'invente : un navigateur inconnu, une fenêtre absente ou un
    refus d'automatisation rendent la chaîne vide, et decrire() se tait.
    """
    script = _ONGLET_PAR_NAVIGATEUR.get(app)
    if script is None:
        return ""
    try:
        return " ".join((runner or _executer)(script).split())
    except Exception:  # noqa: BLE001 - la perception est un bonus, jamais une porte
        logger.debug("onglet actif illisible pour %s", app, exc_info=True)
        return ""


def interpreter(
    sortie: str, runner: Optional[Callable[[str], str]] = None
) -> Optional[EtatBureau]:
    """La sortie du script, en état — None si elle ne ressemble à rien."""
    lignes = (sortie or "").strip("\n").split("\n")
    if not lignes or not lignes[0].strip():
        return None
    premier = lignes[0].strip()
    apps = tuple(
        nom.strip()
        for nom in (lignes[1] if len(lignes) > 1 else "").split("|")
        if nom.strip()
    )
    titre = " ".join(lignes[2].split()) if len(lignes) > 2 else ""
    # L'onglet coûte un SECOND appel osascript : on ne le paie que pour un
    # navigateur, et seulement quand il est déjà devant.
    onglet = onglet_actif(premier, runner) if premier in _ONGLET_PAR_NAVIGATEUR else ""
    return EtatBureau(
        premier_plan=premier,
        en_marche=apps,
        quand=time.monotonic(),
        titre_fenetre=titre,
        onglet=onglet,
    )


def etat_du_bureau(
    *,
    ttl_s: float = TTL_S,
    runner: Optional[Callable[[str], str]] = None,
    horloge: Callable[[], float] = time.monotonic,
) -> Optional[EtatBureau]:
    """Le cliché courant, rafraîchi s'il a dépassé son âge. None hors macOS."""
    global _cache
    if runner is None and sys.platform != "darwin":
        return None
    if _cache is not None and horloge() - _cache.quand < ttl_s:
        return _cache
    try:
        etat = interpreter((runner or _executer)(_SCRIPT), runner)
    except Exception:  # noqa: BLE001 - la perception est un bonus, jamais une porte
        logger.debug("état du bureau illisible", exc_info=True)
        return _cache
    if etat is not None:
        _cache = etat
    return _cache


def dernier_etat_connu() -> Optional[EtatBureau]:
    """Le cliché tel quel, sans lecture — jamais une milliseconde d'attente."""
    return _cache


def premier_plan(runner: Optional[Callable[[str], str]] = None) -> str:
    """L'app au premier plan, à l'instant même (lecture directe, ~80 ms)."""
    script = (
        'tell application "System Events" to get name of '
        "first process whose frontmost is true"
    )
    try:
        return (runner or _executer)(script).strip()
    except Exception:  # noqa: BLE001
        return ""


def decrire(etat: EtatBureau, limite: int = _APPS_MAX) -> str:
    """L'état en une phrase française, prête pour le contexte du modèle.

    La phrase de base est INCHANGÉE quand titre et onglet sont vides : elle
    est comparée à l'égalité par des tests, et surtout un cliché plus bavard
    qu'il n'a de matière ferait deviner le modèle.
    """
    autres = [nom for nom in etat.en_marche if nom != etat.premier_plan]
    coupe = autres[:limite]
    suite = f" (+{len(autres) - limite})" if len(autres) > limite else ""
    en_marche = ", ".join(coupe) + suite if coupe else "rien d'autre"
    # « Safari » ne dit rien ; « Safari — Gmail, brouillon à Julie » dit tout.
    precision = etat.onglet or etat.titre_fenetre
    devant = (
        f"{etat.premier_plan} — {precision[:120]}"
        if precision
        else etat.premier_plan
    )
    return (
        f"État du bureau : au premier plan, {devant}. "
        f"Aussi en marche : {en_marche}."
    )


__all__ = [
    "EtatBureau",
    "onglet_actif",
    "dernier_etat_connu",
    "decrire",
    "etat_du_bureau",
    "interpreter",
    "premier_plan",
]
