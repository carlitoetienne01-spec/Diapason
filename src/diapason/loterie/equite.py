"""Le tirage est-il équitable ? La question a une réponse, et elle se calcule.

C'est le cœur honnête de ce module. Si le test dit « équitable », alors aucun
numéro n'est fiable — et on le SAIT, au lieu de le croire.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from statistics import NormalDist
from typing import Iterable

from diapason.loterie.tirages import NUMERO_MAX, NUMEROS_PAR_TIRAGE, Tirage


def frequences(tirages: Iterable[Tirage]) -> dict[int, int]:
    """Combien de fois chaque numéro est sorti. Les 49 sont présents, même à 0."""
    compte: Counter[int] = Counter()
    for tirage in tirages:
        compte.update(tirage.numeros)
    return {n: compte.get(n, 0) for n in range(1, NUMERO_MAX + 1)}


@dataclass(frozen=True, slots=True)
class Verdict:
    """Ce que dit le test, avec de quoi le contredire."""

    tirages: int
    attendu: float
    """Sorties attendues par numéro si le tirage est équitable."""
    ecart_type: float
    khi2: float
    degres: int
    valeur_p: float
    plus_frequent: tuple[int, int]
    moins_frequent: tuple[int, int]
    ecart_max_attendu: float
    """L'écart-type du plus extrême des 49, par pur hasard.

    C'est le chiffre qui désarme l'idée de « numéro chaud » : sur 49 numéros
    équitables, le plus sorti l'est TOUJOURS d'environ deux écarts-types. Le
    voir ne prouve donc rien.
    """

    @property
    def equitable(self) -> bool:
        """Au seuil usuel de 5 %.

        Un `False` ne prouverait pas une fraude : il dirait qu'il faut
        regarder. Avec 49 catégories, un tirage parfait sort sous 5 % une fois
        sur vingt.
        """
        return self.valeur_p >= 0.05


def _survie_khi2(khi2: float, degres: int) -> float:
    """P(X > khi2) pour une loi du khi-deux.

    Approximation de Wilson-Hilferty : elle est excellente au-delà de trente
    degrés de liberté, et nous en avons quarante-huit. Elle évite d'ajouter
    SciPy — six cents mégaoctets pour une fonction — à un projet qui tient à
    tourner sur une machine.
    """
    if degres <= 0:
        return float("nan")
    if khi2 <= 0:
        return 1.0
    t = 2.0 / (9.0 * degres)
    z = ((khi2 / degres) ** (1 / 3) - (1 - t)) / math.sqrt(t)
    return 1.0 - NormalDist().cdf(z)


def examiner(tirages: list[Tirage]) -> Verdict | None:
    """Le test du khi-deux sur la fréquence des 49 numéros.

    Nommée `examiner` et non `tester` : pytest ramasse TOUTE fonction dont le
    nom commence par « test », y compris importée depuis un module de
    production. `tester` se faisait collecter comme un cas de test et réclamait
    une fixture nommée « tirages ».

    `None` en dessous de cent tirages : le test existerait encore, mais il ne
    saurait rien distinguer, et annoncer « équitable » sur vingt tirages serait
    exactement la fausse assurance que ce module combat.
    """
    if len(tirages) < 100:
        return None
    freq = frequences(tirages)
    n = len(tirages)
    attendu = NUMEROS_PAR_TIRAGE * n / NUMERO_MAX
    p = NUMEROS_PAR_TIRAGE / NUMERO_MAX
    ecart_type = math.sqrt(n * p * (1 - p))
    khi2 = sum((o - attendu) ** 2 / attendu for o in freq.values())
    degres = NUMERO_MAX - 1
    haut = max(freq.items(), key=lambda kv: kv[1])
    bas = min(freq.items(), key=lambda kv: kv[1])
    # L'écart-type du maximum de 49 tirages indépendants, approché par le
    # quantile 1 - 1/(n+1) : c'est la valeur qu'un « numéro chaud » atteint
    # sans qu'aucune machine ne soit biaisée.
    ecart_max = NormalDist().inv_cdf(1 - 1 / (NUMERO_MAX + 1))
    return Verdict(
        tirages=n,
        attendu=attendu,
        ecart_type=ecart_type,
        khi2=khi2,
        degres=degres,
        valeur_p=_survie_khi2(khi2, degres),
        plus_frequent=haut,
        moins_frequent=bas,
        ecart_max_attendu=ecart_max,
    )
