"""succes.db devient vie.db — sans ses photos, rien n'aurait tenu.

25/09/2026, étapes 5 et 6 du plan de la phase 1b (docs/development/
diapason-mobile.md) : le fichier, les photos, puis les 26 tables succes_*
qui deviennent vie_*. Chaque test tourne dans un dossier de données
temporaire : la vraie base de Carlito (311 Mo, 62 photos) ne se touche
qu'au redémarrage du serveur, jamais depuis un test (voir la garde de
tests/conftest.py).

Une base « héritée » est fabriquée par le code d'aujourd'hui puis
vieillie (tables et index rendus à leurs noms succes_*) ;
``schema_succes_avant_vie.sql``, dumpé du code d'avant, prouve que la
fabrique rend exactement le schéma que ce code écrivait.
"""

from __future__ import annotations

import base64
import importlib
import multiprocessing
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.vie import emplacement
from diapason.vie import routes as routes_vie
from diapason.vie.emplacement import (
    DOSSIER_PHOTOS,
    DOSSIER_PHOTOS_HERITE,
    NOM_BASE,
    NOM_BASE_HERITE,
    BaseVieNonMigree,
    DeuxBasesVie,
    chemin_base_vie,
    migrer_base_vie,
)
from diapason.vie.store import VERSION_SCHEMA
from diapason.vie.sync import VieSyncStore
from diapason.vie.workspace import VieWorkspaceStore

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


SCHEMA_AVANT = Path(__file__).with_name("schema_succes_avant_vie.sql")


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite%' ORDER BY name"
        )
    ]


def _comptes(chemin: Path) -> dict[str, int]:
    """Lignes par table, sous le nom SANS préfixe : succes_tasks et vie_tasks
    se comparent comme « tasks »."""
    with closing(sqlite3.connect(chemin)) as conn:
        return {
            table.split("_", 1)[1]: conn.execute(
                f"SELECT count(*) FROM {table}"  # noqa: S608 - nom tiré de sqlite_master
            ).fetchone()[0]
            for table in _tables(conn)
        }


def _schema(conn: sqlite3.Connection) -> set[tuple[str, str, str, str]]:
    """sqlite_master sans ses guillemets ni ses blancs, pour comparer."""
    return {
        (
            genre,
            nom,
            table,
            " ".join((sql or "").replace('"', "").split()),
        )
        for genre, nom, table, sql in conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name != 'sqlite_sequence'"
        )
    }


def vieillir(chemin: Path) -> None:
    """Rend à une base d'aujourd'hui les noms du code d'avant l'étape 6."""
    with closing(sqlite3.connect(chemin)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        for table in _tables(conn):
            if table.startswith("vie_"):
                conn.execute(f'ALTER TABLE "{table}" RENAME TO "succes_{table[4:]}"')
        for nom, sql in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' "
            "AND sql IS NOT NULL AND instr(name, 'vie_') > 0"
        ).fetchall():
            conn.execute(f'DROP INDEX "{nom}"')
            ancien = nom.replace("vie_", "succes_", 1)
            conn.execute(sql.replace(nom, ancien, 1))
        # La dernière classe construite par le serveur (VieSyncStore) posait 4.
        conn.execute("PRAGMA user_version = 4")
        conn.execute("COMMIT")


def _remplir(chemin: Path, *, taches: int = 3) -> VieSyncStore:
    """Une base aux tables d'aujourd'hui (vie_*), quel que soit son nom."""
    magasin = VieSyncStore(chemin)
    for i in range(taches):
        magasin.create_task({"title": f"Tâche {i}", "date": "2026-09-25"})
    magasin.create_note({"title": "Note", "content": "texte"})
    return magasin


def _remplir_heritee(chemin: Path, *, taches: int = 3) -> Path:
    """Une base telle que le code d'avant le 25/09/2026 la laissait."""
    _remplir(chemin, taches=taches)
    vieillir(chemin)
    return chemin


def _fichiers(dossier: Path) -> list[str]:
    return sorted(str(p.relative_to(dossier)) for p in dossier.rglob("*"))


@pytest.fixture
def donnees(tmp_path: Path) -> Path:
    dossier = tmp_path / "foyer"
    dossier.mkdir()
    return dossier


class TestLaResolutionSansMigration:
    """Tout ouvrant sauf `diapason serve` : lire, jamais déplacer ni créer."""

    def test_seule_succes_db_est_rendue_et_rien_n_est_cree(self, donnees):
        _remplir_heritee(donnees / NOM_BASE_HERITE)
        avant = _fichiers(donnees)
        chemin = chemin_base_vie(donnees, migrer=False)
        assert chemin == donnees / NOM_BASE_HERITE, (
            "succes.db tant qu'elle n'est pas migrée"
        )
        assert _fichiers(donnees) == avant, "la résolution ne doit rien créer"

    def test_sans_aucune_base_la_nouvelle_s_appelle_vie_db(self, donnees, monkeypatch):
        monkeypatch.setenv("DIAPASON_HOME", str(donnees))
        magasin = VieSyncStore()
        assert magasin.db_path == donnees / NOM_BASE
        assert not (donnees / NOM_BASE_HERITE).exists(), "aucune succes.db neuve"
        assert magasin.photos_dir == donnees / DOSSIER_PHOTOS

    def test_un_magasin_par_defaut_ouvre_succes_db_aux_tables_renommees(
        self, donnees, monkeypatch
    ):
        """Le tick de 900 s, sur une succes.db dont les tables sont déjà
        vie_* (le serveur n'a pas pu la déplacer) : il la lit au lieu de
        créer une vie.db vide à côté de la pleine."""
        _remplir(donnees / NOM_BASE_HERITE, taches=2)
        monkeypatch.setenv("DIAPASON_HOME", str(donnees))
        magasin = VieSyncStore()
        assert magasin.db_path == donnees / NOM_BASE_HERITE
        assert len(magasin.list_tasks()) == 2, "les tâches de succes.db doivent se lire"
        assert not (donnees / NOM_BASE).exists(), "aucune vie.db ne doit naître à côté"
        assert magasin.photos_dir == donnees / DOSSIER_PHOTOS_HERITE


class TestLaMigration:
    def test_le_fichier_change_de_nom_et_garde_ses_comptes(self, donnees):
        _remplir_heritee(donnees / NOM_BASE_HERITE, taches=5)
        avant = _comptes(donnees / NOM_BASE_HERITE)

        resultat = migrer_base_vie(donnees)

        assert resultat.etat == "migree", resultat
        assert not (donnees / NOM_BASE_HERITE).exists(), "succes.db doit être partie"
        assert _comptes(donnees / NOM_BASE) == avant, "mêmes comptes par table"
        sauvegardes = list((donnees / "backups").glob("succes.db.avant-vie-*"))
        assert len(sauvegardes) == 1, "une sauvegarde d'avant, exactement"
        assert _comptes(sauvegardes[0]) == avant, "la sauvegarde est complète"
        restes = [p.name for p in donnees.iterdir() if p.name.startswith("succes.db")]
        assert restes == [], f"ni -wal ni -shm ne doivent rester : {restes}"

    def test_une_transaction_restee_dans_le_wal_arrive_dans_vie_db(
        self, donnees, tmp_path
    ):
        """L'état d'un serveur tué net : les dernières écritures ne sont que
        dans succes.db-wal. Renommer le seul fichier principal les perdait."""
        atelier = tmp_path / "atelier"
        atelier.mkdir()
        _remplir_heritee(atelier / NOM_BASE_HERITE, taches=1)
        conn = sqlite3.connect(atelier / NOM_BASE_HERITE)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute(
            "UPDATE succes_tasks SET title='écrite dans le WAL' WHERE title='Tâche 0'"
        )
        conn.commit()
        # Copie « à chaud » : le -wal porte la transaction, le fichier
        # principal ne l'a pas encore.
        for nom in (NOM_BASE_HERITE, "succes.db-wal", "succes.db-shm"):
            if (atelier / nom).exists():
                shutil.copy2(atelier / nom, donnees / nom)
        conn.close()
        assert (donnees / "succes.db-wal").stat().st_size > 0, "le WAL doit être plein"

        assert migrer_base_vie(donnees).etat == "migree"

        with closing(sqlite3.connect(donnees / NOM_BASE)) as lecture:
            titres = [r[0] for r in lecture.execute("SELECT title FROM vie_tasks")]
        assert titres == ["écrite dans le WAL"], f"transaction du WAL perdue : {titres}"

    def test_une_seconde_connexion_reporte_la_migration(self, donnees):
        _remplir_heritee(donnees / NOM_BASE_HERITE)
        avant = _comptes(donnees / NOM_BASE_HERITE)
        autre = sqlite3.connect(donnees / NOM_BASE_HERITE)
        autre.execute("PRAGMA journal_mode=WAL")
        autre.execute("SELECT count(*) FROM succes_tasks").fetchone()
        try:
            resultat = migrer_base_vie(donnees)
        finally:
            autre.close()
        assert resultat.etat == "reportee", resultat
        assert resultat.chemin == donnees / NOM_BASE_HERITE
        assert not (donnees / NOM_BASE).exists(), "aucune vie.db ne doit exister"
        assert _comptes(donnees / NOM_BASE_HERITE) == avant, "succes.db intacte"
        assert not (donnees / "backups").exists() or not list(
            (donnees / "backups").glob("succes.db.avant-vie-*")
        ), "pas de sauvegarde pour une migration qui n'a pas eu lieu"

    def test_la_migration_est_idempotente(self, donnees):
        _remplir_heritee(donnees / NOM_BASE_HERITE)
        premiere = migrer_base_vie(donnees)
        apres = _comptes(donnees / NOM_BASE)
        seconde = migrer_base_vie(donnees)
        assert (premiere.etat, seconde.etat) == ("migree", "deja_faite")
        assert _comptes(donnees / NOM_BASE) == apres, "rien ne bouge au second passage"
        assert len(list((donnees / "backups").iterdir())) == 1, "une seule sauvegarde"

    def test_une_base_neuve_reste_neuve(self, donnees):
        resultat = migrer_base_vie(donnees)
        assert resultat.etat == "neuve"
        assert not (donnees / NOM_BASE).exists(), "la migration ne crée pas la base"

    def test_deux_processus_ne_migrent_qu_une_fois(self, donnees):
        """Un kickstart pendant un démarrage à la main : deux `serve`."""
        _remplir_heritee(donnees / NOM_BASE_HERITE)
        contexte = multiprocessing.get_context("spawn")
        with contexte.Pool(2) as pool:
            etats = sorted(pool.map(_migrer_dans_un_processus, [str(donnees)] * 2))
        assert etats == ["deja_faite", "migree"], f"une seule migration : {etats}"
        assert len(list((donnees / "backups").glob("succes.db.avant-vie-*"))) == 1

    def test_un_magasin_ouvert_avant_ne_recree_pas_succes_db(self, donnees):
        """Le défaut que `mode=rw` évite : un processus qui tenait le vieux
        chemin recréait une succes.db vide, et les écritures se coupaient en
        deux bases sans une erreur."""
        ancien = _remplir(donnees / NOM_BASE_HERITE)
        assert migrer_base_vie(donnees).etat == "migree"
        with pytest.raises(sqlite3.OperationalError, match="relance"):
            ancien.list_tasks()
        assert not (donnees / NOM_BASE_HERITE).exists(), "aucune succes.db recréée"


def _migrer_dans_un_processus(dossier: str) -> str:
    return migrer_base_vie(Path(dossier)).etat


class TestLesDeuxBases:
    def test_deux_bases_pleines_rendent_503_et_rien_ne_bouge(
        self, donnees, monkeypatch
    ):
        _remplir_heritee(donnees / NOM_BASE_HERITE, taches=2)
        _remplir(donnees / NOM_BASE, taches=3)
        avant = _fichiers(donnees)
        comptes = (_comptes(donnees / NOM_BASE_HERITE), _comptes(donnees / NOM_BASE))

        resultat = migrer_base_vie(donnees)
        assert resultat.etat == "deux_bases", resultat
        apres = [f for f in _fichiers(donnees) if f != emplacement.NOM_VERROU]
        assert apres == avant, f"aucun fichier ne doit bouger : {apres}"
        assert (
            _comptes(donnees / NOM_BASE_HERITE),
            _comptes(donnees / NOM_BASE),
        ) == comptes, "aucune donnée ne doit changer"
        with pytest.raises(DeuxBasesVie):
            chemin_base_vie(donnees, migrer=False)

        monkeypatch.setenv("DIAPASON_HOME", str(donnees))
        routes_vie.set_store_for_tests(None)
        app = FastAPI()
        routes_vie.monter(app)
        try:
            reponse = TestClient(app).get("/v1/vie/tasks")
        finally:
            routes_vie.set_store_for_tests(None)
        assert reponse.status_code == 503, reponse.text
        assert "Deux bases de vie" in reponse.json()["detail"]

    def test_les_outils_le_disent_au_lieu_de_tomber(self, donnees, monkeypatch):
        """Construits au premier appel : la trousse du chat ne tombe plus
        entière, et le modèle lit la raison."""
        from diapason.tools.vie_tasks import VieTasksTool

        _remplir_heritee(donnees / NOM_BASE_HERITE, taches=1)
        _remplir(donnees / NOM_BASE, taches=1)
        monkeypatch.setenv("DIAPASON_HOME", str(donnees))
        outil = VieTasksTool()  # ne doit pas lever
        resultat = outil.execute(action="list")
        assert resultat.success is False, "deux bases : l'outil doit échouer"
        assert "Deux bases de vie" in resultat.content, resultat.content

    def test_une_base_vide_recreee_part_dans_les_sauvegardes(self, donnees):
        """Le fantôme : une succes.db recréée vide par un vieux processus
        après la migration. Elle part dans backups/, la pleine reste seule."""
        _remplir_heritee(donnees / NOM_BASE_HERITE, taches=4)
        assert migrer_base_vie(donnees).etat == "migree"
        VieSyncStore(donnees / NOM_BASE_HERITE)  # recréée vide
        avant = _comptes(donnees / NOM_BASE)

        resultat = migrer_base_vie(donnees)

        assert resultat.etat == "deja_faite", resultat
        assert not (donnees / NOM_BASE_HERITE).exists(), "le fantôme doit partir"
        assert _comptes(donnees / NOM_BASE) == avant
        assert list((donnees / "backups").glob("succes.db.fantome-*")), (
            "le fantôme est mis de côté, pas effacé"
        )


class TestLesPhotos:
    def _trois_photos_absolues(self, donnees: Path) -> tuple[VieSyncStore, list[str]]:
        magasin = _remplir(donnees / NOM_BASE_HERITE, taches=0)
        projet = magasin.create_project({"name": "Pile"})
        pile = magasin.create_photo_pile(projet["id"], "Photos")
        ids = []
        for i in range(3):
            photo = magasin.add_photo(
                pile["id"],
                {
                    "fileName": f"p{i}.png",
                    "dataBase64": _b64(PNG),
                    "thumbBase64": _b64(JPEG),
                },
            )
            ids.append(photo["id"])
        # Les 62 photos du 25/09/2026 : chemins ABSOLUS, comme avant ce jour.
        with closing(sqlite3.connect(donnees / NOM_BASE_HERITE)) as conn, conn:
            for ligne in conn.execute(
                "SELECT id, file_path, thumb_path FROM vie_photos"
            ).fetchall():
                conn.execute(
                    "UPDATE vie_photos SET file_path=?, thumb_path=? WHERE id=?",
                    (str(donnees / ligne[1]), str(donnees / ligne[2]), ligne[0]),
                )
        vieillir(donnees / NOM_BASE_HERITE)
        return magasin, ids

    def test_trois_photos_a_chemins_absolus_se_lisent_apres_migration(self, donnees):
        _, ids = self._trois_photos_absolues(donnees)
        resultat = migrer_base_vie(donnees)
        assert resultat.etat == "migree"
        assert resultat.photos == 3, f"3 lignes réécrites, pas {resultat.photos}"
        assert not (donnees / DOSSIER_PHOTOS_HERITE).exists()

        magasin = VieSyncStore(donnees / NOM_BASE)
        for ident in ids:
            contenu = magasin.photo_content(ident)
            assert base64.b64decode(contenu["dataBase64"]) == PNG, "l'original se lit"
        projet = magasin.list_projects()[0]
        pile = magasin.list_photo_piles(projet["id"])["piles"][0]
        apercus = magasin.list_photos(pile["id"])["photos"]
        assert all(p["thumb"].startswith("data:image/jpeg") for p in apercus), (
            'un aperçu vide ("") est exactement le défaut évité'
        )
        with closing(sqlite3.connect(donnees / NOM_BASE)) as conn:
            chemins = [
                c
                for r in conn.execute("SELECT file_path, thumb_path FROM vie_photos")
                for c in r
            ]
        assert all(c.startswith(f"{DOSSIER_PHOTOS}/") for c in chemins), chemins

    def test_une_nouvelle_photo_s_ecrit_en_relatif(self, donnees):
        magasin = VieSyncStore(donnees / NOM_BASE)
        projet = magasin.create_project({"name": "P"})
        pile = magasin.create_photo_pile(projet["id"], "Pile")
        photo = magasin.add_photo(
            pile["id"],
            {"fileName": "x.png", "dataBase64": _b64(PNG), "thumbBase64": _b64(JPEG)},
        )
        with closing(sqlite3.connect(donnees / NOM_BASE)) as conn:
            fichier = conn.execute(
                "SELECT file_path FROM vie_photos WHERE id=?", (photo["id"],)
            ).fetchone()[0]
        assert fichier == f"{DOSSIER_PHOTOS}/{projet['id']}/{photo['id']}.png"

    def test_une_reecriture_qui_echoue_rend_son_nom_au_dossier(
        self, donnees, monkeypatch
    ):
        _, ids = self._trois_photos_absolues(donnees)
        vraie_reecriture = emplacement._reecrire_chemins_photos

        def panne(*_a, **_k):
            raise sqlite3.OperationalError("disque plein (simulé)")

        monkeypatch.setattr(emplacement, "_reecrire_chemins_photos", panne)
        resultat = migrer_base_vie(donnees)
        assert resultat.etat == "migree", "la base, elle, est migrée"
        assert "photos non migrées" in resultat.detail
        assert (donnees / DOSSIER_PHOTOS_HERITE).is_dir(), "le dossier reprend son nom"
        assert not (donnees / DOSSIER_PHOTOS).exists()
        magasin = VieSyncStore(donnees / NOM_BASE)
        assert base64.b64decode(magasin.photo_content(ids[0])["dataBase64"]) == PNG, (
            "les chemins absolus restés en base doivent encore mener aux fichiers"
        )

        # Le démarrage suivant finit le travail.
        monkeypatch.setattr(emplacement, "_reecrire_chemins_photos", vraie_reecriture)
        suite = emplacement.migrer_base_vie(donnees)
        assert suite.photos == 3, suite
        assert magasin.photo_content(ids[0])["dataBase64"]


def _base_riche(chemin: Path) -> None:
    """Une ligne dans chacune des tables qu'un usage ordinaire remplit
    (25 sur 26 : succes_settings n'est écrite par aucun chemin du code)."""
    magasin = _remplir(chemin, taches=4)
    projet = magasin.create_project({"name": "Réseau", "structure": "network"})
    a = magasin.create_task({"title": "A", "projectId": projet["id"]})
    b = magasin.create_task({"title": "B", "projectId": projet["id"]})
    magasin.add_subtask(a["id"], "sous-tâche")
    magasin.create_task_edge(projet["id"], a["id"], b["id"])
    magasin.delete_task(magasin.create_task({"title": "Pierre tombale"})["id"])
    magasin.create_template(
        {
            "id": "sport",
            "title": "Sport",
            "frequency": "weekly",
            "weeklyDays": [1, 3],
            "startDate": "2026-08-01",
            "endDate": "2026-08-31",
        }
    )
    habitude = magasin.create_habit(
        {"name": "Lire", "frequency": "daily", "startDate": "2026-09-01"}
    )
    magasin.set_habit_done(habitude["id"], done=True, log_date="2026-09-20")
    magasin.create_note({"title": "Classée", "content": "x", "category": "Idées"})
    magasin.order_note_categories(["Idées"])
    magasin.create_quote({"id": "q", "text": "Avance"})
    compte = magasin.create_account({"name": "Chèques", "type": "checking"})
    magasin.create_transaction(
        {
            "accountId": compte["id"],
            "type": "expense",
            "amount": "12",
            "date": "2026-09-20",
        }
    )
    magasin.create_subscription(
        {"name": "Abo", "amount": "9", "cadence": "monthly", "nextDate": "2026-10-01"}
    )
    magasin.upsert_budget({"scope": "global", "limit": "500", "yearMonth": "2026-09"})
    magasin.create_goal({"name": "Épargne", "target": "1000"})
    pile = magasin.create_photo_pile(projet["id"], "Pile")
    magasin.add_photo(
        pile["id"],
        {"fileName": "a.png", "dataBase64": _b64(PNG), "thumbBase64": _b64(JPEG)},
    )
    magasin.import_legacy_snapshot(
        {"tasks": [{"id": "legacy1", "title": "Ancienne", "date": "2026-09-01"}]}
    )
    invitation = magasin.create_pairing("Téléphone")
    pair = magasin.redeem_pairing(invitation["pairingToken"])
    operation = {
        "opId": "op-r1",
        "deviceId": "phone-a",
        "entity": "tasks",
        "entityId": "task_r1",
        "timestampMs": 1_700_000_000_000,
    }
    magasin.apply_remote_operations(
        pair["peerId"],
        [{**operation, "kind": "upsert", "payload": {"id": "task_r1", "title": "D"}}],
    )
    magasin.apply_remote_operations(
        pair["peerId"],
        [
            {
                **operation,
                "opId": "op-r2",
                "kind": "delete",
                "timestampMs": 1_700_000_000_500,
                "payload": {"id": "task_r1"},
            }
        ],
    )


def _sequence(chemin: Path) -> list[tuple[str, int]]:
    with closing(sqlite3.connect(chemin)) as conn:
        return [
            (nom.split("_", 1)[1], valeur)
            for nom, valeur in conn.execute("SELECT name, seq FROM sqlite_sequence")
        ]


class TestLeRenommageDesTables:
    """Étape 6 : succes_* → vie_*, première migration de schéma du projet.

    Le défaut évité : une requête oubliée sur un chemin rare (pierres
    tombales, imports) ne lève « no such table » que des semaines plus tard ;
    et un tick qui crée des tables vie_* vides à côté des pleines fait
    trouver à la migration une vie_tasks vide — les données semblent perdues.
    """

    def test_la_base_fabriquee_a_le_schema_du_code_d_avant(self, donnees):
        """Sans ce témoin, une fabrique fausse ferait passer une migration qui
        ne sait pas traiter la vraie base."""
        chemin = _remplir_heritee(donnees / NOM_BASE_HERITE)
        temoin = sqlite3.connect(":memory:")
        temoin.executescript(SCHEMA_AVANT.read_text(encoding="utf-8"))
        with closing(sqlite3.connect(chemin)) as conn:
            fabrique = _schema(conn)
        assert fabrique == _schema(temoin), (
            "la base vieillie doit porter exactement le schéma du commit 7eecc67 : "
            f"{sorted(fabrique ^ _schema(temoin))[:4]}"
        )
        assert len([t for t in fabrique if t[0] == "table"]) == 26, "26 tables"

    def test_les_comptes_par_table_sont_identiques_avant_et_apres(self, donnees):
        chemin = donnees / NOM_BASE_HERITE
        _base_riche(chemin)
        vieillir(chemin)
        avant, sequence = _comptes(chemin), _sequence(chemin)
        assert len(avant) == 26 and sum(1 for n in avant.values() if n) == 25, avant

        resultat = migrer_base_vie(donnees)

        assert resultat.etat == "migree", resultat
        assert _comptes(donnees / NOM_BASE) == avant, "mêmes lignes, table par table"
        assert _sequence(donnees / NOM_BASE) == sequence, (
            "le compteur AUTOINCREMENT de vie_operations doit suivre"
        )
        with closing(sqlite3.connect(donnees / NOM_BASE)) as conn:
            assert _tables(conn) == sorted(f"vie_{t}" for t in avant), _tables(conn)
            restes = conn.execute(
                "SELECT name FROM sqlite_master WHERE instr(name, 'succes') > 0"
            ).fetchall()
            assert restes == [], f"aucun objet ne doit garder l'ancien nom : {restes}"
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            assert conn.execute("PRAGMA user_version").fetchone()[0] == VERSION_SCHEMA

    def test_le_schema_migre_est_celui_d_une_base_neuve(self, donnees, tmp_path):
        """Un index resté sous l'ancien nom aurait été recréé en double par le
        schéma neuf — sur vie_operations, 306 Mo des 311 de la vraie base."""
        _base_riche(donnees / NOM_BASE_HERITE)
        vieillir(donnees / NOM_BASE_HERITE)
        migrer_base_vie(donnees)
        VieSyncStore(donnees / NOM_BASE)  # rouvre : CREATE … IF NOT EXISTS
        neuve = tmp_path / "neuve.db"
        _base_riche(neuve)
        with (
            closing(sqlite3.connect(donnees / NOM_BASE)) as migree,
            closing(sqlite3.connect(neuve)) as temoin,
        ):
            assert _schema(migree) == _schema(temoin), sorted(
                _schema(migree) ^ _schema(temoin)
            )[:4]
            assert (
                migree.execute("PRAGMA user_version").fetchone()
                == temoin.execute("PRAGMA user_version").fetchone()
                == (VERSION_SCHEMA,)
            )

    def test_une_sauvegarde_d_avant_restauree_se_migre_de_nouveau(self, donnees):
        """La restauration qu'un mauvais jour demande : la copie d'avant,
        remise en succes.db, repasse par la même migration."""
        _base_riche(donnees / NOM_BASE_HERITE)
        vieillir(donnees / NOM_BASE_HERITE)
        avant = _comptes(donnees / NOM_BASE_HERITE)
        assert migrer_base_vie(donnees).etat == "migree"
        (sauvegarde,) = (donnees / "backups").glob("succes.db.avant-vie-*")
        with closing(sqlite3.connect(sauvegarde)) as conn:
            assert all(t.startswith("succes_") for t in _tables(conn)), (
                "la sauvegarde est prise AVANT le renommage des tables"
            )

        (donnees / NOM_BASE).unlink()
        shutil.copy2(sauvegarde, donnees / NOM_BASE_HERITE)
        resultat = migrer_base_vie(donnees)

        assert resultat.etat == "migree", resultat
        assert _comptes(donnees / NOM_BASE) == avant, "mêmes comptes après restauration"
        assert len(list((donnees / "backups").glob("succes.db.avant-vie-*"))) == 2, (
            "la seconde migration ne doit pas écraser la première sauvegarde"
        )

    def test_une_sauvegarde_restauree_sous_le_nom_vie_db_se_migre(self, donnees):
        """Le même jour, restaurée directement en vie.db : le fichier est
        déjà à sa place, seules les tables se renomment — après leur propre
        sauvegarde."""
        _base_riche(donnees / NOM_BASE_HERITE)
        vieillir(donnees / NOM_BASE_HERITE)
        avant = _comptes(donnees / NOM_BASE_HERITE)
        migrer_base_vie(donnees)
        (sauvegarde,) = (donnees / "backups").glob("succes.db.avant-vie-*")
        shutil.copy2(sauvegarde, donnees / NOM_BASE)

        resultat = migrer_base_vie(donnees)

        assert resultat.etat == "deja_faite", resultat
        assert _comptes(donnees / NOM_BASE) == avant
        with closing(sqlite3.connect(donnees / NOM_BASE)) as conn:
            assert all(t.startswith("vie_") for t in _tables(conn)), _tables(conn)
        copies = list((donnees / "backups").glob("vie.db.avant-tables-vie-*"))
        assert len(copies) == 1, "les tables ne se renomment qu'après une copie"
        assert _comptes(copies[0]) == avant

    def test_un_tick_refuse_une_base_pas_encore_migree(self, donnees, monkeypatch):
        """La règle : aucun ouvrant autre que le serveur ne crée de table
        vie_* dans une base qui a encore des tables succes_*."""
        chemin = _remplir_heritee(donnees / NOM_BASE_HERITE, taches=2)
        with closing(sqlite3.connect(chemin)) as conn:
            schema_avant = _schema(conn)
        monkeypatch.setenv("DIAPASON_HOME", str(donnees))

        for fabrique in (VieSyncStore, VieWorkspaceStore):
            with pytest.raises(BaseVieNonMigree, match="relance le serveur"):
                fabrique()

        with closing(sqlite3.connect(chemin)) as conn:
            assert _schema(conn) == schema_avant, "rien ne doit être créé à côté"
        assert not (donnees / NOM_BASE).exists(), "aucune vie.db ne doit naître"
        assert migrer_base_vie(donnees).etat == "migree", (
            "le serveur, lui, trouve la base intacte et la migre"
        )
        assert len(VieSyncStore().list_tasks()) == 2

    def test_les_routes_disent_503_tant_que_la_migration_est_reportee(
        self, donnees, monkeypatch
    ):
        """Sans le 503, _domain_error en faisait un 409 : l'interface l'aurait
        pris pour un conflit d'écriture."""
        _remplir_heritee(donnees / NOM_BASE_HERITE)
        monkeypatch.setenv("DIAPASON_HOME", str(donnees))
        routes_vie.set_store_for_tests(None)
        app = FastAPI()
        routes_vie.monter(app)
        try:
            reponse = TestClient(app).get("/v1/vie/tasks")
        finally:
            routes_vie.set_store_for_tests(None)
        assert reponse.status_code == 503, reponse.text
        assert "pas encore migrée" in reponse.json()["detail"]

    def test_une_panne_au_milieu_ne_renomme_rien(self, donnees, monkeypatch):
        """Tout ou rien : une table renommée sans ses sœurs couperait les
        jointures en deux."""
        chemin = _remplir_heritee(donnees / NOM_BASE_HERITE)
        avant = _comptes(chemin)
        vrai = emplacement._nom_neuf

        def panne(nom: str) -> str:
            # Deux index sous le même nom neuf : le second CREATE INDEX échoue
            # APRÈS que toutes les tables ont été renommées.
            return "vie_index_en_double" if nom.endswith("_idx") else vrai(nom)

        monkeypatch.setattr(emplacement, "_nom_neuf", panne)
        resultat = migrer_base_vie(donnees)

        assert resultat.etat == "reportee", resultat
        assert "tables non renommées" in resultat.detail
        assert not (donnees / NOM_BASE).exists(), "le fichier ne bouge pas non plus"
        with closing(sqlite3.connect(chemin)) as conn:
            assert all(t.startswith("succes_") for t in _tables(conn)), _tables(conn)
        assert _comptes(chemin) == avant

        monkeypatch.setattr(emplacement, "_nom_neuf", vrai)
        assert migrer_base_vie(donnees).etat == "migree", "le démarrage suivant migre"
        assert _comptes(donnees / NOM_BASE) == avant

    def test_des_tables_des_deux_noms_ne_sont_pas_touchees(self, donnees):
        """succes_tasks ET vie_tasks : choisir l'une perdrait l'autre."""
        chemin = _remplir_heritee(donnees / NOM_BASE_HERITE)
        with closing(sqlite3.connect(chemin)) as conn, conn:
            conn.execute("CREATE TABLE vie_tasks (id TEXT PRIMARY KEY)")
            schema_avant = _schema(conn)
        resultat = migrer_base_vie(donnees)
        assert resultat.etat == "reportee", resultat
        assert "vie_tasks existe(nt) aussi" in resultat.detail, resultat.detail
        assert not (donnees / NOM_BASE).exists(), "le fichier ne bouge pas"
        with closing(sqlite3.connect(chemin)) as conn:
            assert _schema(conn) == schema_avant, "rien ne doit être renommé"


class TestLeServeur:
    def test_serve_migre_apres_le_port_et_avant_le_moteur(self, tmp_path, monkeypatch):
        """Après le port (l'ancien serveur est mort), avant tout magasin."""
        from unittest.mock import MagicMock

        from click.testing import CliRunner

        from diapason.cli import cli

        serve_mod = importlib.import_module("diapason.cli.serve")
        from diapason.core.config import DiapasonConfig

        config = DiapasonConfig()
        config.server.host = "127.0.0.1"
        config.server.port = 8124
        monkeypatch.setattr(serve_mod, "load_config", lambda *a, **k: config)
        monkeypatch.setattr(serve_mod, "inject_credentials", lambda: None)
        ordre: list[str] = []
        monkeypatch.setattr(
            serve_mod, "attendre_le_port", lambda *a, **k: ordre.append("port")
        )

        def migrer(console=None, **_):
            ordre.append("migration")
            raise SystemExit(0)

        monkeypatch.setattr(serve_mod, "migrer_la_base_de_vie", migrer)
        trop_tot = MagicMock(side_effect=AssertionError("moteur avant la migration"))
        monkeypatch.setattr(serve_mod, "register_builtin_models", trop_tot)

        resultat = CliRunner().invoke(cli, ["serve"], catch_exceptions=False)
        assert resultat.exit_code == 0, resultat.output
        assert ordre == ["port", "migration"], ordre
        trop_tot.assert_not_called()

    def test_le_magasin_construit_avant_est_jete(self, donnees, monkeypatch):
        """Une succes.db aux tables déjà renommées (le déplacement avait été
        reporté) : un magasin s'y construit, puis la migration la déplace."""
        from diapason.cli.serve import migrer_la_base_de_vie

        _remplir(donnees / NOM_BASE_HERITE)
        monkeypatch.setenv("DIAPASON_HOME", str(donnees))
        routes_vie.set_store_for_tests(None)
        try:
            avant = routes_vie.get_store()
            assert avant.db_path.name == NOM_BASE_HERITE
            resultat = migrer_la_base_de_vie()
            assert resultat is not None and resultat.etat == "migree", resultat
            apres = routes_vie.get_store()
            assert apres.db_path == donnees / NOM_BASE, (
                "le singleton construit avant la migration gardait l'ancien chemin"
            )
            assert len(apres.list_tasks()) == 3
        finally:
            routes_vie.set_store_for_tests(None)


class TestLaGardeDesTests:
    """Aucun test ne migre un foyer hors du dossier temporaire.

    25/09/2026 : la garde vivait dans tests/conftest.py et remplaçait
    l'attribut ``emplacement.migrer_base_vie``. ``cli/serve.py`` n'y passait
    que parce qu'il importait la fonction DANS la sienne : remonter l'import
    en tête du module (ce qu'un tri d'imports fait) rendait la vraie
    fonction, et test_cli, test_serve_port_tenu, test_serve_single_build
    — qui lancent ``serve`` sans DIAPASON_HOME — auraient migré la vraie
    ~/.diapason, ici comme sur le runner mac-de-carlito. L'ancien test
    appelait l'attribut patché lui-même, et restait vert.

    Le « dossier temporaire » est ici un sous-dossier de tmp_path : le foyer
    qu'on protège est un autre sous-dossier de tmp_path. Si la garde tombe,
    seul un dossier jetable est migré — jamais le vrai foyer.
    """

    @pytest.fixture
    def foyer_hors_temporaire(self, tmp_path, monkeypatch):
        import tempfile

        faux_temp = tmp_path / "temp"
        faux_temp.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(faux_temp))
        foyer = tmp_path / "foyer"
        foyer.mkdir()
        _remplir_heritee(foyer / NOM_BASE_HERITE, taches=2)
        monkeypatch.setenv("DIAPASON_HOME", str(foyer))
        return foyer

    def test_serve_ne_migre_pas_un_foyer_hors_du_dossier_temporaire(
        self, foyer_hors_temporaire
    ):
        from diapason.cli.serve import migrer_la_base_de_vie

        routes_vie.set_store_for_tests(None)
        try:
            resultat = migrer_la_base_de_vie()
        finally:
            routes_vie.set_store_for_tests(None)

        assert resultat is not None and resultat.etat == "ignoree_en_test", resultat
        assert (foyer_hors_temporaire / NOM_BASE_HERITE).exists(), (
            "succes.db ne doit pas être renommée"
        )
        assert not (foyer_hors_temporaire / NOM_BASE).exists(), "aucune vie.db"

    def test_la_garde_ne_depend_pas_de_la_facon_d_importer(self, foyer_hors_temporaire):
        """L'import en tête de module, que la garde du conftest laissait
        passer : ``migrer_base_vie`` est importée en tête de CE fichier, avant
        toute fixture — c'est la vraie fonction, prise telle quelle."""
        resultat = migrer_base_vie(foyer_hors_temporaire)

        assert resultat.etat == "ignoree_en_test", resultat
        assert (foyer_hors_temporaire / NOM_BASE_HERITE).exists()

    def test_sous_le_dossier_temporaire_la_migration_a_lieu(
        self, foyer_hors_temporaire
    ):
        """Témoin : la garde ne doit pas neutraliser les tests de migration."""
        import tempfile

        dedans = Path(tempfile.gettempdir()) / "foyer"
        dedans.mkdir()
        _remplir_heritee(dedans / NOM_BASE_HERITE, taches=2)

        assert emplacement.migrer_base_vie(dedans).etat == "migree"
