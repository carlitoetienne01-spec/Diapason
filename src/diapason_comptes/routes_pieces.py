"""Routes des pièces : réclamer, déposer, relire, marquer orpheline.

Conception : ``docs/development/compte-chiffre.md`` §3.4, §4.3 et §4.7.

Une pièce est une image détachée d'une conversation, chiffrée sur
l'appareil (DPE1 type 02) et nommée par ``pieceId``, un HMAC du contenu sous
une clé d'époque (§2.6). Le serveur ne sait ni ce qu'elle montre, ni quel
objet la référence : il ne peut donc pas décider seul qu'une pièce ne sert
plus. Ce sont les appareils qui la marquent orpheline, et c'est la
réclamation qui la protège.

La course que ce module ferme (revue protocole) : l'appareil A a tiré
jusqu'à ``serverSeq = S`` et ne voit plus aucun objet qui référence la
pièce P ; pendant ce temps, B la réclame (``/pieces/missing``) pour un objet
qu'il va pousser. Si A marque P orpheline après coup, l'image de B est
purgée 30 jours plus tard. D'où :

- toute réclamation consomme un ``seq`` du compte et le range dans
  ``reclame_seq`` — elle devient un événement de la suite que A tire ;
- ``DELETE`` porte ``asOfSeq = S`` et est refusé (409 ``reclaimed``) si
  ``reclame_seq > S`` : A n'a pas vu la réclamation, il n'a pas le droit de
  conclure.

Ce qui reste, et que le §4.7 rattrape : une réclamation VUE par A, dont
l'objet n'est poussé qu'après la décision de A. La pièce n'est purgée
qu'après 30 jours d'orphelinat, et chaque appareil réclame une fois par
jour toutes les pièces qu'il référence : une réclamation ranime.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from diapason_comptes.base import ecriture, jour
from diapason_comptes.routes_identite import contexte, exiger_place
from diapason_comptes.routes_synchro import (
    avancer_seq,
    compte_de_session,
    lire_corps,
    passage_lourd,
    purger_retenues,
    session_d_abord,
)
from diapason_comptes.validation import (
    ENTIER_MAX,
    PLANCHER_PIECE,
    TYPE_PIECE,
    ErreurRequete,
    corps_json,
    entier,
    epoque_enveloppe_donnees,
    identifiant_opaque,
    invalide,
)

routeur = APIRouter(prefix="/api/v1")

MIO = 1024 * 1024

# §3.5 (D10) : une pièce ≤ 10 Mio, 5 000 pièces par compte. 10 Mio couvrent
# une photo de téléphone en pleine définition ; nginx accorde 11 Mio à
# ``/api/v1/pieces/`` (§3.9), la marge d'un en-tête.
PIECE_MAX_OCTETS = 10 * MIO
PIECES_MAX = 5_000
# Une réclamation porte les pièces d'un lot de 50 objets (§4.3) : 1 000
# identifiants de 22 caractères tiennent dans les 64 Kio d'un corps JSON,
# et bornent la requête ``IN (…)`` que SQLite prépare.
RECLAMATION_MAX = 1_000


def _identifiant(valeur: str) -> str:
    identifiant = identifiant_opaque(valeur)
    if identifiant is None:
        raise invalide("pieceId")
    return identifiant


def _as_of_seq(corps: dict[str, Any], compte_seq: int) -> int:
    """``asOfSeq`` : le ``serverSeq`` jusqu'où l'appareil a tiré.

    Au-delà du ``seq`` du compte, l'appareil a vu un état que le serveur n'a
    plus (retour arrière de la machine, §3.10) : lui laisser marquer
    orpheline une pièce réclamée DEPUIS la restauration, sous un ``seq``
    plus petit que le sien, c'était lui laisser effacer l'image d'un autre.
    409 ``serverBehind`` ; l'appareil remet son curseur à zéro (§4.3).
    """
    as_of = entier(corps, "asOfSeq", maximum=ENTIER_MAX)
    if as_of > compte_seq:
        raise ErreurRequete(409, "serverBehind")
    return as_of


# ----------------------------------------------------------------------
# Réclamer
# ----------------------------------------------------------------------


@routeur.post("/pieces/missing")
def pieces_missing(request: Request, corps: dict = Depends(corps_json)) -> JSONResponse:
    """Réclame chaque pièce listée qui existe, et rend celles à envoyer.

    Une pièce orpheline est réclamée aussi (``orpheline_jour = NULL``) ET
    comptée comme manquante (§3.4) : l'appareil la renvoie, et son ``PUT``
    la confirme vivante. Le ``seq`` n'avance que si une pièce existante a
    été réclamée : une liste d'absentes ne change rien au serveur.
    """
    ctx = contexte(request)
    brut = corps.get("pieceIds")
    if not isinstance(brut, list) or len(brut) > RECLAMATION_MAX:
        raise invalide("pieceIds")
    identifiants: list[str] = []
    for i, valeur in enumerate(brut):
        identifiant = identifiant_opaque(valeur)
        if identifiant is None:
            raise invalide(f"pieceIds.{i}")
        if identifiant not in identifiants:
            identifiants.append(identifiant)
    maintenant = ctx.horloge()
    with ctx.base.transaction() as conn:
        compte = compte_de_session(ctx, conn, request, maintenant)
        _as_of_seq(corps, compte.seq)
        existantes: dict[str, int | None] = {}
        if identifiants:
            trous = ", ".join("?" for _ in identifiants)
            existantes = dict(
                conn.execute(
                    "SELECT piece_id, orpheline_jour FROM pieces "
                    f"WHERE compte_id = ? AND piece_id IN ({trous})",
                    (compte.id, *identifiants),
                ).fetchall()
            )
        manquantes = [
            i for i in identifiants if i not in existantes or existantes[i] is not None
        ]
        if existantes:
            seq = avancer_seq(conn, compte.id)
            trous = ", ".join("?" for _ in existantes)
            conn.execute(
                "UPDATE pieces SET reclame_seq = ?, orpheline_jour = NULL "
                f"WHERE compte_id = ? AND piece_id IN ({trous})",
                (seq, compte.id, *existantes),
            )
            ecriture(conn)
    return JSONResponse({"missing": manquantes})


# ----------------------------------------------------------------------
# Déposer, relire
# ----------------------------------------------------------------------


@routeur.put("/pieces/{piece_id}")
def pieces_put(piece_id: str, request: Request) -> JSONResponse:
    """``application/octet-stream`` → 201 (créée) ou 200 (déjà là).

    IMMUABLE : une pièce existante n'est jamais remplacée. Le même
    ``pieceId`` désigne le même contenu dans la même époque (§2.6) ; un
    second envoi, chiffré sous un autre sel, ne dirait rien de plus. Il la
    réclame et la ranime, c'est tout.
    """
    ctx = contexte(request)
    identifiant = _identifiant(piece_id)
    session_d_abord(ctx, request)
    with passage_lourd(ctx):
        exiger_place(ctx)
        blob = lire_corps(request, PIECE_MAX_OCTETS)
        epoque = epoque_enveloppe_donnees(
            blob, TYPE_PIECE, plancher=PLANCHER_PIECE, maximum=PIECE_MAX_OCTETS
        )
        if epoque is None:
            raise ErreurRequete(422, "invalidEnvelope")
        maintenant = ctx.horloge()
        with ctx.base.transaction() as conn:
            compte = compte_de_session(ctx, conn, request, maintenant)
            # Après une rotation, une image se renvoie sous la DEK neuve
            # (§4.7) : une pièce de l'ancienne époque ne s'écrit plus.
            if epoque != compte.epoque_cle:
                raise ErreurRequete(409, "keyEpochChanged")
            # La purge AVANT de regarder si la pièce existe. Jusqu'au
            # 24/09/2026, une orpheline échue était vue présente, puis purgée
            # par cette même transaction, et le PUT répondait 200 « déjà
            # là » : le GET suivant rendait 404 et l'appareil la croyait
            # déposée (§100). Purgée d'abord, elle est recréée en 201.
            octets = compte.octets - purger_retenues(conn, compte.id, maintenant)
            existe = conn.execute(
                "SELECT 1 FROM pieces WHERE compte_id = ? AND piece_id = ?",
                (compte.id, identifiant),
            ).fetchone()
            if existe is None:
                nombre = conn.execute(
                    "SELECT COUNT(*) FROM pieces WHERE compte_id = ?", (compte.id,)
                ).fetchone()[0]
                if nombre >= PIECES_MAX or octets + len(blob) > compte.quota_octets:
                    raise ErreurRequete(507, "quotaExceeded")
            seq = avancer_seq(conn, compte.id)
            if existe is None:
                conn.execute(
                    "INSERT INTO pieces (compte_id, piece_id, blob, reclame_seq) "
                    "VALUES (?, ?, ?, ?)",
                    (compte.id, identifiant, blob, seq),
                )
                octets += len(blob)
            else:
                conn.execute(
                    "UPDATE pieces SET reclame_seq = ?, orpheline_jour = NULL "
                    "WHERE compte_id = ? AND piece_id = ?",
                    (seq, compte.id, identifiant),
                )
            conn.execute(
                "UPDATE comptes SET octets = ? WHERE id = ?", (octets, compte.id)
            )
            ecriture(conn)
    return JSONResponse({}, status_code=201 if existe is None else 200)


@routeur.get("/pieces/{piece_id}")
def pieces_get(piece_id: str, request: Request) -> Response:
    """Les octets, orpheline comprise : marquée n'est pas effacée, et un
    appareil qui la relit dans les 30 jours la réclamera."""
    ctx = contexte(request)
    identifiant = _identifiant(piece_id)
    session_d_abord(ctx, request)
    with passage_lourd(ctx):
        maintenant = ctx.horloge()
        with ctx.base.transaction() as conn:
            compte = compte_de_session(ctx, conn, request, maintenant)
            ligne = conn.execute(
                "SELECT blob FROM pieces WHERE compte_id = ? AND piece_id = ?",
                (compte.id, identifiant),
            ).fetchone()
        if ligne is None:
            raise ErreurRequete(404, "notFound")
        return Response(content=ligne[0], media_type="application/octet-stream")


# ----------------------------------------------------------------------
# Marquer orpheline
# ----------------------------------------------------------------------


@routeur.delete("/pieces/{piece_id}", status_code=204)
def pieces_delete(
    piece_id: str, request: Request, corps: dict = Depends(corps_json)
) -> Response:
    """Marque orpheline si ``reclame_seq <= asOfSeq`` ; purge à +30 jours.

    Rien n'est effacé ici : une session volée ne peut que marquer, et la
    réclamation quotidienne des appareils ranime ce qu'elle a marqué à tort
    (§3.7). Marquer une orpheline de nouveau ne repousse pas sa purge.
    """
    ctx = contexte(request)
    identifiant = _identifiant(piece_id)
    maintenant = ctx.horloge()
    with ctx.base.transaction() as conn:
        compte = compte_de_session(ctx, conn, request, maintenant)
        as_of = _as_of_seq(corps, compte.seq)
        ligne = conn.execute(
            "SELECT reclame_seq, orpheline_jour FROM pieces "
            "WHERE compte_id = ? AND piece_id = ?",
            (compte.id, identifiant),
        ).fetchone()
        if ligne is None:
            raise ErreurRequete(404, "notFound")
        if ligne[0] > as_of:
            raise ErreurRequete(409, "reclaimed")
        if ligne[1] is None:
            conn.execute(
                "UPDATE pieces SET orpheline_jour = ? WHERE compte_id = ? "
                "AND piece_id = ?",
                (jour(maintenant), compte.id, identifiant),
            )
            ecriture(conn)
    return Response(status_code=204)
