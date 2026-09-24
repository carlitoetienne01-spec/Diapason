"""Le compte local : les parcours P1 à P8, sans synchronisation.

Conception : ``docs/development/compte-chiffre.md`` §3.8 (routes locales),
§3.11 (parcours), §3.7 (sessions), §2.8 (rotation), §2.10 (où vit chaque
clé), §4.2 et §4.4 (état local, planchers), §6 bis.

Ce module orchestre : il dérive les clés (``cles``), ouvre et scelle le
coffre (``trousseau``), parle au serveur par ``client`` et ``transport``,
range l'état dans ``etat`` et l'AMK déverrouillée dans ``serrure``. Il ne
contient aucune route HTTP : ``server/compte_routes.py`` le traduit.

Ce qui ne se négocie pas ici :

- **jamais de 401 vers le bundle.** Un 401 du serveur de comptes devient
  :class:`SessionExpiree` (409 ``sessionExpired``) ; ``apiFetch`` rejoue les
  401 en rafraîchissant la clé d'API locale (§3.7) ;
- **sur ``sessionRevoked``**, l'AMK mémorisée, le jeton et l'enveloppe
  locale sont effacés : un changement de mot de passe fait ailleurs atteint
  cet appareil au premier contact (§3.7) ;
- **l'incarnation passée à l'ouverture est jugée par les planchers de
  l'appareil AVANT tout essai de clé** (§6 bis) ;
- **après une récupération par ``R``, les clés tournent AVANT toute
  écriture** (§2.11 bis) : le serveur ne reçoit aucune donnée sous un
  trousseau que l'appareil perdu aurait pu forger ;
- **le mot de passe n'entre dans aucun journal** : on n'y écrit que des
  codes.
"""

from __future__ import annotations

import logging
import platform
import secrets
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from diapason.compte import cles
from diapason.compte.cles import ErreurCompte, b64url
from diapason.compte.client import ClientComptes, Connexion, SessionOuverte
from diapason.compte.enveloppe import (
    CleServeurPerimee,
    EnveloppeIllisible,
    ouvrir_amk,
    ouvrir_nom_appareil,
    sceller_nom_appareil,
)
from diapason.compte.etat import (
    EnveloppeLocale,
    EtatLocal,
    Planchers,
    RetourArriereServeur,
    accueil_fait,
    marquer_accueil,
)
from diapason.compte.gardien import (
    ELEMENT_AMK,
    ELEMENT_SESSION,
    DossierCompte,
    ErreurGardien,
    Protecteur,
    choisir_protecteur,
    motif_refus_memorisation,
    preparer_dossier_compte,
)
from diapason.compte.recuperation import (
    cles_recuperation,
    formater_cle_recuperation,
    generer_cle_recuperation,
    lire_cle_recuperation,
)
from diapason.compte.serrure import LimiteDeverrouillage, Ouverture, Serrure
from diapason.compte.transport import ErreurServeur, Transport
from diapason.compte.trousseau import (
    GARDER,
    CleServeurInvalide,
    Coffre,
    Trousseau,
    creer_coffre,
    faire_tourner_les_cles,
    ouvrir_coffre,
    ouvrir_coffre_par_recuperation,
    ouvrir_trousseau,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DUREE_EN_ATTENTE_S",
    "ETATS",
    "EtatRefuse",
    "ExtraitFaux",
    "MotDePasseFaux",
    "RequeteInvalide",
    "ServiceCompte",
    "SessionExpiree",
    "fabriquer_protecteur",
    "preparer_dossier",
    "racine_du_compte",
]

# §2.7 : ``R`` n'est jamais stockée ; elle vit en mémoire du serveur local
# entre « préparer » et « terminer », 30 min au plus. Au-delà, une clé
# montrée à l'écran puis oubliée dans un onglet resterait dans le processus
# pour toute sa vie — et un ``shell_exec`` de l'assistant la lirait (A7).
DUREE_EN_ATTENTE_S = 30 * 60

# Les comptes ne sont PAS encore ouverts (24/09/2026). Le service de comptes
# n'est déployé nulle part : l'étape 7 (mise en service sur le VPS) attend
# qui héberge (D3), et l'ouverture est l'étape 13. La conception fermait les
# inscriptions côté serveur seulement (INSCRIPTIONS_OUVERTES=0), en
# supposant que l'interface sortirait en même temps que l'ouverture. Or l'app
# se reconstruit depuis main au fil de l'eau : sans ce verrou côté appareil,
# l'écran d'accueil proposait un compte qu'aucun serveur ne pouvait créer, et
# l'inscription échouait au premier appel réseau (§5 : une capacité que rien
# n'exerce est une promesse en attente). Le commit d'ouverture de l'étape 13
# le passe à True, avec INSCRIPTIONS_OUVERTES=1. Ni la configuration ni une
# variable d'environnement ne l'ouvrent : ce serait ouvrir une porte qui ne
# mène nulle part.
COMPTES_OUVERTS = False

# Les états que ``/v1/account/status`` peut rendre (§3.8).
#
# ``accountDeleted`` n'y est PLUS (24/09/2026) : le VPS ne l'émet jamais —
# un jeton inconnu vaut ``sessionRevoked`` (§6 bis) — et rien ici ne le
# posait. L'annoncer promettait à l'interface un écran que rien n'atteint ;
# un compte supprimé ailleurs se lit ``sessionExpired``, puis
# ``invalidCredentials`` avec ``reason: changedElsewhere`` (voir
# :meth:`ServiceCompte.connecter`).
ETATS = (
    "none",
    "signupInProgress",
    "locked",
    "unlocked",
    "sessionExpired",
    "resetPending",
    "accountReset",
    "serverRolledBack",
    "serverLost",
)
# Ceux qu'un événement du serveur a posés, et que seul un nouveau geste
# (connexion, récupération, réinitialisation) lève.
_ETATS_POSES = frozenset(
    {
        "sessionExpired",
        "accountReset",
        "serverRolledBack",
        "serverLost",
    }
)

_NOM_APPAREIL_MAX = 64


# ----------------------------------------------------------------------
# Ce que la fixture de test ``_isoler_le_compte`` redirige
# ----------------------------------------------------------------------


def racine_du_compte() -> Path:
    """``get_config_dir()`` en production. Les tests la redirigent vers un
    dossier jetable POUR TOUTE LA SESSION (``tests/conftest.py``) : ce Mac
    est aussi le runner de la CI, et un test qui écrirait dans le vrai
    ``~/.diapason/compte`` abîmerait l'état de Carlito."""
    from diapason.core.paths import get_config_dir

    return get_config_dir()


def preparer_dossier(racine: Path) -> DossierCompte:
    return preparer_dossier_compte(racine)


def fabriquer_protecteur(dossier: DossierCompte) -> Protecteur:
    """Le protecteur de cet appareil. Les tests le forcent en mémoire : le
    vrai trousseau de session macOS n'est touché que par les tests ``live``
    du gardien, qui construisent leur protecteur eux-mêmes."""
    return choisir_protecteur(dossier)


# ----------------------------------------------------------------------
# Erreurs propres au service
# ----------------------------------------------------------------------


class RequeteInvalide(ErreurCompte):
    code = "invalidRequest"

    def __init__(self, champ: str) -> None:
        super().__init__(f"champ invalide : {champ}")
        self.champ = champ


class EtatRefuse(ErreurCompte):
    """L'action n'a pas de sens dans l'état présent. Toujours un 409."""

    def __init__(self, code: str, message: str = "", *, raison: str | None = None):
        super().__init__(message or code, code=code)
        self.raison = raison


class SessionExpiree(ErreurCompte):
    """Ce qu'un 401 du serveur de comptes devient ici : 409, jamais 401."""

    code = "sessionExpired"


class MotDePasseFaux(ErreurCompte):
    code = "invalidPassword"


class ExtraitFaux(ErreurCompte):
    """Les deux groupes ressaisis ne sont pas ceux de la clé montrée."""

    code = "recoveryExcerptMismatch"


# ----------------------------------------------------------------------
# Ce qui attend en mémoire (30 min au plus)
# ----------------------------------------------------------------------


def _effacer(valeur: bytearray | None) -> None:
    if valeur is not None:
        for i in range(len(valeur)):
            valeur[i] = 0


@dataclass
class _Inscription:
    email: str
    expire: float
    signup_token: str | None = field(default=None, repr=False)
    account_id: str | None = None
    kdf_salt: bytes | None = field(default=None, repr=False)
    kdf_version: int | None = None
    kek: bytearray | None = field(default=None, repr=False)
    auth_key: bytes | None = field(default=None, repr=False)
    r: bytearray | None = field(default=None, repr=False)
    groupes: tuple[int, int] | None = None
    remember: bool = False

    def effacer(self) -> None:
        _effacer(self.kek)
        _effacer(self.r)
        self.kek = self.r = None
        self.auth_key = None
        self.signup_token = None


@dataclass
class _NouvelleCle:
    """``/recovery-key`` → ``/recovery-key/confirm`` (§3.8)."""

    account_id: str
    expire: float
    kdf_version: int
    r: bytearray = field(repr=False)
    groupes: tuple[int, int]
    kek: bytearray = field(repr=False)
    auth_key: bytes = field(repr=False)

    def effacer(self) -> None:
        _effacer(self.r)
        _effacer(self.kek)
        self.auth_key = b""


def _tirer_groupes() -> tuple[int, int]:
    """Deux groupes distincts parmi les huit, numérotés de 1 à 8."""
    premier = secrets.randbelow(8) + 1
    second = secrets.randbelow(7) + 1
    if second >= premier:
        second += 1
    return tuple(sorted((premier, second)))  # type: ignore[return-value]


_LECTURE_TOLERANTE = str.maketrans({"O": "0", "I": "1", "L": "1"})


def _normaliser_groupe(saisie: str) -> str:
    texte = unicodedata.normalize("NFKC", saisie).upper().translate(_LECTURE_TOLERANTE)
    return "".join(c for c in texte if c != "-" and not c.isspace())


def _verifier_extrait(r: bytes, groupes: tuple[int, int], extrait: object) -> None:
    """Preuve de sauvegarde (§2.7) : les deux groupes demandés, dans l'ordre."""
    if (
        not isinstance(extrait, list)
        or len(extrait) != 2
        or not all(isinstance(e, str) for e in extrait)
    ):
        raise RequeteInvalide("recoveryExcerpt")
    attendus = formater_cle_recuperation(r).split("-")
    justes = [
        secrets.compare_digest(_normaliser_groupe(saisie), attendus[g - 1])
        for g, saisie in zip(groupes, extrait)
    ]
    if not all(justes):
        raise ExtraitFaux("les groupes ressaisis ne correspondent pas à la clé")


def _code_six_chiffres(code: object) -> str:
    if not isinstance(code, str):
        raise RequeteInvalide("code")
    code = code.strip()
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        raise RequeteInvalide("code")
    return code


def _kdf_courante() -> int:
    """La version de KDF des mots de passe NEUFS : la plus haute connue."""
    return max(cles.VERSIONS_KDF)


def _maintenant_ms() -> int:
    return time.time_ns() // 1_000_000


def _nom_par_defaut() -> str:
    return (platform.node() or "Appareil")[:_NOM_APPAREIL_MAX]


# ----------------------------------------------------------------------
# Le service
# ----------------------------------------------------------------------


class ServiceCompte:
    """Un par serveur local, rangé dans ``app.state`` par ``compte_routes``.

    Construit sans rien toucher : le dossier, l'état et le protecteur ne
    sont préparés qu'au premier appel (:meth:`_preparer`). ``create_app``
    tourne dans chaque test du serveur ; un constructeur qui écrirait dans
    ``compte/`` ou interrogerait le trousseau l'aurait fait des centaines
    de fois par suite.
    """

    def __init__(
        self,
        *,
        dossier: DossierCompte | None = None,
        protecteur: Protecteur | None = None,
        transport: Transport | None = None,
        client_http: Any = None,
        config: Any = None,
        compter_conversations: Callable[[], int] | None = None,
        nom_appareil: Callable[[], str] | None = None,
        motif_memorisation: Callable[[Protecteur], str | None] | None = None,
        horloge_monotone: Callable[[], float] = time.monotonic,
        horloge_ms: Callable[[], int] = _maintenant_ms,
        ouverts: bool | None = None,
    ) -> None:
        self._dossier = dossier
        self._protecteur = protecteur
        self._transport = transport
        self._client_http = client_http
        self._config = config
        self._compter_conversations = compter_conversations
        # ``None`` : la constante du module, lue ici et non à l'import, pour
        # que le commit d'ouverture n'ait qu'une ligne à changer.
        self._ouverts = COMPTES_OUVERTS if ouverts is None else bool(ouverts)
        self._nom_appareil = nom_appareil or _nom_par_defaut
        self._motif_memorisation = motif_memorisation or motif_refus_memorisation
        self._mono = horloge_monotone
        self._ms = horloge_ms
        self.serrure = Serrure()
        self._limite = LimiteDeverrouillage(horloge=horloge_monotone)
        self._operation = threading.RLock()
        self._verrou_preparation = threading.Lock()
        self._pret = False
        self._geste = False
        self._inscription: _Inscription | None = None
        self._nouvelle_cle: _NouvelleCle | None = None
        self._etat: EtatLocal | None = None
        self._client: ClientComptes | None = None

    # ------------------------------------------------------------------
    # Préparation, fermeture
    # ------------------------------------------------------------------

    def _preparer(self) -> None:
        with self._verrou_preparation:
            premiere = not self._pret
            if premiere:
                self._construire()
        if premiere:
            self._rouvrir_si_memorise()
        self._purger_attentes()

    def _construire(self) -> None:
        if self._dossier is None:
            self._dossier = preparer_dossier(racine_du_compte())
        if self._protecteur is None:
            self._protecteur = fabriquer_protecteur(self._dossier)
        self._etat = EtatLocal(self._dossier)
        if self._transport is None:
            self._transport = Transport(
                actif=self._est_actif,
                client_http=self._client_http,
                config=self._config,
            )
        self._client = ClientComptes(self._transport)
        self._pret = True

    def _purger_attentes(self) -> None:
        """Efface ce qui attend en mémoire depuis plus de 30 min (§2.7).

        24/09/2026 : l'expiration de ``R`` en attente (et de la KEK qui
        l'accompagne) n'était jugée que dans ``nouvelle_cle_confirmer`` —
        après 24 h de ``status``, de verrouillages et de déverrouillages,
        elles étaient toujours dans le processus, lisibles par un
        ``shell_exec`` (A7). Toute entrée dans le service passe par
        :meth:`_preparer`, donc par ici.

        Sans attendre le verrou : ``status`` est sondé par les vues et ne
        doit pas rester bloqué derrière un appel de 15 s au serveur. Si une
        opération tient le verrou, elle jugera elle-même son attente ; on
        n'efface jamais une attente qu'une opération est en train de lire.
        """
        if not self._operation.acquire(blocking=False):
            return
        try:
            attente = self._nouvelle_cle
            if attente is not None and self._mono() > attente.expire:
                self._oublier_nouvelle_cle()
            self._en_attente_valide()
        finally:
            self._operation.release()

    def _oublier_nouvelle_cle(self) -> None:
        if self._nouvelle_cle is not None:
            self._nouvelle_cle.effacer()
        self._nouvelle_cle = None

    @property
    def etat(self) -> EtatLocal:
        self._preparer()
        assert self._etat is not None
        return self._etat

    @property
    def protecteur(self) -> Protecteur:
        self._preparer()
        assert self._protecteur is not None
        return self._protecteur

    @property
    def client(self) -> ClientComptes:
        self._preparer()
        assert self._client is not None
        return self._client

    @property
    def dossier(self) -> DossierCompte:
        self._preparer()
        assert self._dossier is not None
        return self._dossier

    def fermer(self) -> None:
        self.serrure.fermer()
        with self._operation:
            for attente in (self._inscription, self._nouvelle_cle):
                if attente is not None:
                    attente.effacer()
            self._inscription = self._nouvelle_cle = None
        if self._etat is not None:
            self._etat.fermer()
        if self._transport is not None:
            self._transport.fermer()

    def _est_actif(self) -> bool:
        """Condition 2 et 4 du §3.12 : un geste dans ce processus, ou un
        compte déjà enregistré sur cet appareil."""
        if self._geste:
            return True
        return self._etat is not None and bool(self._etat.lire("accountId"))

    # ------------------------------------------------------------------
    # Lecture de l'état
    # ------------------------------------------------------------------

    def _en_attente_valide(self) -> _Inscription | None:
        inscription = self._inscription
        if inscription is not None and self._mono() > inscription.expire:
            inscription.effacer()
            self._inscription = inscription = None
        return inscription

    def _etat_du_compte(self, valeurs: dict[str, str]) -> str:
        if not valeurs.get("accountId"):
            return "signupInProgress" if self._en_attente_valide() else "none"
        pose = valeurs.get("etatCompte")
        if pose in _ETATS_POSES:
            return pose
        attente = valeurs.get("pendingResetAt")
        # Seulement une date À VENIR (24/09/2026) : une valeur locale passée
        # — réinitialisation terminée ou annulée ailleurs, réponse perdue —
        # laissait le bandeau « prévue le {date passée} — [Annuler] »
        # indéfiniment. ``pendingResetAt`` reste rendu tel quel : l'écran
        # peut dire « réinitialisation possible depuis le {date} ».
        if attente and int(attente) > self._ms():
            return "resetPending"
        return "unlocked" if self.serrure.ouverte else "locked"

    def statut(self) -> dict[str, Any]:
        """``GET /v1/account/status`` — recalculé à chaque lecture, sans
        réseau et sans créer ``etat.key`` (§4.11)."""
        self._preparer()
        valeurs = self.etat.tout()
        etat = self._etat_du_compte(valeurs)
        connecte = bool(valeurs.get("accountId"))
        motif = self._motif_memorisation(self.protecteur)
        recuperation = valeurs.get("recoveryConfigured") == "1"
        memorise = valeurs.get("remembered") == "1"
        attente = valeurs.get("pendingResetAt")
        conversations = None
        if self._compter_conversations is not None:
            try:
                conversations = int(self._compter_conversations())
            except Exception:  # noqa: BLE001 - un compte n'est pas un magasin
                conversations = None
        if etat != "unlocked" and connecte:
            synchro = "paused"
        elif (
            connecte and valeurs.get("consentement") != "1" and (conversations or 0) > 0
        ):
            synchro = "needsConsent"
        else:
            # Aucun moteur à l'étape 8 : « désactivée » est la seule vérité.
            synchro = "disabled"
        return {
            "state": etat,
            "unlocked": self.serrure.ouverte,
            "email": valeurs.get("email") if connecte else None,
            "remembered": memorise,
            "protector": self.protecteur.nom,
            "rememberAllowed": motif is None,
            "rememberRefusal": motif,
            "recoveryConfigured": recuperation,
            # Ce que CET appareil sait : le serveur ignore quels appareils
            # ont mémorisé l'AMK, et n'en saura jamais rien (§2.9). Zéro
            # moyen de secours reste affiché comme tel (D4).
            "backupMeans": {
                "recoveryKey": recuperation,
                "rememberedDevices": (1 if memorise else 0) if connecte else None,
            },
            "onboarding": "done" if accueil_fait(self.dossier) else "pending",
            "localConversations": conversations,
            "sync": {
                "state": synchro,
                "serverSeq": None,
                "lastConfirmedAt": None,
                "pendingCount": None,
                "quarantinedCount": None,
                "repairedCount": None,
                "errorCode": None,
            },
            "clockSkewMs": None,
            "pendingResetAt": int(attente) if attente else None,
            # Faux tant que les comptes ne sont pas ouverts : l'interface ne
            # propose alors ni l'écran d'accueil ni l'inscription.
            "accountsOpen": self._ouverts,
            "serverOrigin": self._transport.origine if self._transport else None,
            # Faux quand ``local_only`` refuserait l'origine configurée (une
            # surcharge ``DIAPASON_SERVEUR_COMPTES``) : l'écran d'activation
            # dit le refus avant le geste, au lieu de nommer une destination
            # qui ne sera jamais jointe (§3.12, condition 1).
            "serverOriginAllowed": (
                self._transport.origine_permise() if self._transport else False
            ),
            "lastKeyChangeAt": (
                int(valeurs["dernierCommitMs"])
                if valeurs.get("dernierCommitMs")
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Outils internes
    # ------------------------------------------------------------------

    def _jeton(self) -> str | None:
        account_id = self.etat.lire("accountId")
        if not account_id:
            return None
        try:
            brut = self.protecteur.lire(account_id, ELEMENT_SESSION)
        except ErreurGardien as exc:
            logger.warning("compte : jeton de session illisible (%s)", exc.code)
            return None
        return None if brut is None else brut.decode("utf-8")

    def _avec_session(self, appel: Callable[[Callable[[], str | None]], Any]) -> Any:
        """Un appel authentifié. Un 401 du serveur devient 409 ici (§3.7)."""
        try:
            return appel(self._jeton)
        except ErreurServeur as exc:
            if exc.statut != 401:
                raise
            self._session_perdue(exc.code)
            raise SessionExpiree(
                "la session de cet appareil n'est plus valable"
            ) from None

    def _session_perdue(self, code: str) -> None:
        """``sessionRevoked`` : un changement de secret fait ailleurs, une
        déconnexion à distance, un compte supprimé. L'AMK mémorisée, le
        jeton et l'enveloppe locale partent (§3.7) — ils appartiennent à des
        clés qui ne sont plus celles du compte. Une clé de récupération en
        attente de confirmation part aussi : elle aurait été scellée pour
        un trousseau mort.

        ``sessionExpired`` (90 jours sans contact) ne compromet rien : on
        redemande seulement le mot de passe, et le jeton RESTE. Il n'ouvre
        plus rien, mais le VPS répond ``sessionExpired`` tant que la ligne
        existe (30 jours de grâce) et ``sessionRevoked`` dès qu'une
        rotation ou une réinitialisation l'a effacée : c'est la seule preuve
        qu'a cet appareil qu'aucune réinitialisation n'a eu lieu depuis, et
        :meth:`_incarnation_confirmee` en a besoin (24/09/2026 — l'effacer
        condamnait la réinitialisation d'un appareil resté 90 jours sans
        contact, c'est-à-dire précisément de qui a oublié son mot de passe).
        """
        account_id = self.etat.lire("accountId")
        logger.info("compte : session refusée par le serveur (%s)", code)
        if code == "sessionExpired":
            self.etat.ecrire(etatCompte="sessionExpired")
            return
        if account_id:
            self._effacer_secret(account_id, ELEMENT_SESSION)
            self._effacer_secret(account_id, ELEMENT_AMK)
        self.etat.effacer_enveloppe_locale()
        self.etat.ecrire(
            etatCompte="sessionExpired",
            sessionId=None,
            remembered=False,
            sessionRevoquee=True,
        )
        self.serrure.fermer()
        self._oublier_nouvelle_cle()

    def _effacer_secret(self, account_id: str, element: str) -> None:
        try:
            self.protecteur.effacer(account_id, element)
        except ErreurGardien as exc:
            logger.warning(
                "compte : %s non effacé du protecteur (%s)", element, exc.code
            )

    def _verifier_memorisation(self, remember: object) -> bool:
        if not isinstance(remember, bool):
            raise RequeteInvalide("remember")
        if remember:
            motif = self._motif_memorisation(self.protecteur)
            if motif is not None:
                raise EtatRefuse(
                    "rememberNotAllowed",
                    "« Garder cet appareil déverrouillé » est refusé ici",
                    raison=motif,
                )
        return remember

    def _exiger_compte(self) -> tuple[str, dict[str, str]]:
        valeurs = self.etat.tout()
        account_id = valeurs.get("accountId")
        if not account_id:
            raise EtatRefuse("notConnected", "aucun compte sur cet appareil")
        return account_id, valeurs

    def _exiger_ouverture(self) -> tuple[Ouverture, dict[str, str]]:
        """Compte présent, aucun état posé par le serveur, AMK en mémoire."""
        account_id, valeurs = self._exiger_compte()
        pose = valeurs.get("etatCompte")
        if pose in _ETATS_POSES:
            raise EtatRefuse(pose, "le compte doit d'abord être rouvert")
        ouverture = self.serrure.exiger()
        if ouverture.account_id != account_id:
            self.serrure.fermer()
            raise EtatRefuse("notConnected", "la serrure ne tient pas ce compte")
        return ouverture, valeurs

    def _refuser_si_deja_ouvert(self) -> None:
        """Connexion et récupération refusées sur un appareil ouvert — SAUF
        si le serveur a posé un état (session expirée, retour arrière…) :
        une session expirée après 90 jours laisse la serrure ouverte, et
        refuser la reconnexion aurait obligé à verrouiller d'abord, sans
        que rien à l'écran ne le dise."""
        if not self.serrure.ouverte:
            return
        if self.etat.lire("etatCompte") in _ETATS_POSES:
            self.serrure.fermer()
            return
        raise EtatRefuse("alreadyConnected", "cet appareil est déjà déverrouillé")

    def _enveloppe(self) -> EnveloppeLocale:
        enveloppe = self.etat.enveloppe_locale()
        if enveloppe is None:
            raise SessionExpiree("l'enveloppe locale a été effacée : reconnectez-vous")
        return enveloppe

    def _verifier_localement(
        self,
        kek: bytes,
        enveloppe: EnveloppeLocale,
        account_id: str,
        incarnation: int,
    ) -> None:
        """Le mot de passe actuel, jugé contre l'enveloppe de CET appareil —
        sans réseau, et sans consommer un essai des délais de ``/login``."""
        planchers = self.etat.planchers()
        try:
            ouvrir_amk(
                kek,
                enveloppe.amk_mdp,
                account_id=account_id,
                incarnation=incarnation,
                kdf_version=enveloppe.kdf_version,
                vault_version=enveloppe.version_coffre,
                plancher_vault_version=planchers.vault_version_max if planchers else 0,
            )
        except EnveloppeIllisible:
            raise MotDePasseFaux("mot de passe incorrect") from None

    def _juger_mot_de_passe(
        self,
        mot_de_passe: str,
        email: str,
        enveloppe: EnveloppeLocale,
        account_id: str,
        incarnation: int,
    ) -> cles.ClesMotDePasse:
        """Tout jugement LOCAL du mot de passe passe par ici, et donc par la
        limite de ``unlock`` : 5 échecs, puis 30 s (§3.8).

        24/09/2026 : seul ``unlock`` comptait ses échecs. ``/delete`` (même
        appareil verrouillé), ``/password``, ``/recovery-key``,
        ``/recovery-key/remove`` et ``/devices/{id}/disconnect`` jugeaient
        le mot de passe contre la même enveloppe sans limite : 50 essais
        de suite sur ``/delete`` rendaient 50 ``invalidPassword``, et un
        31e ``currentPassword`` juste sur ``/password`` remplaçait le mot de
        passe — la limite était décorative (CLAUDE.md §5). La limite est
        vérifiée AVANT Argon2id : un essai refusé ne coûte pas une dérivation.
        """
        self._limite.verifier()
        derivees = cles.deriver_cles_mot_de_passe(
            mot_de_passe, email, enveloppe.sel_kdf, enveloppe.kdf_version
        )
        try:
            self._verifier_localement(derivees.kek, enveloppe, account_id, incarnation)
        except MotDePasseFaux:
            self._limite.echec()
            raise
        self._limite.reussite()
        return derivees

    def _incarnation_locale(self, valeurs: dict[str, str]) -> int:
        return int(valeurs.get("incarnation") or "1")

    def _effacer_compte_local(self, account_id: str | None) -> None:
        """Déconnexion, suppression, autre compte : tout part (§4.4)."""
        self.serrure.fermer()
        if account_id:
            self._effacer_secret(account_id, ELEMENT_AMK)
            self._effacer_secret(account_id, ELEMENT_SESSION)
        self.etat.detruire()
        for attente in (self._inscription, self._nouvelle_cle):
            if attente is not None:
                attente.effacer()
        self._inscription = self._nouvelle_cle = None
        self._geste = False

    def _exiger_compte_a_reinitialiser(
        self, email: str
    ) -> tuple[str, dict[str, str], Planchers]:
        """La réinitialisation ne se DÉMARRE que sur un appareil qui connaît
        ce compte : c'est le seul qui pourra la terminer (l'AAD du coffre
        neuf porte l'incarnation suivante, que seuls ses planchers tiennent).

        24/09/2026 : le refus n'arrivait qu'à ``reset/complete``. Un
        appareil inconnu programmait une réinitialisation — courriel « prévue »
        et avertissement sur tous les appareils — qu'il ne pouvait ni suivre
        (aucun ``pendingResetAt`` écrit) ni terminer : sept jours plus tard,
        ``resetNeedsKnownAccount``. L'impasse du §34, avec une alerte pour
        rien. Le refus précède maintenant tout appel au VPS.
        """
        valeurs = self.etat.tout()
        account_id = valeurs.get("accountId")
        planchers = self.etat.planchers()
        if (
            not account_id
            or valeurs.get("email") != email
            or planchers is None
            or planchers.account_id != account_id
        ):
            raise EtatRefuse(
                "resetNeedsKnownAccount",
                "la réinitialisation se fait depuis un appareil qui connaît ce compte",
                raison="unknownAccount",
            )
        return account_id, valeurs, planchers

    def _incarnation_confirmee(
        self, account_id: str, valeurs: dict[str, str], planchers: Planchers
    ) -> int:
        """L'incarnation COURANTE du compte, confirmée par le serveur — ou un
        refus. Jamais devinée.

        ``reset/complete`` ouvre ``incarnation + 1`` et efface tout AVANT que
        le client lise sa réponse ; le coffre neuf doit donc être scellé
        pour la bonne incarnation dès l'envoi. 24/09/2026, contre-épreuve :
        A réinitialise (1 → 2) ; B, qui ne s'est pas reconnecté depuis,
        réinitialise à son tour avec ses planchers restés à 1. Sa
        confrontation à ``/account`` échouait (session effacée par la
        réinitialisation de A), l'échec était journalisé et le calcul
        continuait : B scellait pour 2, le VPS ouvrait 3, et le compte était
        muré — le nouveau mot de passe se lisait ``envelopeUnreadable`` sur
        tout appareil, comme un mot de passe faux (§34, §100).

        Deux preuves seulement :

        - ``GET /account`` répond, pour ce compte, l'incarnation que tient
          cet appareil ;
        - ``401 sessionExpired`` : la ligne de session existe encore, et une
          réinitialisation (ou une rotation) l'aurait effacée — le VPS
          aurait dit ``sessionRevoked``.

        Tout le reste — pas de jeton, ``sessionRevoked``, une autre
        incarnation — refuse avec ``resetNeedsKnownAccount`` /
        ``incarnationUnconfirmed``. La vraie correction est au contrat du
        VPS (``reset/complete`` refusant une ``expectedIncarnation``
        différente, AVANT tout effacement) : décision à Carlito.
        """
        locale = max(planchers.incarnation_max, self._incarnation_locale(valeurs))

        def refus() -> EtatRefuse:
            return EtatRefuse(
                "resetNeedsKnownAccount",
                "l'incarnation du compte ne peut pas être confirmée depuis cet "
                "appareil",
                raison="incarnationUnconfirmed",
            )

        jeton = self._jeton()
        if not jeton:
            raise refus()
        try:
            compte = self.client.account(lambda: jeton)
        except ErreurServeur as exc:
            if exc.statut != 401:
                raise
            self._session_perdue(exc.code)
            if exc.code == "sessionExpired":
                return locale
            raise refus() from None
        if compte.get("accountId") != account_id or compte["incarnation"] != locale:
            raise refus()
        return locale

    def _rouvrir_si_memorise(self) -> None:
        """Au démarrage : l'AMK mémorisée rouvre le trousseau local (§2.11)."""
        etat = self._etat
        if etat is None or self.serrure.ouverte:
            return
        valeurs = etat.tout()
        account_id = valeurs.get("accountId")
        if not account_id or valeurs.get("remembered") != "1":
            return
        if valeurs.get("etatCompte") in _ETATS_POSES:
            return
        enveloppe = etat.enveloppe_locale()
        planchers = etat.planchers()
        if enveloppe is None or planchers is None:
            return
        try:
            assert self._protecteur is not None
            amk = self._protecteur.lire(account_id, ELEMENT_AMK)
            if amk is None:
                etat.ecrire(remembered=False)
                return
            incarnation = self._incarnation_locale(valeurs)
            trousseau = ouvrir_trousseau(
                amk,
                enveloppe.trousseau,
                account_id=account_id,
                incarnation=incarnation,
                keyring_version=enveloppe.version_trousseau,
                vault_version=enveloppe.version_coffre,
                plancher_keyring_version=planchers.keyring_version_max,
                plancher_vault_version=planchers.vault_version_max,
            )
        except ErreurCompte as exc:
            logger.warning("compte : AMK mémorisée inutilisable (%s)", exc.code)
            return
        self.serrure.ouvrir(
            amk, trousseau, account_id=account_id, incarnation=incarnation
        )

    def _installer(
        self,
        *,
        account_id: str,
        email: str,
        incarnation: int,
        sel_kdf: bytes,
        kdf_version: int,
        coffre_amk: bytes,
        coffre_trousseau: bytes,
        vault_version: int,
        keyring_version: int,
        amk: bytes,
        trousseau: Trousseau,
        session_id: str,
        jeton: str,
        remember: bool,
        recovery_configured: bool,
        pending_reset_at: int | None,
        autres: dict[str, Any] | None = None,
    ) -> None:
        """Ce qu'une session ouverte laisse sur l'appareil, en une fois.

        ``autres`` entre dans la MÊME écriture que ``accountId`` : un marqueur
        écrit après, derrière un appel réseau, pouvait manquer pour toujours
        (voir ``epoqueAuthentifieeMin`` dans :meth:`recuperer`)."""
        actuel = self.etat.lire("accountId")
        if actuel and actuel != account_id:
            # Un autre compte : la portée entière part, planchers compris
            # (§4.4, « une déconnexion ou un autre compte vide tout »).
            self._effacer_compte_local(actuel)
            self._geste = True
        self.etat.relever_planchers(
            account_id,
            incarnation,
            vault_version=vault_version,
            keyring_version=keyring_version,
            key_epoch=trousseau.current_epoch,
        )
        self.etat.ranger_enveloppe_locale(
            EnveloppeLocale(
                kdf_version=kdf_version,
                sel_kdf=sel_kdf,
                amk_mdp=coffre_amk,
                trousseau=coffre_trousseau,
                version_coffre=vault_version,
                version_trousseau=keyring_version,
            )
        )
        self.protecteur.ranger(account_id, ELEMENT_SESSION, jeton.encode("utf-8"))
        if remember:
            self.protecteur.ranger(account_id, ELEMENT_AMK, amk)
        else:
            self._effacer_secret(account_id, ELEMENT_AMK)
        self.etat.ecrire(
            accountId=account_id,
            email=email,
            incarnation=incarnation,
            sessionId=session_id,
            etatCompte=None,
            remembered=remember,
            recoveryConfigured=recovery_configured,
            pendingResetAt=pending_reset_at,
            sessionRevoquee=None,
            **(autres or {}),
        )
        self.serrure.ouvrir(
            amk, trousseau, account_id=account_id, incarnation=incarnation
        )

    def _nommer_session(self) -> None:
        """Le nom de cet appareil, scellé sous ``K_noms`` (type 04). Au mieux :
        un échec ici ne défait pas une connexion réussie."""
        try:
            ouverture = self.serrure.exiger()
            session_id = self.etat.lire("sessionId")
            if not session_id:
                return
            blob = sceller_nom_appareil(
                cles.cle_noms_appareils(ouverture.amk),
                self._nom_appareil()[:_NOM_APPAREIL_MAX],
                account_id=ouverture.account_id,
                session_id=session_id,
                key_epoch=ouverture.trousseau.current_epoch,
            )
            self._avec_session(lambda jeton: self.client.nommer_session(blob, jeton))
        except ErreurCompte as exc:
            logger.info("compte : nom d'appareil non envoyé (%s)", exc.code)

    def _abandonner_session(self, jeton: str) -> None:
        """Une session ouverte par ``/login`` dont le coffre est refusé : on
        la referme, pour ne pas laisser au serveur un jeton sans appareil."""
        try:
            self.client.logout(lambda: jeton)
        except ErreurCompte as exc:
            logger.info("compte : session refusée non refermée (%s)", exc.code)

    # ------------------------------------------------------------------
    # La rotation (§2.8)
    # ------------------------------------------------------------------

    def _tourner(
        self,
        *,
        account_id: str,
        email: str,
        incarnation: int,
        trousseau: Trousseau,
        vault_version: int,
        keyring_version: int,
        kek: bytes,
        auth_key: bytes,
        kdf_version: int,
        sel_kdf: bytes,
        preuve: dict[str, Any],
        recuperation: Any = GARDER,
        auth_recuperation: bytes | None = None,
        session_revoquee: str | None = None,
        avec_session: bool = True,
        remember: bool | None = None,
        ecrire_aussi: Callable[[Coffre], dict[str, Any]] | None = None,
    ) -> Coffre:
        """Les étapes 1 à 5 du §2.8, puis l'installation locale.

        ``recuperation`` : ``GARDER`` (la clé du trousseau déchiffré),
        ``None`` (retirer) ou une clé publique neuve (remplacer, avec
        ``auth_recuperation``).
        """
        coffre = faire_tourner_les_cles(
            trousseau,
            kek=kek,
            account_id=account_id,
            incarnation=incarnation,
            kdf_version=kdf_version,
            vault_version=vault_version,
            keyring_version=keyring_version,
            recovery_public_key=recuperation,
        )
        if coffre.enveloppe_amk_recuperation is None:
            corps_recuperation: dict[str, Any] = {"mode": "remove"}
        elif recuperation is GARDER:
            corps_recuperation = {
                "mode": "keep",
                "sealedMasterKey": b64url(coffre.enveloppe_amk_recuperation),
            }
        else:
            assert auth_recuperation is not None
            corps_recuperation = {
                "mode": "replace",
                "authKey": b64url(auth_recuperation),
                "sealedMasterKey": b64url(coffre.enveloppe_amk_recuperation),
            }

        def appel(jeton: Callable[[], str | None] | None) -> Any:
            return self.client.vault_commit(
                preuve=preuve,
                base_vault_version=vault_version,
                base_keyring_version=keyring_version,
                new_vault_version=coffre.vault_version,
                new_keyring_version=coffre.keyring_version,
                new_key_epoch=coffre.trousseau.current_epoch,
                kdf_version=kdf_version,
                auth_key=auth_key,
                enveloppe_amk=coffre.enveloppe_amk,
                recuperation=corps_recuperation,
                enveloppe_trousseau=coffre.enveloppe_trousseau,
                session_revoquee=session_revoquee,
                jeton=jeton,
            )

        rotation = self._avec_session(appel) if avec_session else appel(None)
        if (
            rotation.vault_version != coffre.vault_version
            or rotation.keyring_version != coffre.keyring_version
            or rotation.key_epoch != coffre.trousseau.current_epoch
        ):
            raise CleServeurInvalide(
                "le serveur annonce d'autres versions que le commit"
            )
        valeurs = self.etat.tout()
        if remember is None:
            remember = valeurs.get("remembered") == "1"
        attente = (
            valeurs.get("pendingResetAt")
            if valeurs.get("accountId") == account_id
            else None
        )
        self._installer(
            account_id=account_id,
            email=email,
            incarnation=incarnation,
            sel_kdf=sel_kdf,
            kdf_version=kdf_version,
            coffre_amk=coffre.enveloppe_amk,
            coffre_trousseau=coffre.enveloppe_trousseau,
            vault_version=coffre.vault_version,
            keyring_version=coffre.keyring_version,
            amk=coffre.amk,
            trousseau=coffre.trousseau,
            session_id=rotation.session_id,
            jeton=rotation.jeton,
            remember=remember,
            recovery_configured=coffre.enveloppe_amk_recuperation is not None,
            pending_reset_at=int(attente) if attente else None,
            autres={
                "dernierCommitMs": self._ms(),
                **(ecrire_aussi(coffre) if ecrire_aussi else {}),
            },
        )
        self._nommer_session()
        return coffre

    def _rotation_depuis_ici(
        self,
        ouverture: Ouverture,
        valeurs: dict[str, str],
        enveloppe: EnveloppeLocale,
        **arguments: Any,
    ) -> Coffre:
        return self._tourner(
            account_id=ouverture.account_id,
            email=valeurs["email"],
            incarnation=ouverture.incarnation,
            trousseau=ouverture.trousseau,
            vault_version=enveloppe.version_coffre,
            keyring_version=enveloppe.version_trousseau,
            sel_kdf=enveloppe.sel_kdf,
            **arguments,
        )

    # ------------------------------------------------------------------
    # P1 — inscription
    # ------------------------------------------------------------------

    def _refuser_si_fermes(self) -> None:
        """Refuse un parcours qui contacterait le serveur de comptes tant
        que les comptes ne sont pas ouverts — AVANT tout appel réseau."""
        if not self._ouverts:
            raise EtatRefuse(
                "accountsNotOpen",
                "les comptes Diapason ne sont pas encore ouverts",
            )

    def inscription_debut(self, email: object, conditions_acceptees: object) -> None:
        with self._operation:
            self._refuser_si_fermes()
            self._preparer()
            if conditions_acceptees is not True:
                raise RequeteInvalide("termsAccepted")
            if not isinstance(email, str):
                raise RequeteInvalide("email")
            email = cles.normaliser_courriel(email)
            valeurs = self.etat.tout()
            if self._etat_du_compte(valeurs) in {"locked", "unlocked", "resetPending"}:
                raise EtatRefuse("alreadyConnected", "un compte est déjà ouvert ici")
            if self._inscription is not None:
                self._inscription.effacer()
            self._geste = True
            self._inscription = None
            self.client.signup_start(email)
            self._inscription = _Inscription(
                email=email, expire=self._mono() + DUREE_EN_ATTENTE_S
            )

    def _exiger_inscription(self) -> _Inscription:
        inscription = self._en_attente_valide()
        if inscription is None:
            raise EtatRefuse("noPendingSignup", "recommencez l'inscription")
        return inscription

    def inscription_code(self, code: object) -> None:
        with self._operation:
            self._preparer()
            inscription = self._exiger_inscription()
            code = _code_six_chiffres(code)
            jeton, account_id, sel = self.client.signup_verify(inscription.email, code)
            inscription.signup_token = jeton
            inscription.account_id = account_id
            inscription.kdf_salt = sel

    def inscription_preparer(
        self, mot_de_passe: object, remember: object
    ) -> dict[str, Any]:
        with self._operation:
            self._preparer()
            inscription = self._exiger_inscription()
            if inscription.signup_token is None or inscription.kdf_salt is None:
                raise EtatRefuse("noPendingSignup", "le code n'a pas été vérifié")
            if not isinstance(mot_de_passe, str):
                raise RequeteInvalide("password")
            cles.verifier_mot_de_passe(mot_de_passe, inscription.email)
            inscription.remember = self._verifier_memorisation(remember)
            kdf = _kdf_courante()
            derivees = cles.deriver_cles_mot_de_passe(
                mot_de_passe, inscription.email, inscription.kdf_salt, kdf
            )
            _effacer(inscription.kek)
            _effacer(inscription.r)
            inscription.kdf_version = kdf
            inscription.kek = bytearray(derivees.kek)
            inscription.auth_key = derivees.auth_key
            inscription.r = bytearray(generer_cle_recuperation())
            inscription.groupes = _tirer_groupes()
            return {
                "recoveryKey": formater_cle_recuperation(bytes(inscription.r)),
                "confirmGroups": list(inscription.groupes),
            }

    def inscription_terminer(self, extrait: object, sans_cle: object) -> None:
        with self._operation:
            self._preparer()
            inscription = self._exiger_inscription()
            if (
                inscription.kek is None
                or inscription.r is None
                or inscription.groupes is None
                or inscription.account_id is None
                or inscription.signup_token is None
                or inscription.kdf_salt is None
                or inscription.kdf_version is None
                or inscription.auth_key is None
            ):
                raise EtatRefuse(
                    "noPendingSignup", "le mot de passe n'a pas été choisi"
                )
            if sans_cle is True:
                cle_publique = None
                recuperation_auth = None
            elif sans_cle in (None, False):
                _verifier_extrait(bytes(inscription.r), inscription.groupes, extrait)
                derivees_r = cles_recuperation(bytes(inscription.r))
                cle_publique = derivees_r.cle_publique
                recuperation_auth = derivees_r.recovery_auth_key
            else:
                raise RequeteInvalide("skipRecovery")
            coffre = creer_coffre(
                bytes(inscription.kek),
                account_id=inscription.account_id,
                incarnation=1,
                kdf_version=inscription.kdf_version,
                recovery_public_key=cle_publique,
            )
            recuperation = (
                None
                if recuperation_auth is None
                else (recuperation_auth, coffre.enveloppe_amk_recuperation)
            )
            try:
                session = self.client.signup_complete(
                    signup_token=inscription.signup_token,
                    kdf_version=inscription.kdf_version,
                    auth_key=inscription.auth_key,
                    enveloppe_amk=coffre.enveloppe_amk,
                    recuperation=recuperation,  # type: ignore[arg-type]
                    enveloppe_trousseau=coffre.enveloppe_trousseau,
                )
            except ErreurServeur as exc:
                if exc.code in {"invalidToken", "accountExists"}:
                    inscription.effacer()
                    self._inscription = None
                raise
            if (
                session.account_id != inscription.account_id
                or session.incarnation != 1
                or session.vault_version != 1
                or session.keyring_version != 1
                or session.key_epoch != 1
            ):
                raise CleServeurInvalide("le serveur n'a pas créé le compte scellé ici")
            self._installer(
                account_id=session.account_id,
                email=inscription.email,
                incarnation=1,
                sel_kdf=inscription.kdf_salt,
                kdf_version=inscription.kdf_version,
                coffre_amk=coffre.enveloppe_amk,
                coffre_trousseau=coffre.enveloppe_trousseau,
                vault_version=1,
                keyring_version=1,
                amk=coffre.amk,
                trousseau=coffre.trousseau,
                session_id=session.session_id,
                jeton=session.jeton,
                remember=inscription.remember,
                recovery_configured=recuperation is not None,
                pending_reset_at=None,
            )
            self.etat.ecrire(dernierCommitMs=self._ms())
            inscription.effacer()
            self._inscription = None
            self._nommer_session()

    # ------------------------------------------------------------------
    # P3 — connexion ; déverrouillage ; verrouillage
    # ------------------------------------------------------------------

    def connecter(self, email: object, mot_de_passe: object, remember: object) -> None:
        with self._operation:
            self._refuser_si_fermes()
            self._preparer()
            self._refuser_si_deja_ouvert()
            if not isinstance(email, str):
                raise RequeteInvalide("email")
            if not isinstance(mot_de_passe, str) or not mot_de_passe:
                raise RequeteInvalide("password")
            email = cles.normaliser_courriel(email)
            remember = self._verifier_memorisation(remember)
            self._geste = True
            kdf_version, sel = self.client.login_params(email)
            # Le déclassement se juge AVANT d'étirer : un serveur qui sert
            # « kdfVersion 0 » n'obtient ni calcul ni authKey (§2.3, §4.12).
            cles.parametres_kdf(kdf_version)
            derivees = cles.deriver_cles_mot_de_passe(
                mot_de_passe, email, sel, kdf_version
            )
            valeurs = self.etat.tout()
            meme_compte = valeurs.get("email") == email
            try:
                connexion = self.client.login(email, derivees.auth_key)
            except ErreurServeur as exc:
                if (
                    exc.code == "invalidCredentials"
                    and meme_compte
                    and valeurs.get("sessionRevoquee") == "1"
                ):
                    # 24/09/2026 : après une révocation, « mot de passe
                    # incorrect » laissait croire à une faute de frappe alors
                    # que le mot de passe a pu être changé, ou le compte
                    # supprimé, depuis un autre appareil. « Mot de passe
                    # oublié » menait alors à attendre un code qui ne vient
                    # pas (anti-énumération) : l'impasse du §34.
                    exc.raison = "changedElsewhere"  # type: ignore[attr-defined]
                raise
            # La session d'avant sur CE compte (appareil verrouillé, session
            # expirée) : sans la refermer, la liste des appareils montrait
            # deux fois celui-ci, et « Déconnecter » le fantôme faisait
            # tourner les clés de tout le compte (24/09/2026).
            ancien_jeton = self._jeton() if meme_compte else None
            try:
                self._ouvrir_connexion(
                    connexion, email, sel, kdf_version, derivees.kek, remember
                )
            except ErreurCompte:
                self._abandonner_session(connexion.session.jeton)
                raise
            if ancien_jeton and ancien_jeton != connexion.session.jeton:
                self._abandonner_session(ancien_jeton)
            self._nommer_session()

    def _ouvrir_connexion(
        self,
        connexion: Connexion,
        email: str,
        sel: bytes,
        kdf_version: int,
        kek: bytes,
        remember: bool,
    ) -> None:
        session: SessionOuverte = connexion.session
        if connexion.kdf_version != kdf_version:
            raise CleServeurInvalide("kdfVersion différente de login/params")
        try:
            # AVANT tout essai de clé (§6 bis) : une incarnation sous celle
            # déjà vue est un retour arrière, pas un mauvais mot de passe.
            planchers = self.etat.planchers_pour(
                session.account_id, session.incarnation
            )
        except RetourArriereServeur:
            if self.etat.lire("accountId") == session.account_id:
                self.etat.ecrire(etatCompte="serverRolledBack")
            raise
        amk, trousseau = ouvrir_coffre(
            kek,
            enveloppe_amk=connexion.enveloppe_amk,
            enveloppe_trousseau=connexion.enveloppe_trousseau,
            account_id=session.account_id,
            incarnation=session.incarnation,
            kdf_version=kdf_version,
            vault_version=session.vault_version,
            keyring_version=session.keyring_version,
            plancher_vault_version=planchers.vault_version_max,
            plancher_keyring_version=planchers.keyring_version_max,
        )
        if trousseau.current_epoch < planchers.key_epoch_max:
            raise CleServeurPerimee("keyEpoch sous le plancher")
        if trousseau.current_epoch != session.key_epoch:
            raise CleServeurInvalide("keyEpoch annoncée différente du trousseau")
        self._installer(
            account_id=session.account_id,
            email=email,
            incarnation=session.incarnation,
            sel_kdf=sel,
            kdf_version=kdf_version,
            coffre_amk=connexion.enveloppe_amk,
            coffre_trousseau=connexion.enveloppe_trousseau,
            vault_version=session.vault_version,
            keyring_version=session.keyring_version,
            amk=amk,
            trousseau=trousseau,
            session_id=session.session_id,
            jeton=session.jeton,
            remember=remember,
            recovery_configured=connexion.recovery_configured,
            pending_reset_at=connexion.pending_reset_at,
        )

    def deverrouiller(self, mot_de_passe: object, remember: object = False) -> None:
        """Hors ligne, contre l'enveloppe locale. 5 échecs, puis 30 s (§3.8).

        ``remember`` : verrouiller oublie l'AMK mémorisée ; sans ce champ, la
        seule façon de la rétablir était une nouvelle connexion, qui laissait
        une session fantôme au serveur (24/09/2026)."""
        with self._operation:
            self._preparer()
            if not isinstance(mot_de_passe, str) or not mot_de_passe:
                raise RequeteInvalide("password")
            remember = self._verifier_memorisation(remember)
            account_id, valeurs = self._exiger_compte()
            if self.serrure.ouverte:
                raise EtatRefuse(
                    "alreadyUnlocked", "cet appareil est déjà déverrouillé"
                )
            enveloppe = self._enveloppe()
            planchers = self.etat.planchers()
            self._limite.verifier()
            incarnation = self._incarnation_locale(valeurs)
            derivees = cles.deriver_cles_mot_de_passe(
                mot_de_passe, valeurs["email"], enveloppe.sel_kdf, enveloppe.kdf_version
            )
            try:
                amk, trousseau = ouvrir_coffre(
                    derivees.kek,
                    enveloppe_amk=enveloppe.amk_mdp,
                    enveloppe_trousseau=enveloppe.trousseau,
                    account_id=account_id,
                    incarnation=incarnation,
                    kdf_version=enveloppe.kdf_version,
                    vault_version=enveloppe.version_coffre,
                    keyring_version=enveloppe.version_trousseau,
                    plancher_vault_version=planchers.vault_version_max
                    if planchers
                    else 0,
                    plancher_keyring_version=(
                        planchers.keyring_version_max if planchers else 0
                    ),
                )
            except EnveloppeIllisible:
                self._limite.echec()
                raise MotDePasseFaux("mot de passe incorrect") from None
            self._limite.reussite()
            if remember:
                self.protecteur.ranger(account_id, ELEMENT_AMK, amk)
                self.etat.ecrire(remembered=True)
            self.serrure.ouvrir(
                amk, trousseau, account_id=account_id, incarnation=incarnation
            )

    def verrouiller(self) -> None:
        """Verrouiller oublie aussi l'AMK mémorisée : un appareil qu'on
        verrouille et qui se rouvrirait seul au prochain lancement mentirait
        sur son état (§100).

        Et la clé de récupération en attente de confirmation, avec sa KEK :
        24/09/2026, après ``/recovery-key`` puis ``/lock``, le statut disait
        ``locked`` alors que la KEK restée en mémoire rouvrait l'AMK et le
        trousseau avec l'enveloppe locale — le voyant mentait (§78)."""
        with self._operation:
            self._preparer()
            self.serrure.fermer()
            self._oublier_nouvelle_cle()
            account_id = self.etat.lire("accountId")
            if account_id and self.etat.lire("remembered") == "1":
                self._effacer_secret(account_id, ELEMENT_AMK)
                self.etat.ecrire(remembered=False)

    # ------------------------------------------------------------------
    # P5 — changement de mot de passe ; P4 chemin 2 — oubli, appareil ouvert
    # ------------------------------------------------------------------

    def changer_mot_de_passe(self, actuel: object, nouveau: object) -> None:
        with self._operation:
            self._preparer()
            if not isinstance(actuel, str) or not actuel:
                raise RequeteInvalide("currentPassword")
            if not isinstance(nouveau, str):
                raise RequeteInvalide("newPassword")
            ouverture, valeurs = self._exiger_ouverture()
            enveloppe = self._enveloppe()
            email = valeurs["email"]
            cles.verifier_mot_de_passe(nouveau, email)
            derivees = self._juger_mot_de_passe(
                actuel, email, enveloppe, ouverture.account_id, ouverture.incarnation
            )
            kdf = _kdf_courante()
            neuves = cles.deriver_cles_mot_de_passe(
                nouveau, email, enveloppe.sel_kdf, kdf
            )
            self._rotation_depuis_ici(
                ouverture,
                valeurs,
                enveloppe,
                kek=neuves.kek,
                auth_key=neuves.auth_key,
                kdf_version=kdf,
                preuve={"kind": "password", "authKey": b64url(derivees.auth_key)},
            )

    def code_oubli_ici(self) -> None:
        """Le code du coffre : exige cet appareil déverrouillé EN CE MOMENT."""
        with self._operation:
            self._preparer()
            self._exiger_ouverture()
            self._avec_session(lambda jeton: self.client.vault_code(jeton))

    def oubli_ici(self, code: object, nouveau: object) -> None:
        with self._operation:
            self._preparer()
            code = _code_six_chiffres(code)
            if not isinstance(nouveau, str):
                raise RequeteInvalide("newPassword")
            ouverture, valeurs = self._exiger_ouverture()
            enveloppe = self._enveloppe()
            email = valeurs["email"]
            cles.verifier_mot_de_passe(nouveau, email)
            kdf = _kdf_courante()
            neuves = cles.deriver_cles_mot_de_passe(
                nouveau, email, enveloppe.sel_kdf, kdf
            )
            self._rotation_depuis_ici(
                ouverture,
                valeurs,
                enveloppe,
                kek=neuves.kek,
                auth_key=neuves.auth_key,
                kdf_version=kdf,
                preuve={"kind": "emailCode", "code": code},
            )

    # ------------------------------------------------------------------
    # P4 chemin 1 — récupération par la clé
    # ------------------------------------------------------------------

    def recuperer(
        self,
        email: object,
        cle: object,
        nouveau: object,
        remember: object,
        garder_cle: object,
    ) -> dict[str, Any]:
        with self._operation:
            self._refuser_si_fermes()
            self._preparer()
            self._refuser_si_deja_ouvert()
            if not isinstance(email, str):
                raise RequeteInvalide("email")
            if not isinstance(cle, str):
                raise RequeteInvalide("recoveryKey")
            if not isinstance(nouveau, str):
                raise RequeteInvalide("newPassword")
            if not isinstance(garder_cle, bool):
                raise RequeteInvalide("keepRecoveryKey")
            email = cles.normaliser_courriel(email)
            # Une faute de frappe se voit ICI, avant tout appel réseau (§2.7).
            r = lire_cle_recuperation(cle)
            cles.verifier_mot_de_passe(nouveau, email)
            remember = self._verifier_memorisation(remember)
            self._geste = True
            derivees_r = cles_recuperation(r)
            kdf_serveur, sel = self.client.login_params(email)
            cles.parametres_kdf(kdf_serveur)
            deballage = self.client.recovery_unwrap(email, derivees_r.recovery_auth_key)
            try:
                planchers = self.etat.planchers_pour(
                    deballage.account_id, deballage.incarnation
                )
            except RetourArriereServeur:
                if self.etat.lire("accountId") == deballage.account_id:
                    self.etat.ecrire(etatCompte="serverRolledBack")
                raise
            amk, trousseau = ouvrir_coffre_par_recuperation(
                derivees_r.cle_privee,
                enveloppe_amk_recuperation=deballage.enveloppe_amk_recuperation,
                enveloppe_trousseau=deballage.enveloppe_trousseau,
                account_id=deballage.account_id,
                incarnation=deballage.incarnation,
                vault_version=deballage.vault_version,
                keyring_version=deballage.keyring_version,
                plancher_vault_version=planchers.vault_version_max,
                plancher_keyring_version=planchers.keyring_version_max,
            )
            del amk  # l'AMK ouverte par R n'écrit RIEN : la rotation la remplace.
            if trousseau.current_epoch < planchers.key_epoch_max:
                raise CleServeurPerimee("keyEpoch sous le plancher")
            if trousseau.current_epoch != deballage.key_epoch:
                raise CleServeurInvalide("keyEpoch annoncée différente du trousseau")
            kdf = _kdf_courante()
            neuves = cles.deriver_cles_mot_de_passe(nouveau, email, sel, kdf)
            # §2.11 bis : HPKE Base n'authentifie pas l'expéditeur, et un
            # appareil perdu peut avoir forgé ce trousseau avec la VRAIE
            # pk_rec et des DEK à lui. Les clés tournent donc AVANT toute
            # écriture — ``vault/commit`` est la première requête qui dépose
            # quoi que ce soit, et rien ne s'écrit sous l'époque ouverte ici.
            #
            # La clé de récupération est GARDÉE par ce commit, même quand
            # D22 la fait remplacer. 24/09/2026 : le commit la remplaçait
            # d'un coup ; une réponse perdue après la transaction laissait
            # l'ancienne ``R`` morte, la nouvelle jamais montrée (tirée dans
            # ce processus et perdue avec lui), et un statut qui comptait
            # « clé de récupération » comme moyen de secours — que PERSONNE
            # ne détenait (§100). Gardée, l'ancienne rouvre encore après une
            # réponse perdue : la personne réessaie avec la même clé. Garder
            # ne garde que CETTE ``pk_rec`` : ``ouvrir_coffre_par_recuperation``
            # a refusé un trousseau qui en nommait une autre.
            self._tourner(
                account_id=deballage.account_id,
                email=email,
                incarnation=deballage.incarnation,
                trousseau=trousseau,
                vault_version=deballage.vault_version,
                keyring_version=deballage.keyring_version,
                kek=neuves.kek,
                auth_key=neuves.auth_key,
                kdf_version=kdf,
                sel_kdf=sel,
                preuve={
                    "kind": "recovery",
                    "recoveryToken": deballage.jeton_recuperation,
                },
                recuperation=GARDER,
                avec_session=False,
                remember=remember,
                # L'historique ouvert par ce chemin n'est pas authentifié :
                # le moteur de synchronisation (étape 10) ne tient pour sûres
                # que les époques à partir de celle-ci. Écrit DANS
                # l'installation (24/09/2026) : écrit après, derrière le
                # ``PUT /sessions/current`` du nommage (15 s), une fermeture
                # de l'app à ce moment laissait le compte installé sans
                # marqueur, et rien ne le réécrivait jamais.
                ecrire_aussi=lambda coffre: {
                    "epoqueAuthentifieeMin": coffre.trousseau.current_epoch
                },
            )
            if garder_cle:
                return {}
            # D22 : une clé qui vient de servir a été tapée ; on en propose
            # une neuve, qui ne remplace l'ancienne qu'une fois ressaisie
            # (``/recovery-key/confirm``) — montrée, donc détenue.
            return self._proposer_cle(neuves.kek, neuves.auth_key, kdf)

    # ------------------------------------------------------------------
    # Clé de récupération : remplacer, retirer
    # ------------------------------------------------------------------

    def _proposer_cle(self, kek: bytes, auth_key: bytes, kdf: int) -> dict[str, Any]:
        """Une clé de récupération neuve, en attente de ressaisie (30 min).

        Le remplacement au serveur n'a lieu qu'à :meth:`nouvelle_cle_confirmer`,
        après que la personne a recopié deux groupes : aucune clé que
        personne n'a vue ne devient le moyen de secours du compte."""
        ouverture = self.serrure.exiger()
        self._oublier_nouvelle_cle()
        self._nouvelle_cle = _NouvelleCle(
            account_id=ouverture.account_id,
            expire=self._mono() + DUREE_EN_ATTENTE_S,
            kdf_version=kdf,
            r=bytearray(generer_cle_recuperation()),
            groupes=_tirer_groupes(),
            kek=bytearray(kek),
            auth_key=auth_key,
        )
        return {
            "newRecoveryKey": formater_cle_recuperation(bytes(self._nouvelle_cle.r)),
            "confirmGroups": list(self._nouvelle_cle.groupes),
        }

    def nouvelle_cle_preparer(self, mot_de_passe: object) -> dict[str, Any]:
        with self._operation:
            self._preparer()
            if not isinstance(mot_de_passe, str) or not mot_de_passe:
                raise RequeteInvalide("password")
            ouverture, valeurs = self._exiger_ouverture()
            enveloppe = self._enveloppe()
            derivees = self._juger_mot_de_passe(
                mot_de_passe,
                valeurs["email"],
                enveloppe,
                ouverture.account_id,
                ouverture.incarnation,
            )
            if self._nouvelle_cle is not None:
                self._nouvelle_cle.effacer()
            self._nouvelle_cle = _NouvelleCle(
                account_id=ouverture.account_id,
                expire=self._mono() + DUREE_EN_ATTENTE_S,
                kdf_version=enveloppe.kdf_version,
                r=bytearray(generer_cle_recuperation()),
                groupes=_tirer_groupes(),
                kek=bytearray(derivees.kek),
                auth_key=derivees.auth_key,
            )
            return {
                "recoveryKey": formater_cle_recuperation(bytes(self._nouvelle_cle.r)),
                "confirmGroups": list(self._nouvelle_cle.groupes),
            }

    def nouvelle_cle_confirmer(self, extrait: object) -> None:
        with self._operation:
            self._preparer()
            attente = self._nouvelle_cle
            if attente is not None and self._mono() > attente.expire:
                attente.effacer()
                self._nouvelle_cle = attente = None
            if attente is None:
                raise EtatRefuse(
                    "noPendingRecoveryKey", "recommencez depuis le mot de passe"
                )
            ouverture, valeurs = self._exiger_ouverture()
            if ouverture.account_id != attente.account_id:
                raise EtatRefuse("noPendingRecoveryKey", "autre compte")
            _verifier_extrait(bytes(attente.r), attente.groupes, extrait)
            enveloppe = self._enveloppe()
            derivees_r = cles_recuperation(bytes(attente.r))
            self._rotation_depuis_ici(
                ouverture,
                valeurs,
                enveloppe,
                kek=bytes(attente.kek),
                auth_key=attente.auth_key,
                kdf_version=attente.kdf_version,
                preuve={"kind": "password", "authKey": b64url(attente.auth_key)},
                recuperation=derivees_r.cle_publique,
                auth_recuperation=derivees_r.recovery_auth_key,
            )
            attente.effacer()
            self._nouvelle_cle = None

    def retirer_cle(self, mot_de_passe: object) -> None:
        with self._operation:
            self._preparer()
            if not isinstance(mot_de_passe, str) or not mot_de_passe:
                raise RequeteInvalide("password")
            ouverture, valeurs = self._exiger_ouverture()
            enveloppe = self._enveloppe()
            derivees = self._juger_mot_de_passe(
                mot_de_passe,
                valeurs["email"],
                enveloppe,
                ouverture.account_id,
                ouverture.incarnation,
            )
            self._rotation_depuis_ici(
                ouverture,
                valeurs,
                enveloppe,
                kek=derivees.kek,
                auth_key=derivees.auth_key,
                kdf_version=enveloppe.kdf_version,
                preuve={"kind": "password", "authKey": b64url(derivees.auth_key)},
                recuperation=None,
            )

    # ------------------------------------------------------------------
    # P6 — appareils
    # ------------------------------------------------------------------

    def appareils(self) -> list[dict[str, Any]]:
        with self._operation:
            self._preparer()
            ouverture, _ = self._exiger_ouverture()
            sessions = self._avec_session(lambda jeton: self.client.sessions(jeton))
            k_noms = cles.cle_noms_appareils(ouverture.amk)
            rendu = []
            for s in sessions:
                nom = None
                if s["encryptedName"] is not None:
                    try:
                        nom = ouvrir_nom_appareil(
                            k_noms,
                            s["encryptedName"],
                            account_id=ouverture.account_id,
                            session_id=s["sessionId"],
                        )
                    except EnveloppeIllisible:
                        # Scellé sous l'AMK d'avant une rotation : l'appareil
                        # se renommera à sa prochaine connexion.
                        nom = None
                rendu.append(
                    {
                        "sessionId": s["sessionId"],
                        "name": nom,
                        "createdDay": s["createdDay"],
                        "lastSeenDay": s["lastSeenDay"],
                        "current": s["current"],
                    }
                )
            return rendu

    def deconnecter_appareil(self, session_id: object, mot_de_passe: object) -> None:
        """D21 : déconnecter un AUTRE appareil fait tourner les clés."""
        with self._operation:
            self._preparer()
            if (
                not isinstance(session_id, str)
                or not session_id
                or len(session_id) > 64
            ):
                raise RequeteInvalide("id")
            if not isinstance(mot_de_passe, str) or not mot_de_passe:
                raise RequeteInvalide("password")
            ouverture, valeurs = self._exiger_ouverture()
            if session_id == valeurs.get("sessionId"):
                raise EtatRefuse(
                    "currentDevice", "pour cet appareil, utilisez « Se déconnecter »"
                )
            enveloppe = self._enveloppe()
            derivees = self._juger_mot_de_passe(
                mot_de_passe,
                valeurs["email"],
                enveloppe,
                ouverture.account_id,
                ouverture.incarnation,
            )
            self._rotation_depuis_ici(
                ouverture,
                valeurs,
                enveloppe,
                kek=derivees.kek,
                auth_key=derivees.auth_key,
                kdf_version=enveloppe.kdf_version,
                preuve={"kind": "password", "authKey": b64url(derivees.auth_key)},
                session_revoquee=session_id,
            )

    # ------------------------------------------------------------------
    # P4 chemin 3 — réinitialisation
    # ------------------------------------------------------------------

    def reinit_demander(self, email: object) -> None:
        with self._operation:
            self._refuser_si_fermes()
            self._preparer()
            if not isinstance(email, str):
                raise RequeteInvalide("email")
            email = cles.normaliser_courriel(email)
            self._exiger_compte_a_reinitialiser(email)
            self._geste = True
            self.client.reset_request(email)

    def reinit_confirmer(self, email: object, code: object) -> dict[str, Any]:
        """Programme la réinitialisation — seulement si cet appareil pourra
        la terminer : compte connu ET incarnation confirmée maintenant.
        Sinon sept jours d'attente, un courriel « prévue » et un
        avertissement sur chaque appareil, pour un ``reset/complete`` que
        cet appareil refuserait."""
        with self._operation:
            self._preparer()
            if not isinstance(email, str):
                raise RequeteInvalide("email")
            email = cles.normaliser_courriel(email)
            code = _code_six_chiffres(code)
            account_id, valeurs, planchers = self._exiger_compte_a_reinitialiser(email)
            self._geste = True
            self._incarnation_confirmee(account_id, valeurs, planchers)
            effectif = self.client.reset_confirm(email, code)
            self.etat.ecrire(pendingResetAt=effectif)
            return {"effectiveAt": effectif}

    def reinit_annuler(self) -> None:
        with self._operation:
            self._preparer()
            self._exiger_compte()
            self._avec_session(lambda jeton: self.client.reset_cancel(jeton))
            self.etat.ecrire(pendingResetAt=None)

    def reinit_terminer(
        self, email: object, code: object, nouveau: object, remember: object
    ) -> dict[str, Any]:
        """``reset/complete`` scelle un coffre NEUF sous l'incarnation
        suivante, qu'il faut connaître AVANT l'appel : l'AAD porte ``i``.

        Le corps du VPS ne la rend qu'après (§3.4). Cet appareil la tient de
        ses planchers, CONFIRMÉE par le serveur (:meth:`_incarnation_confirmee`)
        — sinon il refuse (``resetNeedsKnownAccount``) plutôt que de sceller
        un coffre que personne ne rouvrirait.

        Le coffre neuf part SANS clé de récupération ; la clé rendue attend
        sa ressaisie (``/recovery-key/confirm``) pour être scellée. Une
        réponse perdue après la transaction laissait sinon au serveur une
        clé que personne n'avait vue, comptée « moyen de secours » (§100).
        """
        with self._operation:
            self._preparer()
            if not isinstance(email, str):
                raise RequeteInvalide("email")
            email = cles.normaliser_courriel(email)
            code = _code_six_chiffres(code)
            if not isinstance(nouveau, str):
                raise RequeteInvalide("newPassword")
            cles.verifier_mot_de_passe(nouveau, email)
            remember = self._verifier_memorisation(remember)
            account_id, valeurs, planchers = self._exiger_compte_a_reinitialiser(email)
            self._geste = True
            nouvelle = self._incarnation_confirmee(account_id, valeurs, planchers) + 1
            kdf_serveur, sel = self.client.login_params(email)
            cles.parametres_kdf(kdf_serveur)
            kdf = _kdf_courante()
            neuves = cles.deriver_cles_mot_de_passe(nouveau, email, sel, kdf)
            coffre = creer_coffre(
                neuves.kek,
                account_id=account_id,
                incarnation=nouvelle,
                kdf_version=kdf,
                recovery_public_key=None,
            )
            session = self.client.reset_complete(
                email=email,
                code=code,
                kdf_version=kdf,
                auth_key=neuves.auth_key,
                enveloppe_amk=coffre.enveloppe_amk,
                recuperation=None,
                enveloppe_trousseau=coffre.enveloppe_trousseau,
            )
            if (
                session.account_id != account_id
                or session.incarnation != nouvelle
                or session.vault_version != 1
                or session.keyring_version != 1
                or session.key_epoch != 1
            ):
                self.etat.ecrire(etatCompte="accountReset")
                raise CleServeurInvalide(
                    "le serveur a ouvert une autre incarnation que celle scellée ici"
                )
            self._installer(
                account_id=account_id,
                email=email,
                incarnation=nouvelle,
                sel_kdf=sel,
                kdf_version=kdf,
                coffre_amk=coffre.enveloppe_amk,
                coffre_trousseau=coffre.enveloppe_trousseau,
                vault_version=1,
                keyring_version=1,
                amk=coffre.amk,
                trousseau=coffre.trousseau,
                session_id=session.session_id,
                jeton=session.jeton,
                remember=remember,
                recovery_configured=False,
                pending_reset_at=None,
                autres={"dernierCommitMs": self._ms()},
            )
            self._nommer_session()
            return self._proposer_cle(neuves.kek, neuves.auth_key, kdf)

    # ------------------------------------------------------------------
    # P7 — déconnexion ; P8 — suppression
    # ------------------------------------------------------------------

    def deconnecter(self, effacer_donnees: object) -> dict[str, Any]:
        """Ne fait PAS tourner les clés : l'appareil est entre vos mains (§2.8)."""
        with self._operation:
            self._preparer()
            if effacer_donnees is not False and effacer_donnees is not None:
                # Effacer les conversations locales à la déconnexion n'existe
                # pas encore : dire « oui » en ne l'ayant pas fait serait un
                # faux SUCCESS (§100).
                raise RequeteInvalide("eraseLocalData")
            account_id, _ = self._exiger_compte()
            ferme = True
            try:
                self._avec_session(lambda jeton: self.client.logout(jeton))
            except SessionExpiree:
                ferme = True
            except ErreurCompte as exc:
                logger.info("compte : session serveur non refermée (%s)", exc.code)
                ferme = False
            self._effacer_compte_local(account_id)
            return {"serverSessionClosed": ferme}

    def supprimer(self, mot_de_passe: object, effacer_donnees: object) -> None:
        with self._operation:
            self._preparer()
            if not isinstance(mot_de_passe, str) or not mot_de_passe:
                raise RequeteInvalide("password")
            if effacer_donnees is not False and effacer_donnees is not None:
                raise RequeteInvalide("eraseLocalData")
            account_id, valeurs = self._exiger_compte()
            email = valeurs["email"]
            enveloppe = self.etat.enveloppe_locale()
            if enveloppe is not None:
                # Même sur un appareil VERROUILLÉ : sans la limite, cette
                # route servait d'oracle du mot de passe (voir
                # :meth:`_juger_mot_de_passe`).
                derivees = self._juger_mot_de_passe(
                    mot_de_passe,
                    email,
                    enveloppe,
                    account_id,
                    self._incarnation_locale(valeurs),
                )
            else:
                self._limite.verifier()
                kdf_version, sel = self.client.login_params(email)
                cles.parametres_kdf(kdf_version)
                derivees = cles.deriver_cles_mot_de_passe(
                    mot_de_passe, email, sel, kdf_version
                )
            try:
                self._avec_session(
                    lambda jeton: self.client.account_delete(derivees.auth_key, jeton)
                )
            except ErreurServeur as exc:
                if exc.code == "invalidProof":
                    self._limite.echec()
                    raise MotDePasseFaux("mot de passe incorrect") from None
                raise
            self._effacer_compte_local(account_id)

    # ------------------------------------------------------------------
    # Consentement, synchronisation, premier lancement
    # ------------------------------------------------------------------

    def consentir(self) -> None:
        with self._operation:
            self._preparer()
            self._exiger_compte()
            self.etat.ecrire(consentement=True)

    def synchroniser_maintenant(self) -> None:
        # Le moteur arrive à l'étape 10. Rendre 200 ici ferait croire à la
        # fermeture de l'app (P10) que ses modifications sont parties.
        raise EtatRefuse("syncUnavailable", "la synchronisation n'existe pas encore")

    def accueil_termine(self) -> None:
        with self._operation:
            self._preparer()
            marquer_accueil(self.dossier)
