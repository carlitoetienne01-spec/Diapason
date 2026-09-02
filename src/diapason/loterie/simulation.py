"""Jouer une grille pendant des années, en quelques secondes.

Un tableau de probabilités ne se sent pas. « Une chance sur 13 348 188 » est un
nombre ; deux tirages par semaine pendant cinquante ans sans jamais rien
toucher de plus que 20 $, ça se voit.

Le tirage simulé est ÉQUITABLE par construction — c'est le résultat du test du
khi-deux sur les 1 030 tirages réels, pas une hypothèse de confort. Simuler
autrement reviendrait à inventer un biais que les données ne montrent pas.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction

from diapason.loterie.lots import PRIX_PARTICIPATION, PROBABILITES, categorie
from diapason.loterie.tirages import (
    GRAND_NUMERO_MAX,
    NUMERO_MAX,
    NUMEROS_PAR_TIRAGE,
)

#: Au-delà, on refuse plutôt que de faire attendre sans le dire.
TIRAGES_MAX = 2_000_000


class GrilleInvalide(ValueError):
    """Une grille qu'on refuse de jouer plutôt que de la corriger en silence."""


def valider_grille(numeros: list[int] | tuple[int, ...], grand: int) -> tuple[int, ...]:
    """Les cinq numéros triés, ou une erreur qui dit laquelle."""
    choisis = tuple(sorted(int(n) for n in numeros))
    if len(choisis) != NUMEROS_PAR_TIRAGE:
        raise GrilleInvalide(
            f"il faut {NUMEROS_PAR_TIRAGE} numéros, pas {len(choisis)}"
        )
    if len(set(choisis)) != NUMEROS_PAR_TIRAGE:
        raise GrilleInvalide("deux fois le même numéro")
    for n in choisis:
        if not 1 <= n <= NUMERO_MAX:
            raise GrilleInvalide(f"le numéro {n} est hors de 1..{NUMERO_MAX}")
    if not 1 <= int(grand) <= GRAND_NUMERO_MAX:
        raise GrilleInvalide(f"le Grand Numéro doit être entre 1 et {GRAND_NUMERO_MAX}")
    return choisis


@dataclass(frozen=True, slots=True)
class Resultat:
    """Ce qu'une vie de jeu a donné, et ce qu'elle aurait dû donner."""

    tirages: int
    depense: int
    gagne: int
    par_categorie: dict[str, int] = field(default_factory=dict)
    esperance: float = 0.0
    """Le gain moyen par participation, calculé — pas simulé.

    On le donne à côté du résultat tiré au sort pour que la comparaison soit
    possible : une simulation est UNE vie, pas la moyenne des vies.
    """

    @property
    def solde(self) -> int:
        return self.gagne - self.depense


def esperance_par_participation() -> float:
    """Le retour moyen d'un billet, en dollars.

    Les deux plus gros lots sont comptés à leur valeur FORFAITAIRE. Une rente
    versée sur des décennies vaut moins que la même somme aujourd'hui, donc ce
    chiffre est un PLAFOND : le retour réel est plus bas.
    """
    total = Fraction(0)
    for (bons, grand), p in PROBABILITES.items():
        lot = categorie(bons, grand)
        if lot is not None:
            total += p * lot.valeur
    return float(total)


def simuler(
    numeros: list[int] | tuple[int, ...],
    grand: int,
    tirages: int,
    graine: int | None = None,
) -> Resultat:
    """Dérouler `tirages` tirages équitables contre cette grille.

    `graine` rend la simulation REPRODUCTIBLE. Sans elle, deux exécutions
    donneraient deux réponses différentes à la même question, et l'on ne
    saurait jamais si un écart vient du hasard ou d'un changement de code.
    """
    choisis = valider_grille(numeros, grand)
    if not 1 <= tirages <= TIRAGES_MAX:
        raise GrilleInvalide(f"le nombre de tirages doit être entre 1 et {TIRAGES_MAX}")
    alea = random.Random(graine)
    ensemble = set(choisis)
    urne = range(1, NUMERO_MAX + 1)
    compte: Counter[str] = Counter()
    gagne = 0
    for _ in range(tirages):
        sortis = alea.sample(urne, NUMEROS_PAR_TIRAGE)
        bons = len(ensemble.intersection(sortis))
        bon_grand = alea.randint(1, GRAND_NUMERO_MAX) == grand
        lot = categorie(bons, bon_grand)
        if lot is not None:
            compte[lot.libelle] += 1
            gagne += lot.valeur
    return Resultat(
        tirages=tirages,
        depense=tirages * PRIX_PARTICIPATION,
        gagne=gagne,
        par_categorie=dict(compte),
        esperance=esperance_par_participation(),
    )
