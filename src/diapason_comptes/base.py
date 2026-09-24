"""La base SQLite du service, complète dès la naissance.

Conception : ``docs/development/compte-chiffre.md`` §3.3.

Aucune migration SQLite n'existe dans ce projet (CLAUDE.md §5) : le schéma
porte dès la v1 les tables de la synchronisation (``objets``, ``pieces``),
que l'étape 5 remplira. Une seule connexion, protégée par un verrou, comme
``conversations_store.py`` : les routes sont des ``def`` exécutées dans le
pool de Starlette, et deux fils sur une connexion SQLite sans verrou se
marchent dessus.
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_journal = logging.getLogger("diapason_comptes.base")

JOUR_MS = 86_400_000

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS comptes (
  id                  TEXT PRIMARY KEY,
  courriel_index      BLOB NOT NULL UNIQUE,
  courriel_chiffre    BLOB NOT NULL,
  cree_jour           INTEGER NOT NULL,
  conditions_version  INTEGER NOT NULL,
  secrets_version     INTEGER NOT NULL,
  kdf_version         INTEGER NOT NULL,
  sel_kdf             BLOB NOT NULL,
  verif_auth          BLOB NOT NULL,
  amk_mdp             BLOB NOT NULL,
  verif_recup         BLOB,
  amk_recup           BLOB,
  version_coffre      INTEGER NOT NULL,
  trousseau           BLOB NOT NULL,
  version_trousseau   INTEGER NOT NULL,
  epoque_cle          INTEGER NOT NULL DEFAULT 1,
  incarnation         INTEGER NOT NULL DEFAULT 1,
  seq                 INTEGER NOT NULL DEFAULT 0,
  octets              INTEGER NOT NULL DEFAULT 0,
  quota_octets        INTEGER NOT NULL,
  reinit_demandee_ms  INTEGER,
  reinit_effective_ms INTEGER
);

CREATE TABLE IF NOT EXISTS codes (courriel_index BLOB NOT NULL,
  but TEXT NOT NULL CHECK (but IN ('inscription','coffre','reinitialisation')),
  code_mac BLOB NOT NULL, expire_ms INTEGER NOT NULL,
  essais INTEGER NOT NULL DEFAULT 0, consomme_ms INTEGER,
  PRIMARY KEY (courriel_index, but));

CREATE TABLE IF NOT EXISTS jetons_temporaires (hash BLOB PRIMARY KEY,
  but TEXT NOT NULL CHECK (but IN ('inscription','recuperation')),
  courriel_index BLOB NOT NULL, compte_id TEXT, expire_ms INTEGER NOT NULL,
  consomme_ms INTEGER);

CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY,
  compte_id TEXT NOT NULL REFERENCES comptes(id) ON DELETE CASCADE,
  jeton_hash BLOB NOT NULL UNIQUE, nom_chiffre BLOB,
  cree_jour INTEGER NOT NULL, vu_jour INTEGER NOT NULL, expire_ms INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS objets (
  compte_id TEXT NOT NULL REFERENCES comptes(id) ON DELETE CASCADE,
  objet_id TEXT NOT NULL, rev INTEGER NOT NULL, seq INTEGER NOT NULL,
  blob BLOB NOT NULL,
  blob_precedent BLOB, rev_precedente INTEGER, precedent_jour INTEGER,
  PRIMARY KEY (compte_id, objet_id));
CREATE INDEX IF NOT EXISTS objets_seq ON objets (compte_id, seq);

CREATE TABLE IF NOT EXISTS pieces (
  compte_id TEXT NOT NULL REFERENCES comptes(id) ON DELETE CASCADE,
  piece_id TEXT NOT NULL, blob BLOB NOT NULL,
  reclame_seq INTEGER NOT NULL,
  orpheline_jour INTEGER,
  PRIMARY KEY (compte_id, piece_id));

CREATE TABLE IF NOT EXISTS limites (cle BLOB PRIMARY KEY, echecs INTEGER NOT NULL,
  debut_ms INTEGER NOT NULL, bloque_jusqua_ms INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS envois (cle BLOB PRIMARY KEY, minute INTEGER, heure INTEGER,
  jour INTEGER, fenetre_ms INTEGER NOT NULL);
"""

# Les colonnes de ``comptes`` dans l'ordre du schéma : ``Compte`` les lit
# par nom, le journal les recopie toutes (§3.3, « ligne complète »).
COLONNES_COMPTE = (
    "id",
    "courriel_index",
    "courriel_chiffre",
    "cree_jour",
    "conditions_version",
    "secrets_version",
    "kdf_version",
    "sel_kdf",
    "verif_auth",
    "amk_mdp",
    "verif_recup",
    "amk_recup",
    "version_coffre",
    "trousseau",
    "version_trousseau",
    "epoque_cle",
    "incarnation",
    "seq",
    "octets",
    "quota_octets",
    "reinit_demandee_ms",
    "reinit_effective_ms",
)


def jour(ms: int) -> int:
    """Le numéro du jour UTC : le service ne garde aucune heure par session
    ni par objet (§3.3), seulement des jours."""
    return ms // JOUR_MS


def _chemin_valide(chemin: object) -> Path:
    # ``Path(MagicMock())`` rend « MagicMock/<nom>/<id> » : 42 vraies bases
    # SQLite ont dormi à la racine du dépôt avant ce garde (CLAUDE.md §5).
    if not isinstance(chemin, (str, os.PathLike)):
        raise TypeError(f"chemin de base invalide : {type(chemin).__name__}")
    resultat = Path(chemin)
    if "MagicMock" in str(resultat):
        raise TypeError("chemin de base issu d'un MagicMock")
    return resultat


@dataclass(frozen=True)
class Compte:
    """Une ligne de ``comptes``, colonnes sous leur nom de schéma."""

    id: str
    courriel_index: bytes
    courriel_chiffre: bytes
    cree_jour: int
    conditions_version: int
    secrets_version: int
    kdf_version: int
    sel_kdf: bytes
    verif_auth: bytes
    amk_mdp: bytes
    verif_recup: bytes | None
    amk_recup: bytes | None
    version_coffre: int
    trousseau: bytes
    version_trousseau: int
    epoque_cle: int
    incarnation: int
    seq: int
    octets: int
    quota_octets: int
    reinit_demandee_ms: int | None
    reinit_effective_ms: int | None

    def __repr__(self) -> str:  # jamais de vérificateur dans une trace
        return f"Compte(id={self.id!r}, incarnation={self.incarnation})"

    @property
    def reinitialisation_attendue(self) -> int | None:
        """``pendingResetAt`` (§3.6) : l'heure où ``reset/complete`` devient
        permis, ou ``None`` si aucune réinitialisation n'est en attente."""
        if self.reinit_demandee_ms is None:
            return None
        return self.reinit_effective_ms


_SELECT_COMPTE = "SELECT " + ", ".join(COLONNES_COMPTE) + " FROM comptes"


def _compte(ligne: tuple | None) -> Compte | None:
    if ligne is None:
        return None
    return Compte(**dict(zip(COLONNES_COMPTE, ligne, strict=True)))


class Base:
    """``comptes.db`` : une connexion, un verrou, un schéma complet."""

    def __init__(self, chemin: object) -> None:
        self.chemin = _chemin_valide(chemin)
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self._verrou = threading.RLock()
        self._rappels_annulation: list[Callable[[], None]] | None = None
        self._conn = sqlite3.connect(
            str(self.chemin), check_same_thread=False, isolation_level=None
        )
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        # ``secure_delete`` : un compte supprimé est écrasé de zéros dans les
        # pages, pas seulement marqué libre (§3.3, P8). Sans lui, l'adresse
        # chiffrée et les enveloppes dormaient dans le fichier jusqu'à ce
        # qu'une page soit réutilisée.
        self._conn.execute("PRAGMA secure_delete = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        # ``executescript`` valide d'abord toute transaction ouverte : il ne
        # peut pas vivre dans ``transaction()``. Chaque ordre est idempotent.
        with self._verrou:
            self._conn.executescript(SCHEMA)
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO meta (cle, valeur) VALUES ('schema', ?)",
                (SCHEMA_VERSION,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta (cle, valeur) VALUES ('generation', ?)",
                (secrets.token_hex(16),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta (cle, valeur) VALUES ('globalSeq', '0')"
            )

    # --- Transactions ---------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE`` … ``COMMIT``, ou ``ROLLBACK`` sur exception —
        y compris quand c'est le ``COMMIT`` qui échoue.

        Jusqu'au 24/09/2026, un ``COMMIT`` refusé (disque plein, ``IOERR``)
        sortait sans ``ROLLBACK`` : l'unique connexion restait dans sa
        transaction, et chaque requête suivante échouait sur ``BEGIN`` en
        500 jusqu'au redémarrage du service. Les rappels de
        :meth:`si_annulee` s'exécutent alors : le journal y marque annulée la
        ligne qu'il a déjà écrite (§3.3).
        """
        with self._verrou:
            self._conn.execute("BEGIN IMMEDIATE")
            self._rappels_annulation = []
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                for rappel in self._rappels_annulation:
                    try:
                        rappel()
                    except Exception as exc:
                        # Le disque qui a refusé le COMMIT peut refuser aussi
                        # la marque d'annulation : l'erreur d'origine prime.
                        _journal.error(
                            "annulation non journalisée : %s", type(exc).__name__
                        )
                raise
            finally:
                self._rappels_annulation = None

    def si_annulee(self, rappel: Callable[[], None]) -> None:
        """Appelle ``rappel`` si la transaction EN COURS n'est pas validée.
        Hors transaction, ne fait rien : il n'y a rien à annuler."""
        if self._rappels_annulation is not None:
            self._rappels_annulation.append(rappel)

    @contextmanager
    def lecture(self) -> Iterator[sqlite3.Connection]:
        with self._verrou:
            yield self._conn

    def fermer(self) -> None:
        with self._verrou:
            self._conn.close()

    def point_de_controle(self) -> None:
        """Vide le WAL dans la base et le tronque.

        Après une suppression de compte : ``secure_delete`` écrase les pages
        de la BASE, mais les anciennes versions de ces pages restent dans le
        fichier ``-wal`` jusqu'au prochain point de contrôle automatique,
        mille pages plus tard. « Effacement immédiat » (§3.4) exige de le
        forcer.
        """
        with self._verrou:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # --- Taille (garde globale, §3.5) ------------------------------------

    def taille_octets(self) -> int:
        total = 0
        for suffixe in ("", "-wal"):
            try:
                total += os.path.getsize(str(self.chemin) + suffixe)
            except OSError:
                pass
        return total


# ----------------------------------------------------------------------
# meta
# ----------------------------------------------------------------------


def lire_meta(conn: sqlite3.Connection, cle: str) -> str:
    ligne = conn.execute("SELECT valeur FROM meta WHERE cle = ?", (cle,)).fetchone()
    if ligne is None:
        raise LookupError(f"meta sans « {cle} »")
    return ligne[0]


def generation(conn: sqlite3.Connection) -> str:
    return lire_meta(conn, "generation")


def global_seq(conn: sqlite3.Connection) -> int:
    return int(lire_meta(conn, "globalSeq"))


def ecriture(conn: sqlite3.Connection) -> int:
    """Incrémente ``globalSeq`` et le rend.

    Ce compteur monotone permet à un appareil de voir qu'une restauration de
    TOUTE la machine a fait reculer le serveur (§3.10) : ``generation`` ne
    change pas, mais ``globalSeq`` recule sous le maximum qu'il a vu.
    """
    conn.execute(
        "UPDATE meta SET valeur = CAST(CAST(valeur AS INTEGER) + 1 AS TEXT) "
        "WHERE cle = 'globalSeq'"
    )
    return global_seq(conn)


# ----------------------------------------------------------------------
# comptes
# ----------------------------------------------------------------------


def lire_compte(conn: sqlite3.Connection, compte_id: str) -> Compte | None:
    return _compte(
        conn.execute(_SELECT_COMPTE + " WHERE id = ?", (compte_id,)).fetchone()
    )


def compte_par_indices(conn: sqlite3.Connection, indices: list[bytes]) -> Compte | None:
    """Le compte dont l'index vaut l'un des ``indices`` (un par version de
    poivre encore déclarée), ou ``None``."""
    trous = ", ".join("?" for _ in indices)
    ligne = conn.execute(
        _SELECT_COMPTE + f" WHERE courriel_index IN ({trous})", tuple(indices)
    ).fetchone()
    return _compte(ligne)


def ecrire_compte(conn: sqlite3.Connection, compte: Compte) -> None:
    """INSERT ou remplacement complet d'une ligne — le journal s'en sert pour
    rejouer un coffre (§3.10)."""
    valeurs = tuple(getattr(compte, nom) for nom in COLONNES_COMPTE)
    trous = ", ".join("?" for _ in COLONNES_COMPTE)
    affectations = ", ".join(f"{nom} = excluded.{nom}" for nom in COLONNES_COMPTE[1:])
    conn.execute(
        f"INSERT INTO comptes ({', '.join(COLONNES_COMPTE)}) VALUES ({trous}) "
        f"ON CONFLICT(id) DO UPDATE SET {affectations}",
        valeurs,
    )


# ----------------------------------------------------------------------
# Garde globale (§3.5, D10)
# ----------------------------------------------------------------------


def espace_libre_reel(chemin: Path) -> int:
    return shutil.disk_usage(chemin).free


def garde_depassee(
    base: Base,
    *,
    garde_base_octets: int,
    garde_disque_libre_octets: int,
    chemin_disque: Path,
    espace_libre: Callable[[Path], int] = espace_libre_reel,
) -> bool:
    """Vrai si la base dépasse sa garde, ou si « / » n'a plus sa marge.

    Flashprime tourne en production sur ce même disque (CLAUDE.md §5) : un
    disque plein chez Diapason est une panne chez lui.
    """
    if base.taille_octets() > garde_base_octets:
        return True
    return espace_libre(chemin_disque) < garde_disque_libre_octets
