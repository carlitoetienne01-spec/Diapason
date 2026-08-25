"""La caméra, ouverte le moins longtemps possible.

Spatial Mesh, gestes — 25 août 2026. Le suivi de main a besoin d'un flux,
pas d'une photo : un geste est une SUITE d'images, et une seule ne dit
jamais si la main se ferme ou s'ouvre.

Trois choses que ce module tient, et qui ne sont pas des détails :

**Le voyant vert dit la vérité.** La caméra ne s'ouvre que sur demande
explicite et se ferme dès qu'on ne s'en sert plus. Rien ne tourne « au cas
où » : c'est la différence entre un assistant et une caméra de surveillance.

**Aucune image ne quitte la machine, et aucune n'est gardée.** Le flux
vit en mémoire, la dernière image écrase la précédente, et seuls des
POINTS ARTICULAIRES en sortent — jamais des pixels. Le §10 du cahier des
charges le demande ; ici c'est structurel, pas une promesse.

**La dernière image gagne.** Si l'analyse d'une image n'est pas finie
quand la suivante arrive, la précédente est jetée. Une file d'images qui
s'allonge, c'est une main qu'on suit avec dix secondes de retard.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Assez pour qu'un geste se lise, assez peu pour que la machine respire.
# Le §85 demande d'adapter ; ceci est le régime « équilibré ».
IMAGES_PAR_SECONDE = 15

# La reconnaissance de main n'a pas besoin de netteté : une main occupe une
# grande partie du cadre. 640×480 suffit et coûte quatre fois moins que 720p.
_PRESET = "AVCaptureSessionPreset640x480"

_DELAI_AUTORISATION_S = 30.0


class CameraIndisponible(RuntimeError):
    """Pas de caméra, pas d'autorisation, ou pas de macOS. Jamais silencieux."""


def etat_autorisation() -> str:
    """« autorisée », « refusée », « à demander » — constaté, pas supposé."""
    try:
        import AVFoundation as AV
    except ImportError:
        return "indisponible"
    statut = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo)
    return {0: "à demander", 1: "restreinte", 2: "refusée", 3: "autorisée"}.get(
        statut, "inconnue"
    )


def demander_autorisation(delai_s: float = _DELAI_AUTORISATION_S) -> bool:
    """Demander l'accès à la caméra, et ATTENDRE la réponse de l'utilisateur.

    macOS affiche sa propre boîte de dialogue : c'est lui qui demande, pas
    nous, et c'est bien ainsi — une autorisation qu'une application peut
    contourner n'en est pas une.
    """
    import AVFoundation as AV

    statut = etat_autorisation()
    if statut == "autorisée":
        return True
    if statut in ("refusée", "restreinte"):
        return False

    repondu = threading.Event()
    accorde = {"valeur": False}

    def _retour(ok: bool) -> None:
        accorde["valeur"] = bool(ok)
        repondu.set()

    AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        AV.AVMediaTypeVideo, _retour
    )
    # LA BOUCLE D'ÉVÉNEMENTS, sans quoi rien n'apparaît. Constaté le 25 août
    # 2026 : le rappel n'était jamais appelé et la demande retombait en
    # « refusé » sans qu'aucune boîte de dialogue ne s'affiche. macOS a
    # besoin d'un fil qui tourne pour poser la question — un script qui
    # attend sur un verrou ne tourne pas.
    from Foundation import NSDate, NSRunLoop

    limite = time.monotonic() + delai_s
    boucle = NSRunLoop.currentRunLoop()
    while not repondu.is_set() and time.monotonic() < limite:
        boucle.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
    return accorde["valeur"]


def _pourquoi_refuse() -> str:
    """Dire la VRAIE raison, qui n'est pas celle qu'on croit.

    Constaté le 25 août 2026 : la demande revient refusée IMMÉDIATEMENT,
    sans qu'aucune boîte de dialogue n'apparaisse, et le statut reste « à
    demander ». macOS ne refuse pas la caméra à l'utilisateur — il refuse
    de lui POSER la question, parce que le processus demandeur n'est pas
    une application au sens du système : l'interpréteur Python d'uv est un
    exécutable nu, sans paquet, donc sans Info.plist, donc sans
    NSCameraUsageDescription. TCC exige cette clé pour afficher une
    demande ; sans elle, il n'y a rien à afficher.

    Le micro fonctionne, lui — mais son autorisation a été accordée par un
    autre chemin, à un moment où une application empaquetée la demandait.
    Ce n'est pas une contradiction : la permission suit le PAQUET, pas le
    binaire.

    Envoyer l'utilisateur dans les Réglages serait donc un mauvais conseil :
    il n'y trouverait aucune ligne à cocher.
    """
    if etat_autorisation() == "refusée":
        return (
            "Accès à la caméra refusé. Réglages Système → Confidentialité et "
            "sécurité → Caméra, puis autorise Diapason."
        )
    return (
        "macOS n'a pas posé la question : le processus qui demande n'est pas "
        "une application empaquetée (pas d'Info.plist, donc pas de "
        "NSCameraUsageDescription). Aucun réglage ne débloque cela — la "
        "capture doit être faite par l'application Diapason elle-même. "
        "Voir docs/spatial-mesh/GESTES.md."
    )


class FluxCamera:
    """Un flux ouvert, dont on lit la dernière image — jamais un historique."""

    def __init__(self, *, images_par_seconde: int = IMAGES_PAR_SECONDE) -> None:
        self._session: Any = None
        self._receveur: Any = None
        self._ips = max(1, min(30, int(images_par_seconde)))
        self._ouvert = False

    def __enter__(self) -> "FluxCamera":
        self.ouvrir()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.fermer()

    def ouvrir(self) -> None:
        """Allumer la caméra. Le voyant vert s'allume ici, et pas avant."""
        import objc
        from Foundation import NSObject

        try:
            import AVFoundation as AV
        except ImportError as exc:  # pragma: no cover - macOS seulement
            raise CameraIndisponible(
                "AVFoundation manque : uv pip install "
                "'pyobjc-framework-AVFoundation>=10'"
            ) from exc

        if not demander_autorisation():
            raise CameraIndisponible(_pourquoi_refuse())

        appareil = AV.AVCaptureDevice.defaultDeviceWithMediaType_(
            AV.AVMediaTypeVideo
        )
        if appareil is None:
            raise CameraIndisponible("Aucune caméra sur cette machine.")

        entree, erreur = AV.AVCaptureDeviceInput.deviceInputWithDevice_error_(
            appareil, None
        )
        if entree is None:
            raise CameraIndisponible(f"Caméra inutilisable : {erreur}")

        # La classe de réception est créée ici, une fois : PyObjC enregistre
        # les classes Objective-C globalement, et deux définitions du même
        # nom se disputeraient l'espace de noms du runtime.
        global _ClasseReceveur
        if _ClasseReceveur is None:

            class _Receveur(NSObject):
                def init(self):
                    self = objc.super(_Receveur, self).init()
                    if self is None:
                        return None
                    self._derniere = None
                    self._quand = 0.0
                    self._verrou = threading.Lock()
                    return self

                def captureOutput_didOutputSampleBuffer_fromConnection_(
                    self, _sortie, tampon, _connexion
                ):
                    # LA DERNIÈRE GAGNE : on écrase, on n'empile pas. Une
                    # file d'images qui s'allonge, c'est une main suivie
                    # avec dix secondes de retard.
                    import CoreMedia

                    pixels = CoreMedia.CMSampleBufferGetImageBuffer(tampon)
                    if pixels is None:
                        return
                    with self._verrou:
                        self._derniere = pixels
                        self._quand = time.monotonic()

                def derniere(self):
                    with self._verrou:
                        return self._derniere, self._quand

            _ClasseReceveur = _Receveur

        self._receveur = _ClasseReceveur.alloc().init()

        session = AV.AVCaptureSession.alloc().init()
        if session.canSetSessionPreset_(_PRESET):
            session.setSessionPreset_(_PRESET)
        session.addInput_(entree)

        sortie = AV.AVCaptureVideoDataOutput.alloc().init()
        # Le rejet des images en retard est fait par AVFoundation lui-même :
        # mieux vaut son mécanisme que notre file.
        sortie.setAlwaysDiscardsLateVideoFrames_(True)
        file_attente = _file_dispatch()
        sortie.setSampleBufferDelegate_queue_(self._receveur, file_attente)
        session.addOutput_(sortie)

        session.startRunning()
        self._session = session
        self._ouvert = True
        logger.info("caméra ouverte (%d im/s)", self._ips)

    def image(self, *, attente_s: float = 2.0) -> Optional[Any]:
        """La dernière image disponible, ou None si rien n'arrive."""
        if not self._ouvert or self._receveur is None:
            return None
        limite = time.monotonic() + attente_s
        while time.monotonic() < limite:
            pixels, _quand = self._receveur.derniere()
            if pixels is not None:
                return pixels
            time.sleep(0.02)
        return None

    def fermer(self) -> None:
        """Éteindre. Le voyant vert s'éteint ici — et il doit s'éteindre."""
        if self._session is not None:
            try:
                self._session.stopRunning()
            except Exception:  # noqa: BLE001 - une caméra qui refuse de se
                # fermer proprement doit quand même être oubliée
                logger.debug("arrêt de la caméra imparfait", exc_info=True)
        self._session = None
        self._receveur = None
        self._ouvert = False

    @property
    def ouvert(self) -> bool:
        return self._ouvert


_ClasseReceveur: Any = None
_file: Any = None


def _file_dispatch() -> Any:
    """La file sur laquelle les images arrivent — jamais le fil de l'interface.

    PyObjC n'expose aucune API de file de dispatch : on charge la fonction C
    et on enveloppe le pointeur. C'est le chemin standard, et il est stable
    depuis dix ans — mais il mérite d'être écrit une seule fois, ici.
    """
    global _file
    if _file is None:
        import ctypes

        import objc

        systeme = ctypes.CDLL("/usr/lib/libSystem.dylib")
        systeme.dispatch_queue_create.restype = ctypes.c_void_p
        systeme.dispatch_queue_create.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
        brut = systeme.dispatch_queue_create(b"diapason.camera", None)
        if not brut:
            raise CameraIndisponible("Impossible de créer la file de la caméra.")
        _file = objc.objc_object(c_void_p=ctypes.c_void_p(brut))
    return _file


__all__ = [
    "CameraIndisponible",
    "FluxCamera",
    "IMAGES_PAR_SECONDE",
    "demander_autorisation",
    "etat_autorisation",
]
