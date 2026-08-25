"""Le moteur de gestes : des points articulaires à une intention.

Spatial Mesh, gestes — 25 août 2026. Ce module ne voit pas, ne capture rien
et ne parle à personne : il reçoit vingt-et-un points par main et rend un
état. C'est délibéré — la fiabilité d'un geste se joue ici, pas dans la
caméra, et elle doit se tester sans matériel.

Le §11 du cahier des charges est la règle qui structure tout : **ne jamais
déclencher une action depuis une seule image**. Une main qui passe devant
l'objectif produit, pendant deux ou trois images, quelque chose qui
ressemble à un poing. C'est ainsi qu'un document part tout seul.

D'où la chaîne : points bruts → normalisation → lissage → mesures →
pose → état temporel. Et deux protections que l'expérience impose :

**L'hystérésis.** Le seuil pour ENTRER dans un état est plus exigeant que
celui pour en SORTIR. Sans cela, une main qui hésite à la frontière fait
osciller l'état dix fois par seconde.

**Le temps de repos.** Après un geste reconnu, un délai pendant lequel
rien n'est reconnu. Sans lui, ouvrir la main après un « attraper »
déclenche immédiatement un « relâcher », puis l'inverse.

Les seuils ne sont pas dispersés dans le code : ils vivent dans un objet,
et ils se règlent (§13).
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

# ── Les vingt-et-un points, dans l'ordre où Vision les rend ──────────────
POIGNET = "wrist"
_DOIGTS = ("thumb", "index", "middle", "ring", "little")
# Pour chaque doigt : sa base, ses articulations, son bout.
_ARTICULATIONS = {
    "thumb": ("thumbCMC", "thumbMP", "thumbIP", "thumbTip"),
    "index": ("indexMCP", "indexPIP", "indexDIP", "indexTip"),
    "middle": ("middleMCP", "middlePIP", "middleDIP", "middleTip"),
    "ring": ("ringMCP", "ringPIP", "ringDIP", "ringTip"),
    "little": ("littleMCP", "littlePIP", "littleDIP", "littleTip"),
}


class Pose(str, Enum):
    """Ce qu'une main FAIT sur une image donnée — sans mémoire."""

    INCONNUE = "INCONNUE"
    PAUME_OUVERTE = "PAUME_OUVERTE"
    POING = "POING"
    PINCE = "PINCE"
    POINTE = "POINTE"


class Etat(str, Enum):
    """Ce que l'utilisateur est en train de faire — avec mémoire (§12)."""

    REPOS = "REPOS"
    MAIN_VUE = "MAIN_VUE"
    PAUME_STABLE = "PAUME_STABLE"
    FERMETURE = "FERMETURE"
    SAISI = "SAISI"
    RELACHEMENT = "RELACHEMENT"
    RELACHE = "RELACHE"
    PERDU = "PERDU"
    ANNULE = "ANNULE"


@dataclass(frozen=True, slots=True)
class Seuils:
    """Tous les nombres qui décident, en un seul endroit (§13).

    Aucun de ces nombres n'est magique : ce sont des points de départ
    raisonnables, à régler sur des vraies mains — et le §141 exige que les
    faux positifs soient MESURÉS avant de dire que les gestes sont finis.
    """

    # Sur le MINIMUM des points, pas leur moyenne : une main fantôme a
    # toujours quelques points sûrs. 0,6 écarte le bruit sans exiger un
    # éclairage de studio.
    confiance_minimale: float = 0.6
    # Une main est « fermée » quand ses doigts sont repliés sous ce ratio de
    # leur longueur déployée ; « ouverte » au-dessus. L'écart entre les deux
    # est l'hystérésis : sans lui, la frontière fait osciller l'état.
    # Échelle du repliement local : ~0,3 poing serré, ~1,0 main tendue.
    # L'écart entre entrée et sortie est l'hystérésis.
    fermeture_entree: float = 0.50
    fermeture_sortie: float = 0.62
    ouverture_entree: float = 0.72
    ouverture_sortie: float = 0.60
    # Une pince : pouce et index qui se touchent, mesuré en fraction de la
    # largeur de la paume — donc indépendant de la distance à l'objectif.
    pince_entree: float = 0.35
    pince_sortie: float = 0.50
    # Images consécutives à confirmer avant de croire une pose (§11).
    images_stables: int = 4
    # Au-delà, la main est perdue : mieux vaut annuler que deviner.
    trou_de_suivi_ms: int = 400
    # Après un geste reconnu, le temps pendant lequel rien n'est reconnu.
    repos_ms: int = 800
    # Lissage exponentiel : 0 = pas de lissage, 1 = rien ne bouge jamais.
    # Ce nombre COÛTE : mesuré le 25 août 2026, un lissage de 0,5 demandait
    # huit images pour reconnaître un poing — plus d'une demi-seconde à
    # quinze images par seconde. 0,4 en demande six, sans laisser passer les
    # mains qui traversent le champ. Le test de latence garde ce compromis.
    lissage: float = 0.4


@dataclass(frozen=True, slots=True)
class Point:
    nom: str
    x: float
    y: float
    confiance: float = 1.0


@dataclass(frozen=True, slots=True)
class Mesures:
    """Ce qu'on lit d'une main, indépendamment de sa taille et sa distance."""

    repliement: float  # 0 = poing serré, 1 = main grande ouverte
    pince: float  # distance pouce-index, en largeurs de paume
    confiance: float
    doigts_tendus: int


def _point(points: dict[str, Point], nom: str) -> Optional[Point]:
    p = points.get(nom)
    return p if p is not None else None


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def mesurer(points: Sequence[Point]) -> Optional[Mesures]:
    """Les mesures d'une main, ou None si elle est trop incomplète.

    Tout est rapporté à la largeur de la paume : une main près de
    l'objectif et une main au fond de la pièce donnent les mêmes nombres.
    C'est ce qui rend les seuils tenables sans calibration par utilisateur.
    """
    par_nom = {p.nom: p for p in points}
    poignet = _point(par_nom, POIGNET)
    if poignet is None:
        return None

    # La largeur de la paume : de la base de l'index à celle de l'auriculaire.
    base_index = _point(par_nom, "indexMCP")
    base_auriculaire = _point(par_nom, "littleMCP")
    if base_index is None or base_auriculaire is None:
        return None
    paume = _distance(base_index, base_auriculaire)
    if paume <= 1e-6:
        return None

    replis: list[float] = []
    tendus = 0
    # La confiance retenue est le MINIMUM, pas la moyenne. Constaté le
    # 25 août 2026 : Vision rend des « mains » dans du bruit — un visage,
    # une ombre, un objet — avec quelques points sûrs et beaucoup de points
    # douteux. Une moyenne tirée vers le haut par le poignet laissait
    # passer ces mains fantômes, qui déposaient des choses toutes seules.
    # Un seul point douteux rend la décision douteuse.
    confiances: list[float] = [poignet.confiance]
    for doigt in _DOIGTS:
        base_nom, _pip, _dip, bout_nom = _ARTICULATIONS[doigt]
        base = _point(par_nom, base_nom)
        bout = _point(par_nom, bout_nom)
        if base is None or bout is None:
            continue
        confiances.extend([base.confiance, bout.confiance])
        # La distance du bout à SA PROPRE BASE, et non au poignet. Le
        # poignet est loin, donc sa mesure change avec l'inclinaison de la
        # main : la même main fermée donnait des nombres différents selon
        # qu'elle était droite ou penchée — « tantôt c'était mieux ». Un
        # doigt, lui, est plié ou tendu indépendamment de l'orientation du
        # bras. Mesuré : le critère local sépare trois fois mieux.
        etendue = _distance(base, bout) / paume
        replis.append(etendue)
        if etendue > 0.75:
            tendus += 1

    if len(replis) < 3:
        return None

    # Le pouce ment sur le repliement (il se replie de côté) : on mesure le
    # repliement sur les quatre doigts longs.
    longs = replis[1:] if len(replis) == 5 else replis
    repliement = sum(longs) / len(longs)  # ~0,3 fermé, ~1,0 ouvert

    bout_pouce = _point(par_nom, "thumbTip")
    bout_index = _point(par_nom, "indexTip")
    pince = (
        _distance(bout_pouce, bout_index) / paume
        if bout_pouce and bout_index
        else 9.99
    )

    return Mesures(
        repliement=max(0.0, min(2.0, repliement)),
        pince=pince,
        confiance=min(confiances),
        doigts_tendus=tendus,
    )


class MoteurDeGestes:
    """La machine à états (§12), avec hystérésis et temps de repos.

    Une instance suit UNE main. Elle ne connaît ni caméra, ni fichier, ni
    appareil : elle rend un état, et c'est à l'appelant d'en faire quelque
    chose — ou rien, ce qui est le cas le plus fréquent et le plus sain.
    """

    def __init__(self, seuils: Optional[Seuils] = None) -> None:
        self.seuils = seuils or Seuils()
        self.etat = Etat.REPOS
        self._pose_stable: Pose = Pose.INCONNUE
        self._pose_candidate: Pose = Pose.INCONNUE
        self._images_candidates = 0
        self._lisse: Optional[Mesures] = None
        self._vue_a: float = 0.0
        self._repos_jusqua: float = 0.0
        self._ferme = False  # l'état d'hystérésis, pas la pose brute

    # ── lissage ─────────────────────────────────────────────────────────
    def _lisser(self, mesures: Mesures) -> Mesures:
        if self._lisse is None:
            self._lisse = mesures
            return mesures
        a = self.seuils.lissage
        self._lisse = Mesures(
            repliement=a * self._lisse.repliement + (1 - a) * mesures.repliement,
            pince=a * self._lisse.pince + (1 - a) * mesures.pince,
            confiance=mesures.confiance,
            doigts_tendus=mesures.doigts_tendus,
        )
        return self._lisse

    # ── pose ────────────────────────────────────────────────────────────
    def _pose(self, m: Mesures) -> Pose:
        """La pose de CETTE image, avec hystérésis sur l'ouverture."""
        s = self.seuils
        if m.confiance < s.confiance_minimale:
            return Pose.INCONNUE
        if m.pince < (s.pince_sortie if self._pose_stable is Pose.PINCE else s.pince_entree):
            return Pose.PINCE
        # L'hystérésis : le seuil dépend de l'état où l'on est déjà.
        if self._ferme:
            if m.repliement > s.fermeture_sortie:
                self._ferme = False
        elif m.repliement < s.fermeture_entree:
            self._ferme = True
        if self._ferme:
            return Pose.POING
        if m.doigts_tendus == 1:
            return Pose.POINTE
        if m.repliement > (
            s.ouverture_sortie if self._pose_stable is Pose.PAUME_OUVERTE
            else s.ouverture_entree
        ):
            return Pose.PAUME_OUVERTE
        return Pose.INCONNUE

    # ── l'entrée publique ───────────────────────────────────────────────
    def observer(
        self, points: Optional[Sequence[Point]], *, maintenant: Optional[float] = None
    ) -> Etat:
        """Une image de plus. Rend l'état APRÈS cette image.

        ``points`` vaut None quand aucune main n'est vue — et c'est une
        information, pas une absence d'information : une main qui disparaît
        au milieu d'un geste doit l'annuler, jamais le figer.
        """
        maintenant = time.monotonic() if maintenant is None else maintenant

        if points is None:
            return self._sans_main(maintenant)

        mesures = mesurer(points)
        if mesures is None:
            return self._sans_main(maintenant)

        self._vue_a = maintenant
        lisse = self._lisser(mesures)
        pose = self._pose(lisse)

        # §11 : une pose n'est crue qu'après N images qui la confirment.
        if pose is self._pose_candidate:
            self._images_candidates += 1
        else:
            self._pose_candidate = pose
            self._images_candidates = 1
        if self._images_candidates >= self.seuils.images_stables:
            self._pose_stable = pose

        if maintenant < self._repos_jusqua:
            # Temps de repos : on suit la main, on ne conclut rien.
            return self.etat
        return self._avancer(self._pose_stable, maintenant)

    def _sans_main(self, maintenant: float) -> Etat:
        self._lisse = None
        self._pose_candidate = Pose.INCONNUE
        self._images_candidates = 0
        if self.etat in (Etat.REPOS, Etat.RELACHE, Etat.PERDU, Etat.ANNULE):
            self.etat = Etat.REPOS
            return self.etat
        trou = (maintenant - self._vue_a) * 1000
        if trou >= self.seuils.trou_de_suivi_ms:
            # Une main perdue au milieu d'un geste ANNULE : figer l'état
            # laisserait un objet « attrapé » que personne ne tient.
            precedent = self.etat
            self.etat = Etat.PERDU if precedent is Etat.SAISI else Etat.ANNULE
            self._pose_stable = Pose.INCONNUE
            self._ferme = False
        return self.etat

    def _avancer(self, pose: Pose, maintenant: float) -> Etat:
        avant = self.etat
        if self.etat in (Etat.REPOS, Etat.RELACHE, Etat.PERDU, Etat.ANNULE):
            self.etat = Etat.MAIN_VUE if pose is not Pose.INCONNUE else Etat.REPOS
        if self.etat is Etat.MAIN_VUE and pose is Pose.PAUME_OUVERTE:
            self.etat = Etat.PAUME_STABLE
        elif self.etat is Etat.PAUME_STABLE and pose is Pose.POING:
            self.etat = Etat.SAISI
        elif self.etat is Etat.SAISI and pose is Pose.PAUME_OUVERTE:
            self.etat = Etat.RELACHE
            self._repos_jusqua = maintenant + self.seuils.repos_ms / 1000
        if self.etat is not avant:
            logger.debug("geste : %s → %s (%s)", avant.value, self.etat.value, pose.value)
        return self.etat

    def reinitialiser(self) -> None:
        self.__init__(self.seuils)  # noqa: PLC2801 - remise à neuf explicite


# ── Calibration (§16) ───────────────────────────────────────────────────
# Les seuils par défaut sont des points de départ raisonnables, pas des
# vérités : la taille des mains, la distance à l'objectif et la façon de
# fermer le poing varient d'une personne à l'autre. Plutôt que de deviner,
# on MESURE deux poses et on place les seuils entre elles.


def seuils_calibres(
    repliement_ouvert: float,
    repliement_ferme: float,
    *,
    base: Optional[Seuils] = None,
) -> Seuils:
    """Des seuils dérivés de DEUX mesures réelles, pas d'une supposition.

    L'hystérésis occupe le tiers central de l'écart mesuré : assez large
    pour qu'une main qui hésite ne fasse pas osciller l'état, assez étroite
    pour que le geste reste franc.
    """
    from dataclasses import replace

    base = base or Seuils()
    ecart = repliement_ouvert - repliement_ferme
    if ecart < 0.15:
        # Les deux poses se ressemblent trop : calibrer là-dessus rendrait
        # les seuils ingouvernables. On le dit plutôt que de bricoler.
        raise ValueError(
            "Les deux poses sont trop proches pour en tirer des seuils. "
            "Ouvre bien la main, puis serre franchement le poing."
        )
    milieu = repliement_ferme + ecart / 2
    marge = ecart / 6
    return replace(
        base,
        fermeture_entree=round(milieu - marge, 3),
        fermeture_sortie=round(milieu + marge, 3),
        ouverture_entree=round(milieu + marge * 1.6, 3),
        ouverture_sortie=round(milieu + marge * 0.6, 3),
    )


def chemin_calibration() -> "Path":
    from diapason.core.paths import get_config_dir

    return Path(get_config_dir()) / "gestes.json"


def charger_seuils() -> Seuils:
    """Les seuils de CETTE machine — ceux d'usine si rien n'est calibré."""
    import json

    chemin = chemin_calibration()
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Seuils()
    connus = {c for c in Seuils.__dataclass_fields__}
    return Seuils(**{k: v for k, v in brut.items() if k in connus})


def enregistrer_seuils(seuils: Seuils) -> None:
    import json
    from dataclasses import asdict

    chemin = chemin_calibration()
    chemin.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(asdict(seuils), indent=2) + "\n", encoding="utf-8"
    )


def oublier_la_calibration() -> None:
    chemin_calibration().unlink(missing_ok=True)


__all__ = [
    "Etat",
    "charger_seuils",
    "chemin_calibration",
    "enregistrer_seuils",
    "oublier_la_calibration",
    "seuils_calibres",
    "Mesures",
    "MoteurDeGestes",
    "Point",
    "Pose",
    "Seuils",
    "mesurer",
]
