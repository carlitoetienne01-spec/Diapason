"""Des pixels aux points articulaires — Vision d'Apple, sur la machine.

Spatial Mesh, gestes — 25 août 2026. Le pont entre une image et le moteur
de gestes. Il ne décide de rien : il lit vingt-et-un points par main et
les passe. Tout ce qui ressemble à une intention vit dans
``gestes_main``, qui n'a jamais vu un pixel.

Deux propriétés, et le §10 du cahier des charges les exige :

**Rien ne quitte la machine.** Vision tourne sur le Neural Engine ; aucun
octet ne part sur le réseau, et le créneau Ollama — unique — n'est pas
touché. Un modèle de langue et un suivi de main peuvent donc coexister.

**Aucune image n'est gardée.** L'entrée est un tampon de pixels vivant en
mémoire ; la sortie est une liste de coordonnées. Rien n'est écrit sur le
disque, à aucun moment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Les noms que Vision emploie, traduits une fois, ici. Le moteur de gestes
# ne connaît que ces chaînes — il ignore jusqu'à l'existence de Vision.
_NOMS = {
    "VNHLKWRI": "wrist",
    "VNHLKTCMC": "thumbCMC",
    "VNHLKTMP": "thumbMP",
    "VNHLKTIP": "thumbIP",
    "VNHLKTTIP": "thumbTip",
    "VNHLKIMCP": "indexMCP",
    "VNHLKIPIP": "indexPIP",
    "VNHLKIDIP": "indexDIP",
    "VNHLKITIP": "indexTip",
    "VNHLKMMCP": "middleMCP",
    "VNHLKMPIP": "middlePIP",
    "VNHLKMDIP": "middleDIP",
    "VNHLKMTIP": "middleTip",
    "VNHLKRMCP": "ringMCP",
    "VNHLKRPIP": "ringPIP",
    "VNHLKRDIP": "ringDIP",
    "VNHLKRTIP": "ringTip",
    "VNHLKPMCP": "littleMCP",
    "VNHLKPPIP": "littlePIP",
    "VNHLKPDIP": "littleDIP",
    "VNHLKPTIP": "littleTip",
}


@dataclass(frozen=True, slots=True)
class MainDetectee:
    """Une main lue par Vision, avec sa latéralité.

    La latéralité sert au retournement paume/dos : sans elle, le sens du
    parcours des bases serait ambigu (main gauche vs droite).
    """

    points: list
    lateralite: str  # "left" | "right" | "unknown"


class VisionIndisponible(RuntimeError):
    """Le framework manque — dit, jamais deviné."""


def disponible() -> bool:
    try:
        import Vision  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _requete(mains_max: int = 2) -> Any:
    try:
        import Vision
    except ImportError as exc:
        raise VisionIndisponible(
            "Vision manque : uv pip install 'pyobjc-framework-Vision>=10'"
        ) from exc
    requete = Vision.VNDetectHumanHandPoseRequest.alloc().init()
    requete.setMaximumHandCount_(max(1, min(2, mains_max)))
    return requete


def _lire_points(observation: Any) -> list:
    """Les points d'UNE main, traduits dans le vocabulaire du moteur."""
    import Vision

    from diapason.desktop.gestes_main import Point

    # Le nom de la méthode ET la constante du groupe se LISENT, ils ne se
    # devinent pas. Constaté le 25 août 2026, en direct sur la caméra de
    # Carlito : « recognizedPointsForGroupName_error_ » n'existe pas (c'est
    # « …ForJointsGroupName… »), et le groupe « toutes les articulations »
    # ne s'appelle pas « VNHLKAll » mais « VNIPOAll ». Les tests ne
    # pouvaient pas le voir : sans main dans l'image, cette fonction n'est
    # jamais atteinte — le trou était là, pas dans le pipeline.
    points, erreur = observation.recognizedPointsForJointsGroupName_error_(
        Vision.VNHumanHandPoseObservationJointsGroupNameAll, None
    )
    if not points:
        return []
    sortie = []
    for cle, brut in points.items():
        nom = _NOMS.get(str(cle))
        if nom is None:
            continue
        emplacement = brut.location()
        # Vision rend des coordonnées normalisées dont l'origine est en BAS
        # à gauche. Le moteur raisonne en haut-à-gauche, comme un écran :
        # on retourne y ici, une seule fois, plutôt que partout ensuite.
        sortie.append(
            Point(
                nom=nom,
                x=float(emplacement.x),
                y=1.0 - float(emplacement.y),
                confiance=float(brut.confidence()),
            )
        )
    return sortie


def _lateralite(observation: Any) -> str:
    import Vision

    # chirality() existe depuis les SDK récents ; sans elle le retournement
    # paume/dos refuse plutôt que de deviner (§34).
    lire = getattr(observation, "chirality", None)
    if lire is None:
        return "unknown"
    cote = lire()
    if cote == Vision.VNChiralityLeft:
        return "left"
    if cote == Vision.VNChiralityRight:
        return "right"
    return "unknown"


def _lire_main(observation: Any) -> MainDetectee:
    return MainDetectee(
        points=_lire_points(observation),
        lateralite=_lateralite(observation),
    )


def mains_dans_le_tampon(pixels: Any, *, mains_max: int = 2) -> list[MainDetectee]:
    """Les mains vues dans un tampon de pixels — [] si aucune.

    Le tampon vient directement de la caméra : pas de fichier intermédiaire,
    donc pas d'image qui traîne sur le disque.
    """
    import Vision

    requete = _requete(mains_max)
    gestionnaire = Vision.VNImageRequestHandler.alloc().initWithCVPixelBuffer_options_(
        pixels, None
    )
    ok, erreur = gestionnaire.performRequests_error_([requete], None)
    if not ok:
        raise VisionIndisponible(f"Vision a échoué : {erreur}")
    return [_lire_main(o) for o in (requete.results() or [])]


def mains_dans_le_fichier(chemin: str, *, mains_max: int = 2) -> list[MainDetectee]:
    """Les mains vues dans une image sur disque — pour les bancs d'essai."""
    import Vision
    from Foundation import NSURL

    requete = _requete(mains_max)
    gestionnaire = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
        NSURL.fileURLWithPath_(str(chemin)), None
    )
    ok, erreur = gestionnaire.performRequests_error_([requete], None)
    if not ok:
        raise VisionIndisponible(f"Vision a échoué : {erreur}")
    return [_lire_main(o) for o in (requete.results() or [])]


def mains_dans_les_octets(octets: bytes, *, mains_max: int = 2) -> list[MainDetectee]:
    """Les mains vues dans une image reçue en mémoire — rien sur le disque.

    C'est le chemin de l'interface : elle capture, elle poste, on lit. Écrire
    l'image pour la relire serait laisser une trace de ce que la caméra a vu.
    """
    import Vision
    from Foundation import NSData

    requete = _requete(mains_max)
    donnees = NSData.dataWithBytes_length_(octets, len(octets))
    gestionnaire = Vision.VNImageRequestHandler.alloc().initWithData_options_(
        donnees, None
    )
    ok, erreur = gestionnaire.performRequests_error_([requete], None)
    if not ok:
        raise VisionIndisponible(f"Vision a échoué : {erreur}")
    return [_lire_main(o) for o in (requete.results() or [])]


def points_de_main(main: Any) -> list:
    """Compatibilité tests : une MainDetectee ou une ancienne liste de points."""
    if main is None:
        return []
    if isinstance(main, MainDetectee):
        return list(main.points)
    return list(main)


def lateralite_de_main(main: Any) -> str:
    if isinstance(main, MainDetectee):
        return main.lateralite
    return "unknown"


__all__ = [
    "MainDetectee",
    "VisionIndisponible",
    "disponible",
    "lateralite_de_main",
    "mains_dans_le_fichier",
    "mains_dans_les_octets",
    "mains_dans_le_tampon",
    "points_de_main",
]
