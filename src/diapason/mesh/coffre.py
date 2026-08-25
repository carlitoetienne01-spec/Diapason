"""Le contenu d'un fichier ne traverse pas le réseau en clair.

Spatial Mesh, phase 3 — 25 août 2026. Les commandes du maillage sont
SIGNÉES, pas chiffrées : sur un réseau de confiance, savoir qui parle
suffit pour un ordre du type « ouvre cet écran ». Un fichier, non. Un
document personnel qui traverse un Wi-Fi partagé est lisible par quiconque
écoute, et ce projet promet le contraire.

Le dépôt n'avait aucun précédent — ni X25519, ni AES-GCM, ni HKDF. Les
choix sont donc posés ici, une fois, avec leurs raisons :

**Une paire X25519 ÉPHÉMÈRE par session, signée par la clé Ed25519 de
l'appareil.** Pas de conversion Ed25519 → X25519 : elle n'existe ni dans
``cryptography`` ni ici, et détourner une clé de signature pour de l'accord
de clé est le genre de raccourci qui se paie dix ans plus tard. La paire
éphémère meurt avec la session : une clé d'appareil volée demain ne
déchiffre pas un transfert d'aujourd'hui.

**AES-256-GCM, un nonce par morceau, dérivé et non tiré au sort.** Le
nonce est ``compteur`` sur 12 octets : deux morceaux d'une même session ne
peuvent pas partager un nonce, ce qui serait la seule façon de casser GCM.
Et l'index du morceau entre dans les données authentifiées, donc réordonner
les morceaux invalide le déchiffrement.

**HKDF-SHA256** pour tirer la clé de session du secret partagé, avec
l'identifiant de session en sel : deux transferts entre les mêmes appareils
n'ont jamais la même clé.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_INFO = b"diapason-mesh-transfer-v1"
_TAILLE_CLE = 32
_TAILLE_NONCE = 12


class CoffreIndisponible(RuntimeError):
    """La cryptographie manque — on refuse d'envoyer en clair pour autant."""


def _primitives():
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey,
            X25519PublicKey,
        )
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    except ImportError as exc:  # pragma: no cover - dépendance de base
        raise CoffreIndisponible(
            "Le chiffrement de transfert exige « cryptography » : "
            "uv pip install 'cryptography>=43'"
        ) from exc
    return hashes, X25519PrivateKey, X25519PublicKey, AESGCM, HKDF


@dataclass(frozen=True, slots=True)
class DemiCle:
    """Une paire éphémère : la moitié publique se donne, la privée meurt ici."""

    privee: bytes
    publique: bytes

    @property
    def publique_b64(self) -> str:
        import base64

        return base64.b64encode(self.publique).decode("ascii")


def nouvelle_demi_cle() -> DemiCle:
    """Une paire X25519 neuve, pour UNE session et pas une de plus."""
    _h, X25519PrivateKey, _pub, _aes, _hkdf = _primitives()
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    privee = X25519PrivateKey.generate()
    return DemiCle(
        privee=privee.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()),
        publique=privee.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
    )


def cle_de_session(demi: DemiCle, publique_pair_b64: str, session_id: str) -> bytes:
    """La clé partagée des deux côtés, que ni l'un ni l'autre n'a choisie.

    L'identifiant de session sert de sel : deux transferts entre les mêmes
    appareils ne partagent jamais une clé.
    """
    import base64

    hashes, X25519PrivateKey, X25519PublicKey, _aes, HKDF = _primitives()
    try:
        brute = base64.b64decode(publique_pair_b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Clé publique éphémère illisible.") from exc
    if len(brute) != 32:
        raise ValueError("Clé publique éphémère de taille invalide.")
    partage = X25519PrivateKey.from_private_bytes(demi.privee).exchange(
        X25519PublicKey.from_public_bytes(brute)
    )
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_TAILLE_CLE,
        salt=session_id.encode("utf-8"),
        info=_INFO,
    ).derive(partage)


def _nonce(index: int) -> bytes:
    if index < 0 or index >= 2 ** (8 * _TAILLE_NONCE):
        raise ValueError("Index de morceau hors bornes.")
    return index.to_bytes(_TAILLE_NONCE, "big")


def sceller(cle: bytes, index: int, clair: bytes) -> bytes:
    """Chiffrer un morceau. L'index est authentifié : le réordonner casse."""
    _h, _priv, _pub, AESGCM, _hkdf = _primitives()
    return AESGCM(cle).encrypt(_nonce(index), clair, str(index).encode("ascii"))


def desceller(cle: bytes, index: int, scelle: bytes) -> bytes:
    """Déchiffrer un morceau — lève si le contenu ou l'index a bougé."""
    _h, _priv, _pub, AESGCM, _hkdf = _primitives()
    try:
        return AESGCM(cle).decrypt(_nonce(index), scelle, str(index).encode("ascii"))
    except Exception as exc:  # noqa: BLE001 - InvalidTag et le reste
        raise ValueError(
            f"Morceau {index} illisible : contenu altéré, mauvaise clé, "
            "ou morceau présenté à la mauvaise place."
        ) from exc


def disponible() -> bool:
    """La cryptographie répond-elle ? Constaté, jamais supposé."""
    try:
        _primitives()
        return True
    except CoffreIndisponible:
        return False


__all__ = [
    "CoffreIndisponible",
    "DemiCle",
    "cle_de_session",
    "desceller",
    "disponible",
    "nouvelle_demi_cle",
    "sceller",
]
