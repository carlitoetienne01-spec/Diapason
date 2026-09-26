"""Shared fixtures for server route tests.

Server tests build apps via ``create_app``, which (with traces enabled by
default) wires a ``TraceStore`` at the real ``~/.diapason/traces.db``. Now
that the chat endpoints actually *write* traces, an unguarded run would
pollute the developer's real trace DB and make tests non-hermetic. This
autouse fixture redirects the traces DB to a per-test temp path.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_traces_db(tmp_path, monkeypatch):
    """Point ``config.traces.db_path`` at a temp file for every server test.

    ``load_config`` returns a fresh ``DiapasonConfig`` per call (no caching), so
    wrapping it to rewrite ``traces.db_path`` only affects calls made during
    the test — there is no global leak.
    """
    from diapason.core import config as _config

    real_load_config = _config.load_config
    db_path = str(tmp_path / "traces.db")

    def _patched_load_config(*args, **kwargs):
        cfg = real_load_config(*args, **kwargs)
        cfg.traces.db_path = db_path
        return cfg

    monkeypatch.setattr(_config, "load_config", _patched_load_config)
    return db_path


@pytest.fixture(autouse=True)
def _isoler_le_foyer(tmp_path, monkeypatch):
    """Aucun test serveur n'ouvre le VRAI ``~/.diapason``.

    Constaté le 26/09/2026 par une contre-épreuve lancée avec un HOME
    factice : ``_isolate_traces_db`` ne couvre que ``load_config``, or un
    test qui passe un ``DiapasonConfig()`` direct à ``create_app`` le
    contourne. Deux tests (le micro de la boucle locale dans
    test_passerelle_tailnet.py, le chat 404 de test_app_lan.py) créaient
    ainsi ``traces.db``, ``digest.db``, ``mesh.db`` et l'identité du
    maillage dans le foyer réel — et le vrai ``mesh.db`` de Carlito porte
    depuis les deux tables de session que seule la branche chantier/phase2
    déclare. Un test qui pose son propre ``DIAPASON_HOME`` le remplace.
    """
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "foyer-de-test"))
