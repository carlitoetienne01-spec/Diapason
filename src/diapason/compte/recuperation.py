"""La clé de récupération : format, saisie tolérante, clés qui en dérivent.

Conception : ``docs/development/compte-chiffre.md`` §2.2 et §2.7.

``R`` fait 16 o aléatoires, suivis de 4 o de contrôle, le tout écrit en
base32 Crockford : 32 caractères en 8 groupes de 4. Pas d'Argon2id : 128
bits ne se devinent pas. ``R`` n'est jamais stockée ; il en dérive
``recoveryAuthKey`` (vérifiée par le VPS) et une paire X25519 vers laquelle
tout appareil déverrouillé peut sceller l'AMK sans connaître ``R``.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import unicodedata
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from diapason.compte.cles import (
    INFO_RECUPERATION_AUTH,
    INFO_RECUPERATION_X25519,
    PREFIXE_INFO,
    ErreurCompte,
    en_octets,
    hkdf,
)


class CleRecuperationInvalide(ErreurCompte):
    """Faute de frappe, caractère étranger ou longueur fausse — détectés
    LOCALEMENT, avant tout appel réseau (§2.7)."""

    code = "recoveryKeyInvalid"


LONGUEUR_R = 16
LONGUEUR_CONTROLE = 4
PREFIXE_CONTROLE = PREFIXE_INFO + b"recuperation-controle"
ALPHABET_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_VALEUR_CROCKFORD = {c: i for i, c in enumerate(ALPHABET_CROCKFORD)}
# Les confusions que Crockford a choisi de pardonner : O ressemble à 0,
# I et L à 1. Le U est exclu de l'alphabet et n'est PAS pardonné.
_LECTURE_TOLERANTE = str.maketrans({"O": "0", "I": "1", "L": "1"})
TAILLE_GROUPE = 4
SEPARATEUR = "-"
LONGUEUR_TEXTE = (LONGUEUR_R + LONGUEUR_CONTROLE) * 8 // 5  # 160 bits → 32 caractères


def generer_cle_recuperation() -> bytes:
    return os.urandom(LONGUEUR_R)


def controle(r: bytes) -> bytes:
    """``SHA-256("diapason/compte/v1/recuperation-controle" ‖ R)[:4]``."""
    return hashlib.sha256(PREFIXE_CONTROLE + en_octets(r, "R", LONGUEUR_R)).digest()[
        :LONGUEUR_CONTROLE
    ]


def formater_cle_recuperation(r: bytes) -> str:
    """``XXXX-XXXX-…`` : 8 groupes de 4 caractères Crockford."""
    brut = en_octets(r, "R", LONGUEUR_R) + controle(r)
    nombre = int.from_bytes(brut, "big")
    texte = "".join(
        ALPHABET_CROCKFORD[(nombre >> (5 * i)) & 0x1F]
        for i in reversed(range(LONGUEUR_TEXTE))
    )
    return SEPARATEUR.join(
        texte[i : i + TAILLE_GROUPE] for i in range(0, LONGUEUR_TEXTE, TAILLE_GROUPE)
    )


def lire_cle_recuperation(saisie: str) -> bytes:
    """Rend ``R`` ; lève ``recoveryKeyInvalid`` sur toute faute de frappe.

    Tirets et espaces ignorés, casse indifférente, O lu 0, I et L lus 1.
    Le contrôle de 4 octets laisse passer une faute sur 2^32 : une faute
    détectée ici n'a coûté aucun essai en ligne, qui aurait compté dans les
    délais de ``/login``.
    """
    if not isinstance(saisie, str):
        raise TypeError("la clé de récupération doit être une chaîne")
    texte = unicodedata.normalize("NFKC", saisie).upper().translate(_LECTURE_TOLERANTE)
    texte = "".join(c for c in texte if c != SEPARATEUR and not c.isspace())
    if len(texte) != LONGUEUR_TEXTE:
        raise CleRecuperationInvalide(
            f"la clé fait {LONGUEUR_TEXTE} caractères, pas {len(texte)}"
        )
    nombre = 0
    for c in texte:
        if c not in _VALEUR_CROCKFORD:
            raise CleRecuperationInvalide(f"caractère inattendu : {c!r}")
        nombre = (nombre << 5) | _VALEUR_CROCKFORD[c]
    brut = nombre.to_bytes(LONGUEUR_R + LONGUEUR_CONTROLE, "big")
    r, somme = brut[:LONGUEUR_R], brut[LONGUEUR_R:]
    if not hmac.compare_digest(somme, controle(r)):
        raise CleRecuperationInvalide("faute de frappe dans la clé de récupération")
    return r


@dataclass(frozen=True)
class ClesRecuperation:
    """``recoveryAuthKey`` part au VPS ; ``cle_privee`` ne quitte pas l'appareil."""

    recovery_auth_key: bytes = field(repr=False)
    cle_privee: X25519PrivateKey = field(repr=False)
    cle_publique: bytes


def cles_recuperation(r: bytes) -> ClesRecuperation:
    """``R`` → ``recoveryAuthKey`` et la paire X25519 ``(sk_rec, pk_rec)``."""
    r = en_octets(r, "R", LONGUEUR_R)
    graine = hkdf(r, INFO_RECUPERATION_X25519)
    cle_privee = X25519PrivateKey.from_private_bytes(graine)
    return ClesRecuperation(
        recovery_auth_key=hkdf(r, INFO_RECUPERATION_AUTH),
        cle_privee=cle_privee,
        cle_publique=cle_privee.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        ),
    )
