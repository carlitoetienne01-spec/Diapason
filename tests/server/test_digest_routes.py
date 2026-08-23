"""Tests for /api/digest endpoints."""

from __future__ import annotations

from datetime import datetime

import pytest

pytest.importorskip("fastapi", reason="diapason[server] not installed")

from diapason.agents.digest_store import DigestArtifact, DigestStore


@pytest.fixture()
def store(tmp_path):
    db_path = str(tmp_path / "digest.db")
    s = DigestStore(db_path=db_path)
    s.save(
        DigestArtifact(
            text="Good morning sir.",
            audio_path=tmp_path / "digest.mp3",
            sections={"messages": "3 emails"},
            sources_used=["gmail"],
            # L'heure LOCALE, pas UTC. ``get_today`` compare la date du tampon
            # à aujourd'hui dans le fuseau de la machine — c'est le sens du
            # champ, et sa docstring le dit. Un tampon UTC désigne déjà demain
            # à l'ouest de Greenwich dès le début de soirée.
            generated_at=datetime.now().astimezone(),
            model_used="test",
            voice_used="diapason",
        )
    )
    # Write fake audio file
    (tmp_path / "digest.mp3").write_bytes(b"fake-mp3")
    yield s
    s.close()


def _make_app(db_path: str):
    """A FastAPI app carrying only the digest router.

    Cette fonction enveloppait ``DigestStore.get_today`` dans un ``patch`` qui
    repliait sur ``get_latest``, pour « éviter les soucis de fuseau ». Deux
    choses clochaient. Le ``patch`` n'entourait que la CRÉATION du routeur et
    expirait avant la requête, si bien qu'il ne repliait jamais rien. Et un
    ``patch.object`` sur une classe ne survit pas à un rechargement de module :
    ``tests/cli/test_serve_single_build.py`` recharge les modules pour
    repeupler les registres, après quoi la route tient une AUTRE classe
    ``DigestStore`` que celle qu'on avait patchée — d'où deux échecs qui
    n'apparaissaient qu'en suite complète, jamais isolément.

    Le repli n'a plus lieu d'être : la fixture horodate en heure locale, ce que
    ``get_today`` sait lire. On corrige la cause plutôt que de la masquer.
    """
    from fastapi import FastAPI

    from diapason.server.digest_routes import create_digest_router

    app = FastAPI()
    app.include_router(create_digest_router(db_path=db_path))
    return app


def test_get_digest(store, tmp_path):
    from fastapi.testclient import TestClient

    resp = TestClient(_make_app(str(tmp_path / "digest.db"))).get("/api/digest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "Good morning sir."
    assert data["sources_used"] == ["gmail"]


def test_get_digest_audio(store, tmp_path):
    from fastapi.testclient import TestClient

    app = _make_app(str(tmp_path / "digest.db"))
    resp = TestClient(app).get("/api/digest/audio")
    assert resp.status_code == 200
    assert resp.content == b"fake-mp3"


def test_get_digest_404(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from diapason.server.digest_routes import create_digest_router

    app = FastAPI()
    app.include_router(create_digest_router(db_path=str(tmp_path / "empty.db")))

    client = TestClient(app)
    resp = client.get("/api/digest")
    assert resp.status_code == 404


def test_get_history(store, tmp_path):
    from fastapi.testclient import TestClient

    app = _make_app(str(tmp_path / "digest.db"))
    resp = TestClient(app).get("/api/digest/history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["voice_used"] == "diapason"
