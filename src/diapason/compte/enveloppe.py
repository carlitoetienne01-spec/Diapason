"""Le format d'enveloppe « DPE1 », son AAD et son rembourrage.

Conception : ``docs/development/compte-chiffre.md`` §2.5.

::

    octet 0     format 0x01
    octet 1     type : 01 objet · 02 pièce · 03 AMK sous KEK · 04 nom d'appareil
                       05 trousseau · 06 AMK scellée vers la récupération
    octets 2-5  keyEpoch, uint32 gros-boutiste (0 pour 03, 05 et 06)
    types 01-05 : sel HKDF (32 o) · nonce (12 o) · chiffré ‖ tag (16 o)
                  soit 66 o de surcoût
    type 06     : sortie HPKE = enc (32 o) ‖ chiffré ‖ tag — 86 o pour une AMK

Chaque enveloppe des types 01 à 05 est scellée sous une sous-clé HKDF à
usage unique, tirée d'un sel aléatoire. L'AAD lie l'en-tête et le contexte
(compte, objet, révision, époque, incarnation…) : un blob déplacé d'un
compte, d'un objet ou d'une révision à l'autre ne s'ouvre plus.

Sel et nonce peuvent être INJECTÉS, pour les vecteurs de contrat seulement ;
par défaut, ils viennent toujours d'``os.urandom``.
"""

from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hpke
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from diapason.compte.cles import (
    LONGUEUR_CLE,
    PREFIXE_INFO,
    ErreurCompte,
    en_octets,
    entier,
    hkdf,
    parametres_kdf,
    sans_doublons,
    version_exacte,
)

# ----------------------------------------------------------------------
# Erreurs
# ----------------------------------------------------------------------


class EnveloppeIllisible(ErreurCompte):
    """En-tête, taille, tag ou rembourrage refusés.

    Une seule exception pour tous les refus, à dessein : le moteur de
    synchronisation met l'objet en quarantaine « illisible » quelle que soit
    la cause (§4.3), et un message qui distinguerait « mauvais tag » de
    « mauvais rembourrage » renseignerait qui forge les blobs.
    """

    code = "envelopeUnreadable"


class CleServeurPerimee(ErreurCompte):
    """Coffre ou trousseau sous le plancher local (§4.4)."""

    code = "serverKeyStale"


class ClairInvalide(ErreurCompte):
    code = "plaintextInvalid"


# ----------------------------------------------------------------------
# Constantes figées par les vecteurs
# ----------------------------------------------------------------------

FORMAT_DPE1 = 0x01

TYPE_OBJET = 0x01
TYPE_PIECE = 0x02
TYPE_AMK_MOT_DE_PASSE = 0x03
TYPE_NOM_APPAREIL = 0x04
TYPE_TROUSSEAU = 0x05
TYPE_AMK_RECUPERATION = 0x06

LONGUEUR_EN_TETE_COURT = 6
LONGUEUR_SEL = 32
LONGUEUR_NONCE = 12
LONGUEUR_TAG = 16
LONGUEUR_EN_TETE = LONGUEUR_EN_TETE_COURT + LONGUEUR_SEL + LONGUEUR_NONCE
SURCOUT = LONGUEUR_EN_TETE + LONGUEUR_TAG  # 66 o, que le VPS retranche avant Padmé
LONGUEUR_ENC_HPKE = 32
LONGUEUR_AMK_SCELLEE = (
    LONGUEUR_EN_TETE_COURT + LONGUEUR_ENC_HPKE + LONGUEUR_CLE + LONGUEUR_TAG
)

EPOQUE_MAX = 0xFFFFFFFF
# L'uint32 BE en tête du cadre porte L, la longueur du clair SEUL : au-delà
# de 2^32 − 1 o (4 Gio), ``struct.pack(">I")`` lèverait ``struct.error``, qui
# n'est pas une ``ValueError``. La première passe (24/09/2026) écrivait
# « // 2 » sans raison chiffrée ; le rembourrage, lui, n'entre pas dans L.
_LONGUEUR_CLAIR_MAX = 0xFFFFFFFF

# Planchers de rembourrage (§2.5). 1 024 o : une conversation d'une ligne ne
# se distingue pas d'une conversation de dix. 4 096 o : une vignette ne se
# distingue pas d'une icône. Les deux sont des valeurs de Padmé (2^10, 2^12),
# si bien que le VPS peut vérifier « taille − 66 ∈ Padmé » sans exception.
# Les types 03 et 05 n'ont pas de plancher : leur clair a une taille connue
# de tous (une AMK, un trousseau), le cacher n'apprendrait rien à personne.
# Le type 04 n'en a pas non plus, et ce n'est PAS le même argument : la
# longueur d'un nom d'appareil n'est pas connue, et Padmé seul en laisse
# deviner l'ordre de grandeur au VPS. Le §2.5 ne donne de plancher qu'aux
# types 01 et 02 ; en donner un au 04 (64 o, valeur de Padmé) est une
# décision de format qui revient à Carlito (24/09/2026).
PLANCHER_OBJET = 1024
PLANCHER_PIECE = 4096
_TYPES_SANS_EPOQUE = frozenset(
    {TYPE_AMK_MOT_DE_PASSE, TYPE_TROUSSEAU, TYPE_AMK_RECUPERATION}
)

SUITE_HPKE = hpke.Suite(hpke.KEM.X25519, hpke.KDF.HKDF_SHA256, hpke.AEAD.AES_256_GCM)

VERSION_CLAIR = 1
SCHEMA_CONVERSATIONS = 1


# ----------------------------------------------------------------------
# Rembourrage (§2.5)
# ----------------------------------------------------------------------


def padme(longueur: int) -> int:
    """Padmé (Nikitin et al., PURBs 2019) : surcoût ≤ 12 %, fuite en O(log log L)."""
    longueur = entier(longueur, "longueur", minimum=1)
    e = longueur.bit_length() - 1
    s = e.bit_length()
    masque = (1 << (e - s)) - 1
    return (longueur + masque) & ~masque


def taille_cadre(longueur_clair: int, plancher: int) -> int:
    """``max(plancher, padme(4 + L))`` — la taille du cadre chiffré."""
    return max(plancher, padme(4 + entier(longueur_clair, "longueur du clair")))


def encadrer(clair: bytes, plancher: int) -> bytes:
    """``uint32 BE(L) ‖ clair ‖ zéros`` jusqu'à :func:`taille_cadre`."""
    clair = en_octets(clair, "clair")
    if len(clair) > _LONGUEUR_CLAIR_MAX:
        raise ValueError("clair trop long pour un cadre DPE1")
    cadre = struct.pack(">I", len(clair)) + clair
    return cadre + bytes(taille_cadre(len(clair), plancher) - len(cadre))


def desencadrer(cadre: bytes, plancher: int) -> bytes:
    """L'inverse d':func:`encadrer`, zéros de rembourrage VÉRIFIÉS.

    Jamais ``rstrip(b"\\x00")`` (``scellement.py:444-456``) : une image PNG
    finit souvent par des zéros, et un ``rstrip`` les mangerait sans erreur
    (relevé par la revue du 24/09/2026).
    La longueur écrite en tête dit où finit le clair ; le reste doit être
    nul, et le cadre doit avoir exactement la taille que Padmé impose.
    """
    if len(cadre) < 4:
        raise EnveloppeIllisible("cadre tronqué")
    (longueur,) = struct.unpack(">I", cadre[:4])
    if 4 + longueur > len(cadre) or len(cadre) != taille_cadre(longueur, plancher):
        raise EnveloppeIllisible("taille du cadre incohérente")
    reste = cadre[4 + longueur :]
    if reste.count(0) != len(reste):
        raise EnveloppeIllisible("rembourrage non nul")
    return cadre[4 : 4 + longueur]


# ----------------------------------------------------------------------
# AAD (§2.5)
# ----------------------------------------------------------------------


def aad_canonique(champs: dict[str, Any]) -> bytes:
    """JSON trié, compact, UTF-8 ; seulement des chaînes et des entiers.

    On n'emprunte pas ``identity.canonical_bytes`` : son ``default=str``
    (``identity.py:344``) écrirait ``"b'…'"`` pour des octets, en silence, et
    l'AAD scellée ne serait plus celle que l'appareil suivant recalcule
    (revue du 24/09/2026).
    ``bool`` est refusé aussi : ``json`` l'écrit ``true``, pas ``1``.
    """
    if not isinstance(champs, dict):
        raise TypeError("l'AAD doit être un dictionnaire")
    for cle, valeur in champs.items():
        if not isinstance(cle, str):
            raise TypeError(f"clé d'AAD non textuelle : {cle!r}")
        if isinstance(valeur, bool) or not isinstance(valeur, (str, int)):
            raise TypeError(
                f"valeur d'AAD refusée pour {cle!r} : {type(valeur).__name__}"
            )
    return json.dumps(
        champs, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def aad(en_tete: bytes, champs: dict[str, Any]) -> bytes:
    """``en-tête ‖ b"|" ‖ aad_canonique(champs)``."""
    return en_tete + b"|" + aad_canonique(champs)


# ----------------------------------------------------------------------
# En-tête et sous-clé
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class EnTete:
    format: int
    type: int
    key_epoch: int


def lire_en_tete(blob: bytes) -> EnTete:
    """Les six premiers octets — pour choisir la DEK avant d'ouvrir."""
    blob = en_octets(blob, "blob")
    if len(blob) < LONGUEUR_EN_TETE_COURT:
        raise EnveloppeIllisible("en-tête tronqué")
    format_, type_, epoque = struct.unpack(">BBI", blob[:LONGUEUR_EN_TETE_COURT])
    if format_ != FORMAT_DPE1:
        raise EnveloppeIllisible(f"format inconnu : {format_}")
    return EnTete(format=format_, type=type_, key_epoch=epoque)


def _en_tete_court(type_: int, key_epoch: int) -> bytes:
    key_epoch = entier(key_epoch, "keyEpoch")
    if key_epoch > EPOQUE_MAX:
        raise ValueError("keyEpoch dépasse uint32")
    if type_ in _TYPES_SANS_EPOQUE and key_epoch != 0:
        raise ValueError(f"le type {type_:02x} porte keyEpoch = 0")
    return struct.pack(">BBI", FORMAT_DPE1, type_, key_epoch)


def sous_cle(cle_base: bytes, type_: int, sel: bytes) -> bytes:
    """``HKDF(SHA256, 32, salt=sel, info=b"…/enveloppe|" + type)`` — usage unique."""
    return hkdf(
        en_octets(cle_base, "clé de base", LONGUEUR_CLE),
        PREFIXE_INFO + b"enveloppe|" + bytes([type_]),
        sel=en_octets(sel, "sel", LONGUEUR_SEL),
    )


def _chiffrer(
    type_: int,
    cle_base: bytes,
    cadre: bytes,
    champs: dict[str, Any],
    key_epoch: int,
    sel: bytes | None,
    nonce: bytes | None,
) -> bytes:
    """Scelle un cadre DÉJÀ rembourré. Les tests l'appellent pour forger un
    cadre invalide ; tout autre appelant passe par les fonctions publiques."""
    sel = (
        os.urandom(LONGUEUR_SEL) if sel is None else en_octets(sel, "sel", LONGUEUR_SEL)
    )
    nonce = (
        os.urandom(LONGUEUR_NONCE)
        if nonce is None
        else en_octets(nonce, "nonce", LONGUEUR_NONCE)
    )
    en_tete = _en_tete_court(type_, key_epoch) + sel + nonce
    chiffre = AESGCM(sous_cle(cle_base, type_, sel)).encrypt(
        nonce, cadre, aad(en_tete, champs)
    )
    return en_tete + chiffre


def _dechiffrer(
    type_: int, cle_base: bytes, blob: bytes, champs_sans_epoque: dict[str, Any]
) -> tuple[int, bytes]:
    """Rend ``(keyEpoch, cadre)``. ``champs_sans_epoque`` reçoit ``e`` de
    l'en-tête quand le type en porte une dans son AAD (objet, pièce)."""
    en_tete = lire_en_tete(blob)
    if en_tete.type != type_:
        raise EnveloppeIllisible(f"type {en_tete.type:02x} au lieu de {type_:02x}")
    if type_ in _TYPES_SANS_EPOQUE and en_tete.key_epoch != 0:
        raise EnveloppeIllisible("keyEpoch non nul sur un type qui n'en porte pas")
    if len(blob) < SURCOUT + 4:
        raise EnveloppeIllisible("blob tronqué")
    champs = dict(champs_sans_epoque)
    if "e" in champs:
        champs["e"] = en_tete.key_epoch
    sel = blob[LONGUEUR_EN_TETE_COURT : LONGUEUR_EN_TETE_COURT + LONGUEUR_SEL]
    nonce = blob[LONGUEUR_EN_TETE_COURT + LONGUEUR_SEL : LONGUEUR_EN_TETE]
    try:
        cadre = AESGCM(sous_cle(cle_base, type_, sel)).decrypt(
            nonce, blob[LONGUEUR_EN_TETE:], aad(blob[:LONGUEUR_EN_TETE], champs)
        )
    except InvalidTag as exc:
        raise EnveloppeIllisible("tag refusé") from exc
    return en_tete.key_epoch, cadre


def _texte(valeur: object, nom: str) -> str:
    """Les champs ``a``, ``o`` et ``s`` sont des chaînes : un ``accountId``
    passé en entier donnerait une AAD valide mais différente de celle que
    l'appareil suivant recalcule — un blob illisible, sans erreur à l'écriture."""
    if not isinstance(valeur, str) or not valeur:
        raise TypeError(f"{nom} doit être une chaîne non vide")
    return valeur


def _plancher_de_version(nom: str, version: int, plancher: int) -> None:
    if entier(version, nom) < entier(plancher, f"plancher de {nom}"):
        raise CleServeurPerimee(f"{nom} {version} sous le plancher {plancher}")


# ----------------------------------------------------------------------
# Type 01 — objet
# ----------------------------------------------------------------------


def _champs_objet(
    account_id: str, incarnation: int, object_id: str, rev: int, e: int
) -> dict:
    return {
        "a": _texte(account_id, "accountId"),
        "e": entier(e, "keyEpoch"),
        "i": entier(incarnation, "incarnation"),
        "o": _texte(object_id, "objectId"),
        "r": entier(rev, "rev"),
        "t": "object",
        "v": 1,
    }


def sceller_objet(
    dek: bytes,
    clair: bytes,
    *,
    account_id: str,
    incarnation: int,
    object_id: str,
    rev: int,
    key_epoch: int,
    sel: bytes | None = None,
    nonce: bytes | None = None,
) -> bytes:
    champs = _champs_objet(account_id, incarnation, object_id, rev, key_epoch)
    return _chiffrer(
        TYPE_OBJET, dek, encadrer(clair, PLANCHER_OBJET), champs, key_epoch, sel, nonce
    )


def ouvrir_objet(
    dek: bytes,
    blob: bytes,
    *,
    account_id: str,
    incarnation: int,
    object_id: str,
    rev: int,
) -> bytes:
    """La DEK se choisit d'après :func:`lire_en_tete` ; ``e`` en vient aussi."""
    champs = _champs_objet(account_id, incarnation, object_id, rev, 0)
    _, cadre = _dechiffrer(TYPE_OBJET, dek, blob, champs)
    return desencadrer(cadre, PLANCHER_OBJET)


# ----------------------------------------------------------------------
# Type 02 — pièce
# ----------------------------------------------------------------------


def _champs_piece(account_id: str, incarnation: int, piece_id: str, e: int) -> dict:
    return {
        "a": _texte(account_id, "accountId"),
        "e": entier(e, "keyEpoch"),
        "i": entier(incarnation, "incarnation"),
        "o": _texte(piece_id, "pieceId"),
        "t": "attachment",
        "v": 1,
    }


def sceller_piece(
    dek: bytes,
    octets: bytes,
    *,
    account_id: str,
    incarnation: int,
    piece_id: str,
    key_epoch: int,
    sel: bytes | None = None,
    nonce: bytes | None = None,
) -> bytes:
    champs = _champs_piece(account_id, incarnation, piece_id, key_epoch)
    return _chiffrer(
        TYPE_PIECE, dek, encadrer(octets, PLANCHER_PIECE), champs, key_epoch, sel, nonce
    )


def ouvrir_piece(
    dek: bytes, blob: bytes, *, account_id: str, incarnation: int, piece_id: str
) -> bytes:
    champs = _champs_piece(account_id, incarnation, piece_id, 0)
    _, cadre = _dechiffrer(TYPE_PIECE, dek, blob, champs)
    return desencadrer(cadre, PLANCHER_PIECE)


# ----------------------------------------------------------------------
# Type 03 — AMK sous KEK_mdp
# ----------------------------------------------------------------------


def _champs_amk_mdp(account_id: str, kdf_version: int, vault_version: int) -> dict:
    return {
        "a": _texte(account_id, "accountId"),
        "k": entier(kdf_version, "kdfVersion"),
        "t": "amk",
        "u": "password",
        "w": entier(vault_version, "vaultVersion"),
    }


def envelopper_amk(
    kek: bytes,
    amk: bytes,
    *,
    account_id: str,
    kdf_version: int,
    vault_version: int,
    sel: bytes | None = None,
    nonce: bytes | None = None,
) -> bytes:
    parametres_kdf(kdf_version)
    amk = en_octets(amk, "AMK", LONGUEUR_CLE)
    champs = _champs_amk_mdp(account_id, kdf_version, vault_version)
    return _chiffrer(
        TYPE_AMK_MOT_DE_PASSE, kek, encadrer(amk, 0), champs, 0, sel, nonce
    )


def ouvrir_amk(
    kek: bytes,
    blob: bytes,
    *,
    account_id: str,
    kdf_version: int,
    vault_version: int,
    plancher_vault_version: int,
) -> bytes:
    """Sous le plancher : ``serverKeyStale`` AVANT d'essayer la clé.

    Une restauration du VPS ramène l'enveloppe d'hier avec sa vraie
    ``vaultVersion`` : elle s'ouvrirait avec l'ancien mot de passe et
    redonnerait l'AMK d'avant la rotation. Le plancher la refuse ; et ``w``
    dans l'AAD empêche de la ré-étiqueter à une version supérieure.
    """
    parametres_kdf(kdf_version)
    _plancher_de_version("vaultVersion", vault_version, plancher_vault_version)
    champs = _champs_amk_mdp(account_id, kdf_version, vault_version)
    _, cadre = _dechiffrer(TYPE_AMK_MOT_DE_PASSE, kek, blob, champs)
    amk = desencadrer(cadre, 0)
    if len(amk) != LONGUEUR_CLE:
        raise EnveloppeIllisible("AMK de longueur inattendue")
    return amk


# ----------------------------------------------------------------------
# Type 04 — nom d'appareil
# ----------------------------------------------------------------------


def _champs_nom(account_id: str, session_id: str) -> dict:
    return {
        "a": _texte(account_id, "accountId"),
        "s": _texte(session_id, "sessionId"),
        "t": "deviceName",
        "v": 1,
    }


def sceller_nom_appareil(
    k_noms: bytes,
    nom: str,
    *,
    account_id: str,
    session_id: str,
    key_epoch: int,
    sel: bytes | None = None,
    nonce: bytes | None = None,
) -> bytes:
    if not isinstance(nom, str):
        raise TypeError("le nom d'appareil doit être une chaîne")
    champs = _champs_nom(account_id, session_id)
    return _chiffrer(
        TYPE_NOM_APPAREIL,
        k_noms,
        encadrer(nom.encode("utf-8"), 0),
        champs,
        key_epoch,
        sel,
        nonce,
    )


def ouvrir_nom_appareil(
    k_noms: bytes, blob: bytes, *, account_id: str, session_id: str
) -> str:
    _, cadre = _dechiffrer(
        TYPE_NOM_APPAREIL, k_noms, blob, _champs_nom(account_id, session_id)
    )
    try:
        return desencadrer(cadre, 0).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EnveloppeIllisible("nom d'appareil non UTF-8") from exc


# ----------------------------------------------------------------------
# Type 05 — trousseau
# ----------------------------------------------------------------------


def _champs_trousseau(
    account_id: str, keyring_version: int, vault_version: int
) -> dict:
    return {
        "a": _texte(account_id, "accountId"),
        "r": entier(keyring_version, "keyringVersion"),
        "t": "keyring",
        "v": 1,
        "w": entier(vault_version, "vaultVersion"),
    }


def sceller_trousseau_brut(
    k_trousseau: bytes,
    clair: bytes,
    *,
    account_id: str,
    keyring_version: int,
    vault_version: int,
    sel: bytes | None = None,
    nonce: bytes | None = None,
) -> bytes:
    """Le trousseau déjà sérialisé (``trousseau.serialiser``)."""
    champs = _champs_trousseau(account_id, keyring_version, vault_version)
    return _chiffrer(
        TYPE_TROUSSEAU, k_trousseau, encadrer(clair, 0), champs, 0, sel, nonce
    )


def ouvrir_trousseau_brut(
    k_trousseau: bytes,
    blob: bytes,
    *,
    account_id: str,
    keyring_version: int,
    vault_version: int,
    plancher_keyring_version: int,
    plancher_vault_version: int,
) -> bytes:
    _plancher_de_version("keyringVersion", keyring_version, plancher_keyring_version)
    _plancher_de_version("vaultVersion", vault_version, plancher_vault_version)
    champs = _champs_trousseau(account_id, keyring_version, vault_version)
    _, cadre = _dechiffrer(TYPE_TROUSSEAU, k_trousseau, blob, champs)
    return desencadrer(cadre, 0)


# ----------------------------------------------------------------------
# Type 06 — AMK scellée vers la clé de récupération (HPKE)
# ----------------------------------------------------------------------


def info_recuperation(account_id: str, vault_version: int) -> bytes:
    """L'API HPKE n'a pas de paramètre ``aad`` : tout le contexte passe par ``info``.

    Publique pour que le générateur de vecteurs écrive CETTE valeur : il la
    recalculait à part, et un ``info`` changé ici laissait dans le vecteur
    un ``info`` périmé, avec une suite verte (24/09/2026).
    """
    champs = {
        "a": _texte(account_id, "accountId"),
        "t": "amk",
        "u": "recovery",
        "w": entier(vault_version, "vaultVersion"),
    }
    return aad(_en_tete_court(TYPE_AMK_RECUPERATION, 0), champs)


def sceller_amk_recuperation(
    cle_publique: bytes, amk: bytes, *, account_id: str, vault_version: int
) -> bytes:
    """Scelle vers ``pk_rec`` SANS connaître ``R`` — c'est ce qui permet de
    faire tourner l'AMK alors que ``R`` n'est jamais stockée (§2.2).

    ``cle_publique`` doit venir du trousseau DÉCHIFFRÉ, jamais d'une réponse
    du serveur : un VPS hostile y substituerait la sienne.
    """
    pk = X25519PublicKey.from_public_bytes(
        en_octets(cle_publique, "pk_rec", LONGUEUR_CLE)
    )
    info = info_recuperation(account_id, vault_version)
    amk = en_octets(amk, "AMK", LONGUEUR_CLE)
    return info[:LONGUEUR_EN_TETE_COURT] + SUITE_HPKE.encrypt(amk, pk, info)


def ouvrir_amk_recuperation(
    cle_privee: X25519PrivateKey,
    blob: bytes,
    *,
    account_id: str,
    vault_version: int,
    plancher_vault_version: int,
) -> bytes:
    _plancher_de_version("vaultVersion", vault_version, plancher_vault_version)
    en_tete = lire_en_tete(blob)
    if en_tete.type != TYPE_AMK_RECUPERATION or en_tete.key_epoch != 0:
        raise EnveloppeIllisible("en-tête de type 06 attendu")
    if len(blob) != LONGUEUR_AMK_SCELLEE:
        raise EnveloppeIllisible("AMK scellée de longueur inattendue")
    info = info_recuperation(account_id, vault_version)
    if blob[:LONGUEUR_EN_TETE_COURT] != info[:LONGUEUR_EN_TETE_COURT]:
        raise EnveloppeIllisible("en-tête modifié")
    try:
        return SUITE_HPKE.decrypt(blob[LONGUEUR_EN_TETE_COURT:], cle_privee, info)
    except InvalidTag as exc:
        raise EnveloppeIllisible("tag refusé") from exc


# ----------------------------------------------------------------------
# Clair d'un objet (§2.5)
# ----------------------------------------------------------------------


def clair_objet(
    collection: str, id_local: str, data: dict[str, Any], *, schema: int = 1
) -> dict[str, Any]:
    """``{"v":1,"collection":…,"id":…,"schema":…,"data":{…}}`` — clés en anglais.

    La collection est À L'INTÉRIEUR du chiffré : le VPS ignore quelle
    application produit quoi.
    """
    return {
        "v": VERSION_CLAIR,
        "collection": collection,
        "id": id_local,
        "schema": schema,
        "data": data,
    }


def clair_tombale(
    collection: str, id_local: str, deleted_at: int, *, schema: int = 1
) -> dict[str, Any]:
    return {
        "v": VERSION_CLAIR,
        "collection": collection,
        "id": id_local,
        "schema": schema,
        "deleted": {"deletedAt": entier(deleted_at, "deletedAt")},
    }


def encoder_clair(clair: dict[str, Any]) -> bytes:
    """JSON trié et compact : l'empreinte locale ``SHA-256(clair canonique)``
    doit être la même d'un cycle à l'autre, sinon chaque tirage repousse tout.

    Un substitut UTF-16 isolé lève ``UnicodeEncodeError`` : le projeteur
    (étape 10) applique ``sans_substituts`` AVANT, comme le magasin.
    """
    return json.dumps(
        clair,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def lire_clair(octets: bytes) -> dict[str, Any]:
    """Décode un clair et en vérifie la forme, pas le contenu de ``data``.

    Clé en double, ``v`` ou ``schema`` qui ne sont pas des entiers
    véritables : refusés, comme dans le trousseau (``cles.version_exacte``).
    """
    try:
        clair = json.loads(
            en_octets(octets, "clair").decode("utf-8"), object_pairs_hook=sans_doublons
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ClairInvalide("clair non JSON ou clé en double") from exc
    if not isinstance(clair, dict):
        raise ClairInvalide("clair non objet")
    if not version_exacte(clair.get("v"), VERSION_CLAIR):
        raise ClairInvalide(
            f"version de clair inconnue : {clair.get('v')!r}", code="unknownVersion"
        )
    schema = clair.get("schema")
    if isinstance(schema, bool) or not isinstance(schema, int) or schema < 1:
        raise ClairInvalide(f"schema invalide : {schema!r}")
    if not isinstance(clair.get("collection"), str) or not isinstance(
        clair.get("id"), str
    ):
        raise ClairInvalide("collection ou id manquant")
    if ("data" in clair) == ("deleted" in clair):
        raise ClairInvalide("un clair porte data OU deleted")
    return clair
