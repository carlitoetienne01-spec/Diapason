"""Les images jointes à un message du chat.

22 septembre 2026. Le tuyau existait déjà de bout en bout SAUF sur son
premier mètre : ``Message.images`` est transmis à Ollama par
``engine/_base.py`` (« Vision: forward base64 images to the engine »), et
``qwen3.5:9b`` annonce ``completion vision tools thinking``. Mais
``ChatMessage``, le modèle Pydantic qui reçoit les requêtes HTTP, n'avait
aucun champ ``images`` : le navigateur ne pouvait rien envoyer. Le serveur
savait voir, personne ne pouvait lui montrer.

Ce module garde l'entrée. Ce qui arrive du réseau est toujours une
promesse — une image de vingt mégaoctets, un PDF déguisé, cent images d'un
coup — et le modèle n'a ni la mémoire ni la patience de s'en occuper.

**Le format est du JSON base64, jamais du multipart.** La fenêtre de bureau
est une WKWebView, qui échoue sur un corps binaire avec un « Load failed »
opaque (piège déjà payé, voir CLAUDE.md). Le préfixe ``data:`` est accepté
et retiré : c'est ce que rend ``FileReader.readAsDataURL`` côté navigateur,
et ce n'est pas ce qu'attend Ollama.
"""

from __future__ import annotations

import base64
import binascii
import logging

logger = logging.getLogger(__name__)

# Une photo d'iPhone fait douze mégaoctets, soit seize une fois encodée en
# base64. Le modèle la redimensionne de toute façon avant de la regarder :
# au-delà de ce seuil on transporte des octets pour rien, et la requête
# devient le goulot. Quatre mégaoctets couvrent une capture d'écran Retina
# en PNG et une photo en JPEG de bonne qualité.
TAILLE_MAX = 4 * 1024 * 1024
# Chaque image coûte des centaines de jetons de contexte au modèle. Sur un
# 9b en 32 Ko de fenêtre, trois est déjà généreux.
NOMBRE_MAX = 3

# Les octets de tête qui disent le format, puisqu'on ne peut pas se fier au
# nom d'un fichier qui n'en a plus. PNG, JPEG, GIF, WebP : ce que les
# modèles de vision savent lire.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


class PieceJointeRefusee(ValueError):
    """Ce qui est arrivé ne peut pas être montré au modèle."""


def _sans_entete(brut: str) -> str:
    """Retire le préfixe ``data:image/png;base64,`` s'il y en a un."""
    if brut.startswith("data:"):
        _entete, _sep, donnees = brut.partition(",")
        return donnees
    return brut


def format_de(octets: bytes) -> str | None:
    """Le type MIME lu dans les octets de tête, ou None si ce n'est pas une
    image reconnue.

    On ne croit pas le client sur parole : l'en-tête ``data:`` qu'il envoie
    est une déclaration, pas une preuve.
    """
    for signature, mime in _SIGNATURES:
        if octets.startswith(signature):
            return mime
    # WebP : « RIFF » ... « WEBP », le second marqueur au douzième octet.
    if octets[:4] == b"RIFF" and octets[8:12] == b"WEBP":
        return "image/webp"
    return None


def normaliser(brut: str) -> str:
    """Une image prête pour Ollama : du base64 nu, sans en-tête ``data:``.

    Lève :class:`PieceJointeRefusee` avec une phrase en français que
    l'interface peut afficher telle quelle — l'usager doit savoir CE QUI est
    refusé, pas qu'« une erreur est survenue ».
    """
    donnees = _sans_entete((brut or "").strip())
    if not donnees:
        raise PieceJointeRefusee("Image vide.")
    # Le décodage valide le base64 ; il dit aussi la taille réelle, qui est
    # celle qui compte — la chaîne encodée pèse un tiers de plus.
    try:
        octets = base64.b64decode(donnees, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PieceJointeRefusee("Image illisible : ce n'est pas du base64.") from exc
    if len(octets) > TAILLE_MAX:
        raise PieceJointeRefusee(
            f"Image trop lourde : {len(octets) // 1024 // 1024} Mo, "
            f"maximum {TAILLE_MAX // 1024 // 1024} Mo."
        )
    mime = format_de(octets)
    if mime is None:
        raise PieceJointeRefusee(
            "Format non reconnu. Les images acceptées sont PNG, JPEG, GIF et WebP."
        )
    return donnees


def normaliser_toutes(brutes: list[str] | None) -> list[str] | None:
    """Les images d'un message, validées ; ``None`` quand il n'y en a pas.

    Une seule image refusée refuse le message entier : livrer les deux
    autres en silence ferait croire que la troisième a été vue (§5).
    """
    if not brutes:
        return None
    if len(brutes) > NOMBRE_MAX:
        raise PieceJointeRefusee(
            f"{len(brutes)} images jointes, maximum {NOMBRE_MAX} par message."
        )
    return [normaliser(b) for b in brutes]


__all__ = [
    "NOMBRE_MAX",
    "TAILLE_MAX",
    "PieceJointeRefusee",
    "format_de",
    "normaliser",
    "normaliser_toutes",
]
