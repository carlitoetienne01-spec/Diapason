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
    set avant to name of first process whose frontmost is true
    set liste to name of every process whose background only is false
end tell
set AppleScript's text item delimiters to "|"
return avant & linefeed & (liste as text)
'''


@dataclass(frozen=True)
class EtatBureau:
    premier_plan: str
    en_marche: tuple[str, ...]
    quand: float


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


def interpreter(sortie: str) -> Optional[EtatBureau]:
    """La sortie du script, en état — None si elle ne ressemble à rien."""
    lignes = (sortie or "").strip().split("\n")
    if not lignes or not lignes[0].strip():
        return None
    premier = lignes[0].strip()
    apps = tuple(
        nom.strip()
        for nom in (lignes[1] if len(lignes) > 1 else "").split("|")
        if nom.strip()
    )
    return EtatBureau(premier_plan=premier, en_marche=apps, quand=time.monotonic())


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
        etat = interpreter((runner or _executer)(_SCRIPT))
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
    """L'état en une phrase française, prête pour le contexte du modèle."""
    autres = [nom for nom in etat.en_marche if nom != etat.premier_plan]
    coupe = autres[:limite]
    suite = f" (+{len(autres) - limite})" if len(autres) > limite else ""
    en_marche = ", ".join(coupe) + suite if coupe else "rien d'autre"
    return (
        f"État du bureau : au premier plan, {etat.premier_plan}. "
        f"Aussi en marche : {en_marche}."
    )


__all__ = [
    "EtatBureau",
    "dernier_etat_connu",
    "decrire",
    "etat_du_bureau",
    "interpreter",
    "premier_plan",
]
