"""Les pièces : les images d'une conversation, détachées et chiffrées à part.

Conception : ``docs/development/compte-chiffre.md`` §4.7 (collection
``conversations`` et pièces), §2.6 (``pieceId`` par époque), §2.5 (type 02,
plancher de 4 096 o) et §3.4 (``/pieces/*``).

Une image jointe à un message voyage dans le magasin comme une chaîne
``data:image/png;base64,…`` — l'essentiel du poids d'une ``conversations.db``
réelle, d'après la carte du préambule. Dans un objet, elle repartait à CHAQUE
poussée de la conversation : une réponse qui arrive au fil de l'eau renvoyait
plus d'un Mo pour quelques mots (§4.7). Détachée, elle part une fois par
époque, et l'objet ne porte plus que ``"diapason-piece:<pieceId>"``.

**Le clair d'une pièce** (clés anglaises, CLAUDE.md §3) :

``uint32 BE(L) ‖ en-tête JSON canonique (L octets) ‖ charge``

- ``{"header":"data:image/png;base64,"}`` et les OCTETS décodés de l'image,
  quand le ré-encodage base64 redonne exactement la chaîne ;
- ``{"form":"raw"}`` et la chaîne ENTIÈRE en UTF-8 sinon (base64 coupé de
  retours à la ligne, sans remplissage, SVG en clair…).

La règle « ré-encoder et comparer » est ce qui rend la réintégration exacte
à l'octet près : un décodage tolérant suivi d'un ré-encodage canonique
aurait rendu à l'autre appareil une chaîne différente de celle que la vue a
écrite — une conversation qui diffère d'elle-même d'un appareil à l'autre,
et que la fusion ne départage que par l'ordre des arguments.

**L'identifiant** est ``HMAC(K_piece_e, "attachment\\0" ‖ SHA-256(clair))``
(§2.6) : sans ``K_piece``, le VPS ne peut ni vérifier qu'un blob porte telle
image, ni tester la présence d'une image connue. À la lecture, l'appareil
RECALCULE l'identifiant sur le clair ouvert : l'AAD lie déjà le blob à son
``pieceId``, le recalcul attrape en plus un clair d'une autre image scellé
sous ce nom par un porteur d'une ancienne DEK (§2.11 bis).

**Lire une pièce** est la seule requête du compte dont la réponse n'est pas
du JSON : ``Transport._envoyer`` décode tout corps en JSON et rend ``{}``
pour des octets. :func:`telecharger` refait donc, à l'identique, la
frontière et la lecture du jeton, puis lit le corps brut, borné.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import struct
from collections.abc import Callable
from typing import Any

from diapason.compte.cles import ErreurCompte, sans_doublons
from diapason.compte.enveloppe import (
    TYPE_PIECE,
    EnveloppeIllisible,
    lire_en_tete,
    ouvrir_piece,
    sceller_piece,
)
from diapason.compte.transport import (
    PREFIXE_API,
    ErreurServeur,
    ServeurInjoignable,
    assert_may_reach_account_server,
)
from diapason.compte.trousseau import EpoqueInconnue

logger = logging.getLogger(__name__)

__all__ = [
    "PIECE_MAX_OCTETS",
    "PREFIXE_REFERENCE",
    "PieceIllisible",
    "deballer",
    "detachable",
    "emballer",
    "identifiant_de",
    "ouvrir",
    "reference",
    "sceller",
    "telecharger",
]

PREFIXE_REFERENCE = "diapason-piece:"

# §3.5 (D10) : le VPS refuse une pièce de plus de 10 Mio
# (``routes_pieces.PIECE_MAX_OCTETS``). Une image dont le blob dépasse cette
# borne est bien détachée, mais ``MoteurSynchro._deposer`` la refuse AVANT
# le PUT : sa conversation passe en quarantaine visible
# (``rejected:pieceTooLarge``) jusqu'à sa prochaine écriture locale, plutôt
# que de repartir chaque cycle pour un 413. Le cas reste théorique : la vue
# et ``server/pieces_jointes.py`` bornent une image à 4 Mo. (Jusqu'au
# 24/09/2026, ce commentaire promettait qu'elle « restait dans l'objet » —
# rien ne l'y laissait.) La même borne limite ce que :func:`telecharger`
# accepte de lire : un VPS hostile qui répondrait un flux sans fin
# remplirait sinon la mémoire du serveur local.
PIECE_MAX_OCTETS = 10 * 1024 * 1024

# ``pieceId`` : ``b64url(HMAC(…)[:16])``, 22 caractères sans remplissage
# (§2.6). Une référence d'une autre forme n'est pas une pièce : elle reste
# dans le message telle quelle, jamais réclamée ni demandée au VPS.
_IDENTIFIANT = re.compile(r"[A-Za-z0-9_-]{22}")

# 64 Kio d'en-tête au plus : ``data:image/svg+xml;base64,`` en fait 26. Un
# clair forgé qui annoncerait 4 Gio d'en-tête n'est pas lu plus loin.
_ENTETE_MAX = 64 * 1024


class PieceIllisible(ErreurCompte):
    """Une pièce qu'on ne peut pas rendre : blob refusé, clair mal formé,
    ou contenu qui ne correspond pas à son identifiant."""

    code = "pieceUnreadable"


# ----------------------------------------------------------------------
# Le clair d'une pièce
# ----------------------------------------------------------------------


def detachable(valeur: Any) -> bool:
    """Une image ``data:`` : ce qui devient une pièce."""
    return isinstance(valeur, str) and valeur.startswith("data:")


def _entete_json(entete: dict[str, str]) -> bytes:
    return json.dumps(
        entete, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _forme_compacte(image: str) -> tuple[str, bytes] | None:
    """``(en-tête, octets)`` si ``en-tête + b64encode(octets)`` redonne
    EXACTEMENT ``image`` ; ``None`` sinon."""
    virgule = image.find(",")
    if virgule < 0:
        return None
    entete, donnees = image[: virgule + 1], image[virgule + 1 :]
    if not entete.endswith(";base64,"):
        return None
    try:
        octets = base64.b64decode(donnees, validate=True)
    except (binascii.Error, ValueError):
        return None
    if base64.b64encode(octets).decode("ascii") != donnees:
        return None
    return entete, octets


def emballer(image: str) -> bytes:
    """Le clair de la pièce qui porte ``image`` (voir la docstring du module).

    Lève ``UnicodeEncodeError`` sur un substitut UTF-16 isolé : l'appelant
    laisse alors l'image dans l'objet, où le scellement la refusera comme
    avant les pièces.
    """
    if not detachable(image):
        raise ValueError("seule une image data: devient une pièce")
    compacte = _forme_compacte(image)
    if compacte is not None:
        entete, charge = _entete_json({"header": compacte[0]}), compacte[1]
    else:
        entete, charge = _entete_json({"form": "raw"}), image.encode("utf-8")
    return struct.pack(">I", len(entete)) + entete + charge


def deballer(octets: bytes) -> str:
    """La chaîne exacte qu'avait l'image. Lève :class:`PieceIllisible`."""
    if not isinstance(octets, bytes) or len(octets) < 4:
        raise PieceIllisible("clair de pièce tronqué")
    (longueur,) = struct.unpack(">I", octets[:4])
    if longueur > _ENTETE_MAX or 4 + longueur > len(octets):
        raise PieceIllisible("en-tête de pièce hors du clair")
    try:
        entete = json.loads(
            octets[4 : 4 + longueur].decode("utf-8"), object_pairs_hook=sans_doublons
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise PieceIllisible("en-tête de pièce illisible") from exc
    charge = octets[4 + longueur :]
    if entete == {"form": "raw"}:
        try:
            image = charge.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PieceIllisible("image brute qui n'est pas de l'UTF-8") from exc
        if not detachable(image):
            raise PieceIllisible("image brute sans en-tête data:")
        return image
    if not isinstance(entete, dict) or set(entete) != {"header"}:
        raise PieceIllisible("en-tête de pièce inconnu")
    prefixe = entete["header"]
    if (
        not isinstance(prefixe, str)
        or not prefixe.startswith("data:")
        or not prefixe.endswith(";base64,")
        or prefixe.count(",") != 1
    ):
        raise PieceIllisible("en-tête data: invalide")
    return prefixe + base64.b64encode(charge).decode("ascii")


# ----------------------------------------------------------------------
# Références dans le clair d'un objet
# ----------------------------------------------------------------------


def reference(piece_id: str) -> str:
    return PREFIXE_REFERENCE + piece_id


def identifiant_de(valeur: Any) -> str | None:
    """Le ``pieceId`` d'une référence bien formée, ``None`` sinon."""
    if not isinstance(valeur, str) or not valeur.startswith(PREFIXE_REFERENCE):
        return None
    piece_id = valeur[len(PREFIXE_REFERENCE) :]
    return piece_id if _IDENTIFIANT.fullmatch(piece_id) else None


# ----------------------------------------------------------------------
# Sceller, ouvrir (DPE1 type 02)
# ----------------------------------------------------------------------


def sceller(
    trousseau: Any, octets: bytes, *, account_id: str, incarnation: int
) -> tuple[str, bytes]:
    """``(pieceId, blob)`` sous l'époque COURANTE : le VPS refuse une pièce
    d'une autre époque (409 ``keyEpochChanged``), et une pièce de l'époque
    d'avant resterait sous la DEK que l'appareil perdu connaît (§2.2)."""
    piece_id = trousseau.identifiant_piece(octets)
    blob = sceller_piece(
        trousseau.dek_courante,
        octets,
        account_id=account_id,
        incarnation=incarnation,
        piece_id=piece_id,
        key_epoch=trousseau.current_epoch,
    )
    return piece_id, blob


def ouvrir(
    trousseau: Any, blob: bytes, *, account_id: str, incarnation: int, piece_id: str
) -> bytes:
    """Ouvre, puis RECALCULE ``pieceId`` sur le clair sous l'époque de
    l'en-tête, et vérifie la forme du clair. Lève :class:`PieceIllisible`."""
    try:
        en_tete = lire_en_tete(blob)
        if en_tete.type != TYPE_PIECE:
            raise PieceIllisible(f"type {en_tete.type:02x} au lieu d'une pièce")
        octets = ouvrir_piece(
            trousseau.dek(en_tete.key_epoch),
            blob,
            account_id=account_id,
            incarnation=incarnation,
            piece_id=piece_id,
        )
    except (EnveloppeIllisible, EpoqueInconnue) as exc:
        raise PieceIllisible("pièce refusée") from exc
    if trousseau.identifiant_piece(octets, en_tete.key_epoch) != piece_id:
        raise PieceIllisible("contenu différent de son identifiant")
    deballer(octets)
    return octets


# ----------------------------------------------------------------------
# Lire une pièce sur le VPS
# ----------------------------------------------------------------------


def telecharger(
    transport: Any, piece_id: str, *, jeton: Callable[[], str | None]
) -> bytes:
    """``GET /pieces/{id}`` → les octets du blob, bornés à
    :data:`PIECE_MAX_OCTETS`.

    La frontière passe AVANT la lecture du jeton, comme dans
    ``Transport._envoyer`` (§4.3, étape 2 du cycle) ; aucun suivi de
    redirection (le client de production n'en suit pas, et une redirection
    est refusée ici comme là). ``transport.py`` n'a de méthode typée que
    pour les écritures ; celle-ci en est la lecture, en attendant d'y
    entrer (écart du 24/09/2026 : le fichier n'était pas du périmètre de
    l'étape 11).
    """
    if identifiant_de(reference(piece_id)) is None:
        raise ValueError("pieceId mal formé")
    chemin = f"/pieces/{piece_id}"
    url = transport.origine + PREFIXE_API + chemin
    assert_may_reach_account_server(
        url,
        actif=transport._actif(),  # noqa: SLF001 - voir la docstring
        config=transport._config,  # noqa: SLF001
    )
    valeur = jeton()
    if not valeur:
        raise ErreurServeur(401, "sessionExpired")
    en_tetes = {
        "Accept": "application/octet-stream",
        "Authorization": f"Bearer {valeur}",
    }
    import httpx

    from diapason.compte.transport import _erreur_de

    try:
        with transport._http().stream(  # noqa: SLF001
            "GET", url, headers=en_tetes
        ) as reponse:
            if 300 <= reponse.status_code < 400:
                raise ServeurInjoignable("redirection refusée")
            morceaux: list[bytes] = []
            lus = 0
            for morceau in reponse.iter_bytes():
                lus += len(morceau)
                if lus > PIECE_MAX_OCTETS + 64 * 1024:
                    # Au-delà d'une pièce maximale et d'un corps d'erreur :
                    # ni l'une ni l'autre, et rien de plus n'est lu.
                    raise PieceIllisible("réponse plus lourde qu'une pièce")
                morceaux.append(morceau)
            contenu = b"".join(morceaux)
            statut = reponse.status_code
    except httpx.HTTPError as exc:
        # Le TYPE seulement : le message d'une erreur httpx peut citer l'URL.
        logger.warning("compte : GET /pieces injoignable (%s)", type(exc).__name__)
        raise ServeurInjoignable("le serveur de comptes est injoignable") from None
    logger.debug("compte : GET /pieces → %s", statut)
    if statut >= 400:
        try:
            corps = json.loads(contenu) if contenu else {}
        except ValueError:
            corps = None
        # Le même code d'erreur que toute autre route (``retryAfterS``, 429
        # de nginx sans corps) : le moteur ne distingue pas une pièce.
        raise _erreur_de(statut, corps)
    if len(contenu) > PIECE_MAX_OCTETS:
        raise PieceIllisible("pièce plus lourde que le maximum du VPS")
    return contenu
