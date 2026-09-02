"""La table des lots de la Grande Vie, et la catégorie d'une grille.

Les cotes ne sont PAS recopiées : elles sont recalculées ici, et confrontées à
celles que publie le jeu. Sept des neuf tombent au chiffre près. Les deux
autres écarts sont instructifs et documentés plus bas — ils ne sont pas des
erreurs, mais deux façons différentes de compter, et il fallait savoir
laquelle ce module applique.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import comb

from diapason.loterie.tirages import (
    GRAND_NUMERO_MAX,
    NUMERO_MAX,
    NUMEROS_PAR_TIRAGE,
)

#: Le prix d'une participation, en dollars.
PRIX_PARTICIPATION = 3


@dataclass(frozen=True, slots=True)
class Lot:
    """Une catégorie gagnante : ce qu'il faut, ce qu'on touche."""

    bons: int
    """Combien de numéros réguliers justes."""
    grand: bool
    """Le Grand Numéro est-il juste ?"""
    libelle: str
    valeur: int
    """La valeur en dollars retenue pour les calculs.

    Pour les deux plus gros lots, c'est le montant FORFAITAIRE — la rente est
    une promesse étalée sur des décennies, et l'additionner à un billet de 20 $
    n'aurait aucun sens. Le libellé, lui, dit la rente.
    """


def _probabilite(bons: int, grand: bool) -> Fraction:
    """La probabilité EXACTE d'une catégorie, en fraction — jamais en flottant.

    `comb` et `Fraction` donnent le chiffre juste ; un flottant intermédiaire
    ferait dériver la dernière décimale, et c'est précisément la décimale qu'on
    veut pouvoir comparer aux cotes publiées.
    """
    reste = NUMERO_MAX - NUMEROS_PAR_TIRAGE
    numeros = Fraction(
        comb(NUMEROS_PAR_TIRAGE, bons) * comb(reste, NUMEROS_PAR_TIRAGE - bons),
        comb(NUMERO_MAX, NUMEROS_PAR_TIRAGE),
    )
    part = (
        Fraction(1, GRAND_NUMERO_MAX)
        if grand
        else Fraction(GRAND_NUMERO_MAX - 1, GRAND_NUMERO_MAX)
    )
    return numeros * part


#: La table, du plus gros au plus petit.
#:
#: DEUX ÉCARTS AVEC LES COTES PUBLIÉES, tous deux compris et assumés :
#:
#:   1 numéro + GN   publié « 1 sur 20 »   calculé 1 sur 19,67   → arrondi.
#:   GN seul         publié « 1 sur 7 »    calculé 1 sur 12,29   → deux mesures
#:                   différentes. « 1 sur 7 » est la cote de TROUVER le Grand
#:                   Numéro, quel que soit le reste de la grille ; 1 sur 12,29
#:                   est celle de gagner CE lot-là, c'est-à-dire le Grand
#:                   Numéro ET aucun numéro régulier. Ce module compte les
#:                   catégories, donc il retient 12,29 — sans quoi la somme des
#:                   probabilités dépasserait 1.
TABLE = (
    Lot(5, True, "1 000 $ par jour à vie (7 M$ forfaitaires)", 7_000_000),
    Lot(5, False, "25 000 $ par année à vie (500 000 $ forfaitaires)", 500_000),
    Lot(4, True, "1 000 $", 1_000),
    Lot(4, False, "500 $", 500),
    Lot(3, True, "100 $", 100),
    Lot(3, False, "20 $", 20),
    Lot(2, True, "10 $", 10),
    Lot(1, True, "4 $", 4),
    Lot(0, True, "une participation gratuite", PRIX_PARTICIPATION),
)

#: La probabilité de chaque catégorie, calculée une fois.
PROBABILITES = {
    (lot.bons, lot.grand): _probabilite(lot.bons, lot.grand) for lot in TABLE
}


def categorie(bons: int, grand: bool) -> Lot | None:
    """Le lot correspondant, ou `None` — la plupart des grilles ne gagnent rien.

    Rendre `None` plutôt qu'un lot à zéro dollar : une grille perdante n'est pas
    une catégorie gagnante de valeur nulle, et les compter ensemble ferait dire
    « vous avez gagné 0 $ » à un billet qui n'a rien gagné du tout.
    """
    for lot in TABLE:
        if lot.bons == bons and lot.grand == grand:
            return lot
    return None


def probabilite_de_gagner() -> Fraction:
    """La probabilité de toucher QUELQUE CHOSE, si petit soit-il."""
    return sum(PROBABILITES.values(), Fraction(0))
