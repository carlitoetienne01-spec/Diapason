"""Langue de la voix : détecter, basculer, prononcer.

Les noms suivent les rôles demandés le 29/09/2026 :

- détection : ``detecter``
- consignes kreyòl, français, anglais : ``consigne_kreyol`` et les deux autres
- prononciation : ``forme_orale`` (le guide phonétique) et ``vitesse``
- bascule et mémoire : ``basculer``, ``MemoireLinguistique``
"""

from __future__ import annotations

from diapason.speech.langues.consignes import (
    CONSIGNE_PERMANENTE,
    INVITE_OREILLE,
    consigne_anglais,
    consigne_francais,
    consigne_kreyol,
    consigne_pour,
)
from diapason.speech.langues.detection import (
    Detection,
    MemoireLinguistique,
    detecter,
)
from diapason.speech.langues.phonetique import (
    GUIDE_PHONETIQUE,
    forme_ecrite,
    forme_orale,
    vitesse,
)


def basculer(
    texte: str, memoire: MemoireLinguistique
) -> tuple[Detection, MemoireLinguistique, str]:
    """Un tour : la langue, la mémoire suivante, la consigne à injecter."""
    vu = detecter(texte, memoire)
    suivante = memoire.noter(vu.code) if vu.certaine else memoire
    return vu, suivante, consigne_pour(vu.code)


__all__ = [
    "CONSIGNE_PERMANENTE",
    "GUIDE_PHONETIQUE",
    "INVITE_OREILLE",
    "Detection",
    "MemoireLinguistique",
    "basculer",
    "consigne_anglais",
    "consigne_francais",
    "consigne_kreyol",
    "consigne_pour",
    "detecter",
    "forme_ecrite",
    "forme_orale",
    "vitesse",
]
