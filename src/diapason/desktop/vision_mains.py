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
from typing import Any, Optional

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
    from diapason.desktop.gestes_main import Point

    points, erreur = observation.recognizedPointsForGroupName_error_(
        "VNHLKAll", None
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


def mains_dans_le_tampon(pixels: Any, *, mains_max: int = 2) -> list[list]:
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
    return [_lire_points(o) for o in (requete.results() or [])]


def mains_dans_le_fichier(chemin: str, *, mains_max: int = 2) -> list[list]:
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
    return [_lire_points(o) for o in (requete.results() or [])]


__all__ = [
    "VisionIndisponible",
    "disponible",
    "mains_dans_le_fichier",
    "mains_dans_le_tampon",
]
