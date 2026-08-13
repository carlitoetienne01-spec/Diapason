# ruff: noqa: E402 -- optional FastAPI dependency is checked before imports

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from diapason.core.config import DiapasonConfig
from diapason.server.app import create_app


def _client(engine):
    app = create_app(engine, "qwen3:8b", config=DiapasonConfig())
    return TestClient(app)


def test_prewarm_local_ollama_model():
    engine = MagicMock()
    engine.engine_id = "ollama"
    engine._host = "http://127.0.0.1:11434"
    engine._keep_alive = "30m"
    engine.prewarm.return_value = True

    response = _client(engine).post(
        "/v1/models/prewarm",
        json={"model": "qwen3:8b"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "model": "qwen3:8b",
        "keep_alive": "30m",
    }
    engine.prewarm.assert_called()


def test_prewarm_refuses_non_ollama_engine():
    engine = MagicMock()
    engine.engine_id = "cloud"
    engine._host = "https://example.com"

    response = _client(engine).post(
        "/v1/models/prewarm",
        json={"model": "remote-model"},
    )

    assert response.status_code == 409
