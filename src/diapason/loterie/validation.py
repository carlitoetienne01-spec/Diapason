"""Confronter la moisson à l'instantané officiel.

C'est ce module qui donne le droit d'afficher quoi que ce soit. Sans lui, tout
le reste reposerait sur la parole d'un site tiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from diapason.loterie import reference
from diapason.loterie.equite import frequences
from diapason.loterie.tirages import NUMEROS_PAR_TIRAGE, Tirage


@dataclass(frozen=True, slots=True)
class Controle:
    """Le verdict, et de quoi le contredire."""

    concordant: bool
    tirages_moissonnes: int
    tirages_attendus: int
    somme_moissonnee: int
    somme_attendue: int
    ecarts: dict[int, tuple[int, int]] = field(default_factory=dict)
    """numéro -> (moissonné, officiel), pour les seuls numéros qui divergent."""
    raison: str = ""


def controler(tirages: list[Tirage]) -> Controle:
    """La moisson redonne-t-elle les chiffres officiels ?

    On ne compare que sur la FENÊTRE de l'instantané : les tirages postérieurs
    au relevé sont exclus, sinon la comparaison échouerait à chaque nouveau
    tirage — et un contrôle qui échoue toujours ne contrôle plus rien.
    """
    fenetre = [
        t
        for t in tirages
        if reference.PREMIER_TIRAGE <= t.jour <= reference.DERNIER_TIRAGE
    ]
    obtenues = frequences(fenetre)
    ecarts = {
        n: (obtenues[n], attendu)
        for n, attendu in reference.FREQUENCES.items()
        if obtenues[n] != attendu
    }
    somme = sum(obtenues.values())
    somme_attendue = NUMEROS_PAR_TIRAGE * reference.TIRAGES
    if len(fenetre) != reference.TIRAGES:
        raison = (
            f"{len(fenetre)} tirages moissonnés sur la fenêtre officielle, "
            f"{reference.TIRAGES} attendus"
        )
    elif ecarts:
        raison = f"{len(ecarts)} numéros ne concordent pas"
    else:
        raison = "chaque numéro concorde avec Loto-Québec"
    return Controle(
        concordant=not ecarts and len(fenetre) == reference.TIRAGES,
        tirages_moissonnes=len(fenetre),
        tirages_attendus=reference.TIRAGES,
        somme_moissonnee=somme,
        somme_attendue=somme_attendue,
        ecarts=ecarts,
        raison=raison,
    )
