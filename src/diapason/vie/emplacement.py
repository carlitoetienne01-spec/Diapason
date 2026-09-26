"""Où vit la base du domaine vie, et son passage de succes.db à vie.db.

25/09/2026, étape 5 du plan de la phase 1b (docs/development/
diapason-mobile.md). Le domaine s'appelle ``vie`` ; sa base s'appelait
``succes.db`` et ses photos ``succes-photos/``. Trois défauts guettaient ce
renommage, chacun silencieux :

- une migration lancée par ``tick`` (toutes les 900 s, depuis l'arbre de
  travail) pendant que l'ancien serveur tourne : ce dernier recrée une
  ``succes.db`` vide, avec un nouveau ``device_id``, et les écritures se
  coupent en deux bases ;
- la base renommée sans ses photos : les 62 aperçus deviennent ``""``
  (``photos._data_url``), sans une erreur ;
- un magasin construit avant la migration, qui garde l'ancien chemin.

D'où les règles : **seul ``diapason serve`` migre** (``cli/serve.py``,
avant toute construction de magasin), sous un verrou de fichier ; tout autre
ouvrant prend ``vie.db`` si elle existe, sinon ``succes.db``, et ne crée
``vie.db`` que si aucune des deux n'existe. Un magasin n'ouvre plus en
création une base censée exister (``VieStore._connect``, ``mode=rw``).

Étape 6 (même jour) : les 26 tables ``succes_*`` deviennent ``vie_*``, dans la
même migration et sous le même verrou, après la même sauvegarde. Un ouvrant
autre que le serveur qui trouve encore une table ``succes_*`` refuse
(:class:`~diapason.vie.store.BaseVieNonMigree`) au lieu de créer des tables
``vie_*`` vides à côté des pleines.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from diapason.vie.store import (
    PREFIXE_TABLES,
    PREFIXE_TABLES_HERITE,
    VERSION_SCHEMA,
    BaseVieNonMigree,
    VieError,
    tables_heritees,
)

logger = logging.getLogger(__name__)

NOM_BASE = "vie.db"
NOM_BASE_HERITE = "succes.db"
DOSSIER_PHOTOS = "vie-photos"
DOSSIER_PHOTOS_HERITE = "succes-photos"
NOM_VERROU = ".vie-migration.lock"
DOSSIER_SAUVEGARDES = "backups"

# L'attente du verrou de migration. La migration réelle est une sauvegarde
# `conn.backup()` et un renommage : mesurée à 0,26 s pour une base de 310 Mo
# sur ce Mac (25/09/2026 ; succes.db en pèse 311). Trente secondes laissent
# cent fois la marge à un second `serve` lancé en même temps, sans qu'un
# verrou tenu par un processus bloqué fige le démarrage indéfiniment.
_ATTENTE_VERROU_S = 30.0

# Les tables qui disent « quelqu'un a écrit ici ». Une base neuve n'est pas
# vide au sens de `count(*)` : le constructeur y sème 19 catégories de
# finances, un compte et deux lignes de méta. Compter celles-là ferait
# prendre une base fantôme (recréée vide par un vieux processus) pour une
# base pleine, et toute la vie passerait en 503 pour rien.
_TABLES_DE_DONNEES = (
    "operations",
    "tasks",
    "subtasks",
    "projects",
    "task_edges",
    "task_templates",
    "habits",
    "habit_logs",
    "notes",
    "photos",
    "photo_piles",
    "quotes",
    "transactions",
    "subscriptions",
    "budgets",
    "savings_goals",
    "imports",
)

# Sous Windows, un fichier ouvert ailleurs refuse `os.replace` ; trois essais
# espacés de 0,2 s couvrent un antivirus qui relâche le fichier, pas un
# processus qui le tient — celui-là reporte la migration au démarrage suivant.
_ESSAIS_REMPLACEMENT = 3
_PAUSE_REMPLACEMENT_S = 0.2


class DeuxBasesVie(VieError):
    """succes.db et vie.db portent toutes deux des données.

    Aucune des deux n'est choisie à la place de l'utilisateur : fusionner
    deux historiques de tâches n'est pas une décision qu'un démarrage prend.
    """

    def __init__(self, data_dir: Path) -> None:
        super().__init__(
            "Deux bases de vie existent dans "
            f"{data_dir} ({NOM_BASE_HERITE} et {NOM_BASE}), et toutes deux "
            "contiennent des données. Rien n'a été déplacé ni fusionné : "
            f"mettez de côté celle qu'il ne faut pas garder (dans "
            f"{DOSSIER_SAUVEGARDES}/), puis relancez le serveur."
        )
        self.data_dir = data_dir


@dataclass(frozen=True)
class Migration:
    """Ce que le démarrage a fait de la base, dit une fois dans le journal."""

    etat: str  # neuve | deja_faite | migree | reportee | deux_bases | ignoree_en_test
    chemin: Path
    detail: str = ""
    photos: int = 0


# ── résolution (sans effet de bord) ─────────────────────────────────────


def a_des_donnees(chemin: Path) -> bool:
    """La base porte-t-elle une écriture de l'utilisateur ? Lecture seule.

    Ouverte en ``mode=rw`` (jamais ``rwc`` : rien ne se crée) plutôt qu'en
    ``ro`` : une connexion ``ro`` sur une base WAL laisse derrière elle un
    ``-wal`` et un ``-shm`` qu'elle n'a pas le droit d'effacer (constaté le
    25/09/2026), et une simple question aurait semé des fichiers.
    """
    if not chemin.exists():
        return False
    try:
        with closing(
            sqlite3.connect(
                f"{chemin.absolute().as_uri()}?mode=rw", uri=True, timeout=5
            )
        ) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for suffixe in _TABLES_DE_DONNEES:
                for prefixe in (PREFIXE_TABLES, PREFIXE_TABLES_HERITE):
                    table = prefixe + suffixe
                    if (
                        table in tables
                        and conn.execute(
                            f"SELECT 1 FROM {table} LIMIT 1"  # noqa: S608 - nom tiré de sqlite_master
                        ).fetchone()
                    ):
                        return True
    except sqlite3.DatabaseError:
        # Une base illisible n'est pas « vide » : la déclarer vide la ferait
        # mettre de côté, et une base corrompue se répare, elle ne se jette pas.
        return True
    return False


def migration_en_attente(data_dir: Path) -> bool:
    """Reste-t-il une succes.db, ou des tables succes_* dans vie.db ?

    Lecture seule, rien ne se crée (``mode=rw``, voir :func:`a_des_donnees`).
    Une base illisible compte comme « en attente » : c'est la prudence qui
    fait sonder un serveur voisin avant d'y toucher.
    """
    data_dir = Path(data_dir)
    if (data_dir / NOM_BASE_HERITE).exists():
        return True
    neuve = data_dir / NOM_BASE
    if not neuve.exists():
        return False
    try:
        with closing(
            sqlite3.connect(f"{neuve.absolute().as_uri()}?mode=rw", uri=True, timeout=5)
        ) as conn:
            return bool(tables_heritees(conn))
    except sqlite3.DatabaseError:
        return True


def chemin_base_vie(data_dir: Path, *, migrer: bool = False) -> Path:
    """Le fichier de la base vie dans ``data_dir``.

    ``migrer=False`` (tout le monde sauf ``diapason serve``) : ``vie.db`` si
    elle existe, sinon ``succes.db``, sinon ``vie.db`` à créer. Rien n'est
    déplacé ni créé. Si les deux existent, la pleine gagne ; si les deux
    sont pleines, :class:`DeuxBasesVie`.

    ``migrer=True`` : :func:`migrer_base_vie`, puis la même résolution.
    """
    data_dir = Path(data_dir)
    if migrer:
        migrer_base_vie(data_dir)
    neuve = data_dir / NOM_BASE
    herite = data_dir / NOM_BASE_HERITE
    if not herite.exists():
        return neuve
    if not neuve.exists():
        return herite
    pleine_neuve, pleine_herite = a_des_donnees(neuve), a_des_donnees(herite)
    if pleine_neuve and pleine_herite:
        raise DeuxBasesVie(data_dir)
    return herite if pleine_herite else neuve


def dossier_photos_pour(chemin_base: Path) -> Path:
    """Le dossier des photos qui accompagne une base.

    Une ``succes.db`` pas encore migrée garde ``succes-photos`` : y ranger les
    nouvelles photos dans ``vie-photos`` les séparerait de leurs sœurs, et la
    migration trouverait deux dossiers à réconcilier.
    """
    nom = (
        DOSSIER_PHOTOS_HERITE
        if chemin_base.name == NOM_BASE_HERITE
        else (DOSSIER_PHOTOS)
    )
    return chemin_base.parent / nom


# ── migration (diapason serve seulement) ────────────────────────────────


@contextmanager
def _verrou_exclusif(chemin: Path) -> Iterator[bool]:
    """Le verrou de migration ; rend False s'il n'a pas pu être pris.

    Deux ``serve`` lancés ensemble (un kickstart pendant un démarrage à la
    main) migreraient deux fois : le second trouverait ``succes.db`` à
    moitié déplacée. ``fcntl`` sur macOS et Linux, ``msvcrt`` sous Windows.
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(chemin, os.O_RDWR | os.O_CREAT, 0o600)
    tenu = False
    try:
        limite = time.monotonic() + _ATTENTE_VERROU_S
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt  # noqa: PLC0415

                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl  # noqa: PLC0415

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                tenu = True
                break
            except OSError:
                if time.monotonic() >= limite:
                    break
                time.sleep(0.05)
        yield tenu
    finally:
        if tenu:
            try:
                if sys.platform == "win32":
                    import msvcrt  # noqa: PLC0415

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl  # noqa: PLC0415

                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def _compagnons(chemin: Path) -> list[Path]:
    return [chemin.with_name(chemin.name + s) for s in ("-wal", "-shm", "-journal")]


def _cible_sauvegarde(data_dir: Path, nom: str) -> Path:
    dossier = data_dir / DOSSIER_SAUVEGARDES
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / nom
    if cible.exists():
        # Deux migrations le même jour (une restauration entre les deux) :
        # écraser la première sauvegarde détruirait la seule copie d'avant.
        cible = dossier / f"{nom}-{datetime.now():%H%M%S}"
    return cible


def _rendre_exclusive(conn: sqlite3.Connection) -> str | None:
    """Vider le WAL et quitter le mode WAL ; la raison d'un refus, sinon None.

    La bascule ``journal_mode=DELETE`` exige d'être la SEULE connexion : elle
    sert donc de test d'exclusivité. Constaté le 25/09/2026 : une seconde
    connexion, même oisive, la fait échouer en « database is locked ».
    """
    try:
        occupe, _, _ = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if occupe:
            return "le journal WAL n'a pas pu être vidé (une connexion lit encore)"
        mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
    except sqlite3.OperationalError as exc:
        return f"une autre connexion tient la base ({exc})"
    if str(mode).lower() != "delete":
        return f"la base est restée en mode {mode}"
    return None


def _mettre_de_cote(data_dir: Path, chemin: Path, etiquette: str) -> str | None:
    """Déplacer une base vide dans backups/ ; la raison d'un refus, sinon None."""
    with closing(sqlite3.connect(chemin, timeout=0.5)) as conn:
        refus = _rendre_exclusive(conn)
    if refus:
        return refus
    cible = _cible_sauvegarde(
        data_dir, f"{chemin.name}.{etiquette}-{datetime.now():%Y%m%d%H%M%S}"
    )
    os.replace(chemin, cible)
    for compagnon in _compagnons(chemin):
        if compagnon.exists():
            suffixe = compagnon.name[len(chemin.name) :]
            os.replace(compagnon, cible.with_name(cible.name + suffixe))
    return None


def _remplacer(source: Path, cible: Path) -> bool:
    for essai in range(_ESSAIS_REMPLACEMENT):
        try:
            os.replace(source, cible)
            return True
        except PermissionError:
            if essai + 1 < _ESSAIS_REMPLACEMENT:
                time.sleep(_PAUSE_REMPLACEMENT_S)
    return False


def _migrer_fichier(data_dir: Path) -> str | None:
    """succes.db → vie.db ; la raison d'un report, sinon None."""
    herite = data_dir / NOM_BASE_HERITE
    neuve = data_dir / NOM_BASE
    with closing(sqlite3.connect(herite, timeout=0.5)) as conn:
        refus = _rendre_exclusive(conn)
        if refus:
            return refus
        sauvegarde = _cible_sauvegarde(
            data_dir, f"{NOM_BASE_HERITE}.avant-vie-{datetime.now():%Y%m%d}"
        )
        with closing(sqlite3.connect(sauvegarde)) as copie:
            conn.backup(copie)
        # Les tables, sur la même connexion exclusive et après la même
        # sauvegarde : une seule copie d'avant couvre les deux renommages.
        try:
            renommer_tables(conn)
        except sqlite3.DatabaseError as exc:
            # Le fichier ne bouge pas non plus : une vie.db aux tables
            # succes_* serait refusée par tous les ouvrants, sous un nom neuf
            # qui laisserait croire la migration faite.
            return f"tables non renommées ({exc})"
    restes = [c.name for c in _compagnons(herite) if c.exists()]
    if restes:
        # Quelqu'un a rouvert la base entre la bascule et la fermeture : la
        # déplacer maintenant laisserait son journal orphelin sous l'ancien
        # nom, et ses écritures hors de vie.db.
        return f"{', '.join(restes)} réapparu(s) après la fermeture"
    if not _remplacer(herite, neuve):
        return "le fichier est tenu par un autre processus (Windows)"
    logger.warning(
        "vie : %s renommée en %s ; sauvegarde d'avant dans %s",
        NOM_BASE_HERITE,
        NOM_BASE,
        sauvegarde,
    )
    return None


def _nom_neuf(nom: str) -> str:
    """``succes_tasks_date_idx`` → ``vie_tasks_date_idx`` ; ``idx_succes_txn_date``
    → ``idx_vie_txn_date``. Les noms d'index suivent ceux des tables : les
    laisser dériver ferait créer par le schéma neuf un second index identique
    sur chaque table, et vie_operations pèse 306 Mo sur 311 (25/09/2026)."""
    return nom.replace(PREFIXE_TABLES_HERITE, PREFIXE_TABLES, 1)


def renommer_tables(conn: sqlite3.Connection) -> int:
    """succes_* → vie_*, en une transaction ; rend le nombre de tables.

    ``ALTER TABLE … RENAME`` suit de lui-même les clés étrangères, les index
    automatiques et ``sqlite_sequence`` (vérifié le 25/09/2026 sur SQLite
    3.53) ; il ne renomme pas les index nommés, ni les déclencheurs et les
    vues : ceux-là sont recréés sous leur nom neuf. Tout ou rien : une table
    renommée sans ses sœurs couperait les jointures en deux.

    Idempotente : une base sans table ``succes_*`` rend 0 sans rien écrire.
    Une base qui porte À LA FOIS ``succes_x`` et ``vie_x`` n'est pas touchée
    (``sqlite3.DatabaseError``) : choisir l'une des deux perdrait l'autre.
    """
    heritees = tables_heritees(conn)
    if not heritees:
        return 0
    existantes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    doublons = [_nom_neuf(t) for t in heritees if _nom_neuf(t) in existantes]
    if doublons:
        raise sqlite3.DatabaseError(
            f"{', '.join(doublons)} existe(nt) aussi sous l'ancien nom "
            f"{PREFIXE_TABLES_HERITE}* : rien n'est renommé, c'est à trancher "
            "à la main"
        )
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table in heritees:
            conn.execute(f'ALTER TABLE "{table}" RENAME TO "{_nom_neuf(table)}"')
        objets = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE type IN ('index', 'trigger', 'view') AND sql IS NOT NULL "
            "AND instr(name, ?) > 0",
            (PREFIXE_TABLES_HERITE,),
        ).fetchall()
        for genre, nom, sql in objets:
            conn.execute(f'DROP {genre.upper()} "{nom}"')
            conn.execute(sql.replace(nom, _nom_neuf(nom), 1))
        restes = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE instr(name, ?) > 0",
                (PREFIXE_TABLES_HERITE,),
            )
        ]
        if restes:
            raise sqlite3.DatabaseError(
                f"objets encore nommés {PREFIXE_TABLES_HERITE}* : {restes}"
            )
        conn.execute(f"PRAGMA user_version = {VERSION_SCHEMA}")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    logger.warning(
        "vie : %d tables %s* renommées en %s*",
        len(heritees),
        PREFIXE_TABLES_HERITE,
        PREFIXE_TABLES,
    )
    return len(heritees)


def _migrer_tables(data_dir: Path, base: Path) -> str | None:
    """Les tables d'une vie.db encore en succes_* ; la raison d'un report.

    Le cas d'une base déjà renommée par l'étape 5 et pas encore par l'étape
    6, ou d'une sauvegarde d'avant restaurée sous le nom vie.db.
    """
    with closing(sqlite3.connect(base, timeout=0.5)) as conn:
        if not tables_heritees(conn):
            return None
        refus = _rendre_exclusive(conn)
        if refus:
            return refus
        sauvegarde = _cible_sauvegarde(
            data_dir, f"{base.name}.avant-tables-vie-{datetime.now():%Y%m%d}"
        )
        with closing(sqlite3.connect(sauvegarde)) as copie:
            conn.backup(copie)
        try:
            renommer_tables(conn)
        except sqlite3.DatabaseError as exc:
            return f"tables non renommées ({exc})"
    return None


def relativiser_photo(chemin: str, data_dir: Path) -> str | None:
    """Le chemin d'une photo, relatif au dossier de données — ou None.

    Les 62 photos du 25/09/2026 portent un chemin ABSOLU contenant
    ``/succes-photos/`` : renommer le dossier les aurait toutes perdues.
    Relatif, le chemin survit au prochain déménagement du dossier de données.
    """
    texte = chemin.replace("\\", "/")
    for ancien in (f"/{DOSSIER_PHOTOS_HERITE}/", f"/{DOSSIER_PHOTOS}/"):
        if ancien in texte:
            return f"{DOSSIER_PHOTOS}/{texte.rsplit(ancien, 1)[1]}"
    if texte.startswith(f"{DOSSIER_PHOTOS_HERITE}/"):
        return f"{DOSSIER_PHOTOS}/{texte[len(DOSSIER_PHOTOS_HERITE) + 1 :]}"
    return None


def _table_photos(conn: sqlite3.Connection) -> str | None:
    requete = "SELECT name FROM sqlite_master WHERE type='table'"
    tables = {row[0] for row in conn.execute(requete)}
    for nom in (f"{PREFIXE_TABLES}photos", f"{PREFIXE_TABLES_HERITE}photos"):
        if nom in tables:
            return nom
    return None


def _reecrire_chemins_photos(base: Path, data_dir: Path) -> int:
    """Réécrit file_path et thumb_path en relatif ; rend le nombre de lignes."""
    with closing(sqlite3.connect(base, timeout=5)) as conn:
        table = _table_photos(conn)
        if table is None:
            return 0
        lignes = 0
        with conn:
            for ident, fichier, apercu in conn.execute(
                f"SELECT id, file_path, thumb_path FROM {table}"  # noqa: S608
            ).fetchall():
                neuf_fichier = relativiser_photo(fichier, data_dir)
                neuf_apercu = relativiser_photo(apercu, data_dir)
                if neuf_fichier is None and neuf_apercu is None:
                    continue
                conn.execute(
                    f"UPDATE {table} SET file_path=?, thumb_path=? WHERE id=?",  # noqa: S608
                    (neuf_fichier or fichier, neuf_apercu or apercu, ident),
                )
                lignes += 1
        return lignes


def _migrer_photos(base: Path, data_dir: Path) -> int:
    """succes-photos → vie-photos, puis les chemins en relatif.

    Si la réécriture échoue, les fichiers reprennent leur place : les chemins
    absolus restés en base pointent de nouveau vers eux.
    """
    ancien = data_dir / DOSSIER_PHOTOS_HERITE
    neuf = data_dir / DOSSIER_PHOTOS
    deplaces: list[tuple[Path, Path]] = []
    if ancien.is_dir():
        if not neuf.exists():
            os.replace(ancien, neuf)
            deplaces.append((ancien, neuf))
        else:
            # Les deux dossiers : une migration précédente a réécrit les
            # chemins puis échoué, ou un vieux processus a rangé une photo
            # sous l'ancien nom. On déplace fichier par fichier, sans écraser.
            for source in sorted(p for p in ancien.rglob("*") if p.is_file()):
                cible = neuf / source.relative_to(ancien)
                if cible.exists():
                    logger.warning(
                        "vie : %s existe déjà dans %s, %s laissé en place",
                        cible.name,
                        DOSSIER_PHOTOS,
                        source,
                    )
                    continue
                cible.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, cible)
                deplaces.append((source, cible))
    try:
        lignes = _reecrire_chemins_photos(base, data_dir)
    except Exception:
        for source, cible in reversed(deplaces):
            os.replace(cible, source)
        raise
    if ancien.is_dir():
        for dossier in sorted(ancien.rglob("*"), reverse=True):
            if dossier.is_dir():
                try:
                    dossier.rmdir()
                except OSError:
                    pass
        try:
            ancien.rmdir()
        except OSError:
            pass
    return lignes


def _foyer_reel_sous_pytest(data_dir: Path) -> str:
    """Sous pytest, la raison de ne pas migrer ``data_dir`` ; ``""`` sinon.

    25/09/2026 : la garde vivait dans tests/conftest.py, qui remplaçait
    l'attribut ``migrer_base_vie`` de ce module. ``cli/serve.py`` n'y passait
    que parce qu'il importe la fonction DANS la sienne : un import remonté en
    tête de module rendait la vraie, et les tests qui lancent ``serve`` sans
    DIAPASON_HOME migraient la vraie ~/.diapason — sur ce Mac comme sur le
    runner mac-de-carlito. Ici, aucune façon d'importer ne la contourne, et
    un ``serve`` lancé en sous-processus par un test hérite de la variable.
    """
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        return ""
    import tempfile

    racine = Path(tempfile.gettempdir()).resolve()
    dossier = Path(data_dir).resolve()
    if dossier != racine and racine in dossier.parents:
        return ""
    return f"sous pytest, {dossier} est hors du dossier temporaire : rien n'est migré"


def migrer_base_vie(data_dir: Path) -> Migration:
    """Le passage succes.db → vie.db, idempotent, sous verrou.

    À n'appeler que depuis ``diapason serve``, avant toute construction de
    magasin : voir la docstring du module.
    """
    data_dir = Path(data_dir)
    refus = _foyer_reel_sous_pytest(data_dir)
    if refus:
        return Migration("ignoree_en_test", data_dir / NOM_BASE, refus)
    neuve = data_dir / NOM_BASE
    herite = data_dir / NOM_BASE_HERITE
    with _verrou_exclusif(data_dir / NOM_VERROU) as tenu:
        if not tenu:
            detail = (
                f"verrou {NOM_VERROU} tenu plus de {_ATTENTE_VERROU_S:.0f} s "
                "par un autre processus"
            )
            logger.warning("vie : migration reportée — %s", detail)
            return Migration("reportee", herite if herite.exists() else neuve, detail)

        if neuve.exists() and herite.exists():
            pleine_neuve = a_des_donnees(neuve)
            pleine_herite = a_des_donnees(herite)
            if pleine_neuve and pleine_herite:
                detail = str(DeuxBasesVie(data_dir))
                logger.error("vie : %s", detail)
                return Migration("deux_bases", neuve, detail)
            # Une des deux est une coquille (recréée vide par un processus
            # d'avant le renommage) : elle part dans backups/, pas à la
            # corbeille, et la pleine reste seule.
            vide = neuve if pleine_herite else herite
            refus = _mettre_de_cote(data_dir, vide, "fantome")
            if refus:
                logger.warning("vie : %s vide non mise de côté — %s", vide.name, refus)
                return Migration("reportee", chemin_base_vie(data_dir), refus)
            logger.warning("vie : %s vide mise de côté dans backups/", vide.name)

        etat = "deja_faite"
        if herite.exists():
            refus = _migrer_fichier(data_dir)
            if refus:
                logger.warning(
                    "vie : migration de %s reportée au prochain démarrage — %s",
                    NOM_BASE_HERITE,
                    refus,
                )
                return Migration("reportee", herite, refus)
            etat = "migree"
        elif not neuve.exists():
            return Migration("neuve", neuve)
        else:
            refus = _migrer_tables(data_dir, neuve)
            if refus:
                logger.warning(
                    "vie : tables de %s non renommées, reporté au prochain "
                    "démarrage — %s",
                    NOM_BASE,
                    refus,
                )
                return Migration("reportee", neuve, refus)

        try:
            photos = _migrer_photos(neuve, data_dir)
        except Exception as exc:  # noqa: BLE001 - la base est migrée ; les photos gardent leurs chemins
            logger.warning(
                "vie : photos non migrées, %s garde son nom — %s",
                DOSSIER_PHOTOS_HERITE,
                exc,
            )
            return Migration(etat, neuve, f"photos non migrées : {exc}")
        if photos:
            logger.warning("vie : %d chemins de photos rendus relatifs", photos)
        return Migration(etat, neuve, photos=photos)


__all__ = [
    "BaseVieNonMigree",
    "DOSSIER_PHOTOS",
    "DOSSIER_PHOTOS_HERITE",
    "DeuxBasesVie",
    "Migration",
    "NOM_BASE",
    "NOM_BASE_HERITE",
    "a_des_donnees",
    "chemin_base_vie",
    "dossier_photos_pour",
    "migrer_base_vie",
    "relativiser_photo",
    "renommer_tables",
]
