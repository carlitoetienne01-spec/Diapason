"""Le trousseau des époques, le coffre et la rotation des clés.

Conception : ``docs/development/compte-chiffre.md`` §2.2 et §2.8.

::

    KEYRING = {"v":1, "currentEpoch":e, "epochs":{"1":b64(DEK_1), …},
               "idKey":b64(K_id), "recoveryPublicKey":b64(pk_rec) | null}

Le « coffre » est ce que le VPS garde sans pouvoir l'ouvrir : l'AMK
enveloppée sous la KEK (type 03), scellée vers la récupération (type 06), et
le trousseau chiffré sous une clé tirée de l'AMK (type 05).

La version précédente de la conception réenveloppait la MÊME AMK à chaque
changement de secret : un ancien mot de passe, une ancienne enveloppe ou un
appareil perdu donnaient accès aux données présentes ET futures, pour
toujours (défaut bloquant de la revue cryptographie, 24/09/2026). Chaque
rotation tire donc une AMK neuve et une DEK d'époque suivante.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from diapason.compte.cles import (
    LONGUEUR_CLE,
    ErreurCompte,
    cle_piece,
    cle_trousseau,
    en_octets,
    entier,
    identifiant_objet,
    identifiant_piece,
    sans_doublons,
    version_exacte,
)
from diapason.compte.enveloppe import (
    EPOQUE_MAX,
    encoder_clair,
    envelopper_amk,
    lire_clair,
    lire_en_tete,
    ouvrir_amk,
    ouvrir_amk_recuperation,
    ouvrir_objet,
    ouvrir_trousseau_brut,
    sceller_amk_recuperation,
    sceller_objet,
    sceller_trousseau_brut,
)


class TrousseauInvalide(ErreurCompte):
    code = "keyringInvalid"


class EpoqueInconnue(ErreurCompte):
    """Blob d'une époque absente du trousseau : il faut le recharger (§4.3)."""

    code = "keyEpochUnknown"


class CleServeurInvalide(ErreurCompte):
    """Un coffre qui s'ouvre, mais qui ne peut pas venir du compte (§4.12)."""

    code = "serverKeyInvalid"


class ObjetPermute(ErreurCompte):
    """``objectId`` recalculé depuis le clair ≠ celui du serveur (§2.5)."""

    code = "objectPermuted"


VERSION_TROUSSEAU = 1
_CLES_TROUSSEAU = frozenset(
    {"v", "currentEpoch", "epochs", "idKey", "recoveryPublicKey"}
)


def _b64(octets: bytes) -> str:
    return base64.b64encode(octets).decode("ascii")


def _de_b64(texte: object, nom: str) -> bytes:
    if not isinstance(texte, str):
        raise TrousseauInvalide(f"{nom} n'est pas une chaîne base64")
    try:
        octets = base64.b64decode(texte.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise TrousseauInvalide(f"{nom} : base64 invalide") from exc
    if len(octets) != LONGUEUR_CLE:
        raise TrousseauInvalide(f"{nom} doit faire {LONGUEUR_CLE} o")
    return octets


@dataclass(frozen=True)
class Trousseau:
    """Les DEK de toutes les époques, ``K_id`` et ``pk_rec``.

    Les anciennes DEK restent : c'est ce qui laisse lire l'historique après
    une rotation sans rien rechiffrer (§1.2).
    """

    current_epoch: int
    epochs: Mapping[int, bytes] = field(repr=False)
    id_key: bytes = field(repr=False)
    recovery_public_key: bytes | None

    def __post_init__(self) -> None:
        entier(self.current_epoch, "currentEpoch", minimum=1)
        if self.current_epoch > EPOQUE_MAX:
            raise TrousseauInvalide("currentEpoch dépasse uint32")
        epoques = {}
        for epoque, dek in dict(self.epochs).items():
            entier(epoque, "époque", minimum=1)
            epoques[epoque] = en_octets(dek, f"DEK_{epoque}", LONGUEUR_CLE)
        if self.current_epoch not in epoques:
            raise TrousseauInvalide("la DEK de l'époque courante manque")
        # Un trousseau « courant = 1, epochs = {1, 2} » était accepté
        # (24/09/2026) : les écritures partaient sous DEK_1, que l'appareil
        # perdu connaît, et la rotation suivante ÉCRASAIT DEK_2 en silence —
        # tout ce qui avait été scellé sous elle devenait illisible.
        if self.current_epoch != max(epoques):
            raise TrousseauInvalide("currentEpoch n'est pas la plus haute époque")
        object.__setattr__(self, "epochs", MappingProxyType(epoques))
        object.__setattr__(self, "id_key", en_octets(self.id_key, "K_id", LONGUEUR_CLE))
        if self.recovery_public_key is not None:
            object.__setattr__(
                self,
                "recovery_public_key",
                en_octets(self.recovery_public_key, "pk_rec", LONGUEUR_CLE),
            )

    def dek(self, epoque: int) -> bytes:
        try:
            return self.epochs[epoque]
        except KeyError:
            raise EpoqueInconnue(f"époque {epoque} absente du trousseau") from None

    @property
    def dek_courante(self) -> bytes:
        return self.epochs[self.current_epoch]

    def identifiant_objet(self, collection: str, id_local: str) -> str:
        return identifiant_objet(self.id_key, collection, id_local)

    def identifiant_piece(self, octets: bytes, epoque: int | None = None) -> str:
        """Par époque : après une rotation, la même image change d'identifiant
        et repart sous la nouvelle DEK (§2.2, §4.7)."""
        e = self.current_epoch if epoque is None else epoque
        return identifiant_piece(cle_piece(self.dek(e)), octets)

    def sceller_objet(
        self, clair: dict[str, Any], *, account_id: str, incarnation: int, rev: int
    ) -> tuple[str, bytes]:
        """Rend ``(objectId, blob)``, toujours sous l'époque COURANTE : le VPS
        refuse une poussée d'une autre époque (409 ``keyEpochChanged``)."""
        octets = encoder_clair(clair)
        lire_clair(octets)
        object_id = self.identifiant_objet(clair["collection"], clair["id"])
        blob = sceller_objet(
            self.dek_courante,
            octets,
            account_id=account_id,
            incarnation=incarnation,
            object_id=object_id,
            rev=rev,
            key_epoch=self.current_epoch,
        )
        return object_id, blob

    def ouvrir_objet(
        self,
        blob: bytes,
        *,
        account_id: str,
        incarnation: int,
        object_id: str,
        rev: int,
    ) -> dict[str, Any]:
        """Ouvre, décode, puis RECALCULE ``objectId`` depuis le clair.

        L'AAD lie déjà le blob à son ``objectId`` ; le recalcul attrape en
        plus un clair d'une autre conversation scellé sous le bon
        identifiant — que seul un porteur de la DEK pourrait fabriquer, mais
        qu'on ne doit pas ingérer à la place d'une autre.
        """
        dek = self.dek(lire_en_tete(blob).key_epoch)
        clair = lire_clair(
            ouvrir_objet(
                dek,
                blob,
                account_id=account_id,
                incarnation=incarnation,
                object_id=object_id,
                rev=rev,
            )
        )
        if self.identifiant_objet(clair["collection"], clair["id"]) != object_id:
            raise ObjetPermute("objectId recalculé différent")
        return clair


def nouveau_trousseau(recovery_public_key: bytes | None) -> Trousseau:
    """Époque 1, DEK et ``K_id`` aléatoires."""
    return Trousseau(
        current_epoch=1,
        epochs={1: os.urandom(LONGUEUR_CLE)},
        id_key=os.urandom(LONGUEUR_CLE),
        recovery_public_key=recovery_public_key,
    )


def serialiser(trousseau: Trousseau) -> bytes:
    """JSON trié et compact, clés en anglais camelCase (CLAUDE.md §3)."""
    clair = {
        "v": VERSION_TROUSSEAU,
        "currentEpoch": trousseau.current_epoch,
        "epochs": {str(e): _b64(dek) for e, dek in sorted(trousseau.epochs.items())},
        "idKey": _b64(trousseau.id_key),
        "recoveryPublicKey": (
            None
            if trousseau.recovery_public_key is None
            else _b64(trousseau.recovery_public_key)
        ),
    }
    return json.dumps(clair, sort_keys=True, separators=(",", ":")).encode("utf-8")


def deserialiser(octets: bytes) -> Trousseau:
    """Strict : clé inconnue, version inconnue ou époque mal écrite refusées."""
    try:
        clair = json.loads(
            en_octets(octets, "trousseau").decode("utf-8"),
            object_pairs_hook=sans_doublons,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise TrousseauInvalide("trousseau non JSON ou clé en double") from exc
    if not isinstance(clair, dict) or set(clair) != _CLES_TROUSSEAU:
        raise TrousseauInvalide("clés du trousseau inattendues")
    if not version_exacte(clair["v"], VERSION_TROUSSEAU):
        raise TrousseauInvalide(f"version de trousseau inconnue : {clair['v']!r}")
    epochs = clair["epochs"]
    if not isinstance(epochs, dict) or not epochs:
        raise TrousseauInvalide("epochs vide ou mal formé")
    deks = {}
    for texte, dek in epochs.items():
        # « 01 » et « 1 » désigneraient la même époque : on n'accepte que la
        # forme décimale canonique, pour qu'un trousseau n'ait qu'une écriture.
        if not texte.isascii() or not texte.isdigit() or texte != str(int(texte)):
            raise TrousseauInvalide(f"époque mal écrite : {texte!r}")
        deks[int(texte)] = _de_b64(dek, f"epochs[{texte}]")
    courante = clair["currentEpoch"]
    if isinstance(courante, bool) or not isinstance(courante, int):
        raise TrousseauInvalide("currentEpoch n'est pas un entier")
    pk = clair["recoveryPublicKey"]
    try:
        return Trousseau(
            current_epoch=courante,
            epochs=deks,
            id_key=_de_b64(clair["idKey"], "idKey"),
            recovery_public_key=None
            if pk is None
            else _de_b64(pk, "recoveryPublicKey"),
        )
    except (TypeError, ValueError) as exc:
        raise TrousseauInvalide(str(exc)) from exc


# ----------------------------------------------------------------------
# Le coffre et la rotation (§2.8)
# ----------------------------------------------------------------------


class _Garder:
    def __repr__(self) -> str:
        return "GARDER"


GARDER: Any = _Garder()
"""Pour ``recovery_public_key`` de :func:`faire_tourner_les_cles` : garder
celle du trousseau déchiffré (et non une clé venue du serveur)."""


@dataclass(frozen=True)
class Coffre:
    """Ce qu'un ``POST /vault/commit`` envoie, plus l'AMK et le trousseau clairs.

    ``enveloppe_amk_recuperation`` vaut ``None`` quand le compte n'a pas (ou
    plus) de clé de récupération.
    """

    amk: bytes = field(repr=False)
    trousseau: Trousseau
    vault_version: int
    keyring_version: int
    enveloppe_amk: bytes = field(repr=False)
    enveloppe_amk_recuperation: bytes | None = field(repr=False)
    enveloppe_trousseau: bytes = field(repr=False)


def _sceller_coffre(
    amk: bytes,
    trousseau: Trousseau,
    *,
    kek: bytes,
    account_id: str,
    kdf_version: int,
    vault_version: int,
    keyring_version: int,
) -> Coffre:
    recuperation = None
    if trousseau.recovery_public_key is not None:
        recuperation = sceller_amk_recuperation(
            trousseau.recovery_public_key,
            amk,
            account_id=account_id,
            vault_version=vault_version,
        )
    return Coffre(
        amk=amk,
        trousseau=trousseau,
        vault_version=vault_version,
        keyring_version=keyring_version,
        enveloppe_amk=envelopper_amk(
            kek,
            amk,
            account_id=account_id,
            kdf_version=kdf_version,
            vault_version=vault_version,
        ),
        enveloppe_amk_recuperation=recuperation,
        enveloppe_trousseau=sceller_trousseau_brut(
            cle_trousseau(amk),
            serialiser(trousseau),
            account_id=account_id,
            keyring_version=keyring_version,
            vault_version=vault_version,
        ),
    )


def creer_coffre(
    kek: bytes, *, account_id: str, kdf_version: int, recovery_public_key: bytes | None
) -> Coffre:
    """Le coffre d'un compte neuf : AMK_1, trousseau 1, époque 1."""
    return _sceller_coffre(
        os.urandom(LONGUEUR_CLE),
        nouveau_trousseau(recovery_public_key),
        kek=kek,
        account_id=account_id,
        kdf_version=kdf_version,
        vault_version=1,
        keyring_version=1,
    )


def faire_tourner_les_cles(
    trousseau: Trousseau,
    *,
    kek: bytes,
    account_id: str,
    kdf_version: int,
    vault_version: int,
    keyring_version: int,
    recovery_public_key: Any = GARDER,
) -> Coffre:
    """Les étapes 1 à 4 du §2.8 ; l'étape 5 (``vault/commit``) est au réseau.

    ``kek`` est celle du NOUVEAU mot de passe (ou de l'actuel, pour une
    révocation). ``vault_version`` et ``keyring_version`` sont les versions
    COURANTES : le coffre rendu porte ``+1`` à chacune.
    """
    if trousseau.current_epoch >= EPOQUE_MAX:
        raise TrousseauInvalide("plus aucune époque disponible")
    if recovery_public_key is GARDER:
        recovery_public_key = trousseau.recovery_public_key
    suivante = trousseau.current_epoch + 1
    if suivante in trousseau.epochs:
        # Inatteignable tant que ``Trousseau`` exige courante = max ; gardé
        # parce qu'écraser une DEK rend illisible tout ce qu'elle scelle.
        raise TrousseauInvalide(f"la DEK de l'époque {suivante} existe déjà")
    nouveau = Trousseau(
        current_epoch=suivante,
        epochs={**trousseau.epochs, suivante: os.urandom(LONGUEUR_CLE)},
        id_key=trousseau.id_key,
        recovery_public_key=recovery_public_key,
    )
    return _sceller_coffre(
        os.urandom(LONGUEUR_CLE),
        nouveau,
        kek=kek,
        account_id=account_id,
        kdf_version=kdf_version,
        vault_version=entier(vault_version, "vaultVersion") + 1,
        keyring_version=entier(keyring_version, "keyringVersion") + 1,
    )


def ouvrir_trousseau(
    amk: bytes,
    blob: bytes,
    *,
    account_id: str,
    keyring_version: int,
    vault_version: int,
    plancher_keyring_version: int,
    plancher_vault_version: int,
) -> Trousseau:
    return deserialiser(
        ouvrir_trousseau_brut(
            cle_trousseau(amk),
            blob,
            account_id=account_id,
            keyring_version=keyring_version,
            vault_version=vault_version,
            plancher_keyring_version=plancher_keyring_version,
            plancher_vault_version=plancher_vault_version,
        )
    )


def ouvrir_coffre(
    kek: bytes,
    *,
    enveloppe_amk: bytes,
    enveloppe_trousseau: bytes,
    account_id: str,
    kdf_version: int,
    vault_version: int,
    keyring_version: int,
    plancher_vault_version: int,
    plancher_keyring_version: int,
) -> tuple[bytes, Trousseau]:
    """Mot de passe → ``(AMK, trousseau)``. Les planchers sont OBLIGATOIRES :
    un coffre restauré d'avant une rotation s'ouvrirait sinon avec l'ancien
    mot de passe (§4.4)."""
    amk = ouvrir_amk(
        kek,
        enveloppe_amk,
        account_id=account_id,
        kdf_version=kdf_version,
        vault_version=vault_version,
        plancher_vault_version=plancher_vault_version,
    )
    return amk, ouvrir_trousseau(
        amk,
        enveloppe_trousseau,
        account_id=account_id,
        keyring_version=keyring_version,
        vault_version=vault_version,
        plancher_keyring_version=plancher_keyring_version,
        plancher_vault_version=plancher_vault_version,
    )


def ouvrir_coffre_par_recuperation(
    cle_privee: X25519PrivateKey,
    *,
    enveloppe_amk_recuperation: bytes,
    enveloppe_trousseau: bytes,
    account_id: str,
    vault_version: int,
    keyring_version: int,
    plancher_vault_version: int,
    plancher_keyring_version: int,
) -> tuple[bytes, Trousseau]:
    """``R`` → ``(AMK, trousseau)``, si le trousseau nomme bien CETTE ``pk_rec``.

    HPKE en mode Base n'authentifie pas l'expéditeur : quiconque connaît
    ``pk_rec`` scelle une enveloppe 06 valide. Or ``pk_rec`` est dans le
    trousseau de chaque appareil, l'appareil perdu compris (A4). La première
    passe (24/09/2026) acceptait donc un coffre forgé par l'appareil perdu
    et le VPS (A4 + A1) : une AMK à eux, un trousseau dont
    ``recoveryPublicKey`` était LEUR clé — et la rotation suivante, qui garde
    la récupération par défaut, leur scellait l'AMK neuve. Un trousseau qui
    ne nomme pas la clé tirée de ``R`` est refusé : ``serverKeyInvalid``.

    Ce contrôle ne suffit pas seul : l'appareil perdu peut encore forger un
    coffre qui porte la VRAIE ``pk_rec``, avec des DEK choisies par lui.
    L'appelant (étape 8) doit donc faire tourner les clés AVANT toute
    écriture, et tenir l'historique ouvert par ce chemin pour non
    authentifié.
    """
    amk = ouvrir_amk_recuperation(
        cle_privee,
        enveloppe_amk_recuperation,
        account_id=account_id,
        vault_version=vault_version,
        plancher_vault_version=plancher_vault_version,
    )
    trousseau = ouvrir_trousseau(
        amk,
        enveloppe_trousseau,
        account_id=account_id,
        keyring_version=keyring_version,
        vault_version=vault_version,
        plancher_keyring_version=plancher_keyring_version,
        plancher_vault_version=plancher_vault_version,
    )
    attendue = cle_privee.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    if trousseau.recovery_public_key is None or not hmac.compare_digest(
        trousseau.recovery_public_key, attendue
    ):
        raise CleServeurInvalide(
            "le trousseau ne nomme pas la clé de récupération qui l'a ouvert"
        )
    return amk, trousseau
