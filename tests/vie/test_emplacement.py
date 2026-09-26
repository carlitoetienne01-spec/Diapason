"""succes.db devient vie.db — sans ses photos, rien n'aurait tenu.

25/09/2026, étape 5 du plan de la phase 1b (docs/development/
diapason-mobile.md). Chaque test tourne dans un dossier de données
temporaire : la vraie base de Carlito (311 Mo, 62 photos) ne se touche
qu'au redémarrage du serveur, jamais depuis un test (voir la garde de
tests/conftest.py).
"""

from __future__ import annotations

import base64
import importlib
import multiprocessing
import os
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
    DeuxBasesVie,
    chemin_base_vie,
    migrer_base_vie,
)
from diapason.vie.sync import VieSyncStore

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _comptes(chemin: Path) -> dict[str, int]:
    with closing(sqlite3.connect(chemin)) as conn:
        return {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
            for table in ("succes_tasks", "succes_notes", "succes_photos")
        }


def _remplir(chemin: Path, *, taches: int = 3) -> VieSyncStore:
    magasin = VieSyncStore(chemin)
    for i in range(taches):
        magasin.create_task({"title": f"Tâche {i}", "date": "2026-09-25"})
    magasin.create_note({"title": "Note", "content": "texte"})
    return magasin


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
        _remplir(donnees / NOM_BASE_HERITE)
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

    def test_un_magasin_par_defaut_ouvre_succes_db_non_migree(
        self, donnees, monkeypatch
    ):
        """Le tick de 900 s avant le redémarrage du serveur : il lit l'ancienne
        base au lieu de créer une vie.db vide à côté de la pleine."""
        _remplir(donnees / NOM_BASE_HERITE, taches=2)
        monkeypatch.setenv("DIAPASON_HOME", str(donnees))
        magasin = VieSyncStore()
        assert magasin.db_path == donnees / NOM_BASE_HERITE
        assert len(magasin.list_tasks()) == 2, "les tâches de succes.db doivent se lire"
        assert not (donnees / NOM_BASE).exists(), "aucune vie.db ne doit naître à côté"
        assert magasin.photos_dir == donnees / DOSSIER_PHOTOS_HERITE


class TestLaMigration:
    def test_le_fichier_change_de_nom_et_garde_ses_comptes(self, donnees):
        _remplir(donnees / NOM_BASE_HERITE, taches=5)
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
        _remplir(atelier / NOM_BASE_HERITE, taches=1)
        conn = sqlite3.connect(atelier / NOM_BASE_HERITE)
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
            titres = [r[0] for r in lecture.execute("SELECT title FROM succes_tasks")]
        assert titres == ["écrite dans le WAL"], f"transaction du WAL perdue : {titres}"

    def test_une_seconde_connexion_reporte_la_migration(self, donnees):
        _remplir(donnees / NOM_BASE_HERITE)
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
        _remplir(donnees / NOM_BASE_HERITE)
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
        _remplir(donnees / NOM_BASE_HERITE)
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
        _remplir(donnees / NOM_BASE_HERITE, taches=2)
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

        _remplir(donnees / NOM_BASE_HERITE, taches=1)
        _remplir(donnees / NOM_BASE, taches=1)
        monkeypatch.setenv("DIAPASON_HOME", str(donnees))
        outil = VieTasksTool()  # ne doit pas lever
        resultat = outil.execute(action="list")
        assert resultat.success is False, "deux bases : l'outil doit échouer"
        assert "Deux bases de vie" in resultat.content, resultat.content

    def test_une_base_vide_recreee_part_dans_les_sauvegardes(self, donnees):
        """Le fantôme : une succes.db recréée vide par un vieux processus
        après la migration. Elle part dans backups/, la pleine reste seule."""
        _remplir(donnees / NOM_BASE_HERITE, taches=4)
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
                "SELECT id, file_path, thumb_path FROM succes_photos"
            ).fetchall():
                conn.execute(
                    "UPDATE succes_photos SET file_path=?, thumb_path=? WHERE id=?",
                    (str(donnees / ligne[1]), str(donnees / ligne[2]), ligne[0]),
                )
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
                for r in conn.execute("SELECT file_path, thumb_path FROM succes_photos")
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
                "SELECT file_path FROM succes_photos WHERE id=?", (photo["id"],)
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

        def migrer(console=None):
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
    def test_la_suite_ne_migre_jamais_le_vrai_foyer(self):
        """La garde de tests/conftest.py : hors d'un dossier temporaire, la
        migration est un constat sans effet."""
        vrai = Path(os.path.expanduser("~")) / ".diapason"
        assert emplacement.migrer_base_vie(vrai).etat == "ignoree_en_test"
