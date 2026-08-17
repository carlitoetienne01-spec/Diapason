"""« Connecté » doit vouloir dire « je peux lire ».

Sur macOS, les bases de Messages, Notes et Santé sont sous protection TCC :
le fichier est visible — ``exists()`` rend ``True`` — et toute lecture est
refusée tant que l'accès disque complet n'est pas accordé. Les connecteurs
répondaient ``exists()`` à la question « es-tu connecté ? », et annonçaient
donc une connexion à une base dont ils ne pouvaient pas lire une ligne.

Le coût est double : ``connect --list`` affiche « connected » en vert, la
synchronisation ne rapporte rien, et rien n'explique pourquoi. C'est la
famille de défauts que l'audit appelait « l'interface qui promet ».
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from diapason.connectors._stubs import can_read_sqlite


@pytest.fixture
def base_lisible() -> Path:
    p = Path(tempfile.mkdtemp()) / "vraie.db"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.close()
    return p


class TestCanReadSqlite:
    def test_une_vraie_base_est_lisible(self, base_lisible):
        assert can_read_sqlite(base_lisible) is True

    def test_un_fichier_absent_ne_l_est_pas(self):
        assert can_read_sqlite(Path("/tmp/absolument-rien-ici.db")) is False

    def test_un_fichier_qui_n_est_pas_une_base_ne_l_est_pas(self):
        p = Path(tempfile.mkdtemp()) / "pas-une-base.db"
        p.write_text("ceci est du texte, pas du SQLite")
        assert can_read_sqlite(p) is False

    def test_un_fichier_illisible_ne_l_est_pas(self, base_lisible):
        """Le cas qui compte : le fichier EXISTE et la lecture est refusée.

        C'est exactement ce que produit TCC sur ~/Library/Messages/chat.db,
        et exactement ce que ``exists()`` ne sait pas distinguer.
        """
        base_lisible.chmod(0o000)
        try:
            assert base_lisible.exists() is True, "le fichier reste visible"
            assert can_read_sqlite(base_lisible) is False
        finally:
            base_lisible.chmod(0o600)


class TestLesConnecteursLocauxNeMententPlus:
    """Chacun de ces trois lit une base protégée par TCC."""

    @pytest.mark.parametrize(
        "module,classe,attribut",
        [
            ("imessage", "IMessageConnector", "_db_path"),
            ("apple_notes", "AppleNotesConnector", "_db_path"),
        ],
    )
    def test_une_base_illisible_est_declaree_deconnectee(
        self, module, classe, attribut, base_lisible, monkeypatch
    ):
        import importlib

        mod = importlib.import_module(f"diapason.connectors.{module}")
        connecteur = getattr(mod, classe)()

        monkeypatch.setattr(connecteur, attribut, base_lisible)
        assert connecteur.is_connected() is True, "une base lisible = connecté"

        base_lisible.chmod(0o000)
        try:
            assert connecteur.is_connected() is False
        finally:
            base_lisible.chmod(0o600)

    def test_apple_health_accepte_encore_un_export(self, base_lisible, monkeypatch):
        """L'export Santé est un fichier que la personne a déposé elle-même :
        son existence est la bonne question pour lui, contrairement à la base
        HealthKit."""
        from diapason.connectors.apple_health import AppleHealthConnector

        c = AppleHealthConnector()
        monkeypatch.setattr(c, "_healthkit_db_path", Path("/tmp/rien.db"))
        monkeypatch.setattr(c, "_export_path", base_lisible)
        assert c.is_connected() is True
