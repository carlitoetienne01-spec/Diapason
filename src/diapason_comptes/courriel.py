"""Les courriels : modèles, fil expéditeur dédié, circuit, Resend.

Conception : ``docs/development/compte-chiffre.md`` §3.1 et §3.5.

Jamais par ``BackgroundTasks`` : une tâche de fond synchrone passe par
``run_in_threadpool``, le même pool de 40 fils que toutes les routes ``def``
(``starlette/background.py``, ``CapacityLimiter(40)``). Quarante envois
bloqués dix secondes chacun sur un Resend qui rame, et ``/health`` ne
répondait plus. Ici : UN fil démon, une ``queue.Queue(maxsize=200)`` en
mémoire, et la route se contente de ``put_nowait``. File pleine : l'envoi
est abandonné et compté, jamais attendu.

Aucun courriel ne porte de lien à jeton (les liens ``diapason://`` sont
morts, ``lib.rs:5495-5499``) ni d'image : un code se recopie à la main.
"""

from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from diapason_comptes.limites import BUDGET_CODES, BUDGET_SECURITE, BudgetsCourriel
from diapason_comptes.secrets_serveur import SecretsAbsents

_journal = logging.getLogger("diapason_comptes.courriel")

# ----------------------------------------------------------------------
# Modèles (§3.5)
# ----------------------------------------------------------------------

PIED_FR = (
    "Diapason ne vous demandera jamais votre mot de passe ni votre clé de récupération."
)
PIED_EN = "Diapason will never ask for your password or your recovery key."

# (sujet, texte FR, texte EN). ``{code}`` et ``{date}`` sont remplis à la
# rédaction ; aucun modèle ne mentionne d'IP ni de lieu (D8, D11).
_MODELES: dict[str, tuple[str, str, str]] = {
    "code_inscription": (
        "Votre code Diapason / Your Diapason code",
        "Votre code pour créer un compte Diapason : {code}\n"
        "Il expire dans 15 minutes. Si vous n'avez rien demandé, ignorez ce courriel.",
        "Your code to create a Diapason account: {code}\n"
        "It expires in 15 minutes. If you did not ask for it, ignore this email.",
    ),
    "compte_existant": (
        "Un compte Diapason existe déjà / A Diapason account already exists",
        "Quelqu'un a demandé à créer un compte Diapason avec cette adresse, qui en a "
        "déjà un. Si c'est vous, connectez-vous plutôt. Sinon, rien n'a changé.",
        "Someone asked to create a Diapason account with this address, which already "
        "has one. If that was you, sign in instead. Otherwise, nothing has changed.",
    ),
    "nouvelle_connexion": (
        "Nouvelle connexion à Diapason / New Diapason sign-in",
        "Un appareil vient de se connecter à votre compte Diapason. Si ce n'est pas "
        "vous, changez votre mot de passe depuis un appareil connecté.",
        "A device just signed in to your Diapason account. If this was not you, "
        "change your password from a signed-in device.",
    ),
    "code_coffre": (
        "Votre code Diapason / Your Diapason code",
        "Votre code pour choisir un nouveau mot de passe depuis un appareil "
        "déverrouillé : {code}\nIl expire dans 15 minutes.",
        "Your code to choose a new password from an unlocked device: {code}\n"
        "It expires in 15 minutes.",
    ),
    "mot_de_passe_change": (
        "Mot de passe Diapason changé / Diapason password changed",
        "Le mot de passe de votre compte Diapason a été changé et les clés ont été "
        "renouvelées. Vos autres appareils vous le redemanderont.",
        "Your Diapason account password was changed and the keys were renewed. Your "
        "other devices will ask for it again.",
    ),
    "recuperation_utilisee": (
        "Clé de récupération utilisée / Recovery key used",
        "Votre clé de récupération Diapason vient d'être utilisée pour ouvrir le "
        "compte. Si ce n'est pas vous, changez votre mot de passe sans attendre.",
        "Your Diapason recovery key was just used to open the account. If this was "
        "not you, change your password right away.",
    ),
    "recuperation_remplacee": (
        "Clé de récupération remplacée / Recovery key replaced",
        "La clé de récupération de votre compte Diapason a été remplacée. "
        "L'ancienne ne sert plus.",
        "The recovery key of your Diapason account was replaced. The old one no "
        "longer works.",
    ),
    "recuperation_retiree": (
        "Clé de récupération retirée / Recovery key removed",
        "Votre compte Diapason n'a plus de clé de récupération. Si vous oubliez votre "
        "mot de passe, seul un appareil resté déverrouillé pourra vous aider.",
        "Your Diapason account no longer has a recovery key. If you forget your "
        "password, only a device left unlocked can help.",
    ),
    "appareil_deconnecte": (
        "Appareil déconnecté / Device signed out",
        "Un appareil a été déconnecté de votre compte Diapason et les clés ont été "
        "renouvelées : il ne recevra plus rien.",
        "A device was signed out of your Diapason account and the keys were renewed: "
        "it will receive nothing more.",
    ),
    "connexions_bloquees": (
        "Connexions bloquées / Sign-ins blocked",
        "Trop de tentatives de connexion ont échoué aujourd'hui sur votre compte "
        "Diapason. Les nouvelles connexions sont bloquées jusqu'à demain ; vos "
        "appareils déjà connectés ne sont pas touchés.",
        "Too many sign-in attempts failed today on your Diapason account. New "
        "sign-ins are blocked until tomorrow; devices already signed in are not "
        "affected.",
    ),
    "code_reinitialisation": (
        "Votre code de réinitialisation / Your reset code",
        "Votre code pour réinitialiser le compte Diapason : {code}\n"
        "Il expire dans 15 minutes. Si vous n'avez rien demandé, ignorez ce courriel.",
        "Your code to reset your Diapason account: {code}\n"
        "It expires in 15 minutes. If you did not ask for it, ignore this email.",
    ),
    "reinitialisation_prevue": (
        "Réinitialisation prévue / Reset scheduled",
        "La réinitialisation de votre compte Diapason est prévue le {date}. Elle "
        "effacera la copie chiffrée du serveur. Si ce n'est pas vous, ouvrez Diapason "
        "sur un appareil connecté et annulez-la.",
        "Your Diapason account reset is scheduled for {date}. It will erase the "
        "encrypted copy on the server. If this was not you, open Diapason on a "
        "signed-in device and cancel it.",
    ),
    "reinitialisation_annulee": (
        "Réinitialisation annulée / Reset cancelled",
        "La réinitialisation de votre compte Diapason a été annulée.",
        "The reset of your Diapason account was cancelled.",
    ),
    "reinitialisation_effectuee": (
        "Compte réinitialisé / Account reset",
        "Votre compte Diapason a été réinitialisé : la copie chiffrée du serveur a été "
        "effacée et remplacée. Vos autres appareils devront se reconnecter.",
        "Your Diapason account was reset: the encrypted copy on the server was erased "
        "and replaced. Your other devices will need to sign in again.",
    ),
    "compte_supprime": (
        "Compte Diapason supprimé / Diapason account deleted",
        "Votre compte Diapason a été supprimé. Les données de vos appareils restent "
        "sur vos appareils.",
        "Your Diapason account was deleted. The data on your devices stays on your "
        "devices.",
    ),
}

# Le budget de chaque genre. « Connexions bloquées » est déclenché par des
# échecs, donc par n'importe qui : il puise dans le budget des codes, sinon
# un inconnu viderait le budget réservé aux avis de sécurité.
GENRES_CODES = frozenset(
    {
        "code_inscription",
        "compte_existant",
        "code_coffre",
        "connexions_bloquees",
        "code_reinitialisation",
    }
)
GENRES_SECURITE = frozenset(_MODELES) - GENRES_CODES
UNE_FOIS_PAR_JOUR = frozenset({"compte_existant", "connexions_bloquees"})


def budget_du_genre(genre: str) -> str:
    return BUDGET_CODES if genre in GENRES_CODES else BUDGET_SECURITE


@dataclass(frozen=True)
class Message:
    """Un courriel prêt à partir. ``index_court`` (8 hex de l'index) est ce
    que le journal nomme en cas d'échec — jamais l'adresse."""

    destinataire: str = field(repr=False)
    genre: str
    sujet: str
    texte: str = field(repr=False)
    index_court: str


def _date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def rediger(
    genre: str,
    destinataire: str,
    index: bytes,
    *,
    origine_publique: str | None,
    code: str | None = None,
    date_ms: int | None = None,
) -> Message:
    """Le courriel bilingue (FR puis EN), avec le pied obligatoire (§3.5)."""
    sujet, fr, en = _MODELES[genre]
    valeurs = {"code": code or "", "date": _date(date_ms) if date_ms else ""}
    lignes = [fr.format(**valeurs), "", en.format(**valeurs), ""]
    if origine_publique:
        # AVANT le pied : « chaque courriel se TERMINE par » la phrase de
        # sécurité (§3.5). Les liens passaient après elle jusqu'au 24/09/2026.
        base = origine_publique.rstrip("/")
        lignes += [f"{base}/confidentialite · {base}/conditions", ""]
    lignes += ["—", PIED_FR, PIED_EN]
    return Message(
        destinataire=destinataire,
        genre=genre,
        sujet=sujet,
        texte="\n".join(lignes),
        index_court=index.hex()[2:10],
    )


# ----------------------------------------------------------------------
# Expéditeurs
# ----------------------------------------------------------------------


class Expediteur(Protocol):
    def envoyer(self, message: Message) -> None:
        """Envoie ou lève ; le fil expéditeur décide du nouvel essai."""


# Les noms des variables de ``/etc/diapason/mail.env``. Ce fichier existe
# déjà sur le VPS ; ses NOMS doivent être relevés par Carlito (étape 0,
# ``sudo cut -d= -f1``) et reportés ici. Rien de ce module ne le lit
# directement : systemd le passe en environnement.
VAR_CLE_RESEND = "RESEND_API_KEY"
VAR_EXPEDITEUR = "COURRIEL_EXPEDITEUR"
# D17 — la boîte LUE où arrivent les réponses. Non tranchée : aucune valeur
# par défaut, le service refuse de démarrer sans elle.
VAR_REPONSE = "COURRIEL_REPONSE"
# D3 — l'origine publique des pages légales. Non tranchée non plus.
VAR_ORIGINE = "COMPTES_ORIGINE_PUBLIQUE"

URL_RESEND = "https://api.resend.com/emails"
# §3.5 : un délai de 10 s. Au-delà, Resend est en panne et le circuit le
# dira ; attendre plus longtemps ne ferait que retarder les courriels suivants.
DELAI_RESEND_S = 10


@dataclass(frozen=True)
class ConfigurationCourriel:
    cle_api: str = field(repr=False)
    expediteur: str
    reponse: str
    origine_publique: str


def charger_configuration_courriel(env: Mapping[str, str]) -> ConfigurationCourriel:
    valeurs = {}
    for nom in (VAR_CLE_RESEND, VAR_EXPEDITEUR, VAR_REPONSE, VAR_ORIGINE):
        valeur = env.get(nom, "").strip()
        if not valeur:
            raise SecretsAbsents(f"{nom} manque dans l'environnement (mail.env)")
        valeurs[nom] = valeur
    return ConfigurationCourriel(
        cle_api=valeurs[VAR_CLE_RESEND],
        expediteur=valeurs[VAR_EXPEDITEUR],
        reponse=valeurs[VAR_REPONSE],
        origine_publique=valeurs[VAR_ORIGINE],
    )


class ExpediteurResend:
    """``urllib.request`` vers Resend, suivi désactivé, texte seul."""

    def __init__(self, configuration: ConfigurationCourriel) -> None:
        self._configuration = configuration

    def envoyer(self, message: Message) -> None:
        corps = json.dumps(
            {
                "from": self._configuration.expediteur,
                "to": [message.destinataire],
                "reply_to": self._configuration.reponse,
                "subject": message.sujet,
                "text": message.texte,
            }
        ).encode("utf-8")
        requete = urllib.request.Request(
            URL_RESEND,
            data=corps,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._configuration.cle_api}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(requete, timeout=DELAI_RESEND_S) as reponse:
            if not 200 <= reponse.status < 300:
                raise urllib.error.HTTPError(
                    URL_RESEND, reponse.status, "refus Resend", reponse.headers, None
                )


# ----------------------------------------------------------------------
# Fil expéditeur et circuit
# ----------------------------------------------------------------------

TAILLE_FILE = 200
# §3.5 : un seul nouvel essai, 30 s plus tard. Deux échecs de suite pour le
# même courriel : Resend est en panne, et un troisième essai ne ferait que
# prendre la place des suivants.
DELAI_NOUVEL_ESSAI_S = 30.0
# §3.5 : 5 échecs de suite en 10 min ouvrent le circuit.
ECHECS_CIRCUIT = 5
FENETRE_CIRCUIT_S = 600.0


class FileCourriels:
    """Un fil démon, une file bornée, un circuit."""

    def __init__(
        self,
        expediteur: Expediteur,
        *,
        taille: int = TAILLE_FILE,
        delai_nouvel_essai_s: float = DELAI_NOUVEL_ESSAI_S,
        monotone: Callable[[], float] = time.monotonic,
    ) -> None:
        self._expediteur = expediteur
        self._file: queue.Queue[Message | None] = queue.Queue(maxsize=taille)
        self._delai = delai_nouvel_essai_s
        self._monotone = monotone
        self._verrou = threading.Lock()
        self._reprises: list[tuple[float, Message]] = []
        self._echecs_consecutifs: list[float] = []
        self.abandons = 0
        self.envoyes = 0
        self.echecs = 0
        self._fil = threading.Thread(
            target=self._boucle, name="diapason-comptes-courriel", daemon=True
        )
        self._fil.start()

    # --- Côté route -------------------------------------------------------

    def deposer(self, message: Message) -> bool:
        try:
            self._file.put_nowait(message)
        except queue.Full:
            with self._verrou:
                self.abandons += 1
            _journal.warning(
                "file de courriels pleine : envoi « %s » abandonné (%s)",
                message.genre,
                message.index_court,
            )
            return False
        return True

    def circuit_ouvert(self) -> bool:
        with self._verrou:
            recents = [
                t
                for t in self._echecs_consecutifs
                if t > self._monotone() - FENETRE_CIRCUIT_S
            ]
            return len(recents) >= ECHECS_CIRCUIT

    def arreter(self, delai_s: float = 2.0) -> None:
        try:
            self._file.put_nowait(None)
        except queue.Full:
            pass
        self._fil.join(timeout=delai_s)

    # --- Côté fil -----------------------------------------------------------

    def _tenter(self, message: Message, *, dernier_essai: bool) -> None:
        try:
            self._expediteur.envoyer(message)
        except Exception as exc:  # réseau, HTTP, n'importe quoi : même traitement
            with self._verrou:
                self.echecs += 1
                self._echecs_consecutifs.append(self._monotone())
                if not dernier_essai:
                    self._reprises.append((self._monotone() + self._delai, message))
            _journal.warning(
                "envoi « %s » échoué (%s) : %s%s",
                message.genre,
                message.index_court,
                type(exc).__name__,
                "" if not dernier_essai else ", abandonné",
            )
            if self.circuit_ouvert():
                _journal.error("circuit ouvert : %d échecs de suite", ECHECS_CIRCUIT)
            return
        with self._verrou:
            self.envoyes += 1
            self._echecs_consecutifs.clear()

    def _boucle(self) -> None:
        while True:
            with self._verrou:
                self._reprises.sort(key=lambda r: r[0])
                echues = [r for r in self._reprises if r[0] <= self._monotone()]
                self._reprises = [r for r in self._reprises if r[0] > self._monotone()]
                attente = (
                    max(0.05, self._reprises[0][0] - self._monotone())
                    if self._reprises
                    else 1.0
                )
            for _, message in echues:
                self._tenter(message, dernier_essai=True)
            try:
                message = self._file.get(timeout=attente)
            except queue.Empty:
                continue
            if message is None:
                return
            self._tenter(message, dernier_essai=False)


class Courrier:
    """Budgets + file : ce que les routes appellent.

    Deux temps, à dessein : ``preparer`` compte l'envoi DANS la transaction
    de la route ; ``deposer`` le confie au fil APRÈS le ``COMMIT``. Un
    courriel déposé avant, puis une transaction annulée, aurait annoncé
    « mot de passe changé » pour un mot de passe qui ne l'était pas.
    """

    def __init__(
        self,
        file: FileCourriels,
        budgets: BudgetsCourriel,
        *,
        origine_publique: str | None,
    ) -> None:
        self.file = file
        self.budgets = budgets
        self.origine_publique = origine_publique

    def disponible(self, conn: sqlite3.Connection, maintenant: int) -> bool:
        """Faux si le budget des codes est épuisé ou le circuit ouvert : les
        routes qui envoient un code rendent alors 503 ``mailUnavailable``.

        C'est un état GLOBAL, et il ne renseigne sur aucune adresse parce que
        les routes du §3.5 le font bouger PAREIL pour une adresse connue ou
        inconnue (envoi fantôme, ``reel=False``). Jusqu'au 24/09/2026,
        ``reset/request`` y puisait pour un compte et jamais pour une
        inconnue : sur un service peu fréquenté, le compteur se devine, et
        le 503 suivant disait qui a un compte.
        """
        if self.budgets.epuise(conn, BUDGET_CODES, maintenant):
            _journal.warning("budget quotidien des codes épuisé")
            return False
        if self.file.circuit_ouvert():
            return False
        return True

    def preparer(
        self,
        conn: sqlite3.Connection,
        genre: str,
        destinataire: str,
        index: bytes,
        maintenant: int,
        *,
        code: str | None = None,
        date_ms: int | None = None,
        reel: bool = True,
    ) -> Message | None:
        """Compte l'envoi et rend le courriel, ou ``None`` s'il n'est pas dû.

        ``reel=False`` : l'envoi FANTÔME. Il compte exactement comme un vrai
        (mêmes budgets, mêmes écritures) et ne rend rien. Pour une adresse
        sans compte, là où un compte aurait reçu un avis : l'égalité
        d'énumération tient, et rien ne part vers un non-inscrit.
        """
        permis = self.budgets.autoriser(
            conn,
            budget_du_genre(genre),
            destinataire,
            maintenant,
            une_fois_par_jour=genre if genre in UNE_FOIS_PAR_JOUR else None,
            nouvelle_connexion=genre == "nouvelle_connexion",
        )
        if not permis or not reel:
            return None
        return self.rediger(genre, destinataire, index, code=code, date_ms=date_ms)

    def compter_code(
        self, conn: sqlite3.Connection, destinataire: str, maintenant: int
    ) -> bool:
        """Compte un envoi de CODE (budget des codes, plafonds de l'adresse)
        sans rien rédiger : ``signup/start`` et ``reset/request`` décident
        ensuite quoi envoyer, après avoir fait les mêmes écritures pour une
        adresse connue ou inconnue."""
        return self.budgets.autoriser(conn, BUDGET_CODES, destinataire, maintenant)

    def rediger(
        self,
        genre: str,
        destinataire: str,
        index: bytes,
        *,
        code: str | None = None,
        date_ms: int | None = None,
    ) -> Message:
        return rediger(
            genre,
            destinataire,
            index,
            origine_publique=self.origine_publique,
            code=code,
            date_ms=date_ms,
        )

    def deposer(self, *messages: Message | None) -> None:
        for message in messages:
            if message is not None:
                self.file.deposer(message)
