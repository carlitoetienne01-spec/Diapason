"""Geste 🤙 (shaka / « call me ») — pouce et auriculaire tendus, autres repliés.

Remplace la capture par pince immobile en bas-centre (30 août 2026).
Vision ne nomme pas les poses : on lit les ratios base→bout, normalisés
par la largeur de la paume, comme dans ``pointeur_main._mesurer``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from diapason.desktop.gestes_main import Point

# Seuils calibrés sur mains réelles le 30 août 2026 : un 🤙 naturel laisse
# souvent majeur/annulaire un peu sortis ; le pouce part de côté et raccourcit
# le ratio thumbCMC. Des valeurs trop serrées ne déclenchaient jamais rien.
_REPLIE_MAX = 1.38
_TENDU_MIN = 1.02
_PINCE_ECART_MIN = 0.30
_CONFIANCE_MIN = 0.25
_CONFIANCE_POUCE_BASE = 0.12

_NOMS_REQUIS = (
    "indexMCP",
    "littleMCP",
    "indexTip",
    "middleMCP",
    "middleTip",
    "ringMCP",
    "ringTip",
    "littleTip",
    "thumbTip",
)


@dataclass(frozen=True, slots=True)
class ScoresShaka:
    """Ratios normalisés — sert au diagnostic et aux tests."""

    index: float
    middle: float
    ring: float
    little: float
    thumb: float
    ecart_pince: float


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def scores_shaka(points: Sequence[Point]) -> Optional[ScoresShaka]:
    """Mesurer la pose, ou ``None`` si les repères manquent."""
    par_nom = {p.nom: p for p in points}
    if any(nom not in par_nom for nom in _NOMS_REQUIS):
        return None
    for nom in _NOMS_REQUIS:
        if par_nom[nom].confiance < _CONFIANCE_MIN:
            return None

    paume = _distance(par_nom["indexMCP"], par_nom["littleMCP"])
    if paume <= 1e-6:
        return None

    def ratio(base: str, bout: str) -> float:
        return _distance(par_nom[base], par_nom[bout]) / paume

    pouce_bases = ("thumbCMC", "thumbMP")
    pouce_longueurs = [
        ratio(base, "thumbTip")
        for base in pouce_bases
        if base in par_nom and par_nom[base].confiance >= _CONFIANCE_POUCE_BASE
    ]
    thumb_r = max(pouce_longueurs) if pouce_longueurs else 0.0

    return ScoresShaka(
        index=ratio("indexMCP", "indexTip"),
        middle=ratio("middleMCP", "middleTip"),
        ring=ratio("ringMCP", "ringTip"),
        little=ratio("littleMCP", "littleTip"),
        thumb=thumb_r,
        ecart_pince=_distance(par_nom["thumbTip"], par_nom["indexTip"]) / paume,
    )


def shaka_geste(points: Sequence[Point]) -> bool:
    """True si la main forme un 🤙 assez net pour cette image."""
    scores = scores_shaka(points)
    if scores is None:
        return False
    if scores.ecart_pince < _PINCE_ECART_MIN:
        return False
    if (
        scores.index > _REPLIE_MAX
        or scores.middle > _REPLIE_MAX
        or scores.ring > _REPLIE_MAX
    ):
        return False
    if scores.little < _TENDU_MIN or scores.thumb < _TENDU_MIN:
        return False
    return True


__all__ = ["ScoresShaka", "scores_shaka", "shaka_geste"]
