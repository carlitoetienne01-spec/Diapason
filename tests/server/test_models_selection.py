"""/v1/models : jamais un modèle d'embeddings, le modèle par défaut en tête.

L'app de bureau prend le PREMIER modèle de cette liste comme modèle de chat
quand rien n'est encore choisi. Le 23 août 2026, nomic-embed-text est passé
en tête (tri Ollama par date) et chaque message répondait HTTP 400
« does not support chat ».
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from diapason.core.config import DiapasonConfig  # noqa: E402
from diapason.server.app import create_app  # noqa: E402
from diapason.server.routes import _est_modele_embedding  # noqa: E402


def test_les_embeddings_se_reconnaissent():
    assert _est_modele_embedding("nomic-embed-text:latest")
    assert _est_modele_embedding("mxbai-embed-large")
    assert _est_modele_embedding("BGE-m3")
    assert not _est_modele_embedding("qwen3.5:9b")
    assert not _est_modele_embedding("qwen3:14b")


def _client(modeles, defaut="qwen3.5:9b"):
    engine = MagicMock()
    engine.engine_id = "ollama"
    engine.health.return_value = True
    engine.list_models.return_value = modeles
    cfg = DiapasonConfig()
    cfg.analytics.enabled = False
    cfg.traces.enabled = False
    app = create_app(engine, defaut, config=cfg)
    return TestClient(app)


def test_le_selecteur_ne_voit_jamais_un_embedding():
    client = _client(["nomic-embed-text:latest", "qwen3.8:27b-mlx", "qwen3.5:9b"])
    ids = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert "nomic-embed-text:latest" not in ids
    assert "qwen3.8:27b-mlx" in ids


def test_le_modele_par_defaut_ouvre_la_liste():
    client = _client(
        ["nomic-embed-text:latest", "qwen3.8:27b-mlx", "qwen3:14b", "qwen3.5:9b"],
        defaut="qwen3.5:9b",
    )
    ids = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert ids[0] == "qwen3.5:9b"
    assert ids == ["qwen3.5:9b", "qwen3.8:27b-mlx", "qwen3:14b"]
