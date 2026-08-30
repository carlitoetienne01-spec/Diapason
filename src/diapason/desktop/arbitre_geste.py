"""Choisir le vocabulaire d'une main, sans exécuter l'action.

Les deux moteurs restent séparés : un pincement ne doit jamais envoyer un
fichier, un poing ne doit jamais cliquer. Cet arbitre ne fait qu'une chose
— dire LEQUEL des deux a la main — après confirmation temporelle (§11).

Mélanger les actions dans un seul seuil, c'est ce qui a déjà fait rater
les poings le 25 août (PINCE classée avant le poing). Ici le contact
pouce-index force le pointeur, et un objet déjà tenu force le transfert.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

from diapason.desktop.gestes_main import Point, Seuils, mesurer
from diapason.desktop.pointeur_main import SeuilsPointeur, _mesurer
from diapason.desktop.shaka_main import shaka_geste


class Vocabulaire(str, Enum):
    """Ce qui circule sur le fil — les mêmes noms que le mode verrouillé."""

    TRANSFERT = "TRANSFER"
    POINTEUR = "POINTER"
    INCONNU = "NONE"


@dataclass(frozen=True, slots=True)
class SeuilsArbitre:
    # Trois images à 12 im/s : 250 ms. Une seule silhouette d'index ne
    # doit pas voler un poing déjà en cours de fermeture.
    images_stables: int = 3


def _index_acquiert(points: Sequence[Point], seuils: SeuilsPointeur) -> bool:
    mesure = _mesurer(points)
    if mesure is None:
        return False
    if (
        mesure.confiance_index < seuils.confiance_index_minimale
        or mesure.index < seuils.index_tendu_min
    ):
        return False
    replies = sum(
        confiance >= seuils.confiance_pose_minimale
        and mesure.index - ratio >= seuils.avantage_index_min
        for ratio, confiance in zip(
            mesure.autres, mesure.confiances_autres, strict=True
        )
    )
    return replies >= seuils.autres_replies_requises


def _index_maintient(points: Sequence[Point], seuils: SeuilsPointeur) -> bool:
    mesure = _mesurer(points)
    if mesure is None:
        return False
    pince_possible = bool(
        mesure.confiance_pince >= seuils.confiance_pince_minimale * 0.7
        and mesure.pince <= seuils.pince_lointaine
    )
    index_minimum = (
        seuils.index_pince_maintenu_min if pince_possible else seuils.index_maintenu_min
    )
    if (
        mesure.confiance_index < seuils.confiance_index_minimale * 0.7
        or mesure.index < index_minimum
    ):
        return False
    autres_ouverts = sum(
        confiance >= seuils.confiance_pose_minimale
        and ratio >= seuils.autres_ouvertes_min
        and ratio >= mesure.index - seuils.avantage_index_min
        for ratio, confiance in zip(
            mesure.autres, mesure.confiances_autres, strict=True
        )
    )
    return autres_ouverts < 2


def _transfert_clair(points: Sequence[Point], seuils: Seuils) -> bool:
    mesures = mesurer(points)
    if mesures is None or mesures.confiance < seuils.confiance_minimale * 0.7:
        return False
    return (
        mesures.repliement <= seuils.fermeture_entree
        or mesures.repliement >= seuils.ouverture_entree
    )


def _paume_ouverte(points: Sequence[Point], seuils: Seuils) -> bool:
    """Paume ouverte seule — pas le poing.

    En pointeur, ce geste sert au retournement (changer d'app). Sans cette
    distinction, l'ouverture basculait en transfert et le flip n'existait
    jamais (29 août 2026).
    """
    mesures = mesurer(points)
    if mesures is None or mesures.confiance < seuils.confiance_minimale * 0.7:
        return False
    return mesures.repliement >= seuils.ouverture_entree


class ArbitreDeGeste:
    """Confirmer un vocabulaire avant de le livrer aux moteurs."""

    def __init__(self, seuils: Optional[SeuilsArbitre] = None) -> None:
        self.seuils = seuils or SeuilsArbitre()
        self._vocabulaire = Vocabulaire.INCONNU
        self._candidat = Vocabulaire.INCONNU
        self._images = 0

    def reinitialiser(self) -> None:
        self._vocabulaire = Vocabulaire.INCONNU
        self._candidat = Vocabulaire.INCONNU
        self._images = 0

    def observer(
        self,
        points: Optional[Sequence[Point]],
        *,
        tenu: bool = False,
        depot_en_attente: bool = False,
        pince_confirmee: bool = False,
    ) -> Vocabulaire:
        """Rendre le vocabulaire confirmé, ou le précédent s'il n'y en a pas."""
        if tenu or depot_en_attente:
            self._vocabulaire = Vocabulaire.TRANSFERT
            self._candidat = Vocabulaire.TRANSFERT
            self._images = 0
            return self._vocabulaire
        if pince_confirmee and self._vocabulaire is Vocabulaire.POINTEUR:
            return self._vocabulaire

        voulu = self._lire(points or ())
        if voulu is Vocabulaire.INCONNU:
            return (
                self._vocabulaire
                if self._vocabulaire is not Vocabulaire.INCONNU
                else Vocabulaire.TRANSFERT
            )
        if voulu is self._vocabulaire:
            self._candidat = voulu
            self._images = 0
            return self._vocabulaire
        if voulu is self._candidat:
            self._images += 1
        else:
            self._candidat = voulu
            self._images = 1
        if self._images >= self.seuils.images_stables:
            self._vocabulaire = voulu
            self._images = 0
        if self._vocabulaire is Vocabulaire.INCONNU:
            return Vocabulaire.TRANSFERT
        return self._vocabulaire

    def _lire(self, points: Sequence[Point]) -> Vocabulaire:
        if not points:
            return Vocabulaire.INCONNU
        pointeur = SeuilsPointeur()
        transfert = Seuils()
        if self._vocabulaire is Vocabulaire.POINTEUR and (
            _index_maintient(points, pointeur)
            or _paume_ouverte(points, transfert)
            or shaka_geste(points)
        ):
            return Vocabulaire.POINTEUR
        if _index_acquiert(points, pointeur) or shaka_geste(points):
            return Vocabulaire.POINTEUR
        if _transfert_clair(points, transfert):
            return Vocabulaire.TRANSFERT
        return Vocabulaire.INCONNU


__all__ = ["ArbitreDeGeste", "SeuilsArbitre", "Vocabulaire"]
