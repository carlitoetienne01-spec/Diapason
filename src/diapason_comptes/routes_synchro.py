"""Routes de la synchronisation : tirer, pousser, relire la version remplacée.

Conception : ``docs/development/compte-chiffre.md`` §3.4, §4.3 à §4.6.

Le VPS est un classeur AVEUGLE. Il ne déchiffre rien, ne fusionne rien : il
range des blobs DPE1 sous un ``objectId`` opaque, les numérote par un
``seq`` propre au compte, et fait un comparer-et-échanger sur ``rev``. La
fusion se fait sur les appareils (``fusionner_conversations`` est une
jointure, §4.1) ; le serveur n'a qu'à garantir qu'aucune écriture n'en
écrase une autre qu'elle n'a pas vue.

Ce qu'il garde de plus : la version REMPLACÉE de chaque objet, 30 jours.
Un jeton de session volé peut écraser un objet par du bruit (A9) ; un
appareil qui n'en a pas de copie locale relit alors la version précédente
(``GET /sync/previous``) et répare (§4.6).

Chaque réponse porte ``meta`` (§3.4) : une rotation faite ailleurs, une
réinitialisation en attente, une restauration du serveur se voient au
premier tirage, sans appel de plus. Les refus 409 le portent aussi.

Toutes les routes sont des ``def`` : SQLite, base64 et JSON de plusieurs
mégaoctets n'ont rien à faire sur la boucle d'événements (CLAUDE.md §5).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import anyio.from_thread
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from diapason_comptes.base import Compte, ecriture, generation, jour, lire_compte
from diapason_comptes.limites import ATTENTE_PASSAGE_S
from diapason_comptes.routes_identite import contexte, exiger_place, session_requise
from diapason_comptes.validation import (
    ENTIER_MAX,
    EPOQUE_MAX,
    PLANCHER_OBJET,
    TYPE_OBJET,
    ErreurRequete,
    b64url,
    de_b64url,
    entier,
    entier_de_requete,
    epoque_enveloppe_donnees,
    identifiant_opaque,
    invalide,
    lire_json,
    lire_octets_bornes,
)

if TYPE_CHECKING:
    from diapason_comptes.app import Contexte

routeur = APIRouter(prefix="/api/v1")

MIO = 1024 * 1024

# §3.5 (D10) : un objet ≤ 4 Mio, 50 000 objets par compte. Une conversation
# illustrée pèse ~115 Ko une fois ses images passées en pièces (§4.7) : 4 Mio
# couvrent une conversation de texte de plusieurs années ; au-delà, c'est
# qu'une image n'a pas été détachée, et le serveur ne doit pas le cacher.
OBJET_MAX_OCTETS = 4 * MIO
OBJETS_MAX = 50_000

# §3.4 : au plus 50 éléments et 8 Mio par poussée, 200 éléments et 8 Mio par
# page tirée (§4.3). 8 Mio de blobs font ~11 Mio de base64 : le corps d'une
# poussée est borné à 12 Mio, la valeur que nginx accorde à
# ``/api/v1/sync/`` (§3.9). Au-delà, il ne passerait de toute façon pas.
POUSSEE_ELEMENTS_MAX = 50
POUSSEE_OCTETS_MAX = 8 * MIO
CORPS_POUSSEE_MAX = 12 * MIO
PAGE_ELEMENTS_MAX = 200
PAGE_OCTETS_MAX = 8 * MIO
# Un conflit renvoie la version courante, jusqu'à 4 Mio chacune. Cinquante
# conflits sur des objets de 4 Mio faisaient une réponse de 200 Mio
# (270 Mio en base64), assez pour que systemd tue le service à
# ``MemoryMax=300M`` (24/09/2026). Passé 8 Mio de versions courantes dans
# une réponse, les éléments suivants ne sont pas examinés : ``deferred``,
# à renvoyer tels quels dans la poussée suivante.
CONFLITS_OCTETS_MAX = 8 * MIO

# §3.4 et §4.6 : la version remplacée est gardée 30 jours, puis purgée à la
# poussée suivante du compte (§3.1, entretien sans cron). Trente jours
# laissent à un appareil resté éteint un mois le temps de revenir réparer
# un objet écrasé par un jeton volé ; au-delà, garder chaque version
# remplacée doublerait la place de tout compte actif.
RETENUE_JOURS = 30

# Les issues d'un élément poussé (``results[i].status``), alignées sur
# ``items[i]``.
STOCKE = "stored"
CONFLIT = "conflict"
REFUSE = "rejected"
DIFFERE = "deferred"


# ----------------------------------------------------------------------
# Outils partagés avec ``routes_pieces``
# ----------------------------------------------------------------------


@contextmanager
def passage_lourd(ctx: Contexte) -> Iterator[None]:
    """Un des passages du portillon, ou 503 ``serverBusy`` tout de suite.

    Toujours APRÈS :func:`session_d_abord`. Jusqu'au 24/09/2026 le passage
    se prenait avant : pendant qu'une poussée de 8 Mio tenait la base,
    quatre appels munis d'un faux jeton prenaient les quatre passages en
    attendant le verrou, et le titulaire recevait 503 ``serverBusy``.
    """
    if not ctx.portillon.entrer():
        raise ErreurRequete(503, "serverBusy", retry_after_s=ATTENTE_PASSAGE_S)
    try:
        yield
    finally:
        ctx.portillon.sortir()


def session_d_abord(ctx: Contexte, request: Request) -> str:
    """401 AVANT le portillon et avant tout corps de plusieurs mégaoctets ;
    rend l'identifiant du compte.

    La session est revérifiée dans la transaction qui écrit : elle a pu
    tomber (``vault/commit`` ailleurs) pendant la lecture du corps.
    """
    maintenant = ctx.horloge()
    with ctx.base.transaction() as conn:
        return session_requise(ctx, conn, request, maintenant).compte_id


@contextmanager
def meta_sur_les_refus(ctx: Contexte, compte_id: str) -> Iterator[None]:
    """Joint ``meta`` à tout refus levé une fois la session établie.

    §3.4 : ``meta`` est porté par CHAQUE réponse de ``/sync/*``. Jusqu'au
    24/09/2026, un 507 ``serverFull``, un 413 et un 422 étaient levés avant
    la transaction et partaient sans lui. Restent sans ``meta`` le 401 (le
    compte a pu partir entre-temps) et le 503 ``serverBusy``, levé avant ce
    bloc parce qu'il ne doit pas attendre la base qu'une poussée tient.
    """
    try:
        yield
    except ErreurRequete as refus:
        if refus.extra is None and refus.statut != 401:
            with ctx.base.lecture() as conn:
                compte = lire_compte(conn, compte_id)
                if compte is not None:
                    refus.extra = {"meta": meta(conn, compte)}
        raise


def lire_corps(request: Request, maximum: int) -> bytes:
    """Le corps brut, lu DEPUIS la route ``def``.

    Une dépendance ``async`` l'aurait lu avant la route, donc avant le
    portillon et avant la vérification de session : n'importe qui aurait pu
    faire tenir 12 Mio en mémoire au service, quarante fois à la fois.
    ``from_thread.run`` rend la lecture à la boucle, et ce fil attend.
    """
    return anyio.from_thread.run(lire_octets_bornes, request, maximum)


def compte_de_session(
    ctx: Contexte, conn: sqlite3.Connection, request: Request, maintenant: int
) -> Compte:
    session = session_requise(ctx, conn, request, maintenant)
    compte = lire_compte(conn, session.compte_id)
    assert compte is not None  # la session part avec le compte (CASCADE)
    return compte


def meta(conn: sqlite3.Connection, compte: Compte) -> dict[str, Any]:
    """Le bloc ``meta`` de chaque réponse de ``/sync/*`` (§3.4)."""
    return {
        "generation": generation(conn),
        "incarnation": compte.incarnation,
        "keyEpoch": compte.epoque_cle,
        "vaultVersion": compte.version_coffre,
        "keyringVersion": compte.version_trousseau,
        "serverSeq": compte.seq,
        "pendingResetAt": compte.reinitialisation_attendue,
    }


def refus_avec_meta(
    conn: sqlite3.Connection, compte: Compte, statut: int, code: str
) -> ErreurRequete:
    return ErreurRequete(statut, code, extra={"meta": meta(conn, compte)})


def avancer_seq(conn: sqlite3.Connection, compte_id: str) -> int:
    """Le ``seq`` suivant du compte, écrit. Monotone : rien ne le fait
    reculer, pas même ``reset/complete`` — un appareil qui verrait ``seq``
    redescendre conclurait à une restauration du serveur (§3.10)."""
    conn.execute("UPDATE comptes SET seq = seq + 1 WHERE id = ?", (compte_id,))
    return conn.execute(
        "SELECT seq FROM comptes WHERE id = ?", (compte_id,)
    ).fetchone()[0]


def purger_retenues(conn: sqlite3.Connection, compte_id: str, maintenant: int) -> int:
    """Versions précédentes et pièces orphelines de plus de 30 jours (§3.1).

    Rend les octets libérés ; l'appelant les retire de ``comptes.octets``.
    Jamais par un minuteur : le service n'en a aucun, et un effacement qui
    se déclenche seul est ce que le §3.6 refuse.
    """
    limite = jour(maintenant) - RETENUE_JOURS
    precedents = conn.execute(
        "SELECT COALESCE(SUM(length(blob_precedent)), 0) FROM objets "
        "WHERE compte_id = ? AND precedent_jour < ?",
        (compte_id, limite),
    ).fetchone()[0]
    if precedents:
        conn.execute(
            "UPDATE objets SET blob_precedent = NULL, rev_precedente = NULL, "
            "precedent_jour = NULL WHERE compte_id = ? AND precedent_jour < ?",
            (compte_id, limite),
        )
    orphelines = conn.execute(
        "SELECT COALESCE(SUM(length(blob)), 0) FROM pieces "
        "WHERE compte_id = ? AND orpheline_jour < ?",
        (compte_id, limite),
    ).fetchone()[0]
    if orphelines:
        conn.execute(
            "DELETE FROM pieces WHERE compte_id = ? AND orpheline_jour < ?",
            (compte_id, limite),
        )
    return precedents + orphelines


# ----------------------------------------------------------------------
# Tirer
# ----------------------------------------------------------------------


@routeur.get("/sync/changes")
def sync_changes(request: Request) -> JSONResponse:
    """Les objets de ``seq > since``, dans l'ordre de ``seq``.

    ``until`` est le curseur à reprendre : le ``seq`` du dernier élément
    rendu s'il en reste, sinon le ``serverSeq`` du compte — des ``seq`` n'ont
    aucun objet (une réclamation de pièces en consomme un, voir
    ``routes_pieces``), et un curseur qui s'arrêterait au dernier objet
    redemanderait éternellement la même page vide.
    """
    ctx = contexte(request)
    compte_id = session_d_abord(ctx, request)
    with passage_lourd(ctx), meta_sur_les_refus(ctx, compte_id):
        depuis = entier_de_requete(
            request, "since", defaut=0, minimum=0, maximum=ENTIER_MAX
        )
        limite = entier_de_requete(
            request,
            "limit",
            defaut=PAGE_ELEMENTS_MAX,
            minimum=1,
            maximum=PAGE_ELEMENTS_MAX,
        )
        maintenant = ctx.horloge()
        with ctx.base.transaction() as conn:
            compte = compte_de_session(ctx, conn, request, maintenant)
            # Les tailles d'abord, les blobs ensuite : 200 lignes de 4 Mio
            # lues d'un coup faisaient 800 Mio avant la moindre coupe.
            candidats = conn.execute(
                "SELECT objet_id, rev, seq, length(blob) FROM objets "
                "WHERE compte_id = ? AND seq > ? ORDER BY seq LIMIT ?",
                (compte.id, depuis, limite + 1),
            ).fetchall()
            retenus = []
            total = 0
            for objet_id, rev, seq, taille in candidats[:limite]:
                # Toujours au moins un élément : un objet de 4 Mio doit
                # passer même seul, sinon le curseur ne bouge plus.
                if retenus and total + taille > PAGE_OCTETS_MAX:
                    break
                retenus.append((objet_id, rev, seq))
                total += taille
            encore = len(retenus) < len(candidats)
            elements = []
            for objet_id, rev, seq in retenus:
                (blob,) = conn.execute(
                    "SELECT blob FROM objets WHERE compte_id = ? AND objet_id = ?",
                    (compte.id, objet_id),
                ).fetchone()
                elements.append(
                    {"objectId": objet_id, "rev": rev, "seq": seq, "blob": b64url(blob)}
                )
            jusqu_a = retenus[-1][2] if encore else compte.seq
            corps = {
                "meta": meta(conn, compte),
                "items": elements,
                "until": jusqu_a,
                "hasMore": encore,
            }
        return JSONResponse(corps)


# ----------------------------------------------------------------------
# Pousser
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Element:
    objet_id: str
    base_rev: int
    blob: bytes


@dataclass(frozen=True)
class _Poussee:
    incarnation: int
    epoque: int
    elements: list[_Element]


def _lire_poussee(corps: dict[str, Any]) -> _Poussee:
    incarnation = entier(corps, "incarnation", minimum=1)
    epoque = entier(corps, "keyEpoch", minimum=1, maximum=EPOQUE_MAX)
    items = corps.get("items")
    if not isinstance(items, list) or len(items) > POUSSEE_ELEMENTS_MAX:
        raise invalide("items")
    elements = []
    total = 0
    for i, item in enumerate(items):
        chemin = f"items.{i}."
        if not isinstance(item, dict):
            raise invalide(f"items.{i}")
        objet_id = identifiant_opaque(item.get("objectId"))
        if objet_id is None:
            raise invalide(chemin + "objectId")
        # ``ENTIER_MAX − 1`` : ``rev = baseRev + 1`` doit tenir dans SQLite.
        base_rev = entier(item, "baseRev", maximum=ENTIER_MAX - 1, chemin=chemin)
        blob = de_b64url(item.get("blob"))
        if not blob:
            raise invalide(chemin + "blob")
        total += len(blob)
        if total > POUSSEE_OCTETS_MAX:
            raise ErreurRequete(413, "payloadTooLarge")
        elements.append(_Element(objet_id=objet_id, base_rev=base_rev, blob=blob))
    return _Poussee(incarnation=incarnation, epoque=epoque, elements=elements)


def _refus(code: str) -> dict[str, Any]:
    return {"status": REFUSE, "code": code}


@routeur.post("/sync/push")
def sync_push(request: Request) -> JSONResponse:
    """Comparer-et-échanger sur ``rev``, élément par élément (§3.4, §4.5).

    Un objet absent a pour ``rev`` 0. Un ``baseRev`` qui ne correspond pas
    rend TOUJOURS un conflit AVEC ``current`` (``null`` si l'objet n'existe
    pas), jamais une erreur : le client ingère ``current``, fusionne et
    rejoue. Converger demande au plus deux allers-retours une fois les
    écritures arrêtées.

    Refus du lot entier : 409 ``incarnationChanged`` (une réinitialisation a
    eu lieu, ce qui est scellé sous l'ancienne incarnation ne vaut plus
    rien) et 409 ``keyEpochChanged`` (une rotation a eu lieu : toute
    écriture neuve doit être scellée sous la DEK de l'époque courante,
    §2.8).
    """
    ctx = contexte(request)
    compte_id = session_d_abord(ctx, request)
    with passage_lourd(ctx), meta_sur_les_refus(ctx, compte_id):
        exiger_place(ctx)
        poussee = _lire_poussee(
            lire_json(lire_corps(request, CORPS_POUSSEE_MAX), maximum=CORPS_POUSSEE_MAX)
        )
        maintenant = ctx.horloge()
        with ctx.base.transaction() as conn:
            compte = compte_de_session(ctx, conn, request, maintenant)
            if poussee.incarnation != compte.incarnation:
                raise refus_avec_meta(conn, compte, 409, "incarnationChanged")
            if poussee.epoque != compte.epoque_cle:
                raise refus_avec_meta(conn, compte, 409, "keyEpochChanged")
            resultats = _appliquer(conn, compte, poussee, maintenant)
            corps = {
                "meta": meta(conn, lire_compte(conn, compte.id)),
                "results": resultats,
            }
        return JSONResponse(corps)


def _appliquer(
    conn: sqlite3.Connection, compte: Compte, poussee: _Poussee, maintenant: int
) -> list[dict[str, Any]]:
    octets = compte.octets - purger_retenues(conn, compte.id, maintenant)
    nombre = conn.execute(
        "SELECT COUNT(*) FROM objets WHERE compte_id = ?", (compte.id,)
    ).fetchone()[0]
    seq = compte.seq
    resultats: list[dict[str, Any]] = []
    octets_conflits = 0
    differer = False
    for element in poussee.elements:
        if differer:
            resultats.append({"status": DIFFERE})
            continue
        # La forme d'abord : un blob qui n'est pas un objet DPE1 de l'époque
        # courante ne vient pas d'un client à jour, conflit ou non.
        if len(element.blob) > OBJET_MAX_OCTETS:
            resultats.append(_refus("objectTooLarge"))
            continue
        epoque = epoque_enveloppe_donnees(
            element.blob, TYPE_OBJET, plancher=PLANCHER_OBJET, maximum=OBJET_MAX_OCTETS
        )
        if epoque != compte.epoque_cle:
            resultats.append(_refus("invalidEnvelope"))
            continue
        ligne = conn.execute(
            "SELECT rev, seq, length(blob), length(blob_precedent) FROM objets "
            "WHERE compte_id = ? AND objet_id = ?",
            (compte.id, element.objet_id),
        ).fetchone()
        rev_courante = 0 if ligne is None else ligne[0]
        if element.base_rev != rev_courante:
            if ligne is None:
                resultats.append({"status": CONFLIT, "current": None})
                continue
            if octets_conflits and octets_conflits + ligne[2] > CONFLITS_OCTETS_MAX:
                differer = True
                resultats.append({"status": DIFFERE})
                continue
            (courant,) = conn.execute(
                "SELECT blob FROM objets WHERE compte_id = ? AND objet_id = ?",
                (compte.id, element.objet_id),
            ).fetchone()
            octets_conflits += len(courant)
            resultats.append(
                {
                    "status": CONFLIT,
                    "current": {
                        "rev": ligne[0],
                        "seq": ligne[1],
                        "blob": b64url(courant),
                    },
                }
            )
            continue
        # La version courante devient la précédente, la précédente s'en va :
        # la place occupée varie de ``nouveau − précédent``.
        variation = len(element.blob) - (0 if ligne is None else ligne[3] or 0)
        if ligne is None and nombre >= OBJETS_MAX:
            resultats.append(_refus("quotaExceeded"))
            continue
        # Le quota ne refuse que ce qui fait GROSSIR la version courante.
        # Jusqu'au 24/09/2026, au quota, une tombale était refusée : elle
        # remplaçait 200 Kio par 1 Kio, mais les 200 Kio restaient comptés
        # 30 jours comme précédente, et le compte « grossissait » de 1 Kio.
        # La suppression ne se synchronisait pas, et ``quotaExceeded`` ne se
        # levait qu'après la purge, un mois plus tard. Le dépassement est
        # borné : une suite d'écritures qui ne grossissent pas garde au plus,
        # par objet, sa plus grande version courante deux fois.
        grossit = ligne is None or len(element.blob) > ligne[2]
        if grossit and octets + variation > compte.quota_octets:
            resultats.append(_refus("quotaExceeded"))
            continue
        seq += 1
        rev = rev_courante + 1
        if ligne is None:
            conn.execute(
                "INSERT INTO objets (compte_id, objet_id, rev, seq, blob) "
                "VALUES (?, ?, ?, ?, ?)",
                (compte.id, element.objet_id, rev, seq, element.blob),
            )
            nombre += 1
        else:
            # Dans un UPDATE, chaque expression lit la ligne AVANT : ``blob``
            # et ``rev`` à droite sont l'ancienne version.
            conn.execute(
                "UPDATE objets SET blob_precedent = blob, rev_precedente = rev, "
                "precedent_jour = ?, blob = ?, rev = ?, seq = ? "
                "WHERE compte_id = ? AND objet_id = ?",
                (
                    jour(maintenant),
                    element.blob,
                    rev,
                    seq,
                    compte.id,
                    element.objet_id,
                ),
            )
        octets += variation
        resultats.append({"status": STOCKE, "rev": rev, "seq": seq})
    if seq != compte.seq or octets != compte.octets:
        conn.execute(
            "UPDATE comptes SET seq = ?, octets = ? WHERE id = ?",
            (seq, octets, compte.id),
        )
    if seq != compte.seq:
        ecriture(conn)
    return resultats


# ----------------------------------------------------------------------
# Version remplacée
# ----------------------------------------------------------------------


@routeur.get("/sync/previous/{object_id}")
def sync_previous(object_id: str, request: Request) -> JSONResponse:
    """La version remplacée, 30 jours (§4.6, autoréparation).

    Au-delà de 30 jours, 404 même si la purge n'est pas encore passée : la
    purge attend la poussée suivante du compte, et une réponse qui
    dépendrait de ce hasard ne serait pas une promesse.
    """
    ctx = contexte(request)
    compte_id = session_d_abord(ctx, request)
    with passage_lourd(ctx), meta_sur_les_refus(ctx, compte_id):
        if identifiant_opaque(object_id) is None:
            raise invalide("objectId")
        maintenant = ctx.horloge()
        with ctx.base.transaction() as conn:
            compte = compte_de_session(ctx, conn, request, maintenant)
            ligne = conn.execute(
                "SELECT rev_precedente, blob_precedent, precedent_jour FROM objets "
                "WHERE compte_id = ? AND objet_id = ?",
                (compte.id, object_id),
            ).fetchone()
            if (
                ligne is None
                or ligne[1] is None
                or jour(maintenant) - ligne[2] > RETENUE_JOURS
            ):
                raise refus_avec_meta(conn, compte, 404, "notFound")
            corps = {
                "meta": meta(conn, compte),
                "rev": ligne[0],
                "blob": b64url(ligne[1]),
            }
        return JSONResponse(corps)
