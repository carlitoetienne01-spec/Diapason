"""Le moteur de synchronisation : un second client du magasin des conversations.

Conception : ``docs/development/compte-chiffre.md`` §4 (tout), §4.12 (face à
un VPS hostile), §2.11 bis (quarantaine d'époque) et §6 bis (ce que le
moteur DOIT faire d'après le service : ``deferred``, ``serverBusy``,
``serverBehind``, ``until``, ``generation`` avant ``serverSeq``).

Le cycle (§4.3), à la lettre sauf là où c'est dit :

0. **portée** — ``(compte, incarnation)`` changé : les tables de portée
   partent, le curseur revient à 0, tout ce qui est local repasse dans
   ``sortants`` ; les planchers de suppression d'un même compte restent ;
1. **export** — les écritures locales depuis le curseur d'export entrent
   dans ``sortants`` ; les suppressions relèvent leur plancher ;
2. **garde** — verrouillé, état posé par le serveur ou consentement
   manquant : fin, AUCUNE requête ;
3. **tirage** — jusqu'à ``until`` avec ``hasMore`` faux, ``meta`` jugé à
   chaque page, le curseur posé à ``until`` (jamais au ``seq`` du dernier
   élément : des ``seq`` n'ont pas d'objet) ;
4. **poussée** — par lots de 50 / 8 Mio, comparer-et-échanger sur ``rev``,
   trois rejeux au plus par objet et par cycle ; les PIÈCES d'un lot
   (``/pieces/missing`` puis ``PUT``) partent avant ses objets (étape 11) ;
   entre tirage et poussée, la réclamation quotidienne des pièces, et après
   la poussée, le marquage des orphelines au ``serverSeq`` du tirage ;
5. **conclusion** — ``upToDate`` SEULEMENT sur un ``serverSeq`` rendu par
   le VPS, une file sortante vide, rien à reprendre, et la portée courante.

**Pièces (étape 11, §4.7).** Le moteur ne manipule que la forme ATTACHÉE
d'un clair — celle du magasin, indépendante de l'époque : il RATTACHE un
blob tiré avant de l'empreindre (les images déjà ici d'abord, le VPS
ensuite, et seulement pour une version neuve), et ne DÉTACHE qu'au
scellement, sous l'époque courante. Une pièce en 404 laisse un « trou »
(``pieces_manquantes``) que le moteur rend au clair avant toute empreinte ou
poussée : un appareil dégradé n'efface jamais l'image du serveur.

**Endormi tant qu'aucun compte n'est déverrouillé** (exigence du
24/09/2026). Tant que les comptes sont fermés (``COMPTES_OUVERTS``), le
serveur local n'importe pas ce module : ``server/app.py`` ne construit le
moteur que pour un service aux comptes ouverts, et la tâche du lifespan
n'importe :func:`servir` qu'au premier réveil. Comptes ouverts, le module
est importé dès que le service du compte est construit (premier sondage de
``/v1/account/status``) — importé, pas actif : :func:`servir` attend sur un
``asyncio.Event`` sans délai tant que la serrure est fermée — pas de
sondage, pas de fil, pas de requête. (La docstring d'avant affirmait qu'il
n'était jamais importé sans compte ouvert ; c'était faux dès le premier
sondage du statut, contre-épreuve du 24/09/2026.)

Les planchers (§4.4) ne descendent jamais sur une valeur du serveur : ni une
``generation`` nouvelle, ni un ``serverSeq`` qui recule ne vident ``connus``
ou ``planchers_suppression``. La ``generation`` n'est authentifiée par
rien ; un VPS qui la change pour rejouer la version d'avant une suppression
trouve le plancher de suppression et la révision maximale en travers.

``connus.rev_max`` ne monte que sur une révision AUTHENTIFIÉE : celle d'un
blob ouvert (``r`` est dans l'AAD) ou celle que le VPS rend à notre propre
poussée. La révision d'un blob illisible ne sert que de base au prochain
comparer-et-échanger (``_indices_base``), le temps du cycle : une seule
réponse forgée avec ``rev = 10**12`` rendait sinon l'appareil sourd, pour
toujours, aux écritures des autres (contre-épreuve du 24/09/2026).

« Notre propre écriture » se reconnaît au CONTENU (l'empreinte du clair
déchiffré), jamais au ``seq`` : le ``seq`` vient du VPS, hors de l'AAD, et
un VPS qui rejouait une vieille version au ``seq`` déjà vu échappait à la
réaffirmation du §4.12 (même contre-épreuve).

**Quarantaine d'époque (§2.11 bis), datée dans l'ordre du serveur.** Le VPS
honnête refuse toute écriture d'une autre époque que la courante : un blob
d'époque ``e`` a donc été écrit AVANT la rotation vers ``e + 1``. Cet
appareil retient, pour chaque époque ``E`` de son trousseau, le
``serverSeq`` de la première réponse obtenue sous elle (``bornesEpoque``) ;
un blob d'époque ``e < E`` dont le ``seq`` dépasse la borne de l'époque qui
suit est une écriture postérieure à la rotation — un porteur d'une ancienne
DEK et un VPS complice. En dessous, c'est de l'historique, ingéré comme
tel : la règle d'avant (« révision neuve sous une ancienne époque »),
appliquée sans ordre, prenait pour une forgerie l'écriture qu'un autre
appareil avait confirmée juste avant la rotation, l'effaçait du serveur et
affichait « Synchronisé » (constat bloquant de la contre-épreuve).
**Reste** : le ``seq`` n'est pas authentifié. Un VPS complice qui étiquette
sa forgerie d'un ``seq`` sous la borne ne la fait passer que dans un tirage
depuis 0 (un appareil neuf, ou une ``generation`` changée) et, pour un objet
que l'appareil connaît, bute encore sur ``rev_max`` et l'empreinte.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import random
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any

from diapason.compte import pieces as module_pieces
from diapason.compte.cles import ErreurCompte
from diapason.compte.collections import COLLECTIONS_SYNCHRONISEES
from diapason.compte.collections.base import Collection
from diapason.compte.enveloppe import (
    ClairInvalide,
    EnveloppeIllisible,
    clair_tombale,
    encoder_clair,
    lire_en_tete,
)
from diapason.compte.etat import EtatLocal
from diapason.compte.serrure import CompteVerrouille, Ouverture
from diapason.compte.service import ETATS_POSES
from diapason.compte.transport import (
    CompteInactif,
    EnveloppeChiffree,
    ErreurServeur,
    ReponseServeur,
    ServeurInjoignable,
    SortieRefusee,
)
from diapason.compte.trousseau import EpoqueInconnue, ObjetPermute

logger = logging.getLogger(__name__)

__all__ = [
    "MoteurSynchro",
    "empreinte",
    "servir",
]

# ----------------------------------------------------------------------
# Rythmes (§4.3)
# ----------------------------------------------------------------------

# La vue pousse toutes les 1,2 s pendant un flux (``convSync.ts:67``) : une
# réponse de 60 s ferait 50 envois au VPS sans ce calme, deux plus le final
# avec lui.
_CALME_S = 5.0
# Une réponse longue n'attend pas indéfiniment son calme.
_POUSSEE_MAX_S = 30.0
# 30 s suffisent entre appareils quand quelqu'un regarde ; 5 min quand
# personne ne regarde restent légères pour 2 vCPU partagés avec Flashprime.
_TIRAGE_ACTIF_S = 30.0
_TIRAGE_REPOS_S = 300.0
_SONDAGE_RECENT_S = 60.0
# Repli après un échec : 30 s, doublé à chaque échec, plafonné à 15 min,
# ±20 % pour que les appareils d'un même compte ne frappent pas ensemble.
_REPLI_MIN_S = 30.0
_REPLI_MAX_S = 15 * 60.0
_GIGUE = 0.2

# §3.4 : 200 éléments par page tirée, 50 éléments et 8 Mio par poussée.
_PAGE_ELEMENTS = 200
_LOT_ELEMENTS = 50
_LOT_OCTETS = 8 * 1024 * 1024
# Un serveur hostile peut répondre ``hasMore`` à l'infini avec un ``until``
# qui avance d'un cran : 1 000 pages (200 000 objets, quatre fois le quota
# de 50 000) et le cycle rend la main ; le curseur, posé page par page,
# reprend au cycle suivant.
_PAGES_MAX = 1000
# §4.3 : on converge en deux allers-retours une fois les écritures arrêtées ;
# trois rejeux laissent une marge sans boucler sur un serveur qui répondrait
# « conflit » à tout.
_REJEUX_MAX = 3
# Au plus 20 passes de poussée par cycle : 1 000 objets en lots de 50. Un
# premier envoi plus gros se termine aux cycles suivants.
_PASSES_MAX = 20
# La purge des tombales confirmées : au plus une fois par jour (§4.6).
_PURGE_S = 24 * 3600.0
# §4.7 : chaque appareil réclame, au plus une fois par jour, toutes les
# pièces qu'il référence — ce qui rattrape une pièce marquée orpheline à tort
# (jeton volé, A9) bien avant sa purge à 30 jours.
_RECLAMATION_MS = 24 * 3600 * 1000
# ``/pieces/missing`` : 1 000 identifiants au plus par requête
# (``routes_pieces.RECLAMATION_MAX``).
_RECLAMATION_MAX = 1000
# Les clairs des pièces d'un lot restent en mémoire jusqu'à leur dépôt :
# 32 Mio bornent ce qu'un lot de 50 conversations illustrées retient, là où
# les 8 Mio de ``_LOT_OCTETS`` ne comptent plus que les objets. Le PREMIER
# élément passe toujours (sinon une conversation plus lourde ne partirait
# jamais) : ses pièces pèsent alors ce que pèse déjà sa copie locale, lue
# entière pour être scellée — la borne est celle du lot, pas d'une
# conversation (précisé le 24/09/2026 : ce commentaire laissait croire à
# une borne absolue).
_LOT_PIECES_OCTETS = 32 * 1024 * 1024
# Au plus 200 pièces marquées orphelines par cycle : une conversation
# supprimée qui en portait mille les libère en cinq cycles, sans qu'un seul
# cycle ne tienne le verrou d'exclusivité pendant mille requêtes.
_ORPHELINES_MAX = 200

# Le motif ``a_reprendre`` d'un objet dont une pièce n'a pas pu être lue
# MAINTENANT (5xx, injoignable) : on relira les pièces, pas l'objet.
_MOTIF_PIECES = "pieces"

# Un motif de quarantaine qui empêche « Synchronisé » : l'objet LOCAL n'a
# pas pu partir. Une quarantaine d'un blob du serveur (illisible, permuté)
# se compte et s'affiche, mais n'empêche pas de dire que tout ce qui est ici
# est là-bas.
_REFUS_LOCAL = "rejected:"


def empreinte(clair: dict[str, Any]) -> bytes:
    """``SHA-256(clair canonique)`` — LOCALE seulement, jamais envoyée (§2.3)."""
    return hashlib.sha256(encoder_clair(clair)).digest()


def _maintenant_ms() -> int:
    return time.time_ns() // 1_000_000


# ----------------------------------------------------------------------
# Lecture stricte des réponses de /sync/*
# ----------------------------------------------------------------------


class _ReponseInattendue(ErreurServeur):
    def __init__(self, champ: str) -> None:
        super().__init__(502, "serverError")
        self.champ = champ


def _entier(corps: Any, nom: str, *, minimum: int = 0) -> int:
    valeur = corps.get(nom) if isinstance(corps, dict) else None
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur < minimum:
        raise _ReponseInattendue(nom)
    return valeur


def _octets(texte: Any, nom: str) -> bytes:
    if not isinstance(texte, str) or not texte:
        raise _ReponseInattendue(nom)
    try:
        return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))
    except (binascii.Error, ValueError):
        raise _ReponseInattendue(nom) from None


@dataclass(frozen=True)
class _Meta:
    generation: str
    incarnation: int
    key_epoch: int
    vault_version: int
    keyring_version: int
    server_seq: int
    pending_reset_at: int | None


def _lire_meta(corps: Any) -> _Meta:
    meta = corps.get("meta") if isinstance(corps, dict) else None
    if not isinstance(meta, dict):
        raise _ReponseInattendue("meta")
    generation = meta.get("generation")
    if not isinstance(generation, str) or not generation:
        raise _ReponseInattendue("meta.generation")
    attente = meta.get("pendingResetAt")
    if attente is not None and (
        isinstance(attente, bool) or not isinstance(attente, int)
    ):
        raise _ReponseInattendue("meta.pendingResetAt")
    return _Meta(
        generation=generation,
        incarnation=_entier(meta, "incarnation", minimum=1),
        key_epoch=_entier(meta, "keyEpoch", minimum=1),
        vault_version=_entier(meta, "vaultVersion", minimum=1),
        keyring_version=_entier(meta, "keyringVersion", minimum=1),
        server_seq=_entier(meta, "serverSeq"),
        pending_reset_at=attente,
    )


@dataclass(frozen=True)
class _Element:
    object_id: str
    rev: int
    seq: int
    blob: bytes


def _lire_element(item: Any) -> _Element:
    if not isinstance(item, dict):
        raise _ReponseInattendue("items")
    object_id = item.get("objectId")
    if not isinstance(object_id, str) or not object_id or len(object_id) > 64:
        raise _ReponseInattendue("items.objectId")
    return _Element(
        object_id=object_id,
        rev=_entier(item, "rev", minimum=1),
        seq=_entier(item, "seq", minimum=1),
        blob=_octets(item.get("blob"), "items.blob"),
    )


# ----------------------------------------------------------------------
# Les tables de portée de etat.key (§4.2)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Connu:
    collection: str
    id_local: str
    object_id: str
    rev_max: int
    seq: int
    empreinte: bytes | None
    illisible: bool


# Deux tables de plus dans ``etat.key`` pour les pièces (étape 11,
# 24/09/2026), créées au premier accès comme toute table de ce dépôt
# (aucune migration, CLAUDE.md §5). Le §4.2 ne donnait que
# ``pieces_connues`` (époque, pièce), sans l'objet qui la référence :
#
# - ``references_pieces`` : les pièces que la version SERVEUR de chaque
#   objet référence. Sans elle, « plus aucun objet ne la référence »
#   (§4.7, orphelines) et « toutes les pièces qu'il référence »
#   (réclamation quotidienne) ne se calculaient pas — la seconde, déduite
#   des images locales sous l'époque courante, aurait réclamé des pièces
#   que personne n'a déposées et laissé mourir celles, d'une époque passée,
#   que le serveur référence encore ;
# - ``pieces_manquantes`` : les trous d'un objet dégradé (§4.7), par
#   message. Le magasin n'en garde aucune trace (une référence y serait une
#   image cassée et ferait refuser le chat) ; sans eux, la première poussée
#   d'un appareil dégradé effaçait l'image du serveur.
_TABLES_PIECES = (
    "CREATE TABLE IF NOT EXISTS references_pieces (account_id TEXT,"
    " incarnation INTEGER, object_id TEXT, piece_id TEXT,"
    " key_epoch INTEGER NOT NULL,"
    " PRIMARY KEY (account_id, incarnation, object_id, piece_id))",
    "CREATE TABLE IF NOT EXISTS pieces_manquantes (account_id TEXT,"
    " incarnation INTEGER, collection TEXT, id_local TEXT, cle TEXT,"
    " images TEXT NOT NULL,"
    " PRIMARY KEY (account_id, incarnation, collection, id_local, cle))",
)


class _PorteePerdue(Exception):
    """``etat.key`` a disparu (déconnexion, suppression) ou appartient
    désormais à une autre portée (autre compte, réinitialisation) pendant
    le cycle : plus rien ne doit s'y écrire."""


class _Registre:
    """Les tables de ``etat.key`` vues pour UNE portée ``(compte, incarnation)``.

    ``EtatLocal`` n'expose que ``etat``, les planchers et l'enveloppe : ses
    tables de synchronisation, créées à l'étape 8 « pour que l'étape 10 les
    remplisse », n'ont pas d'accesseur. On passe par sa connexion et SON
    verrou — une seconde connexion au même fichier, en ``journal_mode=DELETE``,
    se serait bloquée contre la première à chaque écriture d'une route.

    **Rien ne crée le fichier, et tout vérifie la portée** (24/09/2026).
    Une déconnexion pendant un cycle détruisait ``etat.key`` ; le cycle,
    qui ne tient pas le verrou d'opération du service, le RECRÉAIT à sa
    prochaine écriture (``_ouvrir(creer=True)``) avec ``curseurDistant``,
    ``serverSeqMax``, ``synchroPortee``… Sans aucun compte, le magasin
    croyait alors pour toujours qu'un compte existait (plus de purge des
    tombales à l'âge), chaque démarrage construisait le service, et chaque
    fermeture de l'app passait par la dernière synchronisation — et le
    compte suivant héritait de ``serverSeqMax`` et se lisait
    ``serverRolledBack``. Chaque accès relit donc ``accountId`` et
    ``incarnation`` sous le verrou de l'état, sur un fichier qu'il n'ouvre
    que s'il existe, et lève :class:`_PorteePerdue` sinon.
    """

    def __init__(self, etat: EtatLocal, account_id: str, incarnation: int) -> None:
        self.etat = etat
        self.a = account_id
        self.i = incarnation

    @property
    def portee(self) -> str:
        return f"{self.a}|{self.i}"

    @contextmanager
    def _base(self) -> Iterator[Any]:
        with self.etat._verrou:  # noqa: SLF001 - voir la docstring de la classe
            conn = self.etat._ouvrir(creer=False)  # noqa: SLF001
            if conn is None:
                raise _PorteePerdue()
            valeurs = dict(
                conn.execute(
                    "SELECT cle, valeur FROM etat WHERE cle IN "
                    "('accountId', 'incarnation')"
                ).fetchall()
            )
            if (
                valeurs.get("accountId") != self.a
                or int(valeurs.get("incarnation") or 1) != self.i
            ):
                raise _PorteePerdue()
            with conn:
                yield conn

    def preparer_tables(self) -> None:
        """Les tables des pièces, au début d'un cycle seulement : une lecture
        du statut n'écrit rien dans ``etat.key``."""
        with self._base() as conn:
            for creation in _TABLES_PIECES:
                conn.execute(creation)

    # --- Clés-valeurs ----------------------------------------------------

    def kv(self) -> dict[str, str]:
        return self.etat.tout()

    def ecrire(self, **valeurs: Any) -> None:
        """``EtatLocal.ecrire``, dans la portée : ``None`` efface la clé,
        les booléens s'écrivent ``1``/``0`` — mais jamais sur un fichier
        disparu ni sous un autre compte."""
        with self._base() as conn:
            for cle, valeur in valeurs.items():
                if valeur is None:
                    conn.execute("DELETE FROM etat WHERE cle = ?", (cle,))
                    continue
                if isinstance(valeur, bool):
                    texte = "1" if valeur else "0"
                else:
                    texte = str(valeur)
                conn.execute(
                    "INSERT INTO etat (cle, valeur) VALUES (?, ?) "
                    "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                    (cle, texte),
                )

    # --- Portée (étape 0) -------------------------------------------------

    def purger_hors_portee(self) -> None:
        """Vide tout ce qui n'est pas de cette portée ; les planchers de
        suppression d'un AUTRE compte seulement (§4.4)."""
        with self._base() as conn:
            for table in (
                "connus",
                "curseurs_export",
                "sortants",
                "quarantaine",
                "inconnus",
                "pieces_connues",
                "a_reprendre",
                "references_pieces",
                "pieces_manquantes",
            ):
                conn.execute(
                    f"DELETE FROM {table} WHERE account_id IS NOT ? "
                    "OR incarnation IS NOT ?",
                    (self.a, self.i),
                )
            conn.execute(
                "DELETE FROM planchers_suppression WHERE account_id IS NOT ?",
                (self.a,),
            )

    # --- connus -----------------------------------------------------------

    _COLONNES_CONNU = (
        "collection, id_local, object_id, rev_max, seq, empreinte, illisible"
    )

    def _connu(self, ligne: Any) -> _Connu | None:
        if ligne is None:
            return None
        return _Connu(
            collection=ligne[0],
            id_local=ligne[1],
            object_id=ligne[2],
            rev_max=int(ligne[3]),
            seq=int(ligne[4]),
            empreinte=None if ligne[5] is None else bytes(ligne[5]),
            illisible=bool(ligne[6]),
        )

    def connu(self, collection: str, id_local: str) -> _Connu | None:
        with self._base() as conn:
            ligne = conn.execute(
                f"SELECT {self._COLONNES_CONNU} FROM connus WHERE account_id = ? "
                "AND incarnation = ? AND collection = ? AND id_local = ?",
                (self.a, self.i, collection, id_local),
            ).fetchone()
        return self._connu(ligne)

    def connu_objet(self, object_id: str) -> _Connu | None:
        with self._base() as conn:
            ligne = conn.execute(
                f"SELECT {self._COLONNES_CONNU} FROM connus WHERE account_id = ? "
                "AND incarnation = ? AND object_id = ?",
                (self.a, self.i, object_id),
            ).fetchone()
        return self._connu(ligne)

    def connus(self) -> list[_Connu]:
        with self._base() as conn:
            lignes = conn.execute(
                f"SELECT {self._COLONNES_CONNU} FROM connus WHERE account_id = ? "
                "AND incarnation = ?",
                (self.a, self.i),
            ).fetchall()
        return [c for c in (self._connu(ligne) for ligne in lignes) if c is not None]

    def noter_connu(
        self,
        collection: str,
        id_local: str,
        object_id: str,
        *,
        rev: int,
        seq: int,
        empreinte_: bytes | None,
        illisible: bool = False,
    ) -> None:
        """``rev_max`` ne descend JAMAIS (§4.4) ; le reste suit la dernière
        version vue ou écrite.

        ``degrade`` naît de ``pieces_manquantes`` : jusqu'au 24/09/2026,
        la relecture de la version précédente posait les trous AVANT de
        connaître l'objet — l'``UPDATE`` de :meth:`poser_trous` ne touchait
        aucune ligne, et l'``INSERT`` d'ici écrivait ``degrade = 0`` sur un
        objet troué."""
        with self._base() as conn:
            conn.execute(
                "INSERT INTO connus (account_id, incarnation, collection, id_local,"
                " object_id, rev_max, seq, empreinte, illisible, degrade)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, EXISTS (SELECT 1 FROM"
                " pieces_manquantes WHERE account_id = ? AND incarnation = ?"
                " AND collection = ? AND id_local = ?))"
                " ON CONFLICT(account_id, incarnation, collection, id_local)"
                " DO UPDATE SET object_id = excluded.object_id,"
                " rev_max = MAX(rev_max, excluded.rev_max), seq = excluded.seq,"
                " empreinte = excluded.empreinte, illisible = excluded.illisible",
                (
                    self.a,
                    self.i,
                    collection,
                    id_local,
                    object_id,
                    rev,
                    seq,
                    empreinte_,
                    1 if illisible else 0,
                    self.a,
                    self.i,
                    collection,
                    id_local,
                ),
            )

    def oublier_empreinte(self, object_id: str) -> None:
        """Le serveur ne tient plus ce que cet appareil avait confirmé : la
        prochaine poussée ne doit pas conclure « déjà là »."""
        with self._base() as conn:
            conn.execute(
                "UPDATE connus SET empreinte = NULL WHERE account_id = ? AND "
                "incarnation = ? AND object_id = ?",
                (self.a, self.i, object_id),
            )

    # --- sortants ---------------------------------------------------------

    def ajouter_sortant(
        self, collection: str, id_local: str, supprime_le_ms: int | None
    ) -> None:
        """Une ré-exportation remet ``empreinte_poussee`` à NULL : une
        poussée en vol, qui effacera la ligne « si l'empreinte poussée est
        la sienne », laisse alors survivre la version plus récente (§4.3)."""
        with self._base() as conn:
            conn.execute(
                "INSERT INTO sortants (account_id, incarnation, collection, id_local,"
                " supprime_le_ms, empreinte_poussee, tentatives, prochain_essai_ms)"
                " VALUES (?, ?, ?, ?, ?, NULL, 0, 0)"
                " ON CONFLICT(account_id, incarnation, collection, id_local)"
                " DO UPDATE SET supprime_le_ms = CASE"
                "  WHEN excluded.supprime_le_ms IS NULL THEN supprime_le_ms"
                "  WHEN supprime_le_ms IS NULL THEN excluded.supprime_le_ms"
                "  ELSE MAX(supprime_le_ms, excluded.supprime_le_ms) END,"
                " empreinte_poussee = NULL, prochain_essai_ms = 0,"
                " derniere_erreur = NULL",
                (self.a, self.i, collection, id_local, supprime_le_ms),
            )

    def retirer_sortant(
        self, collection: str, id_local: str, *, si_poussee: bytes | None = None
    ) -> None:
        with self._base() as conn:
            if si_poussee is None:
                conn.execute(
                    "DELETE FROM sortants WHERE account_id = ? AND incarnation = ?"
                    " AND collection = ? AND id_local = ?",
                    (self.a, self.i, collection, id_local),
                )
            else:
                conn.execute(
                    "DELETE FROM sortants WHERE account_id = ? AND incarnation = ?"
                    " AND collection = ? AND id_local = ? AND empreinte_poussee = ?",
                    (self.a, self.i, collection, id_local, si_poussee),
                )

    def sortants_dus(self, maintenant: int) -> list[tuple[str, str, int | None]]:
        with self._base() as conn:
            lignes = conn.execute(
                "SELECT collection, id_local, supprime_le_ms FROM sortants"
                " WHERE account_id = ? AND incarnation = ? AND prochain_essai_ms <= ?"
                " ORDER BY prochain_essai_ms, collection, id_local",
                (self.a, self.i, maintenant),
            ).fetchall()
        return [(c, i, None if s is None else int(s)) for c, i, s in lignes]

    def noter_poussee(self, collection: str, id_local: str, h: bytes) -> None:
        with self._base() as conn:
            conn.execute(
                "UPDATE sortants SET empreinte_poussee = ?, tentatives = tentatives + 1"
                " WHERE account_id = ? AND incarnation = ? AND collection = ?"
                " AND id_local = ?",
                (h, self.a, self.i, collection, id_local),
            )

    def reporter_sortant(
        self, collection: str, id_local: str, prochain_ms: int, erreur: str
    ) -> None:
        with self._base() as conn:
            conn.execute(
                "UPDATE sortants SET prochain_essai_ms = ?, derniere_erreur = ?"
                " WHERE account_id = ? AND incarnation = ? AND collection = ?"
                " AND id_local = ?",
                (prochain_ms, erreur, self.a, self.i, collection, id_local),
            )

    def ids_sortants(self) -> set[tuple[str, str]]:
        with self._base() as conn:
            lignes = conn.execute(
                "SELECT collection, id_local FROM sortants WHERE account_id = ?"
                " AND incarnation = ?",
                (self.a, self.i),
            ).fetchall()
        return {(c, i) for c, i in lignes}

    def sortant_existe(self, collection: str, id_local: str) -> bool:
        with self._base() as conn:
            ligne = conn.execute(
                "SELECT 1 FROM sortants WHERE account_id = ? AND incarnation = ?"
                " AND collection = ? AND id_local = ?",
                (self.a, self.i, collection, id_local),
            ).fetchone()
        return ligne is not None

    # --- planchers de suppression -----------------------------------------

    def plancher_suppression(self, collection: str, id_local: str) -> int | None:
        with self._base() as conn:
            ligne = conn.execute(
                "SELECT deleted_at FROM planchers_suppression WHERE account_id = ?"
                " AND collection = ? AND id_local = ?",
                (self.a, collection, id_local),
            ).fetchone()
        return None if ligne is None else int(ligne[0])

    def relever_plancher_suppression(
        self, collection: str, id_local: str, deleted_at: int
    ) -> None:
        with self._base() as conn:
            conn.execute(
                "INSERT INTO planchers_suppression (account_id, collection, id_local,"
                " deleted_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(account_id, collection, id_local)"
                " DO UPDATE SET deleted_at = MAX(deleted_at, excluded.deleted_at)",
                (self.a, collection, id_local, deleted_at),
            )

    def planchers_de_suppression(self) -> list[tuple[str, str, int]]:
        with self._base() as conn:
            lignes = conn.execute(
                "SELECT collection, id_local, deleted_at FROM planchers_suppression"
                " WHERE account_id = ?",
                (self.a,),
            ).fetchall()
        return [(c, i, int(d)) for c, i, d in lignes]

    # --- curseurs d'export --------------------------------------------------

    def curseur_export(self, collection: str) -> int:
        with self._base() as conn:
            ligne = conn.execute(
                "SELECT seq_local FROM curseurs_export WHERE account_id = ?"
                " AND incarnation = ? AND collection = ?",
                (self.a, self.i, collection),
            ).fetchone()
        return 0 if ligne is None else int(ligne[0])

    def poser_curseur_export(self, collection: str, seq: int) -> None:
        with self._base() as conn:
            conn.execute(
                "INSERT INTO curseurs_export (account_id, incarnation, collection,"
                " seq_local) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(account_id, incarnation, collection)"
                " DO UPDATE SET seq_local = excluded.seq_local",
                (self.a, self.i, collection, seq),
            )

    # --- quarantaine, inconnus, à reprendre --------------------------------

    def quarantiner(
        self, object_id: str, motif: str, h: bytes | None, maintenant: int
    ) -> None:
        with self._base() as conn:
            conn.execute(
                "INSERT INTO quarantaine (account_id, incarnation, object_id, motif,"
                " empreinte, depuis_ms) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(account_id, incarnation, object_id)"
                " DO UPDATE SET motif = excluded.motif, empreinte = excluded.empreinte",
                (self.a, self.i, object_id, motif, h, maintenant),
            )

    def lever_quarantaine(self, object_id: str) -> None:
        with self._base() as conn:
            conn.execute(
                "DELETE FROM quarantaine WHERE account_id = ? AND incarnation = ?"
                " AND object_id = ?",
                (self.a, self.i, object_id),
            )

    def compter_quarantaine(self, *, prefixe: str | None = None) -> int:
        with self._base() as conn:
            if prefixe is None:
                ligne = conn.execute(
                    "SELECT COUNT(*) FROM quarantaine WHERE account_id = ?"
                    " AND incarnation = ?",
                    (self.a, self.i),
                ).fetchone()
            else:
                ligne = conn.execute(
                    "SELECT COUNT(*) FROM quarantaine WHERE account_id = ?"
                    " AND incarnation = ? AND motif LIKE ?",
                    (self.a, self.i, prefixe + "%"),
                ).fetchone()
        return int(ligne[0])

    def quarantaine_connue_sans_reparation(self) -> int:
        """Les objets QUE CET APPAREIL CONNAÎT, en quarantaine, sans copie
        en file pour les réparer : le compte ne les a plus sous une forme
        lisible, et « Synchronisé » mentirait (§100)."""
        with self._base() as conn:
            ligne = conn.execute(
                "SELECT COUNT(*) FROM quarantaine q JOIN connus c"
                " ON c.account_id = q.account_id AND c.incarnation = q.incarnation"
                " AND c.object_id = q.object_id"
                " WHERE q.account_id = ? AND q.incarnation = ?"
                " AND q.motif NOT LIKE ? AND NOT EXISTS (SELECT 1 FROM sortants s"
                "  WHERE s.account_id = c.account_id"
                "  AND s.incarnation = c.incarnation"
                "  AND s.collection = c.collection AND s.id_local = c.id_local)",
                (self.a, self.i, _REFUS_LOCAL + "%"),
            ).fetchone()
        return int(ligne[0])

    def motif_quarantaine(self, object_id: str) -> str | None:
        with self._base() as conn:
            ligne = conn.execute(
                "SELECT motif FROM quarantaine WHERE account_id = ? AND incarnation = ?"
                " AND object_id = ?",
                (self.a, self.i, object_id),
            ).fetchone()
        return None if ligne is None else str(ligne[0])

    def ranger_inconnu(self, element: _Element) -> None:
        with self._base() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO inconnus (account_id, incarnation, object_id,"
                " rev, seq, blob) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.a,
                    self.i,
                    element.object_id,
                    element.rev,
                    element.seq,
                    element.blob,
                ),
            )

    def inconnus(self) -> list[_Element]:
        with self._base() as conn:
            lignes = conn.execute(
                "SELECT object_id, rev, seq, blob FROM inconnus WHERE account_id = ?"
                " AND incarnation = ?",
                (self.a, self.i),
            ).fetchall()
        return [_Element(o, int(r), int(s), bytes(b)) for o, r, s, b in lignes]

    def retirer_inconnu(self, object_id: str) -> None:
        with self._base() as conn:
            conn.execute(
                "DELETE FROM inconnus WHERE account_id = ? AND incarnation = ?"
                " AND object_id = ?",
                (self.a, self.i, object_id),
            )

    def a_reprendre(self, object_id: str, motif: str, prochain_ms: int) -> None:
        with self._base() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO a_reprendre (account_id, incarnation,"
                " object_id, motif, prochain_essai_ms) VALUES (?, ?, ?, ?, ?)",
                (self.a, self.i, object_id, motif, prochain_ms),
            )

    def repris(self, object_id: str) -> None:
        with self._base() as conn:
            conn.execute(
                "DELETE FROM a_reprendre WHERE account_id = ? AND incarnation = ?"
                " AND object_id = ?",
                (self.a, self.i, object_id),
            )

    def a_reprendre_dus(self, maintenant: int) -> list[tuple[str, str]]:
        with self._base() as conn:
            lignes = conn.execute(
                "SELECT object_id, motif FROM a_reprendre WHERE account_id = ?"
                " AND incarnation = ? AND prochain_essai_ms <= ?",
                (self.a, self.i, maintenant),
            ).fetchall()
        return [(o, m) for o, m in lignes]

    # --- pièces (§4.7) -------------------------------------------------------

    def poser_references(
        self, object_id: str, epoque: int, identifiants: Sequence[str]
    ) -> None:
        """Les pièces que la version SERVEUR de cet objet référence, telle
        que cet appareil la connaît. Chacune entre aussi dans
        ``pieces_connues`` : c'est parmi elles, une fois plus référencées
        par rien, que se choisissent les orphelines."""
        with self._base() as conn:
            conn.execute(
                "DELETE FROM references_pieces WHERE account_id = ? AND"
                " incarnation = ? AND object_id = ?",
                (self.a, self.i, object_id),
            )
            for piece_id in identifiants:
                conn.execute(
                    "INSERT OR IGNORE INTO references_pieces (account_id,"
                    " incarnation, object_id, piece_id, key_epoch)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (self.a, self.i, object_id, piece_id, epoque),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO pieces_connues (account_id,"
                    " incarnation, key_epoch, piece_id) VALUES (?, ?, ?, ?)",
                    (self.a, self.i, epoque, piece_id),
                )

    def references_de(self, object_id: str) -> set[str]:
        with self._base() as conn:
            lignes = conn.execute(
                "SELECT piece_id FROM references_pieces WHERE account_id = ?"
                " AND incarnation = ? AND object_id = ?",
                (self.a, self.i, object_id),
            ).fetchall()
        return {ligne[0] for ligne in lignes}

    def toutes_references(self) -> dict[str, set[str]]:
        """``pieceId`` → les objets dont la version serveur le référence."""
        with self._base() as conn:
            lignes = conn.execute(
                "SELECT piece_id, object_id FROM references_pieces"
                " WHERE account_id = ? AND incarnation = ?",
                (self.a, self.i),
            ).fetchall()
        par_piece: dict[str, set[str]] = {}
        for piece_id, object_id in lignes:
            par_piece.setdefault(piece_id, set()).add(object_id)
        return par_piece

    def pieces_sans_reference(self, limite: int) -> list[str]:
        """Les pièces connues qu'aucune version serveur connue ne référence
        plus : les candidates à ``DELETE /pieces/{id}``."""
        with self._base() as conn:
            lignes = conn.execute(
                "SELECT DISTINCT piece_id FROM pieces_connues p"
                " WHERE account_id = ? AND incarnation = ? AND NOT EXISTS"
                " (SELECT 1 FROM references_pieces r WHERE r.account_id ="
                " p.account_id AND r.incarnation = p.incarnation"
                " AND r.piece_id = p.piece_id) ORDER BY piece_id LIMIT ?",
                (self.a, self.i, limite),
            ).fetchall()
        return [ligne[0] for ligne in lignes]

    def connaitre_piece(self, epoque: int, piece_id: str) -> None:
        """Une pièce que CET appareil vient de déposer : candidate à
        l'orphelinat tant qu'aucune version serveur ne la référence."""
        with self._base() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO pieces_connues (account_id,"
                " incarnation, key_epoch, piece_id) VALUES (?, ?, ?, ?)",
                (self.a, self.i, epoque, piece_id),
            )

    def oublier_piece(self, piece_id: str) -> None:
        with self._base() as conn:
            conn.execute(
                "DELETE FROM pieces_connues WHERE account_id = ? AND"
                " incarnation = ? AND piece_id = ?",
                (self.a, self.i, piece_id),
            )

    def trous(self, collection: str, id_local: str) -> dict[str, list[Any]]:
        with self._base() as conn:
            lignes = conn.execute(
                "SELECT cle, images FROM pieces_manquantes WHERE account_id = ?"
                " AND incarnation = ? AND collection = ? AND id_local = ?",
                (self.a, self.i, collection, id_local),
            ).fetchall()
        trous: dict[str, list[Any]] = {}
        for cle, images in lignes:
            try:
                valeur = json.loads(images)
            except ValueError:
                continue
            if isinstance(valeur, list):
                trous[cle] = valeur
        return trous

    def poser_trous(
        self, collection: str, id_local: str, trous: dict[str, list[Any]]
    ) -> None:
        """Remplace les trous de l'objet ; ``connus.degrade`` le dit aussi
        (§4.3 : « appliquer SANS la pièce, degrade=1 »)."""
        with self._base() as conn:
            conn.execute(
                "DELETE FROM pieces_manquantes WHERE account_id = ? AND"
                " incarnation = ? AND collection = ? AND id_local = ?",
                (self.a, self.i, collection, id_local),
            )
            for cle, images in trous.items():
                conn.execute(
                    "INSERT INTO pieces_manquantes (account_id, incarnation,"
                    " collection, id_local, cle, images) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        self.a,
                        self.i,
                        collection,
                        id_local,
                        cle,
                        json.dumps(images, ensure_ascii=False),
                    ),
                )
            conn.execute(
                "UPDATE connus SET degrade = ? WHERE account_id = ? AND"
                " incarnation = ? AND collection = ? AND id_local = ?",
                (1 if trous else 0, self.a, self.i, collection, id_local),
            )

    def objets_troues(self) -> list[tuple[str, str]]:
        with self._base() as conn:
            lignes = conn.execute(
                "SELECT DISTINCT collection, id_local FROM pieces_manquantes"
                " WHERE account_id = ? AND incarnation = ?",
                (self.a, self.i),
            ).fetchall()
        return [(c, i) for c, i in lignes]

    def compter(self, table: str) -> int:
        assert table in {"sortants", "a_reprendre"}
        with self._base() as conn:
            ligne = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE account_id = ?"
                " AND incarnation = ?",
                (self.a, self.i),
            ).fetchone()
        return int(ligne[0])


# ----------------------------------------------------------------------
# Issues internes d'un cycle
# ----------------------------------------------------------------------


class _Arret(Exception):
    """Le cycle rend la main avec un état : posé, repli, refus."""

    def __init__(
        self, etat: str, *, erreur: str | None = None, attente_s: float | None = None
    ):
        super().__init__(etat)
        self.etat = etat
        self.erreur = erreur
        self.attente_s = attente_s


class _Interrompu(Exception):
    """L'arrêt du serveur local a été demandé pendant le cycle."""


class _PieceTransitoire(Exception):
    """Une pièce que le VPS n'a pas pu rendre MAINTENANT (5xx, 429,
    injoignable) : l'objet attend dans ``a_reprendre`` et le curseur avance
    quand même (§4.3). Un 404, lui, est définitif : l'objet est dégradé."""


# ----------------------------------------------------------------------
# Le moteur
# ----------------------------------------------------------------------


class MoteurSynchro:
    """Un moteur par service de compte. Toute la synchronisation passe par
    :meth:`cycle`, sous un verrou d'exclusivité : « Synchroniser maintenant »
    et la tâche du lifespan ne se chevauchent jamais (§4.3)."""

    def __init__(
        self,
        service: Any,
        collections: Sequence[Collection],
        *,
        horloge_ms: Callable[[], int] | None = None,
        monotone: Callable[[], float] = time.monotonic,
        hasard: Callable[[], float] = random.random,
    ) -> None:
        self._service = service
        self._collections: dict[str, Collection] = {}
        for collection in collections:
            if collection.nom not in COLLECTIONS_SYNCHRONISEES:
                raise ValueError(f"collection hors liste blanche : {collection.nom}")
            self._collections[collection.nom] = collection
        self._ms = horloge_ms or _maintenant_ms
        self._mono = monotone
        self._hasard = hasard
        self._exclusif = threading.Lock()
        self._arret = threading.Event()
        self._fil = threading.local()
        self.en_cours = False
        self.cycles = 0
        self.eveille = False
        self.derniere_ecriture = 0.0
        self._echecs = 0
        self._repli_jusqu_a = 0.0
        self._derniere_purge: float | None = None
        self._reveiller: Callable[..., None] | None = None
        self._magasin: Any = None
        # La base du prochain comparer-et-échanger d'un objet dont le blob
        # courant est illisible (ou forgé) : SA révision, que rien
        # n'authentifie, vaut pour ce cycle seulement et n'entre jamais
        # dans ``connus.rev_max`` (voir la docstring du module).
        self._indices_base: dict[tuple[str, str], int] = {}
        # Le ``serverSeq`` jusqu'où CE cycle a tiré sans reste (``hasMore``
        # faux), ou ``None`` : seul un tirage complet autorise à marquer une
        # pièce orpheline (§4.7) et à la réclamer (``asOfSeq``).
        self._tire_jusqu_a: int | None = None

    # ------------------------------------------------------------------
    # Branchements
    # ------------------------------------------------------------------

    def brancher(self, magasin: Any, reveiller: Callable[..., None]) -> None:
        """Pose les deux crochets du magasin (§4.3, §4.6). Appelé au premier
        réveil seulement : sans compte déverrouillé, le magasin garde
        ``None`` et se comporte exactement comme avant le compte."""
        self._magasin = magasin
        self._reveiller = reveiller
        magasin.peut_purger = self.peut_purger
        magasin.sur_ecriture = self.signaler_ecriture

    def signaler_ecriture(self, _seq: int) -> None:
        """Le crochet ``sur_ecriture`` : une affectation et, éveillé, un réveil.

        Les écritures du moteur lui-même (ingestion) ne le réveillent pas :
        chaque tirage aurait sinon déclenché un second cycle pour exporter
        l'écho de ce qu'il venait d'écrire.
        """
        if getattr(self._fil, "ingestion", False):
            return
        self.derniere_ecriture = self._mono()
        reveiller = self._reveiller
        if self.eveille and reveiller is not None:
            reveiller(urgent=False)

    def arreter(self) -> None:
        """Le serveur local s'arrête : le cycle en cours rend la main à la
        prochaine page ou au prochain lot, sans attendre de finir."""
        self._arret.set()

    def fermer(self) -> None:
        self._arret.set()
        for collection in self._collections.values():
            try:
                collection.fermer()
            except Exception:  # noqa: BLE001 - fermer ne doit rien casser
                pass

    # ------------------------------------------------------------------
    # Ce que la tâche du lifespan interroge
    # ------------------------------------------------------------------

    def actif(self) -> bool:
        """Des comptes ouverts, un compte déverrouillé ici, sans état posé
        par le serveur ni rotation exigée.

        ``comptes_ouverts`` d'abord (24/09/2026) : un ``etat.key`` hérité
        d'un banc suffisait, comptes fermés (§6 bis), à faire contacter le
        VPS par un compte mémorisé."""
        service = self._service
        if not getattr(service, "comptes_ouverts", False):
            return False
        if not service.serrure.ouverte:
            return False
        valeurs = service.etat.tout()
        if not valeurs.get("accountId") or valeurs.get("etatCompte") in ETATS_POSES:
            return False
        return not self._rotation_exigee(valeurs)

    def _rotation_exigee(self, valeurs: dict[str, str]) -> bool:
        """§3.10 : après ``serverRolledBack``, « une rotation est
        obligatoire ». Vrai tant que le trousseau ouvert n'a pas dépassé
        l'époque de la détection, pour la même portée.

        24/09/2026 : une simple reconnexion levait ``serverRolledBack``
        (``_installer`` efface ``etatCompte``) et le cycle suivant disait
        « Synchronisé » face au serveur revenu en arrière, sans rotation."""
        exigee = valeurs.get("rotationExigee")
        if not exigee:
            return False
        portee, _, epoque = exigee.rpartition("|")
        if portee != f"{valeurs.get('accountId')}|{valeurs.get('incarnation') or 1}":
            return False
        try:
            ouverture = self._service.serrure.exiger()
        except CompteVerrouille:
            return True
        return ouverture.trousseau.current_epoch <= int(epoque)

    def attente_avant_suite(self) -> float:
        """Combien attendre le prochain cycle sans écriture locale."""
        reste = self._repli_jusqu_a - self._mono()
        if reste > 0:
            return reste
        sondage = getattr(self._service, "dernier_sondage", None)
        if sondage is not None and self._mono() - sondage < _SONDAGE_RECENT_S:
            return _TIRAGE_ACTIF_S
        return _TIRAGE_REPOS_S

    def repli_restant(self) -> float:
        return max(0.0, self._repli_jusqu_a - self._mono())

    def purger_si_du(self) -> int:
        """Purge des tombales confirmées, au plus une fois par jour."""
        magasin = self._magasin
        if magasin is None:
            return 0
        maintenant = self._mono()
        if (
            self._derniere_purge is not None
            and maintenant - self._derniere_purge < _PURGE_S
        ):
            return 0
        self._derniere_purge = maintenant
        try:
            return int(magasin.purger_tombales())
        except Exception:  # noqa: BLE001 - une purge manquée ne coûte que 60 o
            logger.exception("compte : purge des tombales échouée")
            return 0

    # ------------------------------------------------------------------
    # peut_purger (§4.6)
    # ------------------------------------------------------------------

    def peut_purger(self, id_local: str, deleted_at: int) -> bool:
        """Une tombale de plus de 30 jours ne part que si le serveur l'a
        CONFIRMÉE : aucune ligne ``sortants``, ``connus.empreinte`` égale à
        l'empreinte de CETTE tombale, et un plancher de suppression qui la
        couvre. Sans compte, l'âge seul suffit, comme avant le compte."""
        etat = self._service.etat
        if not etat.existe():
            return True
        valeurs = etat.tout()
        account_id = valeurs.get("accountId")
        if not account_id:
            return True
        registre = _Registre(etat, account_id, int(valeurs.get("incarnation") or 1))
        nom = "conversations"
        if nom not in self._collections:
            return False
        try:
            if registre.sortant_existe(nom, id_local):
                return False
            connu = registre.connu(nom, id_local)
            if connu is None or connu.illisible or connu.empreinte is None:
                return False
            if connu.empreinte != empreinte(clair_tombale(nom, id_local, deleted_at)):
                return False
            plancher = registre.plancher_suppression(nom, id_local)
        except _PorteePerdue:
            # Le compte part pendant la purge : garder la tombale un jour de
            # plus ne coûte que 60 o.
            return False
        return plancher is not None and plancher >= deleted_at

    # ------------------------------------------------------------------
    # Ce que /v1/account/status montre (§4.11)
    # ------------------------------------------------------------------

    def resume(self, valeurs: dict[str, str], conversations: int | None) -> dict:
        """Recalculé à chaque lecture, sans réseau (§4.11)."""
        service = self._service
        account_id = valeurs.get("accountId")
        bloc: dict[str, Any] = {
            "state": "disabled",
            "serverSeq": None,
            "lastConfirmedAt": None,
            "pendingCount": None,
            "quarantinedCount": None,
            "repairedCount": None,
            "errorCode": None,
        }
        if not account_id:
            return bloc
        incarnation = int(valeurs.get("incarnation") or 1)
        registre = _Registre(service.etat, account_id, incarnation)
        de_la_portee = valeurs.get("synchroPortee") == registre.portee
        try:
            attente = self._en_attente(registre)
            quarantaine = registre.compter_quarantaine()
        except _PorteePerdue:
            # Déconnecté entre la lecture des valeurs et celle des tables.
            return bloc
        bloc["pendingCount"] = attente
        bloc["quarantinedCount"] = quarantaine
        bloc["repairedCount"] = int(valeurs.get("repairedCount") or 0)
        if de_la_portee:
            bloc["errorCode"] = valeurs.get("synchroErreur") or None
            if valeurs.get("serverSeq"):
                bloc["serverSeq"] = int(valeurs["serverSeq"])
            if valeurs.get("lastConfirmedAt"):
                bloc["lastConfirmedAt"] = int(valeurs["lastConfirmedAt"])
        pose = valeurs.get("etatCompte")
        if pose in ETATS_POSES:
            bloc["state"] = pose
        elif self._rotation_exigee(valeurs):
            # Reconnecté, mais la rotation du §3.10 n'a pas eu lieu : rien ne
            # part, et l'écran le dit.
            bloc["state"] = "serverRolledBack"
        elif not service.serrure.ouverte:
            bloc["state"] = "paused"
        elif valeurs.get("consentement") != "1" and (conversations or 0) > 0:
            bloc["state"] = "needsConsent"
        elif self.en_cours:
            bloc["state"] = "syncing"
        elif not de_la_portee:
            # Une incarnation neuve, un compte neuf : rien de ce qu'on avait
            # confirmé ne vaut plus (§100 — « un état qui correspond à
            # l'incarnation courante »).
            bloc["state"] = "pending"
        else:
            enregistre = valeurs.get("synchroEtat") or "pending"
            if enregistre == "upToDate" and (
                attente or bloc["serverSeq"] is None or bloc["lastConfirmedAt"] is None
            ):
                enregistre = "pending"
            bloc["state"] = enregistre
        return bloc

    def _en_attente(self, registre: _Registre) -> int:
        ids = registre.ids_sortants()
        for nom, collection in self._collections.items():
            try:
                depuis = collection.en_attente_depuis(registre.curseur_export(nom))
            except Exception:  # noqa: BLE001 - un compte n'est pas un magasin
                logger.warning("compte : écritures en attente illisibles (%s)", nom)
                continue
            ids.update((nom, i) for i in depuis)
        return len(ids)

    # ------------------------------------------------------------------
    # Le cycle
    # ------------------------------------------------------------------

    def cycle(self, *, attente_s: float | None = None) -> str:
        """Un cycle complet ; rend l'état atteint (§4.11).

        ``attente_s`` borne l'attente du verrou d'exclusivité : ``None``
        attend sans limite (la tâche du lifespan), un nombre rend
        ``syncing`` si un cycle ne s'est pas terminé à temps (« Synchroniser
        maintenant »).
        """
        acquis = (
            self._exclusif.acquire()
            if attente_s is None
            else self._exclusif.acquire(timeout=attente_s)
        )
        if not acquis:
            return "syncing"
        self.en_cours = True
        self._indices_base = {}
        self._tire_jusqu_a = None
        try:
            self.cycles += 1
            return self._cycle()
        except _PorteePerdue:
            # Déconnecté, supprimé ou réinitialisé pendant le cycle : rien
            # de ce cycle ne s'écrit plus nulle part (voir ``_Registre``).
            logger.info("compte : la portée a changé pendant le cycle — abandon")
            return "disabled"
        finally:
            self._indices_base = {}
            self.en_cours = False
            self._exclusif.release()

    def _ouverture(self) -> Ouverture | str:
        service = self._service
        valeurs = service.etat.tout()
        account_id = valeurs.get("accountId")
        if not account_id:
            return "disabled"
        if valeurs.get("etatCompte") in ETATS_POSES:
            return str(valeurs["etatCompte"])
        try:
            ouverture = service.serrure.exiger()
        except CompteVerrouille:
            return "paused"
        if ouverture.account_id != account_id or ouverture.incarnation != int(
            valeurs.get("incarnation") or 1
        ):
            return "paused"
        if self._rotation_exigee(valeurs):
            # §3.10 : pas une requête avant la rotation.
            return "serverRolledBack"
        return ouverture

    def _verifier_serrure(self, registre: _Registre) -> Ouverture:
        """Entre deux requêtes : la serrure est-elle toujours ouverte, pour
        la même portée ?

        24/09/2026 : « Verrouiller » pendant un cycle laissait le cycle
        pousser jusqu'au bout avec l'``Ouverture`` prise au départ — le
        statut disait ``paused`` pendant que des lots scellés partaient, et
        les DEK restaient vivantes dans le fil (A7)."""
        ouverture = self._service.serrure.exiger()
        if ouverture.account_id != registre.a or ouverture.incarnation != registre.i:
            raise _PorteePerdue()
        return ouverture

    def _cycle(self) -> str:
        ouverture = self._ouverture()
        if isinstance(ouverture, str):
            return ouverture
        registre = _Registre(
            self._service.etat, ouverture.account_id, ouverture.incarnation
        )
        registre.preparer_tables()
        self._verifier_portee(registre)
        self._exporter(registre)
        kv = registre.kv()
        if kv.get("consentement") != "1":
            if any(c.a_des_donnees() for c in self._collections.values()):
                return self._enregistrer(registre, "needsConsent")
            # Rien ici à ajouter au compte : la question du §3.11 P3 n'a pas
            # d'objet, et la poser plus tard, une fois les conversations du
            # compte tirées, demanderait d'« ajouter » ce qui en vient.
            registre.ecrire(consentement=True)
        try:
            meta = self._tirer(registre, ouverture)
            self._reprendre(registre, ouverture)
            # Avant la poussée : une pièce ranimée l'est avant que l'objet
            # qui la référence reparte, et un objet à renvoyer sous l'époque
            # courante part dans ce cycle-ci (§4.7).
            self._reclamer(registre, ouverture)
            ouverture = self._pousser(registre, ouverture)
            self._marquer_orphelines(registre)
            # Absorber l'écho de ce que le tirage vient d'écrire : sans ce
            # second export, ``pendingCount`` compterait comme « en attente »
            # des conversations qui viennent du serveur.
            self._exporter(registre)
            return self._conclure(registre, meta)
        except _Arret as arret:
            return self._enregistrer(
                registre, arret.etat, erreur=arret.erreur, attente_s=arret.attente_s
            )
        except _Interrompu:
            return self._enregistrer(registre, "pending", erreur="interrupted")
        except ErreurServeur as exc:
            return self._erreur_serveur(registre, exc)
        except ServeurInjoignable:
            return self._enregistrer(
                registre, "offline", erreur="serverUnreachable", echec=True
            )
        except (SortieRefusee, CompteInactif) as exc:
            return self._enregistrer(registre, "offline", erreur=exc.code, echec=True)
        except CompteVerrouille:
            return self._enregistrer(registre, "paused")

    # --- Étape 0 : la portée ---------------------------------------------

    def _verifier_portee(self, registre: _Registre) -> None:
        kv = registre.kv()
        if kv.get("synchroPortee") == registre.portee:
            return
        registre.purger_hors_portee()
        precedent = (kv.get("synchroPortee") or "").rpartition("|")[0]
        par_compte: dict[str, Any] = {}
        if precedent != registre.a:
            # ``generation`` et ``serverSeqMax`` sont des valeurs PAR COMPTE
            # (24/09/2026) : laissées par un autre compte, un ``seq`` plus
            # petit (compte plus jeune, même VPS) se lisait comme un retour
            # arrière de toute la machine, et le compte neuf restait
            # ``serverRolledBack``. Une incarnation neuve du MÊME compte les
            # garde : son ``seq`` ne recule jamais (``avancer_seq``).
            par_compte = {"generation": None, "serverSeqMax": None}
        registre.ecrire(
            synchroPortee=registre.portee,
            curseurDistant=0,
            synchroEtat=None,
            synchroErreur=None,
            serverSeq=None,
            lastConfirmedAt=None,
            # Les bornes d'époque et la rotation exigée tiennent à un
            # trousseau : une incarnation neuve repart de l'époque 1.
            bornesEpoque=None,
            rotationExigee=None,
            reclamationPiecesMs=None,
            **par_compte,
        )
        # Toutes les suppressions que cet appareil connaît repassent aussi,
        # même purgées du magasin (§4.5) : sans elles, un appareil revenu
        # avec sa vieille copie ressusciterait sous la nouvelle incarnation
        # ce qui a été supprimé sous l'ancienne. Le reste repasse par
        # l'export depuis 0 (aucun curseur dans la portée neuve).
        for collection, id_local, deleted_at in registre.planchers_de_suppression():
            if collection in self._collections:
                registre.ajouter_sortant(collection, id_local, deleted_at)
        logger.info("compte : portée de synchronisation neuve — tout repart")

    # --- Étape 1 : l'export ------------------------------------------------

    def _exporter(self, registre: _Registre) -> None:
        for nom, collection in self._collections.items():
            depuis = registre.curseur_export(nom)
            changements, nouveau = collection.changements_depuis(depuis)
            for changement in changements:
                if changement.supprime_le_ms is not None:
                    registre.relever_plancher_suppression(
                        nom, changement.id_local, changement.supprime_le_ms
                    )
                clair = self._sous_les_planchers(
                    registre,
                    collection,
                    changement.id_local,
                    self._combler(
                        registre, collection, changement.id_local, changement.clair
                    ),
                )
                connu = registre.connu(nom, changement.id_local)
                if (
                    connu is not None
                    and not connu.illisible
                    and connu.empreinte is not None
                    and connu.empreinte == empreinte(clair)
                ):
                    # Ce que le serveur tient déjà : l'écho d'une ingestion,
                    # ou une écriture sans effet.
                    registre.retirer_sortant(nom, changement.id_local)
                    continue
                registre.ajouter_sortant(
                    nom, changement.id_local, changement.supprime_le_ms
                )
            registre.poser_curseur_export(nom, nouveau)

    def _sous_les_planchers(
        self,
        registre: _Registre,
        collection: Collection,
        id_local: str,
        clair: dict[str, Any] | None,
        supprime_le_ms: int | None = None,
    ) -> dict[str, Any] | None:
        """Le clair à pousser pour cet objet — jamais une copie vivante sous
        son plancher de suppression, et une tombale quand la copie locale a
        été purgée (§4.3, étape 4)."""
        plancher = registre.plancher_suppression(collection.nom, id_local)
        dates = [d for d in (plancher, supprime_le_ms) if d is not None]
        suppression = max(dates) if dates else None
        if clair is None:
            if suppression is None:
                return None
            return clair_tombale(
                collection.nom, id_local, suppression, schema=collection.schema
            )
        if "deleted" in clair or suppression is None:
            return clair
        if suppression >= collection.date_de(clair):
            return clair_tombale(
                collection.nom, id_local, suppression, schema=collection.schema
            )
        return clair

    # --- Étape 3 : le tirage -----------------------------------------------

    def _requete(
        self, registre: _Registre, chemin: str, *, jeton: Callable[[], str | None]
    ) -> ReponseServeur:
        """Un GET vers ``/sync/*``, par la même porte que tout le reste.

        ``Transport`` n'a de méthodes typées que pour les ÉCRITURES
        (``pousser_objets``, ``deposer_piece`` : ce sont elles que la
        condition 3 du §3.12 doit garder). Un GET ne porte aucun corps ; il
        passe par ``_envoyer``, qui applique la frontière AVANT de lire le
        jeton, comme pour toute requête.
        """
        transport = self._service.client.transport
        debut = self._ms()
        reponse = transport._envoyer("GET", chemin, jeton=jeton)  # noqa: SLF001
        # Verrouillé ou déconnecté pendant que la requête volait : rien de
        # la réponse ne s'ouvre ni ne s'écrit.
        self._verifier_serrure(registre)
        self._mesurer_ecart(registre, reponse, debut, self._ms())
        return reponse

    def _mesurer_ecart(
        self, registre: _Registre, reponse: ReponseServeur, debut: int, fin: int
    ) -> None:
        """``clockSkewMs`` sur l'en-tête ``Date``, corrigé de la moitié de
        l'aller-retour (§4.9). La seconde près de ``Date`` suffit : le
        bandeau ne s'allume qu'au-delà de 120 s."""
        if not reponse.date:
            return
        try:
            serveur = int(parsedate_to_datetime(reponse.date).timestamp() * 1000)
        except (TypeError, ValueError, OverflowError):
            return
        registre.ecrire(clockSkewMs=(debut + fin) // 2 - serveur)

    def _tirer(self, registre: _Registre, ouverture: Ouverture) -> _Meta:
        kv = registre.kv()
        curseur = int(kv.get("curseurDistant") or 0)
        complet = curseur == 0
        vus: set[str] = set()
        meta: _Meta | None = None
        recommence = False
        for _page in range(_PAGES_MAX):
            if self._arret.is_set():
                raise _Interrompu()
            # Les planchers d'AVANT la requête : une rotation faite ici
            # pendant qu'elle vole relève les planchers, et la réponse, née
            # avant la rotation, se serait lue comme un retour arrière
            # (constaté le 24/09/2026 par le test de rotation en cours de
            # synchronisation).
            planchers = registre.etat.planchers()
            # L'époque du trousseau AVANT la requête : la rotation vers elle
            # précède la réponse, dont le ``serverSeq`` borne donc tout ce
            # que les époques d'avant ont pu écrire (voir la docstring du
            # module). Prise après, une rotation faite pendant la requête
            # aurait daté la borne d'une réponse née avant elle.
            epoque_avant = self._verifier_serrure(registre).trousseau.current_epoch
            reponse = self._requete(
                registre,
                f"/sync/changes?since={curseur}&limit={_PAGE_ELEMENTS}",
                jeton=self._service.jeton_de_session,
            )
            corps = reponse.corps
            meta = _lire_meta(corps)
            juge = self._juger_meta(registre, ouverture, meta, curseur, planchers)
            if juge and not recommence:
                # Une ``generation`` nouvelle : restauration logique (§3.10).
                # Le curseur SEUL revient à 0 ; les planchers restent.
                recommence = True
                curseur, complet = 0, True
                vus.clear()
                continue
            self._noter_borne(registre, epoque_avant, meta.server_seq)
            items = corps.get("items")
            if not isinstance(items, list):
                raise _ReponseInattendue("items")
            jusqu_a = _entier(corps, "until")
            encore = corps.get("hasMore")
            if not isinstance(encore, bool):
                raise _ReponseInattendue("hasMore")
            if jusqu_a > meta.server_seq:
                # Un VPS honnête ne rend jamais un ``until`` au-delà de son
                # propre ``serverSeq``. Accepté, un seul ``until = 10**12``
                # disait « Synchronisé », puis ``serverRolledBack`` à chaque
                # cycle suivant — collant jusqu'à une reconnexion
                # (contre-épreuve du 24/09/2026). Refusé, le cycle part en
                # repli et le curseur ne bouge pas.
                raise _ReponseInattendue("until")
            elements = [_lire_element(brut) for brut in items]
            for element in elements:
                if not curseur < element.seq <= jusqu_a:
                    raise _ReponseInattendue("items.seq")
            for element in elements:
                vus.add(element.object_id)
                self._accueillir(registre, ouverture, element)
            if encore and jusqu_a <= curseur:
                # Un curseur qui ne bouge pas redemanderait la même page à
                # l'infini (§6 bis : reprendre à ``until``).
                raise _ReponseInattendue("until")
            # À ``until``, JAMAIS au ``seq`` du dernier élément (§6 bis).
            curseur = jusqu_a
            registre.ecrire(curseurDistant=curseur)
            if not encore:
                self._tire_jusqu_a = curseur
                break
        else:
            complet = False
        assert meta is not None
        if complet:
            self._absents(registre, vus)
        registre.ecrire(serverSeq=meta.server_seq)
        return meta

    def _juger_meta(
        self,
        registre: _Registre,
        ouverture: Ouverture,
        meta: _Meta,
        curseur: int,
        planchers: Any,
    ) -> bool:
        """Lève :class:`_Arret` sur un état posé ; rend ``True`` si la
        ``generation`` a changé et que le tirage doit reprendre à 0.

        ORDRE (§6 bis) : incarnation, planchers du coffre, puis
        ``generation`` AVANT ``serverSeq`` et le curseur — une restauration
        logique fait reculer ``serverSeq`` avec une ``generation`` neuve, et
        se lisait sinon comme un retour arrière de toute la machine.
        """
        service = self._service
        if meta.incarnation > registre.i:
            # Une réinitialisation a eu lieu : ce qui est scellé ici sous
            # l'incarnation courante ne vaut plus rien là-bas (§3.6).
            self._poser_etat(registre, "accountReset")
            raise _Arret("accountReset")
        if meta.incarnation < registre.i or (
            planchers is not None
            and planchers.account_id == registre.a
            and (
                meta.vault_version < planchers.vault_version_max
                or meta.keyring_version < planchers.keyring_version_max
                or meta.key_epoch < planchers.key_epoch_max
            )
        ):
            self._retour_arriere(registre, ouverture)
        kv = registre.kv()
        connue = kv.get("generation")
        vu_max = int(kv.get("serverSeqMax") or 0)
        if connue != meta.generation:
            registre.ecrire(
                generation=meta.generation,
                curseurDistant=0,
                serverSeqMax=meta.server_seq,
            )
            if connue is not None and curseur != 0:
                logger.info("compte : generation nouvelle — tout est retiré")
                return True
        elif meta.server_seq < max(curseur, vu_max):
            # Même generation et un serveur qui a oublié ce qu'il nous a
            # déjà montré : toute la machine est revenue en arrière (§3.10).
            #
            # Le ``serverSeq`` le plus haut VU, et pas seulement le curseur
            # (24/09/2026) : le curseur est posé par le tirage, AVANT la
            # poussée du même cycle. Un appareil qui avait seul écrit depuis
            # l'instantané revoyait un ``serverSeq`` égal à son curseur, et
            # prenait le serveur d'avant pour le serveur courant. Le ``seq``
            # d'un compte ne recule jamais, pas même à ``reset/complete``
            # (``routes_synchro.avancer_seq``) : c'est l'analogue par compte
            # du ``globalSeq`` du §3.10, sans appel de plus.
            self._retour_arriere(registre, ouverture, server_seq=meta.server_seq)
        else:
            self._voir_seq(registre, meta.server_seq)
        if meta.key_epoch > ouverture.trousseau.current_epoch:
            # Une rotation faite ICI pendant le cycle (une rotation faite
            # ailleurs aurait révoqué notre session : 401, pas 200).
            nouvelle = service.serrure.exiger()
            if meta.key_epoch > nouvelle.trousseau.current_epoch:
                raise _Arret("pending", erreur="keyEpochChanged")
        attente = kv.get("pendingResetAt")
        voulue = None if meta.pending_reset_at is None else str(meta.pending_reset_at)
        if attente != voulue:
            # §3.6 : l'attente d'une réinitialisation se lit dans CHAQUE
            # réponse ; une annulation faite ailleurs l'efface ici.
            registre.ecrire(pendingResetAt=meta.pending_reset_at)
            if meta.pending_reset_at is not None:
                logger.warning(
                    "compte : réinitialisation du compte prévue — visible et annulable"
                )
        return False

    def _voir_seq(self, registre: _Registre, server_seq: int) -> None:
        kv = registre.kv()
        if server_seq > int(kv.get("serverSeqMax") or 0):
            registre.ecrire(serverSeqMax=server_seq)

    def _poser_etat(self, registre: _Registre, code: str) -> None:
        """``accountReset`` ou ``serverRolledBack`` : seul un nouveau geste
        les lève (§3.10, §4.3). Dans la portée — ``service.etat.ecrire``
        recréait ``etat.key`` après une déconnexion faite pendant la
        requête (voir ``_Registre``)."""
        if code not in ETATS_POSES:
            raise ValueError(f"état non posable : {code}")
        registre.ecrire(etatCompte=code)

    # --- Bornes d'époque (§2.11 bis) ------------------------------------

    @staticmethod
    def _bornes(kv: dict[str, str]) -> dict[int, int]:
        """``bornesEpoque`` : ``"2:17,3:42"`` — pour chaque époque du
        trousseau, le ``serverSeq`` de la première réponse obtenue sous
        elle. Une valeur illisible vaut « aucune borne » : la règle se tait
        plutôt que de mettre l'historique légitime en quarantaine."""
        bornes: dict[int, int] = {}
        for morceau in (kv.get("bornesEpoque") or "").split(","):
            epoque, _, seq = morceau.partition(":")
            if epoque.isdigit() and seq.isdigit():
                bornes[int(epoque)] = int(seq)
        return bornes

    def _noter_borne(self, registre: _Registre, epoque: int, server_seq: int) -> None:
        """La PREMIÈRE observation seulement : c'est la borne la plus
        serrée qui reste vraie (la rotation vers ``epoque`` la précède)."""
        bornes = self._bornes(registre.kv())
        if epoque in bornes:
            return
        bornes[epoque] = server_seq
        registre.ecrire(
            bornesEpoque=",".join(f"{e}:{s}" for e, s in sorted(bornes.items()))
        )

    def _epoque_courante(self, registre: _Registre) -> int:
        planchers = registre.etat.planchers()
        return max(
            planchers.key_epoch_max if planchers is not None else 0,
            int(registre.kv().get("epoqueAuthentifieeMin") or 0),
        )

    def _epoque_perimee(self, registre: _Registre, epoque: int, seq: int) -> bool:
        """Un blob d'époque ``epoque`` écrit APRÈS la rotation qui l'a
        close : son ``seq`` dépasse la borne d'une époque suivante.

        Sans borne connue pour une époque suivante (une rotation faite ici
        pendant la requête dont vient ce blob), la règle se tait : la borne
        sera prise à la requête suivante."""
        if epoque >= self._epoque_courante(registre):
            return False
        suivantes = [s for e, s in self._bornes(registre.kv()).items() if e > epoque]
        return bool(suivantes) and seq > min(suivantes)

    def _retour_arriere(
        self,
        registre: _Registre,
        ouverture: Ouverture,
        *,
        server_seq: int | None = None,
    ) -> None:
        """``serverRolledBack`` : rien ne s'écrit plus avant un nouveau
        geste ; le prochain tirage repart de 0 pour repousser ce qui manque.

        Le ``serverSeq`` du serveur revenu devient la référence : sans cela,
        chaque cycle après la reconnexion aurait revu le même recul, et le
        compte serait resté ``serverRolledBack`` pour toujours.

        ``rotationExigee`` retient l'époque de la détection : se reconnecter
        ne suffit pas, le moteur reste arrêté jusqu'à ce que le trousseau
        la dépasse (§3.10, « une rotation est obligatoire »)."""
        valeurs: dict[str, Any] = {
            "curseurDistant": 0,
            "rotationExigee": f"{registre.portee}|{ouverture.trousseau.current_epoch}",
        }
        if server_seq is not None:
            valeurs["serverSeqMax"] = server_seq
        registre.ecrire(**valeurs)
        self._poser_etat(registre, "serverRolledBack")
        logger.warning("compte : le serveur de comptes est revenu en arrière")
        raise _Arret("serverRolledBack")

    def _absents(self, registre: _Registre, vus: set[str]) -> None:
        """Après un tirage COMPLET, ce que cet appareil tenait pour confirmé
        et que le serveur n'a pas montré repart (§3.10 : « repousse ce qui
        manque »)."""
        for connu in registre.connus():
            if connu.object_id in vus:
                continue
            if connu.collection not in self._collections:
                continue
            registre.oublier_empreinte(connu.object_id)
            registre.ajouter_sortant(
                connu.collection,
                connu.id_local,
                registre.plancher_suppression(connu.collection, connu.id_local),
            )

    # --- Accueillir un blob du serveur (tirage, conflit) --------------------

    def _accueillir(
        self,
        registre: _Registre,
        ouverture: Ouverture,
        element: _Element,
        *,
        depuis_conflit: bool = False,
    ) -> None:
        """Le §4.3, pour un élément : réaffirmer, ignorer, quarantaine,
        autoréparation, inconnus, plancher de suppression — ou ingérer.

        ``depuis_conflit`` : le ``current`` d'un conflit, relu pendant la
        poussée — une réparation déjà comptée au tirage ne se recompte pas.
        """
        connu = registre.connu_objet(element.object_id)
        try:
            epoque = lire_en_tete(element.blob).key_epoch
        except EnveloppeIllisible:
            self._illisible(
                registre, ouverture, element, connu, depuis_conflit=depuis_conflit
            )
            return
        if self._epoque_perimee(registre, epoque, element.seq):
            # §2.11 bis : écrit sous une DEK d'avant la rotation, APRÈS elle
            # dans l'ordre du serveur. Le VPS honnête refuse toute écriture
            # d'une autre époque que la courante ; seuls un porteur d'une
            # ancienne DEK (l'appareil perdu) et un VPS complice la
            # fabriquent — connue ou NEUVE, elle n'est jamais ingérée
            # (24/09/2026 : un objet neuf forgé sous la DEK 1 entrait chez
            # un appareil à jour).
            registre.quarantiner(element.object_id, "epoquePerimee", None, self._ms())
            self._illisible(
                registre,
                ouverture,
                element,
                connu,
                quarantaine=False,
                depuis_conflit=depuis_conflit,
            )
            return
        try:
            clair = self._ouvrir(ouverture, element)
        except ObjetPermute:
            # Un clair d'un autre objet sous cet identifiant : rien n'est
            # écrit (§4.12, « quarantaine, rien n'est écrit »). Chez
            # l'appareil qui a la copie, elle réécrase le blob comme un blob
            # illisible (24/09/2026 : sans cela, « Synchronisé » s'affichait
            # pendant que l'objet n'existait plus pour le compte).
            registre.quarantiner(element.object_id, "permute", None, self._ms())
            if connu is not None:
                self._illisible(
                    registre,
                    ouverture,
                    element,
                    connu,
                    quarantaine=False,
                    depuis_conflit=depuis_conflit,
                )
            return
        except ClairInvalide as exc:
            if exc.code == "unknownVersion" and (
                connu is None or element.rev >= connu.rev_max
            ):
                registre.ranger_inconnu(element)
                return
            self._illisible(
                registre, ouverture, element, connu, depuis_conflit=depuis_conflit
            )
            return
        except (EnveloppeIllisible, EpoqueInconnue):
            self._illisible(
                registre, ouverture, element, connu, depuis_conflit=depuis_conflit
            )
            return
        # Les pièces d'abord (§4.7) : l'empreinte se prend sur la forme
        # ATTACHÉE, celle du magasin. Une première passe ne lit que les
        # images déjà ici — l'écho de notre propre poussée, ou une vieille
        # version rejouée, ne télécharge rien ; la seconde, pour une version
        # neuve seulement, demande au VPS ce qui manque.
        collection = self._collection_de(clair)
        references = self._references(collection, clair, epoque)
        locales = self._pieces_locales(collection, clair, epoque)
        clair, transitoire = self._rattacher(
            registre, collection, clair, locales, telecharger=False
        )
        h = empreinte(clair)
        if connu is not None and not connu.illisible and connu.empreinte == h:
            # Exactement ce que cet appareil tient pour confirmé : l'écho de
            # sa propre écriture, même à une révision que le serveur a dû
            # reprendre plus bas après un retour arrière. Reconnue au
            # CONTENU : le ``seq`` n'est pas authentifié.
            self._noter_references(registre, element.object_id, references)
            if element.rev > connu.rev_max:
                registre.noter_connu(
                    connu.collection,
                    connu.id_local,
                    element.object_id,
                    rev=element.rev,
                    seq=element.seq,
                    empreinte_=h,
                )
            registre.lever_quarantaine(element.object_id)
            return
        if connu is not None and element.rev < connu.rev_max:
            # Une vieille version avec sa vraie ``rev`` (§4.12) : pas
            # d'ingestion, et le serveur est réécrasé par la copie d'ici.
            self._reaffirmer(registre, connu, element)
            return
        if (
            connu is not None
            and element.rev == connu.rev_max
            and connu.empreinte is not None
            and epoque < self._epoque_courante(registre)
        ):
            # Deux contenus sous la même révision : le comparer-et-échanger
            # d'un VPS honnête l'interdit. Sous une DEK d'avant la rotation,
            # c'est l'appareil perdu — ingéré, le contenu forgé repartait
            # rescellé sous l'époque COURANTE vers tous les appareils
            # (contre-épreuve du 24/09/2026).
            registre.quarantiner(element.object_id, "epoquePerimee", None, self._ms())
            self._illisible(
                registre,
                ouverture,
                element,
                connu,
                quarantaine=False,
                depuis_conflit=depuis_conflit,
            )
            return
        clair, transitoire = self._rattacher(
            registre, collection, clair, locales, telecharger=True
        )
        self._appliquer(
            registre,
            element,
            clair,
            references=references,
            transitoire=transitoire,
        )

    def _reaffirmer(
        self, registre: _Registre, connu: _Connu, element: _Element
    ) -> None:
        registre.oublier_empreinte(connu.object_id)
        registre.ajouter_sortant(
            connu.collection,
            connu.id_local,
            registre.plancher_suppression(connu.collection, connu.id_local),
        )
        # La base du comparer-et-échanger : la révision que le serveur tient,
        # sans toucher au plancher ``rev_max``.
        self._indices_base[(connu.collection, connu.id_local)] = element.rev

    def _ouvrir(self, ouverture: Ouverture, element: _Element) -> dict[str, Any]:
        try:
            return ouverture.trousseau.ouvrir_objet(
                element.blob,
                account_id=ouverture.account_id,
                incarnation=ouverture.incarnation,
                object_id=element.object_id,
                rev=element.rev,
            )
        except EpoqueInconnue:
            # Une rotation faite ICI pendant le cycle : la serrure tient le
            # trousseau neuf, pas l'ouverture prise au début du cycle.
            neuve = self._service.serrure.exiger()
            return neuve.trousseau.ouvrir_objet(
                element.blob,
                account_id=neuve.account_id,
                incarnation=neuve.incarnation,
                object_id=element.object_id,
                rev=element.rev,
            )

    def _appliquer(
        self,
        registre: _Registre,
        element: _Element,
        clair: dict[str, Any],
        *,
        references: tuple[int, list[str]] | None = None,
        transitoire: bool = False,
    ) -> None:
        """Ingère un clair RATTACHÉ (ou troué) de la version serveur.

        ``references`` : l'époque et les pièces de la version serveur,
        lues sur sa forme détachée ; ``transitoire`` : une pièce n'a pas pu
        être lue maintenant, l'objet revient par ``a_reprendre`` (§4.3)."""
        nom = clair["collection"]
        collection = self._collections.get(nom)
        schema = clair.get("schema")
        if (
            collection is None
            or not isinstance(schema, int)
            or schema > collection.schema
        ):
            # Une collection ou un schéma d'une version plus récente : gardé
            # tel quel, rejoué après la mise à jour (§4.8).
            registre.ranger_inconnu(element)
            return
        id_local = clair["id"]
        h = empreinte(clair)
        registre.lever_quarantaine(element.object_id)
        if "data" in clair:
            plancher = registre.plancher_suppression(nom, id_local)
            try:
                date = collection.date_de(clair)
            except ClairInvalide:
                registre.quarantiner(element.object_id, "invalide", h, self._ms())
                return
            if plancher is not None and date <= plancher:
                # Une copie vivante qui n'a pas vu la suppression que cet
                # appareil connaît (§4.3) : pas d'ingestion, la tombale
                # repart — même purgée d'ici depuis des mois.
                registre.noter_connu(
                    nom,
                    id_local,
                    element.object_id,
                    rev=element.rev,
                    seq=element.seq,
                    empreinte_=h,
                )
                self._noter_references(registre, element.object_id, references)
                registre.ajouter_sortant(nom, id_local, plancher)
                return
        try:
            self._ingerer(collection, clair)
        except ClairInvalide:
            registre.quarantiner(element.object_id, "invalide", h, self._ms())
            return
        if "deleted" in clair:
            registre.relever_plancher_suppression(
                nom, id_local, int(clair["deleted"]["deletedAt"])
            )
        registre.noter_connu(
            nom,
            id_local,
            element.object_id,
            rev=element.rev,
            seq=element.seq,
            empreinte_=h,
        )
        self._noter_references(registre, element.object_id, references)
        # Les trous de CETTE version remplacent ceux d'avant : une tombale
        # ou une version complète les efface (§4.7, « dégradé »).
        registre.poser_trous(nom, id_local, collection.trous(clair))
        if transitoire:
            registre.a_reprendre(
                element.object_id,
                _MOTIF_PIECES,
                self._ms() + int(_REPLI_MIN_S * 1000),
            )
        locale = self._clair_local(registre, collection, id_local)
        if locale is not None and empreinte(locale) != h:
            # La jointure diffère de ce que le serveur tient : elle repart.
            registre.ajouter_sortant(nom, id_local, None)

    def _ingerer(self, collection: Collection, clair: dict[str, Any]) -> None:
        """``clair`` est déjà rattaché : la collection retire elle-même ce
        qui reste troué avant d'écrire (§4.7)."""
        self._fil.ingestion = True
        try:
            collection.ingerer(clair)
        finally:
            self._fil.ingestion = False

    def _illisible(
        self,
        registre: _Registre,
        ouverture: Ouverture,
        element: _Element,
        connu: _Connu | None,
        *,
        quarantaine: bool = True,
        depuis_conflit: bool = False,
    ) -> None:
        """Autoréparation (§4.6) : la copie locale réécrase le blob ; sans
        copie locale, la version précédente ; sans elle, la quarantaine.

        ``rev_max`` ne bouge pas : la révision d'un blob qu'on n'a pas pu
        ouvrir n'est authentifiée par rien. Elle ne sert que de base au
        prochain comparer-et-échanger, le temps du cycle (voir la docstring
        du module — 24/09/2026, une réponse forgée à ``rev = 10**12``
        rendait l'appareil sourd, pour toujours, aux écritures des autres).
        """
        if connu is not None:
            registre.noter_connu(
                connu.collection,
                connu.id_local,
                element.object_id,
                rev=connu.rev_max,
                seq=connu.seq,
                empreinte_=None,
                illisible=True,
            )
            self._indices_base[(connu.collection, connu.id_local)] = element.rev
            collection = self._collections.get(connu.collection)
            if collection is not None and (
                self._sous_les_planchers(
                    registre,
                    collection,
                    connu.id_local,
                    collection.clair_local(connu.id_local),
                )
                is not None
            ):
                registre.ajouter_sortant(
                    connu.collection,
                    connu.id_local,
                    registre.plancher_suppression(connu.collection, connu.id_local),
                )
                # Sous ``rev_max``, c'est une réaffirmation (§4.12), pas une
                # réparation ; et un conflit relit ce que le tirage a déjà
                # compté.
                if not depuis_conflit and element.rev >= connu.rev_max:
                    self._compter_reparation(registre)
                return
        self._depuis_la_precedente(
            registre, ouverture, element, quarantaine=quarantaine
        )

    def _compter_reparation(self, registre: _Registre) -> None:
        kv = registre.kv()
        registre.ecrire(repairedCount=int(kv.get("repairedCount") or 0) + 1)

    def _depuis_la_precedente(
        self,
        registre: _Registre,
        ouverture: Ouverture,
        element: _Element,
        *,
        quarantaine: bool = True,
    ) -> None:
        try:
            reponse = self._requete(
                registre,
                f"/sync/previous/{element.object_id}",
                jeton=self._service.jeton_de_session,
            )
        except ErreurServeur as exc:
            if exc.statut == 404:
                if quarantaine:
                    registre.quarantiner(
                        element.object_id, "illisible", None, self._ms()
                    )
                registre.repris(element.object_id)
                return
            if exc.statut == 401:
                raise
            self._reporter_precedente(registre, element)
            return
        except ServeurInjoignable:
            self._reporter_precedente(registre, element)
            return
        corps = reponse.corps
        precedente = _Element(
            object_id=element.object_id,
            rev=_entier(corps, "rev", minimum=1),
            seq=element.seq,
            blob=_octets(corps.get("blob"), "blob"),
        )
        registre.repris(element.object_id)
        try:
            clair = self._ouvrir(ouverture, precedente)
        except (ErreurCompte, ValueError):
            if quarantaine:
                registre.quarantiner(element.object_id, "illisible", None, self._ms())
            return
        nom = clair["collection"]
        collection = self._collections.get(nom)
        if collection is None:
            registre.ranger_inconnu(precedente)
            return
        epoque = lire_en_tete(precedente.blob).key_epoch
        clair, transitoire = self._rattacher(
            registre,
            collection,
            clair,
            self._pieces_locales(collection, clair, epoque),
            telecharger=True,
        )
        try:
            self._ingerer(collection, clair)
        except ClairInvalide:
            registre.quarantiner(element.object_id, "invalide", None, self._ms())
            return
        registre.poser_trous(nom, clair["id"], collection.trous(clair))
        if transitoire:
            registre.a_reprendre(
                element.object_id,
                _MOTIF_PIECES,
                self._ms() + int(_REPLI_MIN_S * 1000),
            )
        registre.lever_quarantaine(element.object_id)
        # Le blob courant reste illisible : SA révision sert de base, le
        # temps du cycle, et la version relue repart au-dessus. Le plancher
        # ne monte qu'à la révision de la version OUVERTE — ``r`` est dans
        # son AAD ; celle du blob illisible n'est authentifiée par rien.
        registre.noter_connu(
            nom,
            clair["id"],
            element.object_id,
            rev=precedente.rev,
            seq=element.seq,
            empreinte_=None,
            illisible=True,
        )
        self._indices_base[(nom, clair["id"])] = element.rev
        registre.ajouter_sortant(nom, clair["id"], None)
        self._compter_reparation(registre)

    def _reporter_precedente(self, registre: _Registre, element: _Element) -> None:
        """Un échec PASSAGER en relisant la version précédente : le curseur
        avance quand même (§4.3), et l'objet attend dans ``a_reprendre`` —
        avec la révision et le ``seq`` du blob illisible, que la table n'a
        pas de colonne pour garder, dans le motif."""
        registre.a_reprendre(
            element.object_id,
            f"previous:{element.rev}:{element.seq}",
            self._ms() + int(_REPLI_MIN_S * 1000),
        )

    def _reprendre(self, registre: _Registre, ouverture: Ouverture) -> None:
        """Les versions précédentes qu'un échec passager a laissées, et les
        objets d'une collection que cette version ne connaissait pas."""
        for object_id, motif in registre.a_reprendre_dus(self._ms()):
            if motif == _MOTIF_PIECES:
                self._reprendre_pieces(registre, object_id)
                continue
            morceaux = motif.split(":")
            if len(morceaux) != 3 or morceaux[0] != "previous":
                continue
            try:
                rev, seq = int(morceaux[1]), int(morceaux[2])
            except ValueError:
                registre.repris(object_id)
                continue
            element = _Element(object_id=object_id, rev=rev, seq=seq, blob=b"")
            self._depuis_la_precedente(registre, ouverture, element)
        for element in registre.inconnus():
            try:
                clair = self._ouvrir(ouverture, element)
            except ErreurCompte:
                continue
            collection = self._collection_de(clair)
            if collection is not None:
                registre.retirer_inconnu(element.object_id)
                epoque = lire_en_tete(element.blob).key_epoch
                references = self._references(collection, clair, epoque)
                clair, transitoire = self._rattacher(
                    registre,
                    collection,
                    clair,
                    self._pieces_locales(collection, clair, epoque),
                    telecharger=True,
                )
                self._appliquer(
                    registre,
                    element,
                    clair,
                    references=references,
                    transitoire=transitoire,
                )

    # --- Étape 4 : la poussée ------------------------------------------------

    def _pousser(self, registre: _Registre, ouverture: Ouverture) -> Ouverture:
        # Les bases que le tirage a relevées sur des blobs illisibles ou
        # forgés : la révision que tient le serveur, hors de ``rev_max``.
        bases: dict[tuple[str, str], int] = dict(self._indices_base)
        rejeux: dict[tuple[str, str], int] = {}
        laisses: set[tuple[str, str]] = set()
        for _passe in range(_PASSES_MAX):
            if self._arret.is_set():
                raise _Interrompu()
            # Verrouillé pendant le cycle : aucun lot de plus ne se scelle.
            self._verifier_serrure(registre)
            lot = self._preparer_lot(registre, ouverture, bases, laisses)
            if not lot:
                break
            try:
                # Les pièces AVANT l'objet qui les référence (§4.3, étape 4) :
                # poussé d'abord, il aurait existé sur le VPS, le temps d'un
                # dépôt qui échoue, sans ses images — et tout appareil qui
                # l'aurait tiré entre-temps l'aurait gardé dégradé.
                lot = self._deposer_pieces(registre, ouverture, lot, laisses)
                if not lot:
                    continue
                reponse = self._service.client.transport.pousser_objets(
                    incarnation=ouverture.incarnation,
                    key_epoch=ouverture.trousseau.current_epoch,
                    elements=[(e.object_id, e.base, e.blob) for e in lot],
                    jeton=self._service.jeton_de_session,
                )
            except ErreurServeur as exc:
                if exc.code == "keyEpochChanged":
                    # §2.8 : une rotation a eu lieu. Faite ICI, la serrure
                    # tient déjà le trousseau neuf : on rescelle et on
                    # repart. Faite ailleurs, notre session est révoquée et
                    # le 401 viendra à la requête suivante.
                    neuve = self._service.serrure.exiger()
                    if (
                        neuve.trousseau.current_epoch
                        == ouverture.trousseau.current_epoch
                    ):
                        raise _Arret("pending", erreur="keyEpochChanged") from None
                    logger.info("compte : trousseau rechargé après une rotation")
                    ouverture = neuve
                    continue
                if exc.code == "incarnationChanged":
                    registre.ecrire(curseurDistant=0)
                    raise _Arret("pending", erreur="incarnationChanged") from None
                raise
            resultats = reponse.corps.get("results")
            if not isinstance(resultats, list) or len(resultats) != len(lot):
                raise _ReponseInattendue("results")
            meta = _lire_meta(reponse.corps)
            registre.ecrire(serverSeq=meta.server_seq)
            self._voir_seq(registre, meta.server_seq)
            for element, resultat in zip(lot, resultats, strict=True):
                self._issue(
                    registre, ouverture, element, resultat, bases, rejeux, laisses
                )
        return ouverture

    def _preparer_lot(
        self,
        registre: _Registre,
        ouverture: Ouverture,
        bases: dict[tuple[str, str], int],
        laisses: set[tuple[str, str]],
    ) -> list[_Poussee]:
        lot: list[_Poussee] = []
        octets = 0
        octets_pieces = 0
        for nom, id_local, supprime_le_ms in registre.sortants_dus(self._ms()):
            cle = (nom, id_local)
            if cle in laisses:
                continue
            collection = self._collections.get(nom)
            if collection is None:
                continue
            clair = self._clair_local(registre, collection, id_local, supprime_le_ms)
            if clair is None:
                registre.retirer_sortant(nom, id_local)
                continue
            h = empreinte(clair)
            connu = registre.connu(nom, id_local)
            if connu is not None and not connu.illisible and connu.empreinte == h:
                registre.retirer_sortant(nom, id_local)
                continue
            base = bases.get(cle, connu.rev_max if connu is not None else 0)
            trousseau = ouverture.trousseau
            # Détachée sous l'époque COURANTE, au scellement seulement : après
            # une rotation, la prochaine poussée renomme les images et les
            # renvoie sous la DEK neuve (§4.7, « Époques »).
            detache, pieces = collection.detacher(clair, trousseau.identifiant_piece)
            poids = sum(len(octets) for octets in pieces.values())
            try:
                object_id, blob = trousseau.sceller_objet(
                    detache,
                    account_id=ouverture.account_id,
                    incarnation=ouverture.incarnation,
                    rev=base + 1,
                )
            except (ValueError, UnicodeEncodeError, ClairInvalide) as exc:
                # Un identifiant avec un NUL, un texte impossible à encoder :
                # ce n'est pas un échec passager, et le reporter à l'infini
                # empêcherait « Synchronisé » pour toujours sans le dire.
                logger.warning("compte : objet local impossible à sceller (%s)", exc)
                registre.retirer_sortant(nom, id_local)
                continue
            if lot and (
                len(lot) >= _LOT_ELEMENTS
                or octets + len(blob) > _LOT_OCTETS
                or octets_pieces + poids > _LOT_PIECES_OCTETS
            ):
                break
            registre.noter_poussee(nom, id_local, h)
            lot.append(
                _Poussee(
                    collection=nom,
                    id_local=id_local,
                    object_id=object_id,
                    base=base,
                    blob=EnveloppeChiffree(blob),
                    empreinte=h,
                    tombale="deleted" in clair,
                    deleted_at=(
                        int(clair["deleted"]["deletedAt"])
                        if "deleted" in clair
                        else None
                    ),
                    key_epoch=trousseau.current_epoch,
                    references=tuple(collection.pieces(detache)),
                    pieces=pieces,
                )
            )
            octets += len(blob)
            octets_pieces += poids
        return lot

    def _issue(
        self,
        registre: _Registre,
        ouverture: Ouverture,
        element: _Poussee,
        resultat: Any,
        bases: dict[tuple[str, str], int],
        rejeux: dict[tuple[str, str], int],
        laisses: set[tuple[str, str]],
    ) -> None:
        cle = (element.collection, element.id_local)
        statut = resultat.get("status") if isinstance(resultat, dict) else None
        if statut == "stored":
            rev = _entier(resultat, "rev", minimum=1)
            seq = _entier(resultat, "seq", minimum=1)
            if rev != element.base + 1:
                # Le blob porte ``r = base + 1`` dans son AAD : rangé sous une
                # autre révision, il est illisible pour tous. La ligne reste
                # dans ``sortants``, et le prochain tirage le réparera.
                logger.warning("compte : révision rendue différente de celle scellée")
                registre.oublier_empreinte(element.object_id)
                laisses.add(cle)
                return
            registre.noter_connu(
                element.collection,
                element.id_local,
                element.object_id,
                rev=rev,
                seq=seq,
                empreinte_=element.empreinte,
            )
            if element.tombale and element.deleted_at is not None:
                registre.relever_plancher_suppression(
                    element.collection, element.id_local, element.deleted_at
                )
            # La version serveur est désormais la nôtre : ses pièces, et plus
            # celles d'avant — qui deviennent candidates à l'orphelinat.
            self._noter_references(
                registre, element.object_id, (element.key_epoch, element.references)
            )
            if element.tombale:
                registre.poser_trous(element.collection, element.id_local, {})
            registre.lever_quarantaine(element.object_id)
            # Seulement si c'est bien CETTE version qui est partie : une
            # ré-exportation pendant le vol a remis l'empreinte à NULL, et la
            # ligne survit pour la poussée suivante (§4.3).
            registre.retirer_sortant(
                element.collection, element.id_local, si_poussee=element.empreinte
            )
            bases.pop(cle, None)
            return
        if statut == "conflict":
            rejeux[cle] = rejeux.get(cle, 0) + 1
            if rejeux[cle] > _REJEUX_MAX:
                laisses.add(cle)
                return
            courant = resultat.get("current")
            if courant is None:
                bases[cle] = 0
                return
            if not isinstance(courant, dict):
                raise _ReponseInattendue("results.current")
            recu = _Element(
                object_id=element.object_id,
                rev=_entier(courant, "rev", minimum=1),
                seq=_entier(courant, "seq", minimum=1),
                blob=_octets(courant.get("blob"), "results.current.blob"),
            )
            self._accueillir(registre, ouverture, recu, depuis_conflit=True)
            bases[cle] = recu.rev
            return
        if statut == "deferred":
            # §6 bis : le serveur n'a pas examiné cet élément (plafond des
            # conflits dans une réponse) — à renvoyer tel quel.
            rejeux[cle] = rejeux.get(cle, 0) + 1
            if rejeux[cle] > _REJEUX_MAX:
                laisses.add(cle)
            return
        if statut == "rejected":
            code = resultat.get("code")
            code = code if isinstance(code, str) and code else "rejected"
            laisses.add(cle)
            if code == "quotaExceeded":
                registre.reporter_sortant(
                    element.collection,
                    element.id_local,
                    self._ms() + int(_REPLI_MAX_S * 1000),
                    code,
                )
                self._quota = True
                return
            # Un refus de forme (``invalidEnvelope``, ``objectTooLarge``) ne
            # passera pas mieux au prochain cycle : quarantaine VISIBLE, et
            # la prochaine écriture locale le retentera.
            registre.quarantiner(
                element.object_id, _REFUS_LOCAL + code, element.empreinte, self._ms()
            )
            registre.retirer_sortant(element.collection, element.id_local)
            return
        raise _ReponseInattendue("results.status")

    # --- Pièces (§4.7) ---------------------------------------------------------

    def _collection_de(self, clair: dict[str, Any]) -> Collection | None:
        """La collection qui sait lire ce clair, ou ``None`` : collection
        inconnue, ou schéma d'une version plus récente (rangé tel quel dans
        ``inconnus`` par :meth:`_appliquer`, sans rien télécharger)."""
        nom = clair.get("collection")
        collection = self._collections.get(nom) if isinstance(nom, str) else None
        schema = clair.get("schema")
        if (
            collection is None
            or isinstance(schema, bool)
            or not isinstance(schema, int)
            or schema > collection.schema
        ):
            return None
        return collection

    @staticmethod
    def _references(
        collection: Collection | None, clair: dict[str, Any], epoque: int
    ) -> tuple[int, list[str]] | None:
        """Les pièces que référence une version serveur (forme DÉTACHÉE)."""
        if collection is None:
            return None
        return epoque, collection.pieces(clair)

    def _noter_references(
        self,
        registre: _Registre,
        object_id: str,
        references: tuple[int, list[str]] | None,
    ) -> None:
        if references is not None:
            epoque, identifiants = references
            registre.poser_references(object_id, epoque, identifiants)

    def _combler(
        self,
        registre: _Registre,
        collection: Collection,
        id_local: str,
        clair: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """La copie locale avec ses trous (§4.7) : sans eux, l'empreinte
        d'un objet dégradé différait à jamais de celle du serveur, et sa
        première poussée effaçait l'image du VPS."""
        if clair is None or "data" not in clair:
            return clair
        trous = registre.trous(collection.nom, id_local)
        return collection.combler(clair, trous) if trous else clair

    def _clair_local(
        self,
        registre: _Registre,
        collection: Collection,
        id_local: str,
        supprime_le_ms: int | None = None,
    ) -> dict[str, Any] | None:
        """Ce que cet appareil pousserait pour cet objet, forme attachée."""
        return self._sous_les_planchers(
            registre,
            collection,
            id_local,
            self._combler(
                registre, collection, id_local, collection.clair_local(id_local)
            ),
            supprime_le_ms,
        )

    def _pieces_locales(
        self, collection: Collection | None, clair: dict[str, Any], epoque: int
    ) -> Callable[[str], bytes | None]:
        """Les images que CET appareil a déjà pour cette conversation,
        nommées sous l'époque du blob reçu — calculées au premier besoin,
        une fois. L'écho de notre propre poussée se rattache ainsi sans un
        téléchargement."""
        memoire: dict[str, bytes] | None = None

        def lire(piece_id: str) -> bytes | None:
            nonlocal memoire
            if memoire is None:
                memoire = {}
                id_local = clair.get("id")
                locale = (
                    collection.clair_local(id_local)
                    if collection is not None and isinstance(id_local, str)
                    else None
                )
                if locale is not None and "data" in locale:
                    trousseau = self._service.serrure.exiger().trousseau
                    try:
                        _, memoire = collection.detacher(  # type: ignore[union-attr]
                            locale,
                            lambda octets: trousseau.identifiant_piece(octets, epoque),
                        )
                    except EpoqueInconnue:
                        memoire = {}
            return memoire.get(piece_id)

        return lire

    def _rattacher(
        self,
        registre: _Registre,
        collection: Collection | None,
        clair: dict[str, Any],
        locales: Callable[[str], bytes | None],
        *,
        telecharger: bool,
    ) -> tuple[dict[str, Any], bool]:
        """Le clair rattaché (ou troué), et « une pièce a manqué pour une
        raison passagère »."""
        if collection is None or "data" not in clair or not collection.pieces(clair):
            return clair, False
        transitoire = False

        def fournir(piece_id: str) -> bytes | None:
            nonlocal transitoire
            octets = locales(piece_id)
            if octets is not None or not telecharger:
                return octets
            try:
                return self._telecharger(registre, piece_id)
            except _PieceTransitoire:
                transitoire = True
                return None

        return collection.rattacher(clair, fournir), transitoire

    def _telecharger(self, registre: _Registre, piece_id: str) -> bytes | None:
        """Le clair d'une pièce du VPS ; ``None`` si elle n'existe pas ou ne
        s'ouvre pas (l'objet est alors dégradé, jamais reporté : §4.3)."""
        if self._arret.is_set():
            raise _Interrompu()
        try:
            blob = module_pieces.telecharger(
                self._service.client.transport,
                piece_id,
                jeton=self._service.jeton_de_session,
            )
        except ErreurServeur as exc:
            if exc.statut == 401:
                raise
            if exc.statut == 429 or exc.statut >= 500:
                raise _PieceTransitoire() from None
            # 404 : purgée, jamais déposée, ou cachée par le serveur.
            return None
        except ServeurInjoignable:
            raise _PieceTransitoire() from None
        except module_pieces.PieceIllisible:
            logger.warning("compte : pièce plus lourde que permis — ignorée")
            return None
        ouverture = self._verifier_serrure(registre)
        try:
            return module_pieces.ouvrir(
                ouverture.trousseau,
                blob,
                account_id=ouverture.account_id,
                incarnation=ouverture.incarnation,
                piece_id=piece_id,
            )
        except module_pieces.PieceIllisible:
            # Blob refusé, ou contenu d'une autre image sous ce nom : le
            # message reste troué plutôt que de montrer une autre image.
            logger.warning("compte : pièce illisible sur le serveur")
            return None

    def _reprendre_pieces(self, registre: _Registre, object_id: str) -> None:
        connu = registre.connu_objet(object_id)
        collection = None if connu is None else self._collections.get(connu.collection)
        if connu is None or collection is None:
            registre.repris(object_id)
            return
        if self._reparer_trous(registre, collection, connu.id_local):
            registre.a_reprendre(
                object_id, _MOTIF_PIECES, self._ms() + int(_REPLI_MIN_S * 1000)
            )
        else:
            registre.repris(object_id)

    def _reparer_trous(
        self, registre: _Registre, collection: Collection, id_local: str
    ) -> bool:
        """Redemande au VPS les pièces qui manquaient ; rend « encore une
        raison passagère ». Une pièce revenue (redéposée par l'appareil qui
        l'a, à sa réclamation quotidienne) rend l'image au magasin."""
        trous = registre.trous(collection.nom, id_local)
        if not trous:
            return False
        locale = collection.clair_local(id_local)
        if locale is None or "data" not in locale:
            registre.poser_trous(collection.nom, id_local, {})
            return False
        troue = collection.combler(locale, trous)
        rattache, transitoire = self._rattacher(
            registre, collection, troue, lambda _piece: None, telecharger=True
        )
        nouveaux = collection.trous(rattache)
        if nouveaux == trous:
            return transitoire
        connu = registre.connu(collection.nom, id_local)
        self._ingerer(collection, rattache)
        registre.poser_trous(collection.nom, id_local, nouveaux)
        if (
            connu is not None
            and not connu.illisible
            and connu.empreinte == empreinte(troue)
        ):
            # La version serveur n'a pas changé : c'est la même, rattachée.
            # Sans cela, l'écho de cette ingestion la repoussait telle quelle.
            registre.noter_connu(
                collection.nom,
                id_local,
                connu.object_id,
                rev=connu.rev_max,
                seq=connu.seq,
                empreinte_=empreinte(rattache),
            )
        return transitoire

    def _envoyer_pieces(
        self, registre: _Registre, methode: str, chemin: str, corps: dict[str, Any]
    ) -> ReponseServeur:
        """``POST /pieces/missing`` et ``DELETE /pieces/{id}`` : des corps
        JSON sans contenu, par la même porte que les GET de ``_requete``
        (voir sa docstring)."""
        if self._arret.is_set():
            raise _Interrompu()
        transport = self._service.client.transport
        reponse = transport._envoyer(  # noqa: SLF001
            methode, chemin, json_=corps, jeton=self._service.jeton_de_session
        )
        self._verifier_serrure(registre)
        return reponse

    def _reclamer_ids(
        self, registre: _Registre, as_of: int, identifiants: list[str]
    ) -> list[str]:
        """Réclame ces pièces (§3.4) ; rend celles à déposer. Un identifiant
        que le serveur ajouterait à la liste n'est pas pris en compte."""
        reponse = self._envoyer_pieces(
            registre,
            "POST",
            "/pieces/missing",
            {"asOfSeq": as_of, "pieceIds": identifiants},
        )
        manquantes = reponse.corps.get("missing")
        if not isinstance(manquantes, list):
            raise _ReponseInattendue("missing")
        demandees = set(identifiants)
        return [p for p in manquantes if isinstance(p, str) and p in demandees]

    def _deposer(
        self, registre: _Registre, ouverture: Ouverture, piece_id: str, octets: bytes
    ) -> str | None:
        """Scelle et dépose une pièce ; rend le code d'un refus DÉFINITIF
        pour cet objet (quota, forme), ``None`` si elle est déposée."""
        nom, blob = module_pieces.sceller(
            ouverture.trousseau,
            octets,
            account_id=ouverture.account_id,
            incarnation=ouverture.incarnation,
        )
        if nom != piece_id:
            # Nommée sous une autre époque que celle du scellement : le VPS
            # la rangerait sous un nom que personne ne recalcule.
            return "pieceMismatch"
        if len(blob) > module_pieces.PIECE_MAX_OCTETS:
            return "pieceTooLarge"
        try:
            self._service.client.transport.deposer_piece(
                piece_id,
                EnveloppeChiffree(blob),
                jeton=self._service.jeton_de_session,
            )
        except ErreurServeur as exc:
            if exc.code == "quotaExceeded":
                return exc.code
            if exc.statut in (413, 422):
                return exc.code or "invalidEnvelope"
            raise
        self._verifier_serrure(registre)
        # Connue dès le dépôt, pas seulement quand un objet rangé la nomme.
        # Le 24/09/2026, une rotation entre ce PUT et la poussée renvoyait
        # l'objet sous l'époque neuve, et cette pièce — scellée sous la DEK
        # que la rotation retirait — restait sur le VPS, jamais marquée : ni
        # rangée, ni tirée, aucune table ne la nommait. Même sort pour un
        # objet refusé ou supprimé après le dépôt de ses images. Le marquage
        # ne peut pas la frapper trop tôt : ce PUT l'a réclamée après ``S``
        # (409 ``reclaimed``), et ``/pieces/missing`` ranime qui repart.
        registre.connaitre_piece(ouverture.trousseau.current_epoch, piece_id)
        return None

    def _deposer_pieces(
        self,
        registre: _Registre,
        ouverture: Ouverture,
        lot: list[_Poussee],
        laisses: set[tuple[str, str]],
    ) -> list[_Poussee]:
        """« Pièces d'abord » (§4.3) : ``/pieces/missing`` puis le PUT des
        manquantes, sous la clé de l'époque courante. Rend le lot sans les
        objets dont une pièce a été refusée pour de bon.

        La réclamation porte TOUTES les pièces du lot, déjà présentes
        comprises : c'est elle qui fait échouer (409 ``reclaimed``) le
        marquage orphelin qu'un autre appareil tenterait sur la foi d'un
        tirage plus ancien. La déduplication s'y lit aussi : une image déjà
        déposée dans cette époque n'est pas « manquante », et ne repart pas.

        « Toutes », ce sont les RÉFÉRENCES du lot, pas seulement les images
        dont cet appareil a les octets. Jusqu'au 24/09/2026, un appareil
        dégradé (trous remis par ``_combler``) poussait des références sans
        les réclamer : le marquage orphelin concurrent d'un autre appareil,
        daté d'avant, passait, et l'image ne tenait plus qu'à la
        réclamation quotidienne. Une référence « manquante » sans octets
        ici est laissée : la réclamation seule l'a déjà ranimée.
        """
        toutes: dict[str, bytes] = {}
        for element in lot:
            toutes.update(element.pieces)
        identifiants = list(
            dict.fromkeys(
                [*toutes, *(p for element in lot for p in element.references)]
            )
        )
        if not identifiants:
            return lot
        as_of = int(registre.kv().get("curseurDistant") or 0)
        manquantes: list[str] = []
        for debut in range(0, len(identifiants), _RECLAMATION_MAX):
            manquantes.extend(
                self._reclamer_ids(
                    registre, as_of, identifiants[debut : debut + _RECLAMATION_MAX]
                )
            )
        refusees: dict[str, str] = {}
        for piece_id in manquantes:
            if piece_id not in toutes:
                continue
            code = self._deposer(registre, ouverture, piece_id, toutes[piece_id])
            if code is not None:
                refusees[piece_id] = code
        if not refusees:
            return lot
        gardes: list[_Poussee] = []
        for element in lot:
            codes = [refusees[p] for p in element.pieces if p in refusees]
            if not codes:
                gardes.append(element)
                continue
            laisses.add((element.collection, element.id_local))
            if "quotaExceeded" in codes:
                registre.reporter_sortant(
                    element.collection,
                    element.id_local,
                    self._ms() + int(_REPLI_MAX_S * 1000),
                    "quotaExceeded",
                )
                self._quota = True
                continue
            # Un refus de forme ne passera pas mieux au prochain cycle :
            # quarantaine VISIBLE, comme un objet refusé (``_issue``).
            registre.quarantiner(
                element.object_id,
                _REFUS_LOCAL + codes[0],
                element.empreinte,
                self._ms(),
            )
            registre.retirer_sortant(element.collection, element.id_local)
        return gardes

    def _entretien(self, nom: str, action: Callable[[], None]) -> bool:
        """Réclamation et orphelines : un échec passager n'y perd rien (tout
        est repris au cycle suivant) et ne doit pas faire dire « hors ligne »
        à un cycle dont la synchronisation a abouti. Le 401 et
        ``serverBehind`` remontent : ils changent l'état du compte."""
        try:
            action()
        except ErreurServeur as exc:
            if exc.statut == 401 or exc.code == "serverBehind":
                raise
            logger.warning("compte : %s interrompue (%s)", nom, exc.code)
            return False
        except (ServeurInjoignable, _PieceTransitoire):
            logger.warning("compte : %s interrompue (serveur injoignable)", nom)
            return False
        return True

    def _reclamer(self, registre: _Registre, ouverture: Ouverture) -> None:
        """La réclamation quotidienne (§4.7) : au plus une fois par jour,
        après un tirage complet, toutes les pièces que référencent les
        versions serveur que cet appareil connaît.

        Une pièce marquée orpheline — à tort, par un jeton volé (A9), ou
        par un appareil qui a conclu sur un tirage d'avant une réclamation
        — revient « manquante » : si ses octets sont ici, elle est
        redéposée (le PUT la ranime) ; si elle est d'une époque passée, que
        le VPS ne reprend plus, l'objet repart sous l'époque courante. Les
        objets dégradés redemandent aussi leurs pièces : une pièce ranimée
        par un autre appareil leur rend l'image.
        """
        as_of = self._tire_jusqu_a
        if as_of is None:
            return
        maintenant = self._ms()
        derniere = registre.kv().get("reclamationPiecesMs") or ""
        if derniere.isdigit() and 0 <= maintenant - int(derniere) < _RECLAMATION_MS:
            return

        def reclamer() -> None:
            par_piece = registre.toutes_references()
            identifiants = sorted(par_piece)
            manquantes: list[str] = []
            for debut in range(0, len(identifiants), _RECLAMATION_MAX):
                manquantes.extend(
                    self._reclamer_ids(
                        registre, as_of, identifiants[debut : debut + _RECLAMATION_MAX]
                    )
                )
            if manquantes:
                self._ranimer(registre, ouverture, manquantes, par_piece)
            for nom, id_local in registre.objets_troues():
                collection = self._collections.get(nom)
                if collection is not None:
                    self._reparer_trous(registre, collection, id_local)

        if self._entretien("réclamation des pièces", reclamer):
            registre.ecrire(reclamationPiecesMs=maintenant)

    def _ranimer(
        self,
        registre: _Registre,
        ouverture: Ouverture,
        manquantes: list[str],
        par_piece: dict[str, set[str]],
    ) -> None:
        par_objet: dict[str, set[str]] = {}
        for piece_id in manquantes:
            for object_id in par_piece.get(piece_id, ()):
                par_objet.setdefault(object_id, set()).add(piece_id)
        trousseau = ouverture.trousseau
        for object_id, pieces in sorted(par_objet.items()):
            connu = registre.connu_objet(object_id)
            collection = (
                None if connu is None else self._collections.get(connu.collection)
            )
            if connu is None or collection is None:
                continue
            clair = self._clair_local(registre, collection, connu.id_local)
            if clair is None or "data" not in clair:
                continue
            detache, locales = collection.detacher(clair, trousseau.identifiant_piece)
            for piece_id in sorted(pieces & set(locales)):
                code = self._deposer(registre, ouverture, piece_id, locales[piece_id])
                if code is not None:
                    logger.warning("compte : pièce non ranimée (%s)", code)
            if set(collection.pieces(detache)) != registre.references_de(object_id):
                # La version serveur nomme ses images sous une époque passée :
                # elles ne se redéposent plus (409 ``keyEpochChanged``), l'objet
                # repart et les renvoie sous la DEK courante.
                registre.oublier_empreinte(object_id)
                registre.ajouter_sortant(
                    connu.collection,
                    connu.id_local,
                    registre.plancher_suppression(connu.collection, connu.id_local),
                )

    def _marquer_orphelines(self, registre: _Registre) -> None:
        """``DELETE /pieces/{id} {asOfSeq: S}`` pour les pièces que plus
        aucune version serveur connue ne référence (§4.7).

        ``S`` est le ``serverSeq`` jusqu'où CE cycle a tiré sans reste :
        toute réclamation postérieure porte un ``reclame_seq`` plus grand,
        et le serveur refuse (409 ``reclaimed``) — la pièce survit, et reste
        candidate pour le cycle suivant. Nos propres poussées de ce cycle,
        venues après ``S``, n'y changent rien : leurs pièces sont dans
        ``references_pieces``, donc pas candidates.
        """
        as_of = self._tire_jusqu_a
        if as_of is None:
            return

        def marquer() -> None:
            for piece_id in registre.pieces_sans_reference(_ORPHELINES_MAX):
                try:
                    self._envoyer_pieces(
                        registre, "DELETE", f"/pieces/{piece_id}", {"asOfSeq": as_of}
                    )
                except ErreurServeur as exc:
                    if exc.statut == 404:
                        # Déjà purgée, ou jamais arrivée : rien à marquer.
                        registre.oublier_piece(piece_id)
                        continue
                    if exc.code == "reclaimed":
                        # Réclamée depuis S : PAS maintenant, mais la pièce
                        # reste candidate. Le 24/09/2026, l'oublier ici la
                        # perdait pour toujours : la réclamation quotidienne
                        # de CE cycle (avant la poussée) réclame tout, donc
                        # une suppression poussée ce jour-là recevait 409, et
                        # un appareil seul ne la marquait plus jamais — 40
                        # jours plus tard, l'image occupait encore le quota.
                        # Le cycle suivant tire au-delà de la réclamation (elle
                        # consomme un ``seq``) et juge de nouveau.
                        continue
                    raise
                registre.oublier_piece(piece_id)

        self._entretien("marquage des pièces orphelines", marquer)

    # --- Étape 5 : la conclusion --------------------------------------------

    _quota = False

    def _conclure(self, registre: _Registre, meta: _Meta) -> str:
        quota, self._quota = self._quota, False
        if registre.compter_quarantaine(prefixe=_REFUS_LOCAL):
            return self._enregistrer(registre, "quarantined")
        if quota:
            return self._enregistrer(registre, "quotaExceeded", erreur="quotaExceeded")
        if registre.compter("sortants") or registre.compter("a_reprendre"):
            return self._enregistrer(registre, "pending")
        if registre.quarantaine_connue_sans_reparation():
            # Un objet que cet appareil connaît n'existe plus pour le compte
            # sous une forme lisible, et rien ici ne peut le réécrire
            # (24/09/2026 : un blob permuté laissait dire « Synchronisé »).
            return self._enregistrer(registre, "quarantined")
        # §100 : « Synchronisé » ne se dit que sur un ``serverSeq`` que le
        # VPS vient de rendre, file vide, pour la portée courante. Le DERNIER
        # rendu : celui de la poussée quand il y en a eu une — le ``meta`` du
        # tirage, plus ancien, affichait le ``serverSeq`` d'avant nos propres
        # écritures (constaté le 24/09/2026 par le test de ``sync-now``).
        dernier = registre.kv().get("serverSeq")
        registre.ecrire(
            serverSeq=dernier if dernier else meta.server_seq,
            lastConfirmedAt=self._ms(),
        )
        return self._enregistrer(registre, "upToDate")

    def _enregistrer(
        self,
        registre: _Registre,
        etat: str,
        *,
        erreur: str | None = None,
        attente_s: float | None = None,
        echec: bool = False,
    ) -> str:
        if echec or attente_s is not None:
            self._echecs += 1
            if attente_s is None:
                attente_s = min(_REPLI_MAX_S, _REPLI_MIN_S * 2 ** (self._echecs - 1))
                attente_s *= 1 + _GIGUE * (2 * self._hasard() - 1)
            self._repli_jusqu_a = self._mono() + attente_s
            if self._echecs == 1:
                logger.warning("compte : synchronisation interrompue (%s)", erreur)
        else:
            if self._echecs:
                logger.info("compte : synchronisation rétablie")
            self._echecs = 0
            self._repli_jusqu_a = 0.0
        if etat in ETATS_POSES:
            return etat
        registre.ecrire(
            synchroEtat=etat, synchroErreur=erreur, synchroPortee=registre.portee
        )
        return etat

    def _erreur_serveur(self, registre: _Registre, exc: ErreurServeur) -> str:
        if exc.statut == 401:
            # §3.7 : jamais un 401 vers le bundle ; la session est perdue,
            # et ``sessionRevoked`` efface AMK mémorisée, jeton et enveloppe.
            # Pour CE compte seulement : un « Se déconnecter » qui vient de
            # fermer la session sur le VPS vaut aussi un 401 à la requête
            # suivante du cycle, et l'effacement recréait ``etat.key``.
            if not self._service.session_refusee(exc.code, registre.a):
                raise _PorteePerdue() from None
            return "sessionExpired"
        if exc.code == "serverBehind":
            # §6 bis : le serveur n'a pas encore vu notre curseur — tout
            # reprendre depuis 0 au prochain cycle.
            registre.ecrire(curseurDistant=0)
            return self._enregistrer(registre, "pending", erreur=exc.code)
        if exc.code == "serverFull":
            return self._enregistrer(
                registre, "serverFull", erreur=exc.code, attente_s=_REPLI_MAX_S
            )
        if exc.code == "quotaExceeded":
            return self._enregistrer(
                registre, "quotaExceeded", erreur=exc.code, attente_s=_REPLI_MAX_S
            )
        if exc.statut == 429 or exc.statut >= 500:
            # ``serverBusy`` et le 429 de nginx portent ``retryAfterS`` (ou
            # 60 s, §3.9) : c'est lui qui fixe le repli, pas notre doublement.
            attente = float(exc.retry_after_s) if exc.retry_after_s else None
            return self._enregistrer(
                registre, "offline", erreur=exc.code, attente_s=attente, echec=True
            )
        return self._enregistrer(registre, "pending", erreur=exc.code, echec=True)


@dataclass(frozen=True)
class _Poussee:
    collection: str
    id_local: str
    object_id: str
    base: int
    blob: EnveloppeChiffree
    empreinte: bytes
    tombale: bool
    deleted_at: int | None
    key_epoch: int
    references: tuple[str, ...]
    # Le clair de chaque pièce détachée, par ``pieceId``, jusqu'au dépôt.
    pieces: dict[str, bytes] = field(repr=False)


# ----------------------------------------------------------------------
# La tâche du lifespan (§4.3)
# ----------------------------------------------------------------------


async def servir(veilleur: Any, reveil: asyncio.Event) -> None:
    """La boucle du moteur, une fois un compte ouvert.

    Endormie sans délai dès que la serrure se ferme : ``await reveil.wait()``
    et rien d'autre, jusqu'à ce que le service réveille (déverrouillage,
    connexion, consentement). Le travail passe par ``asyncio.to_thread`` :
    un cycle attend le réseau et SQLite, et ce qu'une tâche ``async`` fait
    en ligne gèle toute la boucle — le WebSocket vocal, le flux du chat
    (CLAUDE.md §5). Ce n'est pas le ``TaskScheduler``, qui passe derrière le
    créneau unique d'Ollama (``-np 1``).
    """
    branche: Any = None
    while True:
        reveil.clear()
        service = getattr(veilleur, "service", None)
        moteur = getattr(service, "moteur", None)
        if moteur is None or not await asyncio.to_thread(moteur.actif):
            if moteur is not None:
                moteur.eveille = False
            await reveil.wait()
            continue
        if moteur is not branche:
            moteur.brancher(veilleur.magasin, veilleur.reveiller)
            branche = moteur
        moteur.eveille = True
        veilleur.urgent = False
        try:
            await asyncio.to_thread(moteur.cycle)
            await asyncio.to_thread(moteur.purger_si_du)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - la boucle ne doit jamais mourir
            logger.exception("compte : cycle de synchronisation en échec")
        await _attendre_la_suite(moteur, veilleur, reveil)


async def _attendre_la_suite(moteur: Any, veilleur: Any, reveil: asyncio.Event) -> None:
    """Jusqu'au prochain tirage, au repli, ou à une écriture calmée."""
    try:
        await asyncio.wait_for(reveil.wait(), timeout=moteur.attente_avant_suite())
    except TimeoutError:
        return
    if veilleur.urgent:
        return
    # Une écriture : attendre _CALME_S de silence, au plus _POUSSEE_MAX_S.
    debut = moteur._mono()  # noqa: SLF001
    while True:
        maintenant = moteur._mono()  # noqa: SLF001
        calme = _CALME_S - (maintenant - moteur.derniere_ecriture)
        plafond = _POUSSEE_MAX_S - (maintenant - debut)
        repli = moteur.repli_restant()
        attente = max(min(calme, plafond), repli)
        if attente <= 0 or veilleur.urgent:
            return
        reveil.clear()
        try:
            await asyncio.wait_for(reveil.wait(), timeout=attente)
        except TimeoutError:
            pass
