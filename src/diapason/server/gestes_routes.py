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

import asyncio
import logging
import threading
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
# Le temps laissé pour répondre à « vers lequel ? » (§81). Il est
# délibérément plus court que le TTL du presse-papiers (120 s) : un jeton
# ne doit jamais survivre à l'objet qu'il désigne, sinon on répondrait à une
# question dont la réponse est déjà partie en fumée.
_CHOIX_MAX_S = 45.0


@dataclass
class _Session:
    moteur: Any
    armee_a: float = field(default_factory=time.monotonic)
    vue_a: float = field(default_factory=time.monotonic)
    images: int = 0
    mains_vues: int = 0
    # Quand une main a été vue pour la dernière fois — None tant qu'aucune ne
    # l'a été. C'est le seul signal dont dépend l'état d'énergie (§83) : une
    # session armée devant une chaise vide n'a aucune raison de filmer à
    # douze images par seconde.
    main_vue_a: Optional[float] = None
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
    # Un dépôt qui attend que l'utilisateur tranche (§81). Il porte son
    # jeton, l'objet visé et les candidats TELS QUE LE SERVEUR LES A
    # MESURÉS : le client renvoie un identifiant, il ne l'invente pas.
    # {"jeton", "objet", "candidats", "a"}
    depot_en_attente: Any = None

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
        desarmer()
    return _session is not None


def desarmer() -> None:
    global _session
    from diapason.desktop.presse_papiers_spatial import vider

    # La main se vide avec la session. Sans cela, un objet attrapé survit
    # jusqu'à 120 s à la session qui l'a saisi : la caméra est éteinte, le
    # voyant a disparu, et un objet reste « tenu » que plus rien n'affiche.
    vider()
    _session = None


# ── Le double-clap (§78) ────────────────────────────────────────────────
# Une quatrième voie d'armement, à côté du bouton : claper deux fois. Elle
# a un coût que le bouton n'a pas — le micro reste OUVERT pour l'entendre —
# et ce coût ne se subit pas, il se choisit. L'écoute est donc éteinte par
# défaut, et le panneau dit ce qu'elle implique.
_ecouteur_claps: Any = None

# Une calibration ne se chevauche pas : elle prend le micro pour elle seule.
# L'utilisateur a cliqué quatre fois de suite le 25 août 2026 ; sans verrou,
# deux mesures s'arrachent le micro et la dernière écrase la première.
_verrou_calibration = threading.Lock()

# Ce que l'utilisateur VEUT, distinct de ce qui tourne. Toute décision
# d'ouvrir ou de fermer le micro l'incrémente. Une mesure commencée alors que
# l'écoute était ouverte ne doit pas la rouvrir si, pendant les huit secondes
# qu'elle dure, l'utilisateur a décoché la case.
_intention_ecoute = 0

# La pièce mesurée par la première étape, en attente de la seconde.
_piece_mesuree: Any = None
_PEREMPTION_PIECE_S = 30.0

# Pourquoi le dernier double-clap n'a rien armé. Avalée, cette raison
# laissait le panneau conseiller de rapprocher ses claps à quelqu'un qui
# clapait parfaitement.
_echec_de_clap: Optional[str] = None


def claps_actifs() -> bool:
    """Le micro écoute-t-il vraiment ? Un objet gardé n'est pas une preuve."""
    global _ecouteur_claps
    ecouteur = _ecouteur_claps
    if ecouteur is None:
        return False
    if not bool(getattr(ecouteur, "ecoute", True)):
        # Le fil est mort — casque débranché, micro repris par une autre
        # application. Garder le cadavre fait répondre « déjà en écoute » à
        # toute tentative de relance, et le micro reste fermé pour de bon
        # sans que rien ne le dise.
        _ecouteur_claps = None
        return False
    return True


def _reglage_des_claps() -> tuple[float, bool, float]:
    """Le seuil réellement en vigueur, s'il vient d'une mesure, et le fond
    sonore que le détecteur a appris.

    Sans ces chiffres, « ça ne déclenche pas » et « ça déclenche tout seul »
    se ressemblent depuis l'interface, et personne ne peut choisir entre
    calibrer et se rapprocher du micro.
    """
    try:
        from diapason.speech.clap_listener import (
            charger_reglage_claps,
            chemin_reglage_claps,
        )

        mesure = chemin_reglage_claps().exists()
        # Ce que le fil applique VRAIMENT prime sur ce que le fichier dit :
        # un fil démarré avant la calibration garde l'ancien seuil jusqu'à
        # ce qu'on le relance, et afficher le fichier serait proclamer.
        ecouteur = _ecouteur_claps if claps_actifs() else None
        vivant = float(getattr(ecouteur, "seuil", 0.0) or 0.0) if ecouteur else 0.0
        fond = float(getattr(ecouteur, "fond_sonore", 0.0) or 0.0) if ecouteur else 0.0
        if vivant > 0.0:
            return vivant, mesure, fond
        return charger_reglage_claps().min_rms, mesure, 0.0
    except Exception:  # noqa: BLE001
        return 0.0, False, 0.0


def _etat_des_claps() -> dict[str, Any]:
    """Les chiffres qui permettent de DÉCIDER quoi corriger.

    Le seuil seul ne suffit pas : c'est son rapport au fond sonore appris
    qui dit si la marge est confortable. Et la raison d'un armement raté
    doit remonter, sinon le panneau conseille de rapprocher ses claps à
    quelqu'un dont les claps étaient parfaits.
    """
    seuil, mesure, fond = _reglage_des_claps()
    return {
        "clapThreshold": seuil,
        "clapCalibrated": mesure,
        "clapNoiseFloor": round(fond, 5),
        "clapFailure": _echec_de_clap,
    }


def _claps_entendus() -> int:
    """Ce que le micro ENTEND, même quand aucun double ne se forme."""
    ecouteur = _ecouteur_claps
    return int(getattr(ecouteur, "claps_entendus", 0) or 0) if ecouteur else 0


@router.post("/clap/on")
def ecouter_les_claps() -> dict[str, Any]:
    """Ouvrir le micro pour entendre un double-clap, et rien d'autre.

    Le détecteur ne transcrit rien et ne garde rien : il suit le niveau
    sonore et cherche deux pics rapprochés. Aucune parole n'est analysée,
    aucun son n'est enregistré.
    """
    global _ecouteur_claps, _intention_ecoute, _echec_de_clap
    _intention_ecoute += 1
    # CONSTATER, pas supposer : la présence d'un objet n'est pas une écoute.
    # Tester l'objet plutôt que son état interdisait toute relance après la
    # mort silencieuse du fil — le micro restait fermé à vie.
    if claps_actifs():
        return {"listening": True, "already": True}
    if _ecouteur_claps is not None:
        ne_plus_ecouter()
        _intention_ecoute += 1
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
        global _echec_de_clap
        try:
            if session_active():
                desarmer()
                logger.info("double-clap : mode gestes désarmé")
            else:
                armer()
                logger.info("double-clap : mode gestes armé")
            _echec_de_clap = None
        except Exception as exc:  # noqa: BLE001
            _echec_de_clap = str(getattr(exc, "detail", exc))[:160]
            logger.warning("double-clap non traité : %s", _echec_de_clap)

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
    _echec_de_clap = None
    logger.info("écoute des claps démarrée")
    return {"listening": True}


@router.post("/clap/off")
def ne_plus_ecouter() -> dict[str, Any]:
    """Refermer le micro. Il ne doit pas rester ouvert par oubli."""
    global _ecouteur_claps, _intention_ecoute
    _intention_ecoute += 1
    ecouteur, _ecouteur_claps = _ecouteur_claps, None
    if ecouteur is not None:
        try:
            ecouteur.stop()
        except Exception:  # noqa: BLE001
            logger.debug("arrêt de l'écoute imparfait", exc_info=True)
    return {"listening": False}


# ── La mesure du seuil, en DEUX temps ───────────────────────────────────
# En un seul appel, l'interface devait DEVINER quand le serveur passait de
# « j'écoute la pièce » à « clape maintenant » : elle armait son minuteur
# avant d'envoyer la requête, alors que le compte du serveur ne démarre
# qu'une fois le micro ouvert. « Maintenant ! Clape » s'affichait donc
# pendant que le serveur écoutait encore le silence, et celui qui obéissait
# à l'écran polluait sa propre mesure — trois échecs sur quatre le 25 août
# 2026. En deux temps, personne n'a plus à deviner : le serveur rend la main
# quand la pièce est mesurée, et n'écoute les claps qu'après que l'ordre de
# claper a été donné.


def _prendre_le_micro() -> bool:
    """Refermer l'écoute pour libérer le micro. Rend son état d'avant."""
    ecoutait = claps_actifs()
    if ecoutait:
        ne_plus_ecouter()
    return ecoutait


def _rendre_le_micro(ecoutait: bool, intention: int) -> None:
    """Rouvrir l'écoute — mais seulement si personne ne l'a coupée entre
    temps.

    Sans ce garde-fou, décocher la case pendant une mesure rouvrait le micro
    huit secondes plus tard : l'état du serveur disait « écoute active » et
    l'interface affichait le micro éteint, jusqu'au prochain redémarrage.
    """
    if not ecoutait or _intention_ecoute != intention:
        return
    try:
        ecouter_les_claps()
    except HTTPException as exc:
        logger.warning("écoute non reprise après la mesure : %s", exc.detail)


@router.post("/clap/calibrate/room")
def mesurer_la_piece() -> dict[str, Any]:
    """Premier temps : écouter la pièce se taire."""
    global _piece_mesuree
    try:
        from diapason.speech.clap_listener import ecouter_la_piece
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"Écoute indisponible : {str(exc)[:120]}"
        ) from exc

    if not _verrou_calibration.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Une mesure est déjà en cours.")
    try:
        # L'intention se relève APRÈS la prise du micro : refermer l'écoute
        # l'incrémente elle-même, et la relever avant faisait échouer la
        # comparaison à tous les coups — l'écoute n'était alors jamais
        # reprise, ce que seul un test a révélé.
        ecoutait = _prendre_le_micro()
        intention = _intention_ecoute
        try:
            piece = ecouter_la_piece()
        except Exception as exc:  # noqa: BLE001
            # Un échec ne doit pas laisser sans écoute quelqu'un qui en avait.
            _rendre_le_micro(ecoutait, intention)
            raise HTTPException(
                status_code=503,
                detail=f"Le micro n'a pas pu être ouvert : {str(exc)[:120]}",
            ) from exc
        # Le micro reste fermé : le second temps le reprendra.
        _piece_mesuree = {
            "piece": piece,
            "ecoutait": ecoutait,
            "intention": intention,
            "a": time.monotonic(),
        }
    finally:
        _verrou_calibration.release()
    return {
        "roomLevel": round(piece.niveau, 4),
        "roomHigh": round(piece.haute, 4),
        "roomLoudest": round(piece.maximum, 4),
        "disturbed": piece.troublee,
    }


@router.post("/clap/calibrate/claps")
def mesurer_les_claps() -> dict[str, Any]:
    """Second temps : écouter claper, dans la pièce qu'on vient de mesurer."""
    global _piece_mesuree
    try:
        from diapason.speech.clap_listener import (
            ecouter_les_claps as ecouter_des_claps,
        )
        from diapason.speech.clap_listener import (
            enregistrer_reglage_claps,
            reglage_calibre,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"Écoute indisponible : {str(exc)[:120]}"
        ) from exc

    if not _verrou_calibration.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Une mesure est déjà en cours.")
    try:
        attente, _piece_mesuree = _piece_mesuree, None
        if attente is None or (time.monotonic() - attente["a"]) > _PEREMPTION_PIECE_S:
            raise HTTPException(
                status_code=409,
                detail="La pièce n'a pas été mesurée juste avant. Recommence.",
            )
        ecoutait, intention = attente["ecoutait"], attente["intention"]
        try:
            ecoute = ecouter_des_claps(attente["piece"])
            cfg = reglage_calibre(ecoute)
            enregistrer_reglage_claps(cfg)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503, detail=f"La mesure a échoué : {str(exc)[:120]}"
            ) from exc
        finally:
            # Quoi qu'il arrive, le micro revient dans l'état où l'utilisateur
            # l'a laissé. Hors du try, un échec d'écriture perdait l'écoute en
            # silence ; dans le chemin du raise, un 503 de reprise écrasait le
            # 422 qui disait quoi corriger.
            _rendre_le_micro(ecoutait, intention)
    finally:
        _verrou_calibration.release()

    piece = ecoute.piece
    # En WARNING : une calibration est rare et c'est le seul endroit où les
    # chiffres bruts existent. Journalisée en INFO, elle était invisible dans
    # les journaux du service, et il a fallu la redemander.
    logger.warning(
        "claps calibrés : pièce %.4f (haute %.4f, max %.4f), claps %s, "
        "écartés %s, seuil %.4f",
        piece.niveau,
        piece.haute,
        piece.maximum,
        [round(c, 3) for c in ecoute.claps],
        [round(c, 3) for c in ecoute.ecartes],
        cfg.min_rms,
    )
    return {
        "calibrated": True,
        "roomLevel": round(piece.niveau, 4),
        "roomHigh": round(piece.haute, 4),
        "roomLoudest": round(piece.maximum, 4),
        "clapPeaks": [round(c, 4) for c in ecoute.claps],
        "discarded": [round(c, 4) for c in ecoute.ecartes],
        "threshold": cfg.min_rms,
    }


@router.post("/clap/calibrate/reset")
def oublier_les_claps() -> dict[str, Any]:
    """Revenir au réglage d'usine. Le fil garde son seuil tant qu'il tourne :
    il faut donc le relancer pour que l'oubli prenne effet."""
    from diapason.speech.clap_listener import oublier_le_reglage_claps

    oublier_le_reglage_claps()
    if claps_actifs():
        ne_plus_ecouter()
        _rendre_le_micro(True, _intention_ecoute)
    return {"calibrated": False}


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
            **_etat_des_claps(),
            # Dire « OFF, zéro image » plutôt que d'omettre le champ : une
            # interface qui lit `undefined` garde sa cadence précédente, et
            # un mode désarmé continuerait de filmer.
            **_energie(),
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
        **_etat_des_claps(),
        **_energie(),
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
        # La question « vers lequel ? » voyage par le sondage qui existe
        # déjà : elle est posée par un geste, mais elle se répond à l'écran,
        # et l'écran n'est pas forcément celui du panneau.
        "pendingDrop": _choix_public(),
        "journal": list(reversed(_session.journal)),
        "recentStates": list(_session.derniers_etats),
    }


def _energie() -> dict[str, Any]:
    """L'état d'énergie et la cadence à appliquer (§83).

    Rendu par /state ET par /frame : passer par le seul sondage d'une
    seconde ferait travailler l'interface à l'ancienne cadence pendant
    jusqu'à une seconde après chaque changement — c'est-à-dire à chaque fois
    qu'une main entre dans le champ, le moment où la cadence compte le plus.
    """
    from diapason.desktop.energie_gestes import Energie, batterie, cadence, etat_energie

    if _session is None:
        return {"energy": Energie.ETEINT.value, "fps": 0}
    mesure = batterie()
    depuis = (
        None if _session.main_vue_a is None else time.monotonic() - _session.main_vue_a
    )
    etat = etat_energie(
        armee=True,
        depuis_derniere_main_s=depuis,
        sur_batterie=bool(mesure and mesure[1]),
        batterie_pct=mesure[0] if mesure else None,
    )
    return {"energy": etat.value, "fps": cadence(etat)}


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


def _oublier_la_main() -> None:
    """Vider le presse-papiers ET l'écho que l'interface en affiche.

    Les deux vont ensemble, toujours. Vider l'un sans l'autre laisse le
    voyant annoncer « dans ta main : Zéro à Héro » sur une main vide — le
    fantôme exact que le §12 interdit.
    """
    from diapason.desktop.presse_papiers_spatial import vider

    vider()
    if _session is not None:
        _session.dernier_attrape = None
        _session.depot_en_attente = None


def _commande_pour(objet: Any) -> tuple[str, dict[str, Any]] | None:
    """L'outil distant qui affiche cet objet, et ses arguments — ou rien.

    Rien : c'est un écran que le client mobile ne connaît pas. Aucun
    appareil ne l'acceptera jamais, donc ce n'est pas la peine d'aller
    interroger la flotte, ni de garder l'objet en main.
    """
    if objet.type != "screen":
        return (
            "app.show_resource",
            {"resourceType": objet.type, "resourceId": objet.id},
        )
    from diapason.desktop.contexte_app import _ECRANS

    route = (_ECRANS.get(objet.id) or (None, ""))[0]
    if not route:
        return None
    return "app.navigate", {"route": f"success://{route}"}


def _envoyer(objet: Any, cible: dict, *, cle: str = "") -> dict[str, Any]:
    """Envoyer pour de bon, et rendre ce que le RÉCEPTEUR en a dit."""
    from diapason.mesh.dispatch import dispatch_command

    commande = _commande_pour(objet)
    if commande is None:
        return {
            "done": False,
            "reason": "UNSUPPORTED",
            "object": objet.to_dict(),
            "message": f"{objet.titre} n'existe pas sur les autres appareils.",
        }
    outil, arguments = commande
    resultat = dispatch_command(
        target_device_id=str(cible.get("deviceId") or ""),
        tool=outil,
        arguments=arguments,
        idempotency_key=cle,
    )
    # La phrase vient du RÉCEPTEUR, jamais de ce qu'on a envoyé.
    return {
        "done": resultat.get("status") == "SUCCESS",
        "reason": resultat.get("status"),
        "object": objet.to_dict(),
        "target": str(cible.get("name") or "?"),
        "message": str(resultat.get("userSafeMessage") or ""),
    }


def _deposer() -> dict[str, Any]:
    """Ouvrir la main : envoyer ce qu'on tenait — ou dire pourquoi non.

    Le §34 gouverne : aucun capteur de cette flotte ne mesure une
    direction, donc rien n'est deviné. S'il n'y a qu'un seul appareil
    capable, c'est lui ; sinon on le dit et l'utilisateur tranche. Un
    geste ne doit jamais envoyer un document à un appareil choisi au
    hasard — ce serait l'échec le plus grave de cette fonctionnalité.

    **L'objet n'est lâché que sur une issue TERMINALE.** Il l'était
    autrefois dès la première ligne, avant même de savoir s'il existait une
    cible : une question « vers lequel ? » consommait donc ce qu'elle
    proposait d'envoyer, et refaire le geste ne pouvait que reposer la même
    question. Une main ne s'ouvre pas parce qu'on a demandé où viser.
    """
    from diapason.desktop.presse_papiers_spatial import tenu

    objet = tenu()
    if objet is None:
        _oublier_la_main()
        return {
            "done": False,
            "reason": "NOTHING_HELD",
            "message": "La main s'ouvre sur rien : rien n'avait été attrapé.",
        }

    commande = _commande_pour(objet)
    if commande is None:
        # Aucun appareil ne l'acceptera jamais : garder l'objet en main
        # serait promettre une seconde chance qui n'existe pas.
        _oublier_la_main()
        return {
            "done": False,
            "reason": "UNSUPPORTED",
            "object": objet.to_dict(),
            "message": f"{objet.titre} n'existe pas sur les autres appareils.",
        }
    capacite_requise = _capacite_de(commande[0])

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
        return {
            "done": False,
            "reason": "NO_FLEET",
            "message": str(exc)[:120],
            "object": objet.to_dict(),
        }

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

    # Un appareil joignable qui ne sait pas afficher cela n'est pas un
    # candidat : le proposer ferait poser une question dont une des
    # réponses est un refus garanti (dispatch le refuserait en UNSUPPORTED).
    capables = [
        d for d in joignables if capacite_requise in set(d.get("capabilities") or [])
    ]
    if not capables:
        noms = ", ".join(str(d.get("name") or "?") for d in joignables)
        return {
            "done": False,
            "reason": "INCAPABLE",
            "object": objet.to_dict(),
            "message": (
                f"« {objet.titre} » est prêt, mais aucun appareil joignable "
                f"ne sait l'afficher{' (' + noms + ')' if noms else ''}."
            ),
        }

    if len(capables) > 1:
        # §81 : deux candidats, aucune direction mesurée — on demande. Et on
        # garde la main fermée le temps de la réponse.
        return _demander_vers_lequel(objet, capables)

    return _issue_terminale(_envoyer(objet, capables[0]))


def _capacite_de(outil: str) -> str:
    """La capacité qu'un appareil doit déclarer pour accepter cet outil."""
    from diapason.mesh.tools import get_remote_tool

    spec = get_remote_tool(outil)
    return spec.capability if spec is not None else outil


def _issue_terminale(resultat: dict[str, Any]) -> dict[str, Any]:
    """L'envoi a eu lieu : l'intention est consommée, quel qu'en soit le sort.

    Y compris sur un échec. Un refus du récepteur n'est pas une invitation à
    garder l'objet en main : le geste a été fait, il a produit une réponse,
    et la refaire est un nouveau geste — pas une reprise silencieuse.
    """
    _oublier_la_main()
    return resultat


def _demander_vers_lequel(objet: Any, capables: list[dict]) -> dict[str, Any]:
    """Poser la question, et retenir de quoi accepter la réponse."""
    import secrets

    candidats = [
        {
            "deviceId": str(d.get("deviceId") or ""),
            "name": str(d.get("name") or "?"),
        }
        for d in capables
    ]
    jeton = secrets.token_urlsafe(8)
    if _session is not None:
        _session.depot_en_attente = {
            "jeton": jeton,
            "objet": objet,
            "candidats": candidats,
            "a": time.monotonic(),
        }
    return {
        "done": False,
        "reason": "AMBIGUOUS",
        "object": objet.to_dict(),
        "candidates": [c["name"] for c in candidats],
        "token": jeton,
        "message": (
            f"« {objet.titre} » est prêt. Vers lequel : "
            + ", ".join(c["name"] for c in candidats)
            + " ?"
        ),
    }


def _choix_en_attente() -> Optional[dict]:
    """Le dépôt qui attend une réponse, s'il en attend encore une.

    Trois horloges peuvent l'invalider — la sienne, celle de l'objet
    (TTL_S), et celle de la session. La sienne est la plus courte, mais
    l'objet peut disparaître autrement (une nouvelle saisie, un
    désarmement) : on le relit plutôt que de le supposer intact.
    """
    from diapason.desktop.presse_papiers_spatial import tenu

    if _session is None or not _session.depot_en_attente:
        return None
    attente = _session.depot_en_attente
    perime = time.monotonic() - float(attente["a"]) > _CHOIX_MAX_S
    if perime or tenu() is None:
        _session.depot_en_attente = None
        return None
    return attente


def _choix_public() -> Optional[dict]:
    """Ce que l'interface doit savoir pour afficher la question."""
    attente = _choix_en_attente()
    if attente is None:
        return None
    return {
        "token": attente["jeton"],
        "object": attente["objet"].to_dict(),
        "candidates": list(attente["candidats"]),
        "secondsLeft": round(
            max(0.0, _CHOIX_MAX_S - (time.monotonic() - float(attente["a"]))), 1
        ),
    }


# ── Ce que la VOIX et le CHAT peuvent atteindre ─────────────────────────
# Trois affectations, pas des alias d'import : `ruff --fix` supprime les
# seconds en les jugeant inutilisés (CLAUDE.md §5). Elles existent pour que
# `tools/gestes_spatiaux.py` réponde à la question posée par le geste au lieu
# d'en ouvrir une seconde — sans quoi un clic à l'écran et une réponse à la
# voix enverraient deux fois.
choix_en_attente = _choix_en_attente


def repondre_au_choix(attente: dict, cible: dict) -> dict[str, Any]:
    """Trancher une question en attente, et rendre ce que le récepteur a dit.

    Le jeton sert de clé d'idempotence : deux réponses — un clic ET une
    phrase — n'envoient qu'une fois.
    """
    resultat = _issue_terminale(_envoyer(attente["objet"], cible, cle=attente["jeton"]))
    if _session is not None:
        _session.dernier_depot = resultat
    _noter(
        "déposé" if resultat.get("done") else "dépôt refusé",
        str(resultat.get("message") or ""),
        reussi=bool(resultat.get("done")),
    )
    return resultat


def envoyer_ce_qui_est_tenu(objet: Any, cible: dict) -> dict[str, Any]:
    """Envoyer la main vers un appareil, sans question préalable.

    Le chemin de « envoie ça sur mon téléphone » quand aucune question n'est
    en suspens. Même règle que partout : la main ne se vide que sur une issue
    TERMINALE — un refus garde le poing fermé.
    """
    resultat = _issue_terminale(_envoyer(objet, cible))
    if _session is not None:
        _session.dernier_depot = resultat
    _noter(
        "déposé" if resultat.get("done") else "dépôt refusé",
        str(resultat.get("message") or ""),
        reussi=bool(resultat.get("done")),
    )
    return resultat


class ChoixDAppareil(BaseModel):
    """La réponse à « vers lequel ? » : le jeton posé, et un appareil."""

    token: str
    deviceId: str


@router.post("/drop/target")
def choisir_lappareil(body: ChoixDAppareil) -> dict[str, Any]:
    """Trancher entre les candidats, et envoyer pour de bon.

    Le `deviceId` reçu n'est jamais cru sur parole : il doit figurer dans la
    liste que le serveur a lui-même mesurée en posant la question. Un client
    ne choisit pas une destination, il choisit PARMI celles qu'on lui a
    proposées — c'est ce qui empêche cette route de devenir un « envoie
    n'importe quoi à n'importe qui » déguisé en réponse.
    """
    if not session_active() or _session is None:
        raise HTTPException(status_code=409, detail="Le mode gestes n'est pas armé.")
    attente = _choix_en_attente()
    if attente is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Aucun dépôt n'attend de réponse : la question a expiré, ou "
                "la main s'est vidée entre-temps."
            ),
        )
    if body.token != attente["jeton"]:
        raise HTTPException(
            status_code=409,
            detail="Ce jeton ne correspond pas à la question posée.",
        )
    cible = next(
        (c for c in attente["candidats"] if c["deviceId"] == body.deviceId), None
    )
    if cible is None:
        raise HTTPException(
            status_code=409,
            detail="Cet appareil ne faisait pas partie des candidats proposés.",
        )
    return repondre_au_choix(attente, cible)


@router.post("/drop/cancel")
def renoncer_au_depot() -> dict[str, Any]:
    """« Laisse tomber. » Sans cette route, la seule sortie serait le silence.

    Une question qui ne peut qu'expirer laisse l'utilisateur attendre
    quarante-cinq secondes pour apprendre qu'il ne se passera rien. Renoncer
    est une réponse ; elle mérite d'exister.
    """
    attente = _choix_en_attente()
    if attente is None:
        return {
            "cancelled": False,
            "message": "Aucun dépôt n'attendait de réponse.",
        }
    titre = attente["objet"].titre
    _oublier_la_main()
    resultat = {
        "done": False,
        "reason": "CANCELLED",
        "message": f"« {titre} » n'a été envoyé nulle part.",
    }
    if _session is not None:
        _session.dernier_depot = resultat
    _noter("abandonné", titre, reussi=False)
    return {"cancelled": True, **resultat}


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
    from diapason.desktop.presse_papiers_spatial import attraper
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
        # UNE main, alors que Vision en lit deux — un choix, pas une limite.
        # Le moteur n'a aucune notion d'identité de main : `observer()` reçoit
        # une liste de points et rien d'autre. À deux mains il faudrait deux
        # moteurs et une règle disant laquelle agit, sans quoi la seconde main
        # de l'utilisateur — ou celle de quelqu'un qui passe — deviendrait un
        # geste. Vision rend la plus SÛRE, ce qui est le bon défaut.
        #
        # La limite que ce choix ne corrige pas, et qu'il faut connaître :
        # avec deux mains dans le champ, celle qui gagne peut CHANGER d'une
        # image à l'autre. Le moteur verrait alors la main se téléporter, et
        # comme une main perdue annule le geste (§12), le geste échoue —
        # bruyamment, ce qui vaut mieux que de déposer au hasard.
        mains = mains_dans_les_octets(octets, mains_max=1)
    except Exception as exc:  # noqa: BLE001 - une image illisible n'arrête rien
        logger.debug("image de geste illisible", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Image illisible : {exc}") from exc

    points = mains[0] if mains else None
    if points:
        _session.mains_vues += 1
        _session.main_vue_a = _session.vue_a
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
            # Refermer le poing, c'est RECOMMENCER : une question restée sans
            # réponse tombe avec l'objet qu'elle désignait. Sans cela, le
            # jeton survivrait à son objet et désignerait la saisie suivante.
            _session.depot_en_attente = None
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
            # DANS UN FIL, et ce n'est pas une précaution de style. Cette
            # route est `async def`, donc elle s'exécute SUR la boucle
            # d'événements — alors que `_deposer` finit dans `httpx.post`
            # avec six secondes de délai d'attente (mesh/transport.py).
            # Un appareil qui ne répond pas gelait donc tout : le WebSocket
            # vocal, le flux du chat, la cloche d'approbation, et les images
            # de geste suivantes. Six secondes de Diapason entier, pour un
            # geste vers une machine éteinte.
            #
            # Les routes synchrones du module (`/drop/target`) n'ont pas ce
            # défaut : Starlette les exécute déjà dans un fil. C'était
            # `/frame`, et lui seul.
            _session.dernier_depot = await asyncio.to_thread(_deposer)
            _noter(
                "déposé" if _session.dernier_depot.get("done") else "dépôt refusé",
                str(_session.dernier_depot.get("message") or ""),
                reussi=bool(_session.dernier_depot.get("done")),
            )
        elif apres.value in ("PERDU", "ANNULE"):
            _session.pertes += 1
            # Une main perdue au milieu d'un geste ne laisse pas un objet
            # « tenu » que personne ne tient (§12) — ni une question en
            # suspens sur cet objet.
            _oublier_la_main()
    return {
        "state": apres.value,
        "changed": apres is not avant,
        "hand": bool(points),
        "frames": _session.images,
        **_energie(),
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
