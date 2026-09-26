"""Le garde-fou de tests/server/conftest.py : aucun test serveur n'écrit chez Carlito.

26/09/2026. Ce Mac est aussi le runner de la CI, et le serveur launchd lit
~/.diapason. Deux tests créaient traces.db, digest.db et mesh.db dans le
foyer réel en passant un DiapasonConfig() direct à create_app ; le vrai
mesh.db a ainsi reçu un schéma que le serveur en service ne déclare pas.
"""

from __future__ import annotations

from pathlib import Path


class TestLeFoyerDesTestsServeur:
    def test_le_foyer_resolu_est_jetable(self, tmp_path):
        """Sans la fixture autouse, get_config_dir() rend ~/.diapason."""
        from diapason.core.config import DiapasonConfig
        from diapason.core.paths import get_config_dir

        foyer = get_config_dir()
        assert foyer != (Path.home() / ".diapason").resolve(), (
            "un test serveur résout le VRAI ~/.diapason"
        )
        assert tmp_path.resolve() in foyer.parents, foyer
        assert Path(DiapasonConfig().traces.db_path).parent == foyer, (
            "un DiapasonConfig() direct doit suivre le foyer jetable"
        )
