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
from pydantic import BaseModel

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
    # De quoi JUGER la fiabilité, comme le §141 l'exige : un geste n'est
    # fini que quand ses faux positifs sont mesurés. Le serveur ne peut pas
    # savoir ce que l'utilisateur VOULAIT — il compte donc ce qui s'est
    # produit, et c'est l'humain qui dit combien étaient voulus.
    saisies: int = 0
    relachements: int = 0
    pertes: int = 0
    confiance_totale: float = 0.0
    confiance_mesures: int = 0
    dernier_repliement: float = 0.0
    dernier_attrape: Any = None
    dernier_depot: Any = None
    # Le journal des gestes (§73 appliqué aux gestes). Sans lui, un geste
    # qui réussit et dont le message disparaît laisse l'utilisateur dire
    # « je PENSE que ça a marché » — et c'est déjà un échec : il devrait le
    # savoir, pas le supposer.
    journal: list = field(default_factory=list)
    calibration_en_cours: str = ""
    echantillons: list = field(default_factory=list)

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


# ── Le double-clap (§78) ────────────────────────────────────────────────
# Une quatrième voie d'armement, à côté du bouton : claper deux fois. Elle
# a un coût que le bouton n'a pas — le micro reste OUVERT pour l'entendre —
# et ce coût ne se subit pas, il se choisit. L'écoute est donc éteinte par
# défaut, et le panneau dit ce qu'elle implique.
_ecouteur_claps: Any = None


def claps_actifs() -> bool:
    """Le micro écoute-t-il vraiment ? Un objet gardé n'est pas une preuve."""
    ecouteur = _ecouteur_claps
    if ecouteur is None:
        return False
    ecoute = getattr(ecouteur, "ecoute", True)
    return bool(ecoute)


def _claps_entendus() -> int:
    """Ce que le micro a entendu — pour savoir si le seuil est atteignable."""
    ecouteur = _ecouteur_claps
    return int(getattr(ecouteur, "claps_entendus", 0) or 0) if ecouteur else 0


@router.post("/clap/on")
def ecouter_les_claps() -> dict[str, Any]:
    """Ouvrir le micro pour entendre un double-clap, et rien d'autre.

    Le détecteur ne transcrit rien et ne garde rien : il suit le niveau
    sonore et cherche deux pics rapprochés. Aucune parole n'est analysée,
    aucun son n'est enregistré.
    """
    global _ecouteur_claps
    if _ecouteur_claps is not None:
        return {"listening": True, "already": True}
    try:
        from diapason.speech.clap_listener import ClapListener
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"Écoute indisponible : {str(exc)[:120]}"
        ) from exc

    def _sur_double_clap() -> None:
        # Deux claps arment ; deux claps de plus désarment. Le même geste
        # dans les deux sens, parce qu'un mode qu'on ne sait pas couper
        # sans souris n'est pas vraiment mains libres.
        try:
            if session_active():
                desarmer()
                logger.info("double-clap : mode gestes désarmé")
            else:
                armer()
                logger.info("double-clap : mode gestes armé")
        except Exception:  # noqa: BLE001 - un clap raté n'arrête pas l'écoute
            logger.warning("double-clap non traité", exc_info=True)

    try:
        ecouteur = ClapListener(_sur_double_clap, once=False)
        ecouteur.start()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"Le micro n'a pas pu être ouvert : {str(exc)[:120]}",
        ) from exc
    # CONSTATER, pas supposer. Le fil d'écoute meurt en silence quand
    # sounddevice manque ou que le micro refuse : start() rendait la main
    # sans rien dire, et cette route répondait « écoute active » à un
    # utilisateur qui pouvait claper jusqu'au soir (25 août 2026).
    if not ecouteur.ecoute:
        raison = ecouteur.panne or "le micro n'a pas répondu"
        try:
            ecouteur.stop()
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(
            status_code=503, detail=f"L'écoute n'a pas démarré : {raison}"
        )
    _ecouteur_claps = ecouteur
    logger.info("écoute des claps démarrée")
    return {"listening": True}


@router.post("/clap/off")
def ne_plus_ecouter() -> dict[str, Any]:
    """Refermer le micro. Il ne doit pas rester ouvert par oubli."""
    global _ecouteur_claps
    ecouteur, _ecouteur_claps = _ecouteur_claps, None
    if ecouteur is not None:
        try:
            ecouteur.stop()
        except Exception:  # noqa: BLE001
            logger.debug("arrêt de l'écoute imparfait", exc_info=True)
    return {"listening": False}


@router.post("/arm")
def armer() -> dict[str, Any]:
    """Armer le mode gestes. La caméra ne s'ouvre qu'après, côté interface."""
    global _session
    from diapason.desktop.gestes_main import MoteurDeGestes, charger_seuils
    from diapason.desktop.vision_mains import disponible

    if not disponible():
        raise HTTPException(
            status_code=503,
            detail=(
                "La reconnaissance de main n'est pas disponible : "
                "uv pip install 'pyobjc-framework-Vision>=10'"
            ),
        )
    # Les seuils de CETTE machine : calibrés s'ils l'ont été.
    _session = _Session(moteur=MoteurDeGestes(charger_seuils()))
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
        return {
            "armed": False,
            "clapListening": claps_actifs(),
            "clapsHeard": _claps_entendus(),
        }
    confiance = (
        _session.confiance_totale / _session.confiance_mesures
        if _session.confiance_mesures
        else 0.0
    )
    return {
        "armed": True,
        "clapListening": claps_actifs(),
        "clapsHeard": _claps_entendus(),
        "state": _session.moteur.etat.value,
        "frames": _session.images,
        "handsSeen": _session.mains_vues,
        "secondsLeft": round(
            max(0.0, _INACTIVITE_MAX_S - (time.monotonic() - _session.vue_a)), 1
        ),
        # Ce qui permet de juger, et rien de plus : le serveur ne prétend
        # pas savoir lesquelles étaient voulues.
        "grabs": _session.saisies,
        "releases": _session.relachements,
        "losses": _session.pertes,
        "handRatio": round(
            _session.mains_vues / _session.images if _session.images else 0.0, 2
        ),
        "confidence": round(confiance, 2),
        "curl": round(_session.dernier_repliement, 3),
        "calibrating": _session.calibration_en_cours,
        "held": _session.dernier_attrape.to_dict()
        if _session.dernier_attrape is not None
        else None,
        "lastDrop": _session.dernier_depot,
        "journal": list(reversed(_session.journal)),
        "recentStates": list(_session.derniers_etats),
    }


def _noter(quoi: str, detail: str, *, reussi: bool) -> None:
    """Garder trace de ce qui vient de se passer, pour que ça se SACHE."""
    if _session is None:
        return
    _session.journal.append(
        {
            "at": time.strftime("%H:%M:%S"),
            "what": quoi,
            "detail": detail[:160],
            "ok": reussi,
        }
    )
    del _session.journal[:-8]


def _deposer() -> dict[str, Any]:
    """Ouvrir la main : envoyer ce qu'on tenait — ou dire pourquoi non.

    Le §34 gouverne : aucun capteur de cette flotte ne mesure une
    direction, donc rien n'est deviné. S'il n'y a qu'un seul appareil
    joignable, c'est lui ; sinon on le dit et l'utilisateur tranche. Un
    geste ne doit jamais envoyer un document à un appareil choisi au
    hasard — ce serait l'échec le plus grave de cette fonctionnalité.
    """
    from diapason.desktop.presse_papiers_spatial import lacher

    objet = lacher()
    if objet is None:
        return {"done": False, "reason": "NOTHING_HELD",
                "message": "La main s'ouvre sur rien : rien n'avait été attrapé."}
    try:
        from diapason.mesh.presence import presence_of
        from diapason.mesh.registry import DeviceRegistry

        flotte = [
            d
            for d in DeviceRegistry().list_devices()
            if d.get("trustLevel") == "TRUSTED"
        ]
        joignables = [
            d
            for d in flotte
            if (presence_of(d) or {}).get("state") in ("ONLINE", "IDLE")
        ]
    except Exception as exc:  # noqa: BLE001 - un registre illisible se dit
        logger.warning("flotte illisible au dépôt", exc_info=True)
        return {"done": False, "reason": "NO_FLEET", "message": str(exc)[:120],
                "object": objet.to_dict()}

    if not joignables:
        noms = ", ".join(str(d.get("name") or "?") for d in flotte)
        return {
            "done": False,
            "reason": "ALL_OFFLINE",
            "object": objet.to_dict(),
            "message": (
                f"« {objet.titre} » est prêt, mais aucun appareil n'est "
                f"joignable{' (' + noms + ')' if noms else ''}."
            ),
        }
    if len(joignables) > 1:
        # §81 : deux candidats, aucune direction mesurée — on demande.
        return {
            "done": False,
            "reason": "AMBIGUOUS",
            "object": objet.to_dict(),
            "candidates": [str(d.get("name") or "?") for d in joignables],
            "message": (
                f"« {objet.titre} » est prêt. Vers lequel : "
                + ", ".join(str(d.get("name") or "?") for d in joignables)
                + " ?"
            ),
        }

    cible = joignables[0]
    from diapason.mesh.dispatch import dispatch_command

    if objet.type == "screen":
        from diapason.desktop.contexte_app import _ECRANS

        route = (_ECRANS.get(objet.id) or (None, ""))[0]
        if not route:
            return {"done": False, "reason": "UNSUPPORTED",
                    "object": objet.to_dict(),
                    "message": f"{objet.titre} n'existe pas sur les autres appareils."}
        resultat = dispatch_command(
            target_device_id=str(cible.get("deviceId") or ""),
            tool="app.navigate",
            arguments={"route": f"success://{route}"},
        )
    else:
        resultat = dispatch_command(
            target_device_id=str(cible.get("deviceId") or ""),
            tool="app.show_resource",
            arguments={"resourceType": objet.type, "resourceId": objet.id},
        )
    # La phrase vient du RÉCEPTEUR, jamais de ce qu'on a envoyé.
    return {
        "done": resultat.get("status") == "SUCCESS",
        "reason": resultat.get("status"),
        "object": objet.to_dict(),
        "target": str(cible.get("name") or "?"),
        "message": str(resultat.get("userSafeMessage") or ""),
    }


async def _lire_image(request: Request) -> bytes:
    """L'image, qu'elle arrive en binaire ou en base64 dans du JSON.

    Deux chemins, et le second n'est pas un luxe : WKWebView — le moteur de
    la fenêtre Diapason — échoue sur un corps de requête binaire avec un
    « Load failed » opaque, alors que la même requête passe en ligne de
    commande et que le contrôle préalable CORS répond correctement
    (constaté le 25 août 2026, après avoir écarté le port, CORS, puis le
    type Blob, puis ArrayBuffer). Le JSON est le chemin que toute
    l'application emprunte déjà ; il coûte un tiers de volume en plus, sur
    la boucle locale.
    """
    brut = await request.body()
    if not brut:
        return b""
    if "application/json" not in (request.headers.get("content-type") or "").lower():
        return brut
    import base64
    import json

    try:
        charge = json.loads(brut)
        return base64.b64decode(str(charge.get("image") or ""), validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"Charge JSON illisible : {exc}"
        ) from exc


@router.post("/frame")
async def image(request: Request) -> dict[str, Any]:
    """Une image de plus. Rend l'état APRÈS cette image.

    Le corps est l'image brute (JPEG ou PNG) envoyée par l'interface. Elle
    n'est jamais écrite : Vision la lit en mémoire, et seuls des points en
    sortent.
    """
    from diapason.desktop.presse_papiers_spatial import attraper, vider
    from diapason.desktop.vision_mains import mains_dans_les_octets

    if not session_active() or _session is None:
        raise HTTPException(
            status_code=409,
            detail="Le mode gestes n'est pas armé.",
        )
    octets = await _lire_image(request)
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
    if points:
        from diapason.desktop.gestes_main import mesurer

        mesures = mesurer(points)
        if mesures is not None:
            _session.confiance_totale += mesures.confiance
            _session.confiance_mesures += 1
            _session.dernier_repliement = mesures.repliement
            if _session.calibration_en_cours:
                _session.echantillons.append(mesures.repliement)
    avant = _session.moteur.etat
    apres = _session.moteur.observer(points)
    if apres is not avant:
        _session.derniers_etats.append(apres.value)
        del _session.derniers_etats[:-10]
        if apres.value == "SAISI":
            _session.saisies += 1
            # Le geste exprime une INTENTION ; il ne transporte rien. Fermer
            # le poing désigne ce que l'écran affiche et le retient.
            _session.dernier_attrape = attraper()
            _noter(
                "attrapé",
                _session.dernier_attrape.titre
                if _session.dernier_attrape is not None
                else "rien — aucun écran de Diapason n'était ouvert",
                reussi=_session.dernier_attrape is not None,
            )
        elif apres.value == "RELACHE":
            _session.relachements += 1
            _session.dernier_depot = _deposer()
            _noter(
                "déposé" if _session.dernier_depot.get("done") else "dépôt refusé",
                str(_session.dernier_depot.get("message") or ""),
                reussi=bool(_session.dernier_depot.get("done")),
            )
        elif apres.value in ("PERDU", "ANNULE"):
            _session.pertes += 1
            # Une main perdue au milieu d'un geste ne laisse pas un objet
            # « tenu » que personne ne tient (§12).
            vider()
            _session.dernier_attrape = None
    return {
        "state": apres.value,
        "changed": apres is not avant,
        "hand": bool(points),
        "frames": _session.images,
    }


# Les routes FIXES d'abord : « /calibrate/apply » serait sinon capturé par
# « /calibrate/{pose} », qui répondrait « pose inconnue » à une requête
# parfaitement formée. FastAPI essaie les routes dans l'ordre de
# déclaration — l'ordre est donc du sens, pas de la présentation.
class Calibration(BaseModel):
    ouverte: float
    fermee: float


@router.post("/calibrate/apply")
def appliquer(body: Calibration) -> dict[str, Any]:
    """Poser les seuils dérivés des deux mesures, et les garder."""
    from dataclasses import asdict

    from diapason.desktop.gestes_main import enregistrer_seuils, seuils_calibres

    try:
        seuils = seuils_calibres(body.ouverte, body.fermee)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    enregistrer_seuils(seuils)
    if _session is not None:
        _session.moteur.seuils = seuils
        _session.moteur.reinitialiser()
    return {"calibrated": True, "thresholds": asdict(seuils)}


@router.post("/calibrate/reset")
def oublier() -> dict[str, Any]:
    from diapason.desktop.gestes_main import oublier_la_calibration

    oublier_la_calibration()
    return {"calibrated": False}


@router.post("/calibrate/{pose}")
def calibrer(pose: str) -> dict[str, Any]:
    """Mesurer une pose — « ouverte » puis « fermee ».

    La calibration ne devine pas : elle enregistre ce que la main de CETTE
    personne produit réellement, et place les seuils entre les deux poses.
    """
    if pose not in ("ouverte", "fermee"):
        raise HTTPException(status_code=400, detail="Pose inconnue.")
    if not session_active() or _session is None:
        raise HTTPException(status_code=409, detail="Le mode gestes n'est pas armé.")
    _session.calibration_en_cours = pose
    _session.echantillons = []
    return {"measuring": pose}


@router.post("/calibrate/{pose}/stop")
def finir_la_mesure(pose: str) -> dict[str, Any]:
    """Clore une mesure et rendre sa moyenne — ou avouer qu'il n'y a rien."""
    if not session_active() or _session is None:
        raise HTTPException(status_code=409, detail="Le mode gestes n'est pas armé.")
    echantillons = list(_session.echantillons)
    _session.calibration_en_cours = ""
    _session.echantillons = []
    if len(echantillons) < 5:
        raise HTTPException(
            status_code=422,
            detail=(
                "Je n'ai pas assez vu ta main. Rapproche-la de la caméra, "
                "éclaire-la, et recommence."
            ),
        )
    # La médiane, pas la moyenne : une image aberrante ne doit pas
    # déplacer un seuil que l'on gardera.
    tries = sorted(echantillons)
    mediane = tries[len(tries) // 2]
    return {"pose": pose, "value": round(mediane, 3), "samples": len(echantillons)}


__all__ = ["claps_actifs", "desarmer", "router", "session_active"]
