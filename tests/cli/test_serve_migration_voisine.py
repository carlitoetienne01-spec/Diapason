"""Un `serve` sur un autre port ne migre pas la base d'un serveur en marche.

Plan de la phase 1b, étape 5 (docs/development/diapason-mobile.md). La règle
« le port est rendu, donc l'ancien serveur est mort » ne vaut que pour le
MÊME port. Contre-épreuve du 25/09/2026 : un ancien serveur tournait sur la
base héritée ; une migration lancée à côté (ce que fait un
`diapason serve --port 8010` de session parallèle) a rendu « migree », et
l'ancien serveur a aussitôt répondu 500 (« no such table: succes_tasks »)
après avoir recréé une succes.db de 0 octet — cassé en silence jusqu'au
kickstart suivant.
"""

from __future__ import annotations

import importlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from click.testing import CliRunner

serve_mod = importlib.import_module("diapason.cli.serve")


def _base_heritee(dossier: Path) -> Path:
    chemin = dossier / "succes.db"
    with closing(sqlite3.connect(chemin)) as conn:
        conn.execute("CREATE TABLE succes_tasks (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO succes_tasks VALUES ('t1')")
        conn.commit()
    return chemin


class _Arret(Exception):
    """Coupe `serve` juste après la migration, avant le moteur."""


@pytest.fixture
def lancer_serve(tmp_path, monkeypatch):
    """`diapason serve --port <p>` jusqu'à la migration, avec un Diapason sain
    simulé sur les ports de ``voisins``."""
    from diapason.cli import cli
    from diapason.core.config import DiapasonConfig
    from diapason.vie import routes as routes_vie

    config = DiapasonConfig()
    config.server.host = "127.0.0.1"
    config.server.port = 8000
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path))
    monkeypatch.setattr(serve_mod, "load_config", lambda *a, **k: config)
    monkeypatch.setattr(serve_mod, "inject_credentials", lambda: None)
    monkeypatch.setattr(serve_mod, "attendre_le_port", lambda *a, **k: 0)

    def arreter():
        raise _Arret

    monkeypatch.setattr(serve_mod, "register_builtin_models", arreter)
    sondes: list[int] = []

    def lancer(port: int, voisins: tuple[int, ...]):
        def sonder(hote, p):
            sondes.append(p)
            return serve_mod.DIAPASON_SAIN if p in voisins else None

        monkeypatch.setattr(serve_mod, "sonder_diapason", sonder)
        routes_vie.set_store_for_tests(None)
        try:
            resultat = CliRunner().invoke(cli, ["serve", "--port", str(port)])
        finally:
            routes_vie.set_store_for_tests(None)
        assert isinstance(resultat.exception, _Arret), (
            resultat.output,
            resultat.exception,
        )
        return resultat, sondes

    return lancer


class TestUnServeurVoisin:
    def test_un_diapason_sur_le_port_configure_garde_sa_base(
        self, tmp_path, lancer_serve
    ):
        """Le cas de la contre-épreuve : launchd sur :8000, un `serve --port
        8010` à côté. La migration revient au serveur en marche."""
        _base_heritee(tmp_path)

        resultat, sondes = lancer_serve(8010, voisins=(8000,))

        assert 8000 in sondes, "le port configuré doit être sondé"
        assert (tmp_path / "succes.db").exists(), (
            "la base du serveur en marche ne doit pas être renommée sous lui"
        )
        assert not (tmp_path / "vie.db").exists(), "aucune vie.db à côté"
        assert ":8000" in resultat.output, (
            f"le report doit dire pourquoi : {resultat.output!r}"
        )

    def test_sans_voisin_la_migration_a_lieu(self, tmp_path, lancer_serve):
        _base_heritee(tmp_path)

        lancer_serve(8010, voisins=())

        assert (tmp_path / "vie.db").exists(), "personne d'autre : on migre"
        assert not (tmp_path / "succes.db").exists()

    def test_sur_le_port_configure_on_ne_se_sonde_pas_soi_meme(
        self, tmp_path, lancer_serve
    ):
        """Le cas de launchd : le port vient d'être rendu (attendre_le_port),
        il n'y a pas d'autre port à interroger."""
        _base_heritee(tmp_path)

        _, sondes = lancer_serve(8000, voisins=(8000,))

        assert 8000 not in sondes, "sonder son propre port n'a pas de sens"
        assert (tmp_path / "vie.db").exists(), "le serveur du port configuré migre"

    def test_rien_a_migrer_rien_a_sonder(self, tmp_path, lancer_serve):
        """Une base déjà migrée : aucun serveur voisin n'a de raison de
        retarder quoi que ce soit, et aucune sonde ne coûte ses deux
        secondes de délai."""
        from diapason.vie.sync import VieSyncStore

        VieSyncStore(tmp_path / "vie.db")

        _, sondes = lancer_serve(8010, voisins=(8000,))

        assert sondes == [], f"aucune sonde attendue, vu {sondes}"
