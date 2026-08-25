"""Ce qu'on tient dans la main — le presse-papiers spatial (§17, §22).

Spatial Mesh, gestes, phase 5 — 25 août 2026. Le geste exprime une
INTENTION ; il ne transporte rien. Fermer le poing ne déplace aucun octet :
il désigne ce que l'écran affiche à cet instant et le retient, le temps
d'un geste. Ouvrir la main dit où le déposer.

Le §2 du cahier des charges le dit mieux que moi : ne jamais confondre
l'effet visuel et l'architecture. Ici, le presse-papiers est la seule
mémoire du geste, et elle est volatile, minuscule, et honnête — elle ne
contient jamais un fichier, seulement de quoi le retrouver.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Un objet attrapé et jamais déposé n'a pas à hanter la session : on le
# tient le temps d'un geste, pas le temps d'une journée.
TTL_S = 120.0


@dataclass(frozen=True, slots=True)
class ObjetSpatial:
    """Ce qui a été attrapé — une IDENTITÉ, jamais une copie (§19).

    Une tâche n'est pas sérialisée puis renvoyée : on transporte son type
    et son identifiant, et l'appareil d'arrivée va chercher la ressource
    par ses propres moyens. C'est ce qui distingue un handoff d'une
    duplication.
    """

    type: str  # "project" | "note" | "task" | "screen"
    id: str
    titre: str
    ecran: str = ""
    quand: float = 0.0

    @property
    def frais(self) -> bool:
        return (time.monotonic() - self.quand) < TTL_S

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "id": self.id,
            "title": self.titre,
            "screen": self.ecran,
        }


_tenu: Optional[ObjetSpatial] = None


def attraper() -> Optional[ObjetSpatial]:
    """Prendre ce que l'écran affiche à cet instant — ou rien.

    Rien n'est deviné : sans contexte d'application frais, la main se
    referme sur du vide, et le dire vaut mieux qu'attraper au hasard un
    objet que l'utilisateur ne regardait pas.
    """
    global _tenu
    from diapason.desktop.contexte_app import dernier_contexte

    vue = dernier_contexte()
    if vue is None:
        _tenu = None
        return None
    if vue.ressource_id and vue.ressource_type:
        _tenu = ObjetSpatial(
            type=vue.ressource_type,
            id=vue.ressource_id,
            titre=vue.ressource_titre or vue.ressource_id,
            ecran=vue.ecran,
            quand=time.monotonic(),
        )
    else:
        # Aucun élément sélectionné : c'est l'ÉCRAN qu'on attrape. « Reprends
        # ça là-bas » a un sens même sans élément précis.
        _tenu = ObjetSpatial(
            type="screen",
            id=vue.chemin,
            titre=vue.ecran,
            ecran=vue.ecran,
            quand=time.monotonic(),
        )
    logger.info("attrapé : %s « %s »", _tenu.type, _tenu.titre)
    return _tenu


def tenu() -> Optional[ObjetSpatial]:
    """Ce qui est tenu, s'il est encore frais."""
    if _tenu is not None and _tenu.frais:
        return _tenu
    return None


def lacher() -> Optional[ObjetSpatial]:
    """Rendre ce qui était tenu, et ouvrir la main."""
    global _tenu
    objet, _tenu = tenu(), None
    return objet


def vider() -> None:
    global _tenu
    _tenu = None


__all__ = ["ObjetSpatial", "TTL_S", "attraper", "lacher", "tenu", "vider"]
