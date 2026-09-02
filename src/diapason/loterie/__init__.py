"""La Grande Vie — ce que les tirages passés disent, et ce qu'ils ne disent pas.

Ce module existe pour répondre à une question précise, posée le 31 août 2026 :
« est-il possible d'avoir des chiffres fiables à jouer ? »

La réponse est non, et ce module la DÉMONTRE au lieu de l'affirmer. Il moissonne
l'historique complet, le confronte aux statistiques publiées par Loto-Québec,
puis teste l'équité du tirage. Il ne recommande aucun numéro : sur 1 030
tirages, le test du khi-deux rend p ≈ 0,79, c'est-à-dire un tirage parfaitement
équitable, où aucune combinaison n'est plus probable qu'une autre.

Le simulateur, lui, sert à voir ce que « une chance sur 13 348 188 » veut dire
quand on joue toute une vie.
"""

from diapason.loterie.tirages import (
    COMBINAISONS,
    GRAND_NUMERO_MAX,
    NUMERO_MAX,
    NUMEROS_PAR_TIRAGE,
    Tirage,
    analyser_page,
)

_Tirage = Tirage
_analyser_page = analyser_page
_COMBINAISONS = COMBINAISONS
_NUMERO_MAX = NUMERO_MAX
_GRAND_NUMERO_MAX = GRAND_NUMERO_MAX
_NUMEROS_PAR_TIRAGE = NUMEROS_PAR_TIRAGE

__all__ = [
    "COMBINAISONS",
    "GRAND_NUMERO_MAX",
    "NUMEROS_PAR_TIRAGE",
    "NUMERO_MAX",
    "Tirage",
    "analyser_page",
]
