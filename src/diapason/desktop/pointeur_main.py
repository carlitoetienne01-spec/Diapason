"""Transformer une main pointée en commandes de pointeur, sans toucher à l'OS.

Le moteur de transfert reconnaît une paume et un poing. Le pointeur a un
vocabulaire différent et vit donc dans une machine séparée : l'index déplace,
le pincement clique, et un pincement maintenu défile. Mélanger les deux ferait
d'un clic raté un dépôt de fichier — une ambiguïté qu'aucun seuil ne peut
rendre acceptable.

Comme ``gestes_main``, ce module ne voit ni caméra ni écran. Il reçoit les
points de Vision et rend une intention pure, testable sans autorisation
Accessibilité et sans déplacer le vrai curseur pendant les tests.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

from diapason.desktop.gestes_main import Point


class ActionPointeur(str, Enum):
    """L'action sur le fil — en anglais comme tout contrat inter-processus."""

    AUCUNE = "NONE"
    DEPLACER = "MOVE"
    CLIQUER = "CLICK"
    DOUBLE_CLIQUER = "DOUBLE_CLICK"
    DEFILER = "SCROLL"


@dataclass(frozen=True, slots=True)
class SeuilsPointeur:
    """Les nombres qui distinguent pointer, pincer et faire défiler."""

    # Vision baisse souvent la confiance des doigts REPLIÉS parce qu'ils se
    # cachent les uns les autres. Exiger 0,6 sur leurs neuf points faisait
    # perdre un index net dès qu'une phalange disparaissait. La position ne
    # dépend donc que de l'index et des deux bases qui mesurent la paume ; les
    # doigts secondaires ne servent qu'à confirmer la pose quand ils sont
    # assez sûrs.
    confiance_index_minimale: float = 0.45
    confiance_pose_minimale: float = 0.25
    confiance_pince_minimale: float = 0.40
    # Sur une vraie main, un doigt replié est autour de 0,85 largeur de
    # paume et un doigt tendu autour de 1,73. Pour acquérir le pointeur,
    # l'index doit dépasser au moins deux autres doigts : cette différence
    # refuse une paume ouverte sans imposer trois doigts parfaitement pliés.
    index_tendu_min: float = 1.30
    index_maintenu_min: float = 1.05
    # Une valeur absolue sur les doigts repliés cassait dès que la main se
    # tournait : la largeur APPARENTE de la paume rétrécit alors que les
    # longueurs mesurées augmentent toutes. Leur différence avec l'index
    # résiste à cette perspective ; 0,18 sépare encore une paume ouverte,
    # où seul l'auriculaire est franchement plus court.
    avantage_index_min: float = 0.18
    autres_replies_requises: int = 2
    autres_ouvertes_min: float = 1.50
    images_pointeur_stable: int = 3
    # Sept images à 24 im/s. Une occlusion plus longue ne ressemble plus à
    # un hoquet de Vision : le verrou est alors réellement abandonné et les
    # trois images d'acquisition redeviennent obligatoires.
    trou_de_suivi_s: float = 0.28
    images_pince_stable: int = 2
    pince_entree: float = 0.38
    pince_sortie: float = 0.55
    clic_max_s: float = 0.32
    double_clic_max_s: float = 0.45
    maintien_defilement_s: float = 0.38
    zone_gauche: float = 0.14
    zone_droite: float = 0.86
    zone_haute: float = 0.10
    zone_basse: float = 0.86
    # Poids de l'ancienne position. À 24 im/s, 0,45 absorbe le tremblement
    # de Vision sans donner au curseur l'impression de poursuivre la main.
    lissage: float = 0.45
    seuil_defilement: float = 0.012
    lignes_par_image: float = 120.0
    lignes_max: int = 10


@dataclass(frozen=True, slots=True)
class LecturePointeur:
    """Ce que l'interface doit appliquer — ou ne surtout pas appliquer."""

    actif: bool
    action: ActionPointeur = ActionPointeur.AUCUNE
    x: Optional[float] = None
    y: Optional[float] = None
    defilement_y: int = 0
    pince: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "active": self.actif,
            "action": self.action.value,
            "x": self.x,
            "y": self.y,
            "scrollY": self.defilement_y,
            "pinching": self.pince,
        }


@dataclass(frozen=True, slots=True)
class _MesurePointeur:
    x: float
    y: float
    pince: float
    index: float
    autres: tuple[float, float, float]
    confiances_autres: tuple[float, float, float]
    confiance_index: float
    confiance_pince: float


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _mesurer(points: Sequence[Point]) -> Optional[_MesurePointeur]:
    par_nom = {point.nom: point for point in points}
    noms_position = ("indexMCP", "indexTip", "littleMCP")
    if any(nom not in par_nom for nom in noms_position):
        return None
    index_base = par_nom["indexMCP"]
    auriculaire_base = par_nom["littleMCP"]
    paume = _distance(index_base, auriculaire_base)
    if paume <= 1e-6:
        return None
    index = par_nom["indexTip"]
    autres: list[float] = []
    confiances_autres: list[float] = []
    for doigt in ("middle", "ring", "little"):
        base = par_nom.get(f"{doigt}MCP")
        bout = par_nom.get(f"{doigt}Tip")
        if base is None or bout is None:
            autres.append(float("inf"))
            confiances_autres.append(0.0)
            continue
        autres.append(_distance(base, bout) / paume)
        confiances_autres.append(min(base.confiance, bout.confiance))
    pouce = par_nom.get("thumbTip")
    return _MesurePointeur(
        x=index.x,
        y=index.y,
        pince=_distance(pouce, index) / paume if pouce is not None else float("inf"),
        index=_distance(index_base, index) / paume,
        autres=tuple(autres),
        confiances_autres=tuple(confiances_autres),
        confiance_index=min(
            index_base.confiance,
            index.confiance,
            auriculaire_base.confiance,
        ),
        confiance_pince=(
            min(index.confiance, pouce.confiance) if pouce is not None else 0.0
        ),
    )


def _ramener(valeur: float, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        return 0.5
    return max(0.0, min(1.0, (valeur - minimum) / (maximum - minimum)))


class MoteurDePointeur:
    """Suivre un index et confirmer les actions dans le temps."""

    def __init__(self, seuils: Optional[SeuilsPointeur] = None) -> None:
        self.seuils = seuils or SeuilsPointeur()
        self._images_pointeur = 0
        self._x_lisse: Optional[float] = None
        self._y_lisse: Optional[float] = None
        self._pince = False
        self._images_pince = 0
        self._pince_a = 0.0
        self._defile = False
        self._dernier_y_defilement: Optional[float] = None
        self._dernier_clic_a: Optional[float] = None
        self._perdu_depuis: Optional[float] = None

    def reinitialiser(self) -> None:
        """Oublier une main perdue sans transformer sa disparition en clic."""
        self._images_pointeur = 0
        self._x_lisse = None
        self._y_lisse = None
        self._pince = False
        self._images_pince = 0
        self._pince_a = 0.0
        self._defile = False
        self._dernier_y_defilement = None
        self._dernier_clic_a = None
        self._perdu_depuis = None

    def _annuler_pincement(self) -> None:
        """Une mesure douteuse interrompt l'action sans simuler un relâchement."""
        self._pince = False
        self._images_pince = 0
        self._pince_a = 0.0
        self._defile = False
        self._dernier_y_defilement = None

    def _pose_d_acquisition(self, mesure: _MesurePointeur) -> bool:
        """Exiger un index dominant avant de prendre le contrôle."""
        s = self.seuils
        if (
            mesure.confiance_index < s.confiance_index_minimale
            or mesure.index < s.index_tendu_min
        ):
            return False
        replies = sum(
            confiance >= s.confiance_pose_minimale
            and mesure.index - ratio >= s.avantage_index_min
            for ratio, confiance in zip(
                mesure.autres, mesure.confiances_autres, strict=True
            )
        )
        return replies >= s.autres_replies_requises

    def _pose_de_maintien(self, mesure: _MesurePointeur) -> bool:
        """Tolérer un doigt secondaire incertain, mais jamais une paume nette."""
        s = self.seuils
        if (
            mesure.confiance_index < s.confiance_index_minimale * 0.7
            or mesure.index < s.index_maintenu_min
        ):
            return False
        autres_ouverts = sum(
            confiance >= s.confiance_pose_minimale
            and ratio >= s.autres_ouvertes_min
            and ratio >= mesure.index - s.avantage_index_min
            for ratio, confiance in zip(
                mesure.autres, mesure.confiances_autres, strict=True
            )
        )
        return autres_ouverts < 2

    def _sans_pointeur(self, maintenant: float) -> LecturePointeur:
        """Traverser une brève occlusion sans garder une action armée."""
        acquis = self._images_pointeur >= self.seuils.images_pointeur_stable
        self._annuler_pincement()
        # Une discontinuité visuelle sépare aussi deux clics : le second ne
        # doit jamais devenir un double-clic sur la base d'une main perdue.
        self._dernier_clic_a = None
        if not acquis:
            self.reinitialiser()
        else:
            if self._perdu_depuis is None:
                self._perdu_depuis = maintenant
            elif maintenant - self._perdu_depuis >= self.seuils.trou_de_suivi_s:
                self.reinitialiser()
        return LecturePointeur(
            actif=False,
            x=self._x_lisse,
            y=self._y_lisse,
        )

    def _position(self, mesure: _MesurePointeur) -> tuple[float, float]:
        s = self.seuils
        # La caméra frontale agit comme un miroir : la droite de la main doit
        # rester la droite de l'écran. Les marges rendent les quatre bords
        # atteignables sans devoir sortir l'index du champ.
        x = _ramener(1.0 - mesure.x, s.zone_gauche, s.zone_droite)
        y = _ramener(mesure.y, s.zone_haute, s.zone_basse)
        if self._x_lisse is None or self._y_lisse is None:
            self._x_lisse, self._y_lisse = x, y
        else:
            a = s.lissage
            self._x_lisse = a * self._x_lisse + (1.0 - a) * x
            self._y_lisse = a * self._y_lisse + (1.0 - a) * y
        return self._x_lisse, self._y_lisse

    def observer(
        self,
        points: Optional[Sequence[Point]],
        *,
        maintenant: Optional[float] = None,
    ) -> LecturePointeur:
        """Rendre l'intention de cette image après confirmation temporelle."""
        maintenant = time.monotonic() if maintenant is None else maintenant
        mesure = _mesurer(points or ())
        s = self.seuils
        acquis = self._images_pointeur >= s.images_pointeur_stable
        pointe = mesure is not None and (
            self._pose_d_acquisition(mesure)
            or (acquis and self._pose_de_maintien(mesure))
        )
        if not pointe or mesure is None:
            return self._sans_pointeur(maintenant)

        self._perdu_depuis = None
        if not acquis:
            self._images_pointeur += 1
        x, y = self._position(mesure)
        if self._images_pointeur < s.images_pointeur_stable:
            return LecturePointeur(actif=False, x=x, y=y)

        if mesure.confiance_pince < s.confiance_pince_minimale:
            # Une disparition du pouce n'est ni un contact ni un relâchement.
            # Annuler évite qu'il réapparaisse en déclenchant un clic fantôme.
            self._annuler_pincement()
            return LecturePointeur(
                actif=True,
                action=ActionPointeur.DEPLACER,
                x=x,
                y=y,
            )

        pince_maintenant = mesure.pince <= (
            s.pince_sortie if self._pince else s.pince_entree
        )
        if pince_maintenant:
            if not self._pince:
                self._pince = True
                self._images_pince = 1
                self._pince_a = maintenant
                self._dernier_y_defilement = y
            else:
                self._images_pince += 1

            if maintenant - self._pince_a >= s.maintien_defilement_s:
                self._defile = True
                ancien_y = self._dernier_y_defilement
                self._dernier_y_defilement = y
                if ancien_y is not None:
                    deplacement = y - ancien_y
                    if abs(deplacement) >= s.seuil_defilement:
                        lignes = round(-deplacement * s.lignes_par_image)
                        if lignes == 0:
                            lignes = -1 if deplacement > 0 else 1
                        lignes = max(-s.lignes_max, min(s.lignes_max, lignes))
                        return LecturePointeur(
                            actif=True,
                            action=ActionPointeur.DEFILER,
                            x=x,
                            y=y,
                            defilement_y=lignes,
                            pince=True,
                        )
                return LecturePointeur(actif=True, x=x, y=y, pince=True)

            return LecturePointeur(
                actif=True,
                action=ActionPointeur.DEPLACER,
                x=x,
                y=y,
                pince=True,
            )

        if self._pince:
            duree = maintenant - self._pince_a
            images = self._images_pince
            defilait = self._defile
            self._pince = False
            self._images_pince = 0
            self._defile = False
            self._dernier_y_defilement = None
            if (
                not defilait
                and images >= s.images_pince_stable
                and duree <= s.clic_max_s
            ):
                double = bool(
                    self._dernier_clic_a is not None
                    and maintenant - self._dernier_clic_a <= s.double_clic_max_s
                )
                self._dernier_clic_a = None if double else maintenant
                return LecturePointeur(
                    actif=True,
                    action=(
                        ActionPointeur.DOUBLE_CLIQUER
                        if double
                        else ActionPointeur.CLIQUER
                    ),
                    x=x,
                    y=y,
                )

        return LecturePointeur(
            actif=True,
            action=ActionPointeur.DEPLACER,
            x=x,
            y=y,
        )


__all__ = [
    "ActionPointeur",
    "LecturePointeur",
    "MoteurDePointeur",
    "SeuilsPointeur",
]
