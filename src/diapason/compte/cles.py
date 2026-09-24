"""Clés du compte : normalisations, étirement du mot de passe, rôles, identifiants.

Conception : ``docs/development/compte-chiffre.md`` §2.2 (hiérarchie), §2.3
(primitives), §2.4 (normalisations) et §2.6 (identifiants opaques). Tout
``info`` HKDF commence par ``diapason/compte/v1/`` : il ne recoupe ni
``diapason-mesh-transfer-v1`` ni ``diapason-mesh-command-v1``, si bien
qu'aucune clé du maillage ne peut servir ici par accident, ni l'inverse.

Rien ici ne touche au disque ni au réseau. Les erreurs portent un ``code``
en anglais camelCase : c'est lui qui voyagera vers le bundle.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import threading
import unicodedata
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# ----------------------------------------------------------------------
# Erreurs
# ----------------------------------------------------------------------


class ErreurCompte(Exception):
    """Toute erreur du compte chiffré, avec un code stable pour le bundle."""

    code = "accountError"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class DeclassementKdf(ErreurCompte):
    """Version de KDF inconnue ou inférieure au plancher (§2.3)."""

    code = "kdfDowngrade"


class CourrielInvalide(ErreurCompte):
    code = "emailInvalid"


class MotDePasseRefuse(ErreurCompte):
    """Mot de passe hors des règles D5 ; le ``code`` dit laquelle."""

    code = "passwordRejected"


# ----------------------------------------------------------------------
# Constantes figées par les vecteurs (tests/contract/vecteurs_compte.json)
# ----------------------------------------------------------------------

PREFIXE_INFO = b"diapason/compte/v1/"
INFO_AUTH = PREFIXE_INFO + b"auth"
INFO_KEK = PREFIXE_INFO + b"kek"
INFO_RECUPERATION_AUTH = PREFIXE_INFO + b"recuperation-auth"
INFO_RECUPERATION_X25519 = PREFIXE_INFO + b"recuperation-x25519"
INFO_TROUSSEAU = PREFIXE_INFO + b"trousseau"
INFO_NOMS_APPAREILS = PREFIXE_INFO + b"noms-appareils"
INFO_PIECE_ID = PREFIXE_INFO + b"piece-id"
PREFIXE_SEL_ARGON2 = PREFIXE_INFO + b"sel-argon2\0"

LONGUEUR_CLE = 32

# D2, décision par défaut du 24/09/2026 : 256 Mio, t=3, p=4 prennent 0,48 à
# 0,50 s sur ce Mac. On ne descend à 131 072 (0,25 s) que si pc-bureau
# dépasse 2,5 s. La table est EN DUR et en lecture seule : un VPS hostile
# qui servirait « kdfVersion 0, 8 Kio » obtiendrait sinon une empreinte
# devinable en une fraction de seconde par essai — c'est le déclassement que
# §4.12 range sous « impose un Argon2 faible ».
VERSIONS_KDF: MappingProxyType[int, tuple[int, int, int]] = MappingProxyType(
    {1: (262144, 3, 4)}
)
KDF_VERSION_MIN = 1

# D5, décision par défaut du 24/09/2026. 12 caractères : un mot de passe
# d'environ 30 bits tombe en quelques semaines sur GPU même à 256 Mio par
# essai (A5). 1 024 : borne l'entrée d'Argon2id sans gêner une phrase de
# passe, même longue.
#
# La règle « ne pas contenir la partie locale » s'applique À LA LETTRE, quelle
# que soit sa longueur : la première passe (24/09/2026) l'écartait sous 4
# caractères, un seuil que ni D5 ni le §2.4 ne portent. Il refuse désormais
# « enjoy the rain » pour jo@… ; l'assouplir est une décision de Carlito, à
# inscrire d'abord dans la conception.
MOT_DE_PASSE_MIN = 12
MOT_DE_PASSE_MAX = 1024

COURRIEL_MIN = 3
COURRIEL_MAX = 254

# Une seule dérivation Argon2id à la fois (§2.3) : deux dérivations de
# 256 Mio en parallèle — un déverrouillage et un changement de mot de passe
# lancés depuis deux vues — doubleraient l'empreinte mémoire du serveur local
# pendant une demi-seconde, sur une machine qui fait aussi tourner le modèle.
_UNE_DERIVATION_A_LA_FOIS = threading.Semaphore(1)


# ----------------------------------------------------------------------
# Outils
# ----------------------------------------------------------------------


def en_octets(valeur: object, nom: str, longueur: int | None = None) -> bytes:
    """Des octets, de la longueur dite : l'API commune du paquet ``compte``.

    ``bytearray`` est accepté et copié : P, K_mdp et R y vivent pour être
    écrasés après usage (§2.10).
    """
    if not isinstance(valeur, (bytes, bytearray)):
        raise TypeError(f"{nom} doit être des octets, pas {type(valeur).__name__}")
    if longueur is not None and len(valeur) != longueur:
        raise ValueError(f"{nom} doit faire {longueur} o, pas {len(valeur)}")
    return bytes(valeur)


def entier(valeur: object, nom: str, *, minimum: int = 0) -> int:
    """Un entier véritable : ``True`` n'est pas 1, ``1.0`` non plus.

    ``True in {1: …}`` vaut vrai en Python : sans ce contrôle, un
    ``kdfVersion: true`` servi en JSON passerait pour la version 1.
    """
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise TypeError(f"{nom} doit être un entier, pas {type(valeur).__name__}")
    if valeur < minimum:
        raise ValueError(f"{nom} doit être ≥ {minimum}, pas {valeur}")
    return valeur


def version_exacte(valeur: object, attendue: int) -> bool:
    """``valeur`` est l'entier ``attendue``, ni ``true`` ni ``1.0``.

    ``True == 1`` et ``1.0 == 1`` valent vrai en Python : la première passe
    (24/09/2026) acceptait ``"v": true`` et ``"v": 1.0`` dans un clair ou un
    trousseau, qu'un client TypeScript ou Dart aurait lus autrement.
    """
    return type(valeur) is int and valeur == attendue


def sans_doublons(paires: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` de ``json.loads`` : une clé en double est refusée.

    ``json.loads`` garde la DERNIÈRE occurrence ; JavaScript aussi, mais
    d'autres analyseurs gardent la première. Un clair ``{"v":1,…,"v":2}``
    serait alors lu deux fois différemment selon l'appareil (24/09/2026).
    """
    resultat: dict[str, Any] = {}
    for cle, valeur in paires:
        if cle in resultat:
            raise ValueError(f"clé JSON en double : {cle!r}")
        resultat[cle] = valeur
    return resultat


def hkdf(cle: bytes, info: bytes, *, sel: bytes | None = None) -> bytes:
    """``HKDF(SHA256, 32)`` — ``sel=None`` pour les clés de rôle (§2.3)."""
    return HKDF(
        algorithm=hashes.SHA256(), length=LONGUEUR_CLE, salt=sel, info=info
    ).derive(en_octets(cle, "cle"))


def b64url(octets: bytes) -> str:
    """base64url sans remplissage, comme les identifiants du §2.6."""
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


# ----------------------------------------------------------------------
# Normalisations (§2.4)
# ----------------------------------------------------------------------


def normaliser_courriel(courriel: str) -> str:
    """``NFKC``, ``strip``, ``lower``.

    Puis : 3 à 254 caractères, un seul ``@``, aucun espace (§2.4).
    """
    if not isinstance(courriel, str):
        raise TypeError("le courriel doit être une chaîne")
    e = unicodedata.normalize("NFKC", courriel).strip().lower()
    if not COURRIEL_MIN <= len(e) <= COURRIEL_MAX:
        raise CourrielInvalide(
            f"le courriel doit faire {COURRIEL_MIN} à {COURRIEL_MAX} caractères"
        )
    if e.count("@") != 1:
        raise CourrielInvalide("le courriel doit contenir un seul @")
    if any(c.isspace() for c in e):
        raise CourrielInvalide("le courriel ne doit contenir aucun espace")
    return e


def normaliser_mot_de_passe(mot_de_passe: str) -> bytes:
    """``NFKC`` SANS ``strip``, puis UTF-8.

    Un « é » saisi en NFD sous macOS et en NFC sous Windows donnait deux clés
    différentes : le même mot de passe, tapé sur deux appareils, n'ouvrait
    pas le même compte (revue de la conception, 24/09/2026). Pas de
    ``strip`` : une espace finale fait partie du secret que la personne a
    choisi.
    """
    if not isinstance(mot_de_passe, str):
        raise TypeError("le mot de passe doit être une chaîne")
    p = unicodedata.normalize("NFKC", mot_de_passe)
    if len(p) > MOT_DE_PASSE_MAX:
        raise MotDePasseRefuse(
            f"le mot de passe dépasse {MOT_DE_PASSE_MAX} caractères",
            code="passwordTooLong",
        )
    return p.encode("utf-8")


def verifier_mot_de_passe(mot_de_passe: str, courriel: str) -> None:
    """Règles D5, à l'inscription et au changement — PAS au déverrouillage.

    Le déverrouillage ne les applique pas : si D5 se durcit un jour, un
    mot de passe choisi sous l'ancienne règle doit encore ouvrir le compte
    le temps d'en changer.
    """
    p = normaliser_mot_de_passe(mot_de_passe).decode("utf-8")
    if len(p) < MOT_DE_PASSE_MIN:
        raise MotDePasseRefuse(
            f"le mot de passe doit faire au moins {MOT_DE_PASSE_MIN} caractères",
            code="passwordTooShort",
        )
    partie_locale = normaliser_courriel(courriel).split("@", 1)[0]
    # Une partie locale vide (« @ab » passe le §2.4) est « contenue » dans
    # toute chaîne : sans ce test, tout mot de passe serait refusé.
    if partie_locale and partie_locale in p.lower():
        raise MotDePasseRefuse(
            "le mot de passe ne doit pas contenir le début de l'adresse",
            code="passwordContainsEmail",
        )


# ----------------------------------------------------------------------
# Étirement (§2.2, §2.3)
# ----------------------------------------------------------------------


def parametres_kdf(kdf_version: int) -> tuple[int, int, int]:
    """``(memory_cost, iterations, lanes)`` de la version, ou ``kdfDowngrade``."""
    if isinstance(kdf_version, bool) or not isinstance(kdf_version, int):
        raise DeclassementKdf(f"kdfVersion invalide : {kdf_version!r}")
    if kdf_version < KDF_VERSION_MIN or kdf_version not in VERSIONS_KDF:
        raise DeclassementKdf(f"kdfVersion {kdf_version} refusée")
    return VERSIONS_KDF[kdf_version]


def sel_argon2(courriel: str, kdf_salt: bytes) -> bytes:
    """``SHA-256("…/sel-argon2\\0" ‖ E ‖ "\\0" ‖ kdfSalt)``.

    ``E`` est dans le sel : un serveur qui servirait le même ``kdfSalt`` à
    tout le monde n'obtiendrait pas pour autant un dictionnaire commun.
    """
    e = normaliser_courriel(courriel).encode("utf-8")
    kdf_salt = en_octets(kdf_salt, "kdfSalt", LONGUEUR_CLE)
    return hashlib.sha256(PREFIXE_SEL_ARGON2 + e + b"\0" + kdf_salt).digest()


def _etirer_avec_parametres(
    mot_de_passe_utf8: bytes,
    sel: bytes,
    *,
    memory_cost: int,
    iterations: int,
    lanes: int,
) -> bytes:
    """Argon2id aux paramètres EXPLICITES — pour les tests et le banc seulement.

    Privée depuis le 24/09/2026 : publique, elle offrait à l'étape 8 un
    chemin qui étire avec des paramètres venus d'ailleurs que
    :data:`VERSIONS_KDF`, c'est-à-dire le déclassement du §4.12. Tout le
    reste passe par :func:`etirer_mot_de_passe`.
    """
    with _UNE_DERIVATION_A_LA_FOIS:
        return Argon2id(
            salt=en_octets(sel, "sel"),
            length=LONGUEUR_CLE,
            iterations=iterations,
            lanes=lanes,
            memory_cost=memory_cost,
        ).derive(en_octets(mot_de_passe_utf8, "mot de passe"))


def etirer_mot_de_passe(
    mot_de_passe: str, courriel: str, kdf_salt: bytes, kdf_version: int
) -> bytes:
    """``K_mdp = Argon2id(P, sel, paramètres de kdfVersion)``.

    La version vient du serveur ; ses paramètres, jamais.
    """
    memory_cost, iterations, lanes = parametres_kdf(kdf_version)
    return _etirer_avec_parametres(
        normaliser_mot_de_passe(mot_de_passe),
        sel_argon2(courriel, kdf_salt),
        memory_cost=memory_cost,
        iterations=iterations,
        lanes=lanes,
    )


@dataclass(frozen=True)
class ClesMotDePasse:
    """``authKey`` part au VPS ; ``KEK`` ne quitte jamais l'appareil.

    ``repr=False`` : une trace d'exception ou un ``logger.debug(cles)`` ne
    doit pas écrire une clé dans un journal (§2.10).
    """

    auth_key: bytes = field(repr=False)
    kek: bytes = field(repr=False)


def cles_de_role(k_mdp: bytes) -> ClesMotDePasse:
    """Sépare ``K_mdp`` en ``authKey`` et ``KEK`` (HKDF, ``salt=None``)."""
    k_mdp = en_octets(k_mdp, "K_mdp", LONGUEUR_CLE)
    return ClesMotDePasse(auth_key=hkdf(k_mdp, INFO_AUTH), kek=hkdf(k_mdp, INFO_KEK))


def deriver_cles_mot_de_passe(
    mot_de_passe: str, courriel: str, kdf_salt: bytes, kdf_version: int
) -> ClesMotDePasse:
    """Le chemin public complet : mot de passe → ``authKey`` et ``KEK``."""
    return cles_de_role(
        etirer_mot_de_passe(mot_de_passe, courriel, kdf_salt, kdf_version)
    )


# ----------------------------------------------------------------------
# Clés tirées de l'AMK et des DEK (§2.2)
# ----------------------------------------------------------------------


def cle_trousseau(amk: bytes) -> bytes:
    return hkdf(en_octets(amk, "AMK", LONGUEUR_CLE), INFO_TROUSSEAU)


def cle_noms_appareils(amk: bytes) -> bytes:
    return hkdf(en_octets(amk, "AMK", LONGUEUR_CLE), INFO_NOMS_APPAREILS)


def cle_piece(dek: bytes) -> bytes:
    """``K_piece_e`` — PAR ÉPOQUE.

    Tirée de la clé maîtresse, elle survivrait aux rotations :
    ``/pieces/missing`` répondrait « présente » et l'image resterait sous la
    DEK compromise (§2.2, revue cryptographie du 24/09/2026).
    """
    return hkdf(en_octets(dek, "DEK", LONGUEUR_CLE), INFO_PIECE_ID)


# ----------------------------------------------------------------------
# Identifiants opaques (§2.6)
# ----------------------------------------------------------------------


def identifiant_objet(id_key: bytes, collection: str, id_local: str) -> str:
    """``objectId``, stable pendant toute l'incarnation du compte.

    ``b64url(HMAC(K_id, "object\\0" ‖ collection ‖ "\\0" ‖ idLocal)[:16])``

    Un ``\\0`` dans l'un ou l'autre est refusé : (« a\\0b », « c ») et
    (« a », « b\\0c ») donnaient le même message, donc le même ``objectId``,
    et deux objets distincts se seraient écrasés sur le VPS (24/09/2026).
    """
    if not isinstance(collection, str) or not isinstance(id_local, str):
        raise TypeError("collection et id local doivent être des chaînes")
    if "\0" in collection or "\0" in id_local:
        raise ValueError("collection et id local ne doivent pas contenir \\0")
    message = (
        b"object\0" + collection.encode("utf-8") + b"\0" + id_local.encode("utf-8")
    )
    mac = hmac.new(en_octets(id_key, "K_id", LONGUEUR_CLE), message, hashlib.sha256)
    return b64url(mac.digest()[:16])


def identifiant_piece(k_piece: bytes, octets: bytes) -> str:
    """``pieceId = b64url(HMAC(K_piece_e, "attachment\\0" ‖ SHA-256(octets))[:16])``."""
    empreinte = hashlib.sha256(en_octets(octets, "pièce")).digest()
    mac = hmac.new(
        en_octets(k_piece, "K_piece", LONGUEUR_CLE),
        b"attachment\0" + empreinte,
        hashlib.sha256,
    )
    return b64url(mac.digest()[:16])
