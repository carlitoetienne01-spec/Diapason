"""Le client des routes du serveur de comptes (§3.4), sans état ni politique.

Conception : ``docs/development/compte-chiffre.md`` §3.4.

Chaque méthode fait UNE requête par :class:`~diapason.compte.transport.Transport`
et rend ce que le serveur a dit, décodé et vérifié dans sa FORME : octets
en base64url sans remplissage, entiers véritables (``true`` n'est pas 1,
``1.0`` non plus). Rien ici ne décide quoi faire d'une réponse — c'est le
travail de :mod:`diapason.compte.service` — et rien ici n'ouvre une
enveloppe.

Ce que le client envoie ne contient jamais que ce que le §2.9 autorise :
l'adresse, ``authKey``, ``recoveryAuthKey``, des codes, des enveloppes
chiffrées. Ni la KEK, ni l'AMK, ni le mot de passe, ni ``R`` n'ont de
paramètre ici : une méthode qui en demanderait un serait une faute de
conception visible à la signature.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from diapason.compte.cles import b64url
from diapason.compte.transport import ErreurServeur, ReponseServeur, Transport

__all__ = [
    "VERSION_CONDITIONS",
    "ClientComptes",
    "Connexion",
    "Deballage",
    "Rotation",
    "SessionOuverte",
    "ReponseInattendue",
]

# La version des conditions que cette version de l'app fait accepter. Le
# serveur refuse toute autre valeur (409 ``termsOutdated``) : une app plus
# ancienne que les conditions doit d'abord se mettre à jour.
VERSION_CONDITIONS = 1

Jeton = Callable[[], str | None]


class ReponseInattendue(ErreurServeur):
    """Un 2xx dont la forme n'est pas celle du §3.4."""

    def __init__(self, champ: str) -> None:
        super().__init__(502, "serverError")
        self.champ = champ


# ----------------------------------------------------------------------
# Lecture stricte des réponses
# ----------------------------------------------------------------------


def _octets(corps: dict[str, Any], nom: str) -> bytes:
    valeur = corps.get(nom)
    if not isinstance(valeur, str) or not valeur:
        raise ReponseInattendue(nom)
    try:
        return base64.urlsafe_b64decode(valeur + "=" * (-len(valeur) % 4))
    except (binascii.Error, ValueError):
        raise ReponseInattendue(nom) from None


def _entier(corps: dict[str, Any], nom: str, *, minimum: int = 0) -> int:
    valeur = corps.get(nom)
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur < minimum:
        raise ReponseInattendue(nom)
    return valeur


def _texte(corps: dict[str, Any], nom: str) -> str:
    valeur = corps.get(nom)
    if not isinstance(valeur, str) or not valeur:
        raise ReponseInattendue(nom)
    return valeur


def _entier_ou_nul(corps: dict[str, Any], nom: str) -> int | None:
    valeur = corps.get(nom)
    if valeur is None:
        return None
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise ReponseInattendue(nom)
    return valeur


def _booleen(corps: dict[str, Any], nom: str) -> bool:
    valeur = corps.get(nom)
    if not isinstance(valeur, bool):
        raise ReponseInattendue(nom)
    return valeur


# ----------------------------------------------------------------------
# Réponses
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class SessionOuverte:
    """``signup/complete``, ``reset/complete`` : une session et les versions."""

    account_id: str
    session_id: str
    jeton: str = field(repr=False)
    vault_version: int
    keyring_version: int
    key_epoch: int
    incarnation: int


@dataclass(frozen=True)
class Connexion:
    """``POST /login`` : la session, plus le coffre pour s'ouvrir."""

    session: SessionOuverte
    kdf_version: int
    enveloppe_amk: bytes = field(repr=False)
    enveloppe_trousseau: bytes = field(repr=False)
    recovery_configured: bool
    pending_reset_at: int | None


@dataclass(frozen=True)
class Deballage:
    """``POST /recovery/unwrap``."""

    account_id: str
    jeton_recuperation: str = field(repr=False)
    enveloppe_amk_recuperation: bytes = field(repr=False)
    enveloppe_trousseau: bytes = field(repr=False)
    vault_version: int
    keyring_version: int
    key_epoch: int
    incarnation: int


@dataclass(frozen=True)
class Rotation:
    """``POST /vault/commit`` : les versions après, et la session neuve."""

    vault_version: int
    keyring_version: int
    key_epoch: int
    session_id: str
    jeton: str = field(repr=False)


def _session(corps: dict[str, Any]) -> SessionOuverte:
    return SessionOuverte(
        account_id=_texte(corps, "accountId"),
        session_id=_texte(corps, "sessionId"),
        jeton=_texte(corps, "sessionToken"),
        vault_version=_entier(corps, "vaultVersion", minimum=1),
        keyring_version=_entier(corps, "keyringVersion", minimum=1),
        key_epoch=_entier(corps, "keyEpoch", minimum=1),
        incarnation=_entier(corps, "incarnation", minimum=1),
    )


# ----------------------------------------------------------------------
# Le client
# ----------------------------------------------------------------------


class ClientComptes:
    """Une méthode par route du §3.4 dont l'étape 8 a besoin."""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport

    def _post(
        self, chemin: str, corps: dict[str, Any], jeton: Jeton | None = None
    ) -> ReponseServeur:
        return self.transport.requete("POST", chemin, corps=corps, jeton=jeton)

    # --- Inscription ---------------------------------------------------

    def signup_start(self, email: str) -> None:
        self._post(
            "/signup/start", {"email": email, "termsVersion": VERSION_CONDITIONS}
        )

    def signup_verify(self, email: str, code: str) -> tuple[str, str, bytes]:
        """Rend ``(signupToken, accountId, kdfSalt)``."""
        corps = self._post("/signup/verify", {"email": email, "code": code}).corps
        return (
            _texte(corps, "signupToken"),
            _texte(corps, "accountId"),
            _octets(corps, "kdfSalt"),
        )

    def signup_complete(
        self,
        *,
        signup_token: str,
        kdf_version: int,
        auth_key: bytes,
        enveloppe_amk: bytes,
        recuperation: tuple[bytes, bytes] | None,
        enveloppe_trousseau: bytes,
    ) -> SessionOuverte:
        corps = self._post(
            "/signup/complete",
            {
                "signupToken": signup_token,
                "kdfVersion": kdf_version,
                "authKey": b64url(auth_key),
                "wrappedMasterKey": b64url(enveloppe_amk),
                "recovery": _recuperation(recuperation),
                "keyring": b64url(enveloppe_trousseau),
            },
        ).corps
        return _session(corps)

    # --- Connexion -----------------------------------------------------

    def login_params(self, email: str) -> tuple[int, bytes]:
        """Rend ``(kdfVersion, kdfSalt)`` — la version est lue telle quelle ;
        c'est :func:`diapason.compte.cles.parametres_kdf` qui la juge."""
        corps = self._post("/login/params", {"email": email}).corps
        valeur = corps.get("kdfVersion")
        if isinstance(valeur, bool) or not isinstance(valeur, int):
            raise ReponseInattendue("kdfVersion")
        return valeur, _octets(corps, "kdfSalt")

    def login(self, email: str, auth_key: bytes) -> Connexion:
        corps = self._post(
            "/login", {"email": email, "authKey": b64url(auth_key)}
        ).corps
        kdf = corps.get("kdfVersion")
        if isinstance(kdf, bool) or not isinstance(kdf, int):
            raise ReponseInattendue("kdfVersion")
        return Connexion(
            session=_session(corps),
            kdf_version=kdf,
            enveloppe_amk=_octets(corps, "wrappedMasterKey"),
            enveloppe_trousseau=_octets(corps, "keyring"),
            recovery_configured=_booleen(corps, "recoveryConfigured"),
            pending_reset_at=_entier_ou_nul(corps, "pendingResetAt"),
        )

    def logout(self, jeton: Jeton) -> None:
        self._post("/logout", {}, jeton)

    def account(self, jeton: Jeton) -> dict[str, Any]:
        corps = self.transport.requete("GET", "/account", jeton=jeton).corps
        _entier(corps, "incarnation", minimum=1)
        _booleen(corps, "recoveryConfigured")
        _entier_ou_nul(corps, "pendingResetAt")
        return corps

    def nommer_session(self, nom_chiffre: bytes, jeton: Jeton) -> None:
        self.transport.requete(
            "PUT",
            "/sessions/current",
            corps={"encryptedName": b64url(nom_chiffre)},
            jeton=jeton,
        )

    def sessions(self, jeton: Jeton) -> list[dict[str, Any]]:
        corps = self.transport.requete("GET", "/sessions", jeton=jeton).corps
        sessions = corps.get("sessions")
        if not isinstance(sessions, list):
            raise ReponseInattendue("sessions")
        lues = []
        for s in sessions:
            if not isinstance(s, dict):
                raise ReponseInattendue("sessions")
            nom = s.get("encryptedName")
            lues.append(
                {
                    "sessionId": _texte(s, "sessionId"),
                    "encryptedName": None
                    if nom is None
                    else _octets(s, "encryptedName"),
                    "createdDay": _entier(s, "createdDay"),
                    "lastSeenDay": _entier(s, "lastSeenDay"),
                    "current": _booleen(s, "current"),
                }
            )
        return lues

    def account_delete(self, auth_key: bytes, jeton: Jeton) -> None:
        self._post("/account/delete", {"authKey": b64url(auth_key)}, jeton)

    # --- Coffre --------------------------------------------------------

    def vault_code(self, jeton: Jeton) -> None:
        self._post("/vault/code", {}, jeton)

    def vault_commit(
        self,
        *,
        preuve: dict[str, Any],
        base_vault_version: int,
        base_keyring_version: int,
        new_vault_version: int,
        new_keyring_version: int,
        new_key_epoch: int,
        kdf_version: int,
        auth_key: bytes,
        enveloppe_amk: bytes,
        recuperation: dict[str, Any],
        enveloppe_trousseau: bytes,
        session_revoquee: str | None = None,
        jeton: Jeton | None = None,
    ) -> Rotation:
        """``preuve`` et ``recuperation`` sont déjà au format du fil (§3.4)."""
        corps: dict[str, Any] = {
            "proof": preuve,
            "baseVaultVersion": base_vault_version,
            "newVaultVersion": new_vault_version,
            "baseKeyringVersion": base_keyring_version,
            "newKeyringVersion": new_keyring_version,
            "newKeyEpoch": new_key_epoch,
            "password": {
                "kdfVersion": kdf_version,
                "authKey": b64url(auth_key),
                "wrappedMasterKey": b64url(enveloppe_amk),
            },
            "recovery": recuperation,
            "keyring": b64url(enveloppe_trousseau),
        }
        if session_revoquee is not None:
            corps["revokedSessionId"] = session_revoquee
        reponse = self._post("/vault/commit", corps, jeton).corps
        return Rotation(
            vault_version=_entier(reponse, "vaultVersion", minimum=1),
            keyring_version=_entier(reponse, "keyringVersion", minimum=1),
            key_epoch=_entier(reponse, "keyEpoch", minimum=1),
            session_id=_texte(reponse, "sessionId"),
            jeton=_texte(reponse, "sessionToken"),
        )

    def recovery_unwrap(self, email: str, recovery_auth_key: bytes) -> Deballage:
        corps = self._post(
            "/recovery/unwrap",
            {"email": email, "recoveryAuthKey": b64url(recovery_auth_key)},
        ).corps
        return Deballage(
            account_id=_texte(corps, "accountId"),
            jeton_recuperation=_texte(corps, "recoveryToken"),
            enveloppe_amk_recuperation=_octets(corps, "sealedMasterKey"),
            enveloppe_trousseau=_octets(corps, "keyring"),
            vault_version=_entier(corps, "vaultVersion", minimum=1),
            keyring_version=_entier(corps, "keyringVersion", minimum=1),
            key_epoch=_entier(corps, "keyEpoch", minimum=1),
            incarnation=_entier(corps, "incarnation", minimum=1),
        )

    # --- Réinitialisation ----------------------------------------------

    def reset_request(self, email: str) -> None:
        self._post("/reset/request", {"email": email})

    def reset_confirm(self, email: str, code: str) -> int:
        corps = self._post("/reset/confirm", {"email": email, "code": code}).corps
        return _entier(corps, "effectiveAt")

    def reset_cancel(self, jeton: Jeton) -> None:
        self._post("/reset/cancel", {}, jeton)

    def reset_complete(
        self,
        *,
        email: str,
        code: str,
        kdf_version: int,
        auth_key: bytes,
        enveloppe_amk: bytes,
        recuperation: tuple[bytes, bytes] | None,
        enveloppe_trousseau: bytes,
    ) -> SessionOuverte:
        corps = self._post(
            "/reset/complete",
            {
                "email": email,
                "code": code,
                "kdfVersion": kdf_version,
                "authKey": b64url(auth_key),
                "wrappedMasterKey": b64url(enveloppe_amk),
                "recovery": _recuperation(recuperation),
                "keyring": b64url(enveloppe_trousseau),
            },
        ).corps
        return _session(corps)


def _recuperation(valeur: tuple[bytes, bytes] | None) -> dict[str, str] | None:
    if valeur is None:
        return None
    auth, scellee = valeur
    return {"authKey": b64url(auth), "sealedMasterKey": b64url(scellee)}
