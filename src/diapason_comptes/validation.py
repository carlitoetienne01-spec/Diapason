"""Validation écrite à la main, et les erreurs qu'elle rend.

Conception : ``docs/development/compte-chiffre.md`` §3.1 et §3.4.

Pourquoi à la main : le gestionnaire par défaut de FastAPI renvoie, dans un
422, la valeur refusée (``"input": …``). Un ``authKey`` mal encodé serait
alors recopié dans la réponse, puis dans tout journal qui garde les corps
de réponse. Ici, une erreur ne nomme que le CHAMP, jamais la valeur.

Conventions du fil (§3.4) : JSON en camelCase, octets en base64url sans
remplissage, heures en millisecondes entières, AUCUN flottant.
"""

from __future__ import annotations

import base64
import json
import re
import unicodedata
from typing import Any

from fastapi import Request

# ----------------------------------------------------------------------
# Erreurs
# ----------------------------------------------------------------------


class ErreurRequete(Exception):
    """Une réponse d'erreur ``{"error": {"code": …}}`` et son statut HTTP.

    ``champ`` n'est rempli que pour ``invalidRequest`` ; ``retry_after_s``
    que pour ``tooManyAttempts`` et ``serverBusy``. Aucune valeur reçue n'y
    entre jamais.

    ``extra`` s'ajoute à côté de ``error`` : les routes ``/sync/*`` y mettent
    leur bloc ``meta`` (§3.4), pour qu'un 409 ``keyEpochChanged`` dise
    lui-même à quelle époque le compte est passé.
    """

    def __init__(
        self,
        statut: int,
        code: str,
        *,
        champ: str | None = None,
        retry_after_s: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.statut = statut
        self.code = code
        self.champ = champ
        self.retry_after_s = retry_after_s
        self.extra = extra

    def corps(self) -> dict[str, Any]:
        erreur: dict[str, Any] = {"code": self.code}
        if self.champ is not None:
            erreur["field"] = self.champ
        if self.retry_after_s is not None:
            erreur["retryAfterS"] = self.retry_after_s
        return {**(self.extra or {}), "error": erreur}


def invalide(champ: str) -> ErreurRequete:
    return ErreurRequete(422, "invalidRequest", champ=champ)


# ----------------------------------------------------------------------
# Corps JSON
# ----------------------------------------------------------------------

# nginx borne déjà ``/api/`` à 64 Kio (§3.9). La même borne ici : uvicorn
# écoute 127.0.0.1 seulement, mais un ``curl`` lancé sur le VPS même ne passe
# pas par nginx, et un corps de 300 Mo remplirait le ``MemoryMax=300M`` du
# service avant la première ligne de validation. Elle se vérifie donc AVANT
# de lire (``corps_json``) : jusqu'au 24/09/2026, ``request.body()`` lisait
# tout, et la borne ne refusait qu'ensuite.
CORPS_MAX_OCTETS = 64 * 1024


class _Flottant(ValueError):
    pass


def _refuser_flottant(_texte: str) -> Any:
    # Python écrit ``1e-07`` là où Dart écrit ``1e-7`` (CLAUDE.md §4) :
    # le service n'accepte aucun flottant, pour qu'aucun client ne compte
    # un jour sur un arrondi qu'un autre langage ne reproduit pas.
    raise _Flottant("flottant refusé")


def _sans_doublons(paires: list[tuple[str, Any]]) -> dict[str, Any]:
    # ``json.loads`` garde la DERNIÈRE occurrence d'une clé en double : un
    # corps ``{"authKey": A, "authKey": B}`` validé sur l'une et stocké sur
    # l'autre par un intermédiaire qui lit la première n'a rien d'impossible.
    resultat: dict[str, Any] = {}
    for cle, valeur in paires:
        if cle in resultat:
            raise ValueError("clé en double")
        resultat[cle] = valeur
    return resultat


def lire_json(octets: bytes, *, maximum: int = CORPS_MAX_OCTETS) -> dict[str, Any]:
    """Un objet JSON strict : UTF-8, sans flottant, sans clé en double.

    Un corps vide vaut ``{}`` : ``POST /vault/code`` et ``/logout`` n'en
    exigent pas. ``maximum`` n'est relevé que par ``sync/push`` (§3.9 : 12 Mio
    chez nginx pour ``/api/v1/sync/``).
    """
    if len(octets) > maximum:
        raise ErreurRequete(413, "payloadTooLarge")
    if not octets.strip():
        return {}
    try:
        valeur = json.loads(
            octets.decode("utf-8"),
            parse_float=_refuser_flottant,
            parse_constant=_refuser_flottant,
            object_pairs_hook=_sans_doublons,
        )
    except _Flottant as exc:
        raise invalide("body") from exc
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise invalide("body") from exc
    if not isinstance(valeur, dict):
        raise invalide("body")
    return valeur


async def lire_octets_bornes(request: Request, maximum: int) -> bytes:
    """Le corps brut, jamais plus de ``maximum`` octets en mémoire.

    Un ``Content-Length`` au-delà de la borne est refusé sans rien lire ; un
    corps sans longueur annoncée est lu par morceaux et coupé dès qu'il la
    dépasse.
    """
    annonce = request.headers.get("content-length")
    if annonce is not None:
        if not annonce.strip().isdigit():
            raise invalide("body")
        if int(annonce) > maximum:
            raise ErreurRequete(413, "payloadTooLarge")
    lu = bytearray()
    async for morceau in request.stream():
        lu += morceau
        if len(lu) > maximum:
            raise ErreurRequete(413, "payloadTooLarge")
    return bytes(lu)


async def corps_json(request: Request) -> dict[str, Any]:
    """Dépendance FastAPI : lit le corps sur la boucle (non bloquant), le
    valide, puis la route ``def`` travaille dans son fil (§3.1)."""
    return lire_json(await lire_octets_bornes(request, CORPS_MAX_OCTETS))


# ----------------------------------------------------------------------
# Champs
# ----------------------------------------------------------------------

# SQLite range un INTEGER sur 8 octets signés : au-delà, ``OverflowError``
# en pleine transaction, soit un 500 là où un 422 était dû.
ENTIER_MAX = 2**63 - 1


def objet(corps: dict[str, Any], nom: str, *, chemin: str = "") -> dict[str, Any]:
    valeur = corps.get(nom)
    if not isinstance(valeur, dict):
        raise invalide(chemin + nom)
    return valeur


def entier(
    corps: dict[str, Any],
    nom: str,
    *,
    minimum: int = 0,
    maximum: int = ENTIER_MAX,
    chemin: str = "",
) -> int:
    """Un entier véritable : ``true`` n'est pas 1 (``True in {1}`` vaut vrai
    en Python, et un ``kdfVersion: true`` passerait pour la version 1)."""
    valeur = corps.get(nom)
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise invalide(chemin + nom)
    if not minimum <= valeur <= maximum:
        raise invalide(chemin + nom)
    return valeur


def texte(
    corps: dict[str, Any], nom: str, *, maximum: int = 256, chemin: str = ""
) -> str:
    valeur = corps.get(nom)
    if not isinstance(valeur, str) or not valeur or len(valeur) > maximum:
        raise invalide(chemin + nom)
    return valeur


_B64URL = re.compile(r"[A-Za-z0-9_-]*")


def b64url(octets: bytes) -> str:
    """base64url sans remplissage (§3.4)."""
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


def de_b64url(valeur: object) -> bytes | None:
    """Décodage STRICT, ou ``None``.

    Strict parce que ``b64decode`` accepte des bits de queue non nuls : deux
    textes différents donneraient les mêmes octets, et un jeton comparé
    sous sa forme texte ne serait plus unique.
    """
    if not isinstance(valeur, str) or not _B64URL.fullmatch(valeur):
        return None
    if len(valeur) % 4 == 1:
        return None
    octets = base64.urlsafe_b64decode(valeur + "=" * (-len(valeur) % 4))
    if b64url(octets) != valeur:
        return None
    return octets


def octets_b64(
    corps: dict[str, Any],
    nom: str,
    *,
    longueur: int | None = None,
    maximum: int = CORPS_MAX_OCTETS,
    chemin: str = "",
) -> bytes:
    octets = de_b64url(corps.get(nom))
    if octets is None or len(octets) > maximum:
        raise invalide(chemin + nom)
    if longueur is not None and len(octets) != longueur:
        raise invalide(chemin + nom)
    return octets


LONGUEUR_CLE = 32


def cle_32(corps: dict[str, Any], nom: str, *, chemin: str = "") -> bytes:
    """``authKey``, ``recoveryAuthKey`` : 32 o, sortie de HKDF (§2.2)."""
    return octets_b64(corps, nom, longueur=LONGUEUR_CLE, chemin=chemin)


# ----------------------------------------------------------------------
# Courriel (§2.4) — recopié du client, jamais importé
# ----------------------------------------------------------------------

COURRIEL_MIN = 3
COURRIEL_MAX = 254


def normaliser_courriel(valeur: object) -> str | None:
    """``NFKC``, ``strip``, ``lower`` ; 3 à 254 caractères, un seul ``@``,
    aucun espace — ou ``None``.

    Recopiée de ``diapason.compte.cles.normaliser_courriel`` et NON importée
    (§3.1). Un écart entre les deux ferait dériver au client un sel Argon2
    d'une adresse que le serveur indexe sous une autre : le compte
    deviendrait inouvrable sans message. ``test_validation.py`` confronte
    les deux sur les mêmes entrées.
    """
    if not isinstance(valeur, str):
        return None
    e = unicodedata.normalize("NFKC", valeur).strip().lower()
    if not COURRIEL_MIN <= len(e) <= COURRIEL_MAX:
        return None
    if e.count("@") != 1 or any(c.isspace() for c in e):
        return None
    return e


def courriel(corps: dict[str, Any], nom: str = "email") -> str:
    e = normaliser_courriel(corps.get(nom))
    if e is None:
        raise invalide(nom)
    return e


_CODE = re.compile(r"[0-9]{6}")


def code_six_chiffres(
    corps: dict[str, Any], nom: str = "code", chemin: str = ""
) -> str:
    valeur = corps.get(nom)
    if not isinstance(valeur, str) or not _CODE.fullmatch(valeur):
        raise invalide(chemin + nom)
    return valeur


# ----------------------------------------------------------------------
# Forme des enveloppes DPE1 (§2.5) — le serveur n'ouvre rien, il mesure
# ----------------------------------------------------------------------

FORMAT_DPE1 = 0x01
TYPE_NOM_APPAREIL = 0x04
TYPE_AMK_MOT_DE_PASSE = 0x03
TYPE_TROUSSEAU = 0x05
TYPE_AMK_RECUPERATION = 0x06
LONGUEUR_EN_TETE_COURT = 6
SURCOUT = 66  # en-tête 6 + sel 32 + nonce 12 + tag 16


def padme(longueur: int) -> int:
    """Padmé (Nikitin et al., PURBs 2019), recopié du client (§3.1)."""
    e = longueur.bit_length() - 1
    s = e.bit_length()
    masque = (1 << (e - s)) - 1
    return (longueur + masque) & ~masque


# Type 03 : une AMK de 32 o dans un cadre ``uint32 ‖ AMK`` de 36 o, que
# Padmé laisse à 36 ; plus les 66 o de surcoût. Toute autre longueur n'est
# pas une enveloppe AMK : la refuser à l'entrée évite de stocker un coffre
# que l'appareil suivant ne saura pas ouvrir.
LONGUEUR_AMK_MOT_DE_PASSE = SURCOUT + padme(4 + LONGUEUR_CLE)
# Type 06 : en-tête 6 + ``enc`` HPKE 32 + AMK 32 + tag 16.
LONGUEUR_AMK_RECUPERATION = LONGUEUR_EN_TETE_COURT + 32 + LONGUEUR_CLE + 16
# Trousseau : environ 52 o par époque en JSON. 32 Kio en tiennent plus de
# 600, soit des années de rotations ; et 32 Kio en base64 (43 Kio) plus le
# reste d'un ``vault/commit`` tiennent sous les 64 Kio que nginx accorde à
# ``/api/`` (§3.9). Un trousseau plus gros ne pourrait de toute façon plus
# être renvoyé par le client.
TROUSSEAU_MAX_OCTETS = 32 * 1024
# Nom d'appareil : quelques dizaines de caractères. 1 Kio borne ce que
# ``PUT /sessions/current`` peut faire stocker par une session volée.
NOM_APPAREIL_MAX_OCTETS = 1024


def _en_tete_valide(octets: bytes, type_: int, *, epoque_nulle: bool) -> bool:
    if len(octets) < LONGUEUR_EN_TETE_COURT:
        return False
    if octets[0] != FORMAT_DPE1 or octets[1] != type_:
        return False
    return not (epoque_nulle and octets[2:6] != bytes(4))


def _cadre_padme(octets: bytes, maximum: int) -> bool:
    """``taille − 66`` est une valeur de Padmé d'au moins 4 o (§2.5)."""
    if not SURCOUT + 4 <= len(octets) <= maximum:
        return False
    cadre = len(octets) - SURCOUT
    return padme(cadre) == cadre


def enveloppe_amk_mot_de_passe(
    corps: dict[str, Any], nom: str = "wrappedMasterKey", *, chemin: str = ""
) -> bytes:
    octets = octets_b64(corps, nom, longueur=LONGUEUR_AMK_MOT_DE_PASSE, chemin=chemin)
    if not _en_tete_valide(octets, TYPE_AMK_MOT_DE_PASSE, epoque_nulle=True):
        raise invalide(chemin + nom)
    return octets


def enveloppe_amk_recuperation(
    corps: dict[str, Any], nom: str = "sealedMasterKey", *, chemin: str = ""
) -> bytes:
    octets = octets_b64(corps, nom, longueur=LONGUEUR_AMK_RECUPERATION, chemin=chemin)
    if not _en_tete_valide(octets, TYPE_AMK_RECUPERATION, epoque_nulle=True):
        raise invalide(chemin + nom)
    return octets


def enveloppe_trousseau(corps: dict[str, Any], nom: str = "keyring") -> bytes:
    octets = octets_b64(corps, nom, maximum=TROUSSEAU_MAX_OCTETS)
    if not _en_tete_valide(octets, TYPE_TROUSSEAU, epoque_nulle=True):
        raise invalide(nom)
    if not _cadre_padme(octets, TROUSSEAU_MAX_OCTETS):
        raise invalide(nom)
    return octets


def enveloppe_nom_appareil(corps: dict[str, Any], nom: str = "encryptedName") -> bytes:
    octets = octets_b64(corps, nom, maximum=NOM_APPAREIL_MAX_OCTETS)
    if not _en_tete_valide(octets, TYPE_NOM_APPAREIL, epoque_nulle=False):
        raise invalide(nom)
    if not _cadre_padme(octets, NOM_APPAREIL_MAX_OCTETS):
        raise invalide(nom)
    return octets


# Types 01 (objet) et 02 (pièce) : le serveur ne peut vérifier que la
# FORME — format, type, et ``taille − 66`` égale à une valeur de Padmé au
# moins égale au plancher du type (§2.5). Un blob qui ne l'a pas ne vient
# pas d'un client Diapason : le garder, c'était le resservir à chaque
# appareil, qui le mettrait en quarantaine pour toujours.
TYPE_OBJET = 0x01
TYPE_PIECE = 0x02
PLANCHER_OBJET = 1024
PLANCHER_PIECE = 4096
EPOQUE_MAX = 0xFFFFFFFF


def epoque_enveloppe_donnees(
    octets: bytes, type_: int, *, plancher: int, maximum: int
) -> int | None:
    """Le ``keyEpoch`` de l'en-tête d'un objet ou d'une pièce bien formé,
    ou ``None``. Une époque nulle est refusée : elle est réservée aux types
    03, 05 et 06, qui n'en portent pas."""
    if not _en_tete_valide(octets, type_, epoque_nulle=False):
        return None
    if not _cadre_padme(octets, maximum) or len(octets) - SURCOUT < plancher:
        return None
    epoque = int.from_bytes(octets[2:6], "big")
    return epoque or None


# ``objectId`` et ``pieceId`` : ``b64url(HMAC(…)[:16])``, 22 caractères
# (§2.6). Rien d'autre n'entre dans une clé primaire : un identifiant de
# 500 caractères choisi par un client ferait grossir l'index sans fin.
LONGUEUR_IDENTIFIANT = 16


def identifiant_opaque(valeur: object) -> str | None:
    octets = de_b64url(valeur)
    if octets is None or len(octets) != LONGUEUR_IDENTIFIANT:
        return None
    assert isinstance(valeur, str)
    return valeur


def entier_de_requete(
    request: Request, nom: str, *, defaut: int, minimum: int, maximum: int
) -> int:
    """Un paramètre de requête entier, en chiffres ASCII seulement.

    ``int("٣")`` vaut 3 et ``int(" 3")`` aussi : un filtre ``isdigit`` laisse
    passer l'un, ``int`` l'autre. Un paramètre répété est refusé plutôt que
    de choisir en silence lequel croire.
    """
    valeurs = request.query_params.getlist(nom)
    if not valeurs:
        return defaut
    if len(valeurs) > 1 or not re.fullmatch(r"[0-9]{1,19}", valeurs[0]):
        raise invalide(nom)
    valeur = int(valeurs[0])
    if not minimum <= valeur <= maximum:
        raise invalide(nom)
    return valeur


# ----------------------------------------------------------------------
# kdfVersion (§2.3)
# ----------------------------------------------------------------------

# Le serveur n'étire rien (aucun Argon2id sur le VPS, §2.3), mais il refuse
# de STOCKER une version que le client refuserait de lire : un coffre
# enregistré en ``kdfVersion`` 0 rendrait le compte inouvrable, et le client
# y verrait un déclassement (``kdfDowngrade``) sans pouvoir s'en sortir.
VERSIONS_KDF_ACCEPTEES = frozenset({1})
KDF_VERSION_DEFAUT = 1


def kdf_version(
    corps: dict[str, Any], nom: str = "kdfVersion", chemin: str = ""
) -> int:
    valeur = corps.get(nom)
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise invalide(chemin + nom)
    if valeur not in VERSIONS_KDF_ACCEPTEES:
        raise ErreurRequete(400, "kdfDowngrade", champ=chemin + nom)
    return valeur


# ----------------------------------------------------------------------
# Jeton de session (§3.7)
# ----------------------------------------------------------------------

PREFIXE_SESSION = "dps1_"
_JETON_SESSION = re.compile(r"dps1_[A-Za-z0-9_-]{43}")


def jeton_bearer(request: Request) -> str | None:
    """Le jeton ``Authorization: Bearer dps1_…``, ou ``None`` s'il manque.

    Un en-tête présent mais mal formé vaut ``None`` aussi : la route rend le
    même 401 que pour un jeton inconnu, sans dire ce qui clochait.
    """
    en_tete = request.headers.get("authorization")
    if not en_tete:
        return None
    schema, _, jeton = en_tete.partition(" ")
    if schema.lower() != "bearer" or not _JETON_SESSION.fullmatch(jeton.strip()):
        return None
    return jeton.strip()
