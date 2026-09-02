"""L'instantané officiel qui sert de juge.

Le site d'archives est un TIERS. On ne lui fait pas confiance : on le vérifie.
Loto-Québec publie sa propre table de fréquences ; si la moisson la redonne au
chiffre près, le jeu de données est démontré correct. Une divergence, et l'on
sait que la source est mauvaise — sans avoir à croire qui que ce soit.

Cet instantané est DATÉ, et c'est essentiel : il vieillit à chaque tirage. La
comparaison ne vaut que sur la fenêtre qu'il couvre, et le code le vérifie.
"""

from __future__ import annotations

from datetime import date

#: Relevé le 31 août 2026 sur la page « Statistiques » de la Grande Vie.
#: https://loteries.lotoquebec.com/fr/loteries/grande-vie-resultats?outil=statistiques-239
SOURCE = "Loto-Québec, page « Statistiques » de la Grande Vie"
RELEVE_LE = date(2026, 8, 31)
PREMIER_TIRAGE = date(2016, 10, 20)
DERNIER_TIRAGE = date(2026, 8, 31)
TIRAGES = 1030

#: Sorties de chaque numéro sur les 1 030 tirages ci-dessus.
FREQUENCES = {
    1: 113,
    2: 117,
    3: 98,
    4: 110,
    5: 113,
    6: 113,
    7: 120,
    8: 100,
    9: 88,
    10: 94,
    11: 100,
    12: 103,
    13: 107,
    14: 122,
    15: 99,
    16: 91,
    17: 116,
    18: 102,
    19: 100,
    20: 91,
    21: 100,
    22: 94,
    23: 102,
    24: 102,
    25: 110,
    26: 91,
    27: 112,
    28: 103,
    29: 97,
    30: 100,
    31: 107,
    32: 105,
    33: 108,
    34: 109,
    35: 108,
    36: 95,
    37: 123,
    38: 107,
    39: 111,
    40: 81,
    41: 101,
    42: 120,
    43: 117,
    44: 106,
    45: 111,
    46: 111,
    47: 114,
    48: 110,
    49: 98,
}
