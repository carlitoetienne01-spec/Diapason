"""Dictée progressive : les mots s'écrivent pendant qu'on parle.

La dictée transcrivait à la fin puis collait d'un bloc. Ici le texte se pose
au fil des mots et se corrige tout seul, parce que whisper relit tout le
tampon à chaque passe et RÉVISE ce qu'il avait compris.

Le risque n'est pas dans ce module : il est dans les applications. Certaines
gèrent mal le remplacement d'une sélection — terminaux, éditeurs avec
autocomplétion, zones web — et le texte s'y duplique ou atterrit ailleurs.
L'échec se produirait dans le document de quelqu'un, pas dans un journal.

D'où une liste d'applications autorisées plutôt qu'un réglage global :
partout ailleurs, la dictée garde son comportement éprouvé. On étend selon
ce qu'on constate, jamais par optimisme.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Applications où la dictée progressive est active. Choisies pour une raison
# commune : ce sont des champs de texte natifs Cocoa, où le remplacement de
# plage AX est fiable. Terminal, VS Code et les navigateurs en sont absents
# EXPRÈS — pas par oubli.
LIVE_APPS: frozenset[str] = frozenset(
    {
        "notes",
        "mail",
        "pages",
        "textedit",
        "slack",
        "messages",
    }
)


def live_allowed(app_name: Optional[str]) -> bool:
    """Si la dictée progressive doit s'activer dans cette application.

    Sans nom d'application, la réponse est non : ne pas savoir où l'on écrit
    n'est pas une raison d'essayer quand même.
    """
    if not app_name:
        return False
    return app_name.strip().lower() in LIVE_APPS


class LiveDictation:
    """Pose le texte au fil des révisions, et sait revenir en arrière.

    Une seule règle porte la sûreté : ce module ne connaît QUE ce qu'il a
    lui-même écrit, et ne remplace jamais que cela. Il ne lit pas le
    document, ne le modifie pas ailleurs, et s'abstient dès qu'il n'est plus
    sûr de la position.
    """

    def __init__(self, inserer=None, remplacer=None) -> None:
        if inserer is None or remplacer is None:
            from diapason.desktop.accessibility import insert_text, replace_previous

            inserer = inserer or insert_text
            remplacer = remplacer or replace_previous
        self._inserer = inserer
        self._remplacer = remplacer
        self._pose = ""
        self._perdu = False

    @property
    def texte_pose(self) -> str:
        return self._pose

    def mettre_a_jour(self, texte: str) -> bool:
        """Faire en sorte que l'application affiche ``texte``.

        Rend False quand la pose a échoué : l'appelant doit alors cesser
        d'insister et laisser la voie de secours coller à la fin. Réessayer
        après un échec, c'est risquer d'écrire deux fois.
        """
        if self._perdu:
            return False
        texte = texte or ""
        if texte == self._pose:
            return True

        # Cas courant : la révision ne fait qu'allonger. On n'écrit que la
        # suite, sans toucher à ce qui est déjà correct — moins de
        # remplacement, moins de scintillement, moins de surface d'erreur.
        if texte.startswith(self._pose):
            suite = texte[len(self._pose) :]
            ok = self._inserer(suite)
        else:
            ok = self._remplacer(len(self._pose), texte)

        if not ok:
            # Une pose ratée laisse un état inconnu. On se déclare perdu
            # plutôt que de tenter une correction à l'aveugle.
            self._perdu = True
            logger.info("dictée progressive interrompue : pose refusée")
            return False
        self._pose = texte
        return True

    def remplacer_par(self, texte: str) -> bool:
        """Substituer la version polie au brut déjà posé, d'un seul geste."""
        if self._perdu or texte == self._pose:
            return not self._perdu
        if not self._remplacer(len(self._pose), texte):
            self._perdu = True
            return False
        self._pose = texte
        return True

    @property
    def perdu(self) -> bool:
        """Vrai quand une pose a échoué et qu'il ne faut plus rien tenter."""
        return self._perdu
