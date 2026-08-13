# ruff: noqa: E402 -- optional FastAPI dependency is checked before imports

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from diapason.actions.models import ActionOutcome
from diapason.core.config import DiapasonConfig
from diapason.desktop.app_writer import WriteResult
from diapason.server.app import create_app


def _client():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {"content": "model", "usage": {}}
    app = create_app(engine, "test-model", config=DiapasonConfig())
    return TestClient(app, client=("127.0.0.1", 50000)), app, engine


def _outcome():
    return ActionOutcome(
        handled=True,
        success=True,
        message="⚡ Notes ouvert.",
        action="voice.focus_app",
        verified=True,
        total_ms=12.0,
    )


def test_api_default_does_not_control_host():
    client, app, engine = _client()
    app.state.lightning_actions.handle = MagicMock(return_value=_outcome())
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "ouvre Notes"}],
        },
    )
    assert response.status_code == 200
    app.state.lightning_actions.handle.assert_not_called()
    engine.generate.assert_called_once()


def test_explicit_auto_mode_bypasses_model():
    client, app, engine = _client()
    app.state.lightning_actions.handle = MagicMock(return_value=_outcome())
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "ouvre Notes"}],
            "action_mode": "auto",
        },
    )
    assert response.status_code == 200
    assert response.json()["lightning"]["action"] == "voice.focus_app"
    assert response.json()["choices"][0]["message"]["content"].startswith("⚡")
    engine.generate.assert_not_called()


def test_streaming_fast_action_uses_openai_sse_shape():
    client, app, engine = _client()
    app.state.lightning_actions.handle = MagicMock(return_value=_outcome())
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "ouvre Notes"}],
            "action_mode": "auto",
            "stream": True,
        },
    )
    assert response.status_code == 200
    assert "⚡ Notes ouvert." in response.text
    assert '"lightning"' in response.text
    assert "data: [DONE]" in response.text
    engine.generate.assert_not_called()


def test_client_tools_always_disable_host_actions():
    client, app, _engine = _client()
    app.state.lightning_actions.handle = MagicMock(return_value=_outcome())
    client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "ouvre Notes"}],
            "action_mode": "auto",
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "x", "parameters": {}},
                }
            ],
        },
    )
    app.state.lightning_actions.handle.assert_not_called()


def test_remote_client_cannot_opt_itself_into_host_control():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {"content": "model", "usage": {}}
    app = create_app(engine, "test-model", config=DiapasonConfig())
    app.state.lightning_actions.handle = MagicMock(return_value=_outcome())
    client = TestClient(app, client=("203.0.113.10", 50000))

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "ouvre Notes"}],
            "action_mode": "auto",
        },
    )

    assert response.status_code == 200
    app.state.lightning_actions.handle.assert_not_called()
    engine.generate.assert_called_once()


def test_generated_content_is_created_then_written(monkeypatch):
    client, _app, engine = _client()
    engine.generate.return_value = {
        "content": "Résumé créé par le modèle.",
        "usage": {},
    }
    write = MagicMock(
        return_value=WriteResult(
            success=True,
            method="accessibility",
            app="Notes",
            verified=True,
        )
    )
    monkeypatch.setattr("diapason.desktop.app_writer.write_text", write)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [
                {
                    "role": "user",
                    "content": "ouvre Notes et rédige un résumé professionnel",
                }
            ],
            "action_mode": "auto",
        },
    )

    assert response.status_code == 200
    assert response.json()["lightning"]["action"] == "app.generate_and_type"
    assert "créé et écrit" in response.json()["choices"][0]["message"]["content"]
    write.assert_called_once()
    assert write.call_args.args[0] == "Résumé créé par le modèle."
