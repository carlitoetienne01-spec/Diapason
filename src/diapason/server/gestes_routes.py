"""Le mode gestes : armer, envoyer des images, désarmer.

Spatial Mesh, gestes — 25 août 2026. La caméra est ouverte par
l'APPLICATION, pas par le serveur : macOS ne pose la question qu'à un
paquet, et l'interpréteur Python n'en est pas un (voir
docs/spatial-mesh/GESTES.md). L'interface capture donc, et poste ici les
images ; le serveur voit, décide, et rend un état.

Le §78 gouverne ce module : **rien ne guette en permanence**. Une session
s'arme explicitement, se désarme d'elle-même après un temps mort, et le
voyant vert de la caméra dit la vérité pendant tout ce temps. Une caméra
qui tournerait « au cas où » ferait de Diapason autre chose qu'un
assistant.

Aucune image n'est écrite sur le disque, jamais : elle vit le temps d'un
appel à Vision, et seuls des points articulaires lui survivent.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/gestures", tags=["gestures"])

# Un mode armé qu'on oublierait de désarmer laisserait la caméra allumée.
# Au-delà de ce silence, la session se ferme d'elle-même.
_INACTIVITE_MAX_S = 90.0
# Le §83 : la caméra coûte. Une session ne tient pas une heure par accident.
_DUREE_MAX_S = 600.0


@dataclass
class _Session:
    moteur: Any
    armee_a: float = field(default_factory=time.monotonic)
    vue_a: float = field(default_factory=time.monotonic)
    images: int = 0
    mains_vues: int = 0
    derniers_etats: list = field(default_factory=list)

    @property
    def expiree(self) -> bool:
        maintenant = time.monotonic()
        return (
            maintenant - self.vue_a > _INACTIVITE_MAX_S
            or maintenant - self.armee_a > _DUREE_MAX_S
        )


_session: Optional[_Session] = None


def session_active() -> bool:
    """Le mode gestes est-il armé ? Constaté, pour l'interface et les tests."""
    global _session
    if _session is not None and _session.expiree:
        logger.info("mode gestes désarmé : silence ou durée dépassée")
        _session = None
    return _session is not None


def desarmer() -> None:
    global _session
    _session = None


@router.post("/arm")
def armer() -> dict[str, Any]:
    """Armer le mode gestes. La caméra ne s'ouvre qu'après, côté interface."""
    global _session
    from diapason.desktop.gestes_main import MoteurDeGestes
    from diapason.desktop.vision_mains import disponible

    if not disponible():
        raise HTTPException(
            status_code=503,
            detail=(
                "La reconnaissance de main n'est pas disponible : "
                "uv pip install 'pyobjc-framework-Vision>=10'"
            ),
        )
    _session = _Session(moteur=MoteurDeGestes())
    logger.info("mode gestes armé")
    return {
        "armed": True,
        "inactivityTimeoutS": _INACTIVITE_MAX_S,
        "maxDurationS": _DUREE_MAX_S,
    }


@router.post("/disarm")
def desarmer_route() -> dict[str, Any]:
    """Désarmer. L'interface éteint la caméra en recevant cette réponse."""
    etait = session_active()
    desarmer()
    logger.info("mode gestes désarmé")
    return {"armed": False, "was": etait}


@router.get("/state")
def etat() -> dict[str, Any]:
    if not session_active() or _session is None:
        return {"armed": False}
    return {
        "armed": True,
        "state": _session.moteur.etat.value,
        "frames": _session.images,
        "handsSeen": _session.mains_vues,
        "secondsLeft": round(
            max(0.0, _INACTIVITE_MAX_S - (time.monotonic() - _session.vue_a)), 1
        ),
    }


@router.post("/frame")
async def image(request: Request) -> dict[str, Any]:
    """Une image de plus. Rend l'état APRÈS cette image.

    Le corps est l'image brute (JPEG ou PNG) envoyée par l'interface. Elle
    n'est jamais écrite : Vision la lit en mémoire, et seuls des points en
    sortent.
    """
    from diapason.desktop.vision_mains import mains_dans_les_octets

    if not session_active() or _session is None:
        raise HTTPException(
            status_code=409,
            detail="Le mode gestes n'est pas armé.",
        )
    octets = await request.body()
    if not octets:
        raise HTTPException(status_code=400, detail="Image vide.")
    if len(octets) > 4 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image trop grande.")

    _session.vue_a = time.monotonic()
    _session.images += 1
    try:
        mains = mains_dans_les_octets(octets, mains_max=1)
    except Exception as exc:  # noqa: BLE001 - une image illisible n'arrête rien
        logger.debug("image de geste illisible", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Image illisible : {exc}") from exc

    points = mains[0] if mains else None
    if points:
        _session.mains_vues += 1
    avant = _session.moteur.etat
    apres = _session.moteur.observer(points)
    if apres is not avant:
        _session.derniers_etats.append(apres.value)
        del _session.derniers_etats[:-10]
    return {
        "state": apres.value,
        "changed": apres is not avant,
        "hand": bool(points),
        "frames": _session.images,
    }


__all__ = ["desarmer", "router", "session_active"]
