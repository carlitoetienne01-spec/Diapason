"""Ce que le mode gestes COÛTE, et comment il cesse de le coûter (§83).

Spatial Mesh, gestes — 25 août 2026. Le §78 dit qu'une caméra ne guette pas
en permanence, et quatre chemins d'extinction le tiennent déjà. Le §83 dit
autre chose : même armée, la caméra ne doit pas coûter le même prix selon
qu'on s'en sert ou non.

Jusqu'ici la cadence était **figée à douze images par seconde**, du premier
instant au désarmement. Armer le mode et aller lire un document, c'était
douze captures, douze encodages JPEG et douze appels à Vision par seconde,
pendant dix minutes, pour filmer une chaise.

Quatre états, et un seul chiffre en sort — la cadence que l'interface doit
appliquer. C'est le SERVEUR qui décide, parce qu'il est le seul à savoir si
une main a été vue ; l'interface obéit et ne devine rien.

Ce que ce module refuse de faire : baisser la cadence pendant qu'une main
est suivie. Le geste se mesure en IMAGES (« ≤ 10 images pour un attraper »,
figé par un test), donc une cadence qui tombe au milieu d'un geste allonge
ce geste en secondes sans que personne l'ait demandé. On économise entre les
gestes, jamais pendant.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Optional


# Les noms sur le fil sont ceux du cahier des charges (§83), en anglais comme
# tout ce qui traverse une frontière ; les membres restent français.
class Energie(str, Enum):
    ETEINT = "OFF"
    PRET = "READY"
    ACTIF = "ACTIVE"
    ECONOMIE = "LOW_POWER"


# La cadence de travail : mesurée, pas choisie. Le serveur reconnaît en ~4 ms ;
# la limite est le codage JPEG et la boucle locale.
CADENCE_ACTIVE = 12
# Assez pour voir une main ENTRER dans le champ — un tiers de seconde — et
# quatre fois moins cher. Dès la première main vue on repasse à la cadence
# pleine, donc cette lenteur ne se paie jamais pendant un geste.
CADENCE_PRETE = 3
# Sur batterie faible, on garde de quoi remarquer une main, et rien de plus.
CADENCE_ECONOMIE = 2

# Au-delà de ce silence sans main, plus rien ne se passe : on veille.
SANS_MAIN_AVANT_VEILLE_S = 3.0
# En dessous, la batterie décide à la place du confort.
BATTERIE_BASSE_PCT = 20


def etat_energie(
    *,
    armee: bool,
    depuis_derniere_main_s: Optional[float],
    sur_batterie: bool = False,
    batterie_pct: Optional[int] = None,
) -> Energie:
    """L'état d'énergie, à partir de ce qui est CONSTATÉ.

    ``depuis_derniere_main_s`` vaut None tant qu'aucune main n'a jamais été
    vue : une session qu'on vient d'armer n'est pas « active », elle attend.
    """
    if not armee:
        return Energie.ETEINT
    if sur_batterie and batterie_pct is not None and batterie_pct <= BATTERIE_BASSE_PCT:
        return Energie.ECONOMIE
    if depuis_derniere_main_s is None:
        return Energie.PRET
    if depuis_derniere_main_s <= SANS_MAIN_AVANT_VEILLE_S:
        return Energie.ACTIF
    return Energie.PRET


def cadence(etat: Energie) -> int:
    """Les images par seconde que l'interface doit appliquer."""
    return {
        Energie.ETEINT: 0,
        Energie.PRET: CADENCE_PRETE,
        Energie.ACTIF: CADENCE_ACTIVE,
        Energie.ECONOMIE: CADENCE_ECONOMIE,
    }[etat]


# `pmset` est un sous-processus : l'appeler à chaque image, douze fois par
# seconde, coûterait bien plus que ce que cet état fait économiser. On le
# relit au plus une fois par demi-minute — une batterie ne se vide pas plus
# vite que ça, et un câble qu'on rebranche est vu au pire trente secondes
# plus tard.
_RELECTURE_BATTERIE_S = 30.0
_batterie_vue: Optional[tuple[float, Optional[tuple[int, bool]]]] = None


def batterie(*, maintenant: Optional[float] = None) -> Optional[tuple[int, bool]]:
    """(pourcentage, sur batterie) — en cache, ou None si illisible."""
    global _batterie_vue
    maintenant = time.monotonic() if maintenant is None else maintenant
    if (
        _batterie_vue is not None
        and maintenant - _batterie_vue[0] < _RELECTURE_BATTERIE_S
    ):
        return _batterie_vue[1]
    try:
        from diapason.heartbeat.tick import lire_batterie

        mesure = lire_batterie()
    except Exception:  # noqa: BLE001 - une machine sans batterie n'est pas en panne
        mesure = None
    _batterie_vue = (maintenant, mesure)
    return mesure


def oublier_la_batterie() -> None:
    """Vider le cache — pour les tests, et pour un réveil de veille."""
    global _batterie_vue
    _batterie_vue = None


__all__ = [
    "BATTERIE_BASSE_PCT",
    "CADENCE_ACTIVE",
    "CADENCE_ECONOMIE",
    "CADENCE_PRETE",
    "SANS_MAIN_AVANT_VEILLE_S",
    "Energie",
    "batterie",
    "cadence",
    "etat_energie",
    "oublier_la_batterie",
]
