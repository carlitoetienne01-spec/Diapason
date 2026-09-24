"""Outils des tests du service : faux expéditeur, horloge, parcours.

Conception : ``docs/development/compte-chiffre.md`` §3 et étape 4 du §6.

Aucun courriel réel ne part d'ici : ``FauxExpediteur`` range les messages
dans une liste. Aucune lecture de ``/etc/diapason`` : les secrets sont tirés
au hasard pour chaque test.

Les enveloppes envoyées au service viennent du VRAI client
(``diapason.compte.enveloppe``) : si le serveur refusait la forme de ce que
le client produit, ces tests le verraient. Le service, lui, n'importe rien
de ``diapason`` (``test_forme.py``).
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient

from diapason.compte import enveloppe as env
from diapason_comptes.app import Contexte
from diapason_comptes.base import JOUR_MS as _JOUR_MS
from diapason_comptes.courriel import Message
from diapason_comptes.secrets_serveur import Configuration, SecretsServeur
from diapason_comptes.validation import b64url

MINUTE_MS = 60_000
HEURE_MS = 3_600_000
# Ré-export par AFFECTATION : ``ruff --fix`` supprime un alias d'import que
# le module n'utilise pas lui-même, même importé d'ailleurs (CLAUDE.md §5).
JOUR_MS = _JOUR_MS
DEBUT_MS = 1_790_000_000_000  # 21/09/2026, une date fixe : aucun test ne lit l'heure


class Horloge:
    def __init__(self, ms: int = DEBUT_MS) -> None:
        self.ms = ms

    def __call__(self) -> int:
        return self.ms

    def avancer(self, ms: int) -> None:
        self.ms += ms


class FauxExpediteur:
    """Range les messages ; peut rester bloqué ou échouer sur commande."""

    def __init__(self) -> None:
        self.envoyes: list[Message] = []
        self.echouer = False
        self.retenir = False
        self.entre = threading.Event()
        self.relache = threading.Event()
        self._verrou = threading.Lock()

    def envoyer(self, message: Message) -> None:
        self.entre.set()
        if self.retenir:
            # 60 s au plus : c'est l'expéditeur bloqué du §6, étape 4.
            self.relache.wait(60)
        if self.echouer:
            raise ConnectionError("panne simulée de Resend")
        with self._verrou:
            self.envoyes.append(message)

    def messages(self, destinataire: str | None = None, genre: str | None = None):
        with self._verrou:
            return [
                m
                for m in self.envoyes
                if (destinataire is None or m.destinataire == destinataire)
                and (genre is None or m.genre == genre)
            ]

    def attendre(
        self, destinataire: str, genre: str, nombre: int = 1, delai_s: float = 5.0
    ) -> Message:
        limite = time.monotonic() + delai_s
        while time.monotonic() < limite:
            trouves = self.messages(destinataire, genre)
            if len(trouves) >= nombre:
                return trouves[nombre - 1]
            time.sleep(0.005)
        raise AssertionError(f"aucun courriel « {genre} » pour {destinataire}")


def secrets_de_test(
    version: int = 1, anciens: SecretsServeur | None = None
) -> SecretsServeur:
    poivres = dict(anciens.poivres) if anciens else {}
    cles = dict(anciens.cles_repos) if anciens else {}
    poivres[version] = os.urandom(32)
    cles[version] = os.urandom(32)
    return SecretsServeur(
        version=version,
        poivres=poivres,
        cles_repos=cles,
        graine_sel=anciens.graine_sel if anciens else os.urandom(32),
    )


def code_de(message: Message) -> str:
    trouve = re.search(r"\b(\d{6})\b", message.texte)
    assert trouve, f"le courriel « {message.genre} » doit porter un code"
    return trouve.group(1)


# ----------------------------------------------------------------------
# Enveloppes du vrai client
# ----------------------------------------------------------------------


def amk_mdp(account_id: str, vault_version: int = 1) -> bytes:
    return env.envelopper_amk(
        os.urandom(32),
        os.urandom(32),
        account_id=account_id,
        kdf_version=1,
        vault_version=vault_version,
    )


def amk_recup(account_id: str, vault_version: int = 1) -> bytes:
    pk = X25519PrivateKey.generate().public_key().public_bytes_raw()
    return env.sceller_amk_recuperation(
        pk, os.urandom(32), account_id=account_id, vault_version=vault_version
    )


def trousseau(
    account_id: str, keyring_version: int = 1, vault_version: int = 1
) -> bytes:
    clair = b'{"currentEpoch":1,"epochs":{"1":"' + b"A" * 43 + b'"},"v":1}'
    return env.sceller_trousseau_brut(
        os.urandom(32),
        clair,
        account_id=account_id,
        keyring_version=keyring_version,
        vault_version=vault_version,
    )


def nom_appareil(account_id: str, session_id: str, nom: str = "Mac de test") -> bytes:
    return env.sceller_nom_appareil(
        os.urandom(32), nom, account_id=account_id, session_id=session_id, key_epoch=1
    )


@dataclass
class Inscrit:
    """Un compte créé de bout en bout, avec ce que le client a envoyé."""

    email: str
    account_id: str
    session_id: str
    jeton: str
    auth_key: bytes
    recovery_auth_key: bytes | None
    wrapped: bytes
    sealed: bytes | None
    keyring: bytes
    kdf_salt: str
    vault_version: int = 1
    keyring_version: int = 1
    key_epoch: int = 1
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def bearer(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.jeton}"}


@dataclass
class Service:
    ctx: Contexte
    app: Any
    client: TestClient
    horloge: Horloge
    expediteur: FauxExpediteur
    configuration: Configuration
    secrets: SecretsServeur
    _clients: list[TestClient] = field(default_factory=list)

    def depuis(self, ip: str) -> TestClient:
        """Un client dont l'adresse source est ``ip`` (préfixe /24 ou /48)."""
        client = TestClient(self.app, client=(ip, 50000))
        self._clients.append(client)
        return client

    def post(self, chemin: str, corps: dict | None = None, **kw: Any):
        return self.client.post("/api/v1" + chemin, json=corps, **kw)

    def get(self, chemin: str, **kw: Any):
        return self.client.get("/api/v1" + chemin, **kw)

    # --- Parcours ------------------------------------------------------

    def inscrire(self, email: str, *, recuperation: bool = True) -> Inscrit:
        r = self.post("/signup/start", {"email": email, "termsVersion": 1})
        assert r.status_code == 202, r.text
        code = code_de(self.expediteur.attendre(email, "code_inscription"))
        r = self.post("/signup/verify", {"email": email, "code": code})
        assert r.status_code == 200, r.text
        verifie = r.json()
        account_id = verifie["accountId"]
        auth_key = os.urandom(32)
        recovery_auth_key = os.urandom(32) if recuperation else None
        wrapped = amk_mdp(account_id)
        sealed = amk_recup(account_id) if recuperation else None
        keyring = trousseau(account_id)
        corps = {
            "signupToken": verifie["signupToken"],
            "kdfVersion": 1,
            "authKey": b64url(auth_key),
            "wrappedMasterKey": b64url(wrapped),
            "recovery": (
                {
                    "authKey": b64url(recovery_auth_key),
                    "sealedMasterKey": b64url(sealed),
                }
                if recuperation
                else None
            ),
            "keyring": b64url(keyring),
        }
        r = self.post("/signup/complete", corps)
        assert r.status_code == 201, r.text
        session = r.json()
        return Inscrit(
            email=email,
            account_id=account_id,
            session_id=session["sessionId"],
            jeton=session["sessionToken"],
            auth_key=auth_key,
            recovery_auth_key=recovery_auth_key,
            wrapped=wrapped,
            sealed=sealed,
            keyring=keyring,
            kdf_salt=verifie["kdfSalt"],
        )

    def connecter(self, inscrit: Inscrit, client: TestClient | None = None):
        client = client or self.client
        return client.post(
            "/api/v1/login",
            json={"email": inscrit.email, "authKey": b64url(inscrit.auth_key)},
        )

    def corps_commit(
        self,
        inscrit: Inscrit,
        *,
        preuve: dict | None = None,
        nouvelle_auth: bytes | None = None,
        recuperation: dict | None = None,
        base_coffre: int | None = None,
        base_trousseau: int | None = None,
        epoque: int | None = None,
        **extra: Any,
    ) -> dict:
        """Le corps d'une rotation, tel que ``faire_tourner_les_cles`` le
        prépare : versions + 1, époque + 1, enveloppes neuves."""
        vv = inscrit.vault_version if base_coffre is None else base_coffre
        kv = inscrit.keyring_version if base_trousseau is None else base_trousseau
        nouvelle_auth = nouvelle_auth or inscrit.auth_key
        if recuperation is None:
            recuperation = (
                {
                    "mode": "keep",
                    "sealedMasterKey": b64url(amk_recup(inscrit.account_id, vv + 1)),
                }
                if inscrit.sealed is not None
                else {"mode": "remove"}
            )
        return {
            "proof": preuve
            or {"kind": "password", "authKey": b64url(inscrit.auth_key)},
            "baseVaultVersion": vv,
            "newVaultVersion": vv + 1,
            "baseKeyringVersion": kv,
            "newKeyringVersion": kv + 1,
            "newKeyEpoch": (inscrit.key_epoch + 1) if epoque is None else epoque,
            "password": {
                "kdfVersion": 1,
                "authKey": b64url(nouvelle_auth),
                "wrappedMasterKey": b64url(amk_mdp(inscrit.account_id, vv + 1)),
            },
            "recovery": recuperation,
            "keyring": b64url(trousseau(inscrit.account_id, kv + 1, vv + 1)),
            **extra,
        }

    def octets_sur_disque(self) -> bytes:
        """Tout ce qu'un voleur de ``comptes.db`` emporterait, WAL compris."""
        total = b""
        for suffixe in ("", "-wal"):
            chemin = Path(str(self.configuration.chemin_base) + suffixe)
            if chemin.exists():
                total += chemin.read_bytes()
        return total
