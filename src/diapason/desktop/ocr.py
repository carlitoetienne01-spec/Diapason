"""Le texte EXACT de l'écran — OCR natif Apple, sans quitter la machine.

Atlas, panier « Ensuite », 24 août 2026. « Regarde mon écran » passait par
gemma3:4b, qui décrit bien mais PARAPHRASE : un numéro de dossier, un
montant, un message d'erreur ressortaient réinterprétés. Le framework
Vision d'Apple (VNRecognizeTextRequest) lit les caractères eux-mêmes —
plus précis, plus rapide, et sans toucher au créneau Ollama unique.

Import de Vision paresseux (PyObjC, macOS seulement) ; les résultats sont
triés en ordre de lecture — Vision parle en coordonnées normalisées dont
l'origine est en BAS à gauche, donc y décroissant puis x croissant.
"""

from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def ocr_available() -> bool:
    """Le framework Vision répond-il ? (PyObjC installé, macOS.)"""
    try:
        import Vision  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 - absent = indisponible, pas une panne
        return False


def recognize_text(
    path: str,
    *,
    languages: tuple[str, ...] = ("fr-FR", "en-US"),
    fast: bool = False,
) -> List[dict]:
    """Les lignes de texte d'une image : [{text, confidence, x, y}].

    ``x``/``y`` sont normalisés [0,1], origine bas-gauche (convention
    Vision) — les appelants trient, ils ne devinent pas.
    """
    import Vision
    from Foundation import NSURL

    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
        NSURL.fileURLWithPath_(str(path)), None
    )
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(
        Vision.VNRequestTextRecognitionLevelFast
        if fast
        else Vision.VNRequestTextRecognitionLevelAccurate
    )
    request.setUsesLanguageCorrection_(True)
    request.setRecognitionLanguages_(list(languages))

    # performRequests rend un COUPLE (ok, erreur) — même piège que
    # get_engine (screen_vision_tools.py) : ne pas prendre le couple pour
    # la valeur.
    ok, erreur = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision OCR failed: {erreur}")

    lignes: List[dict] = []
    for observation in request.results() or []:
        candidats = observation.topCandidates_(1)
        if not candidats or not len(candidats):
            continue
        premier = candidats[0]
        boite = observation.boundingBox()
        lignes.append(
            {
                "text": str(premier.string()),
                "confidence": float(premier.confidence()),
                "x": float(boite.origin.x),
                "y": float(boite.origin.y),
            }
        )
    # Ordre de lecture : haut de l'écran d'abord (y décroissant), puis
    # gauche → droite.
    lignes.sort(key=lambda l: (-l["y"], l["x"]))
    return lignes


__all__ = ["ocr_available", "recognize_text"]
