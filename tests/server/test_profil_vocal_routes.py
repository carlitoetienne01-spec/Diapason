"""§78/§100 : profil local, authentifié, explicite et préservé en cas d'échec."""

import base64
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.server.auth_middleware import AuthMiddleware
from diapason.server.profil_vocal_routes import profil_vocal_router
from diapason.speech.speaker_id import SpeakerVerifier


@pytest.fixture()
def client(tmp_path, monkeypatch):
    v = SpeakerVerifier(profile_path=tmp_path / "profil.npz")
    monkeypatch.setattr(
        v, "embed", Mock(return_value=np.array([1.0, 0.0], dtype=np.float32))
    )
    monkeypatch.setattr("diapason.server.profil_vocal_routes.get_verifier", lambda: v)
    app = FastAPI()
    app.include_router(profil_vocal_router)
    app.add_middleware(AuthMiddleware, api_key="cle-de-test")
    with TestClient(app, headers={"Authorization": "Bearer cle-de-test"}) as c:
        yield c, v


def captures():
    pcm = (np.sin(np.arange(48000) * 0.1) * 4000).astype("<i2").tobytes()
    return [{"audio": base64.b64encode(pcm).decode()}] * 8


class TestRoutesProfil:
    def test_le_parcours_ne_persiste_qu_a_la_confirmation(self, client):
        """§100 : validation, sauvegarde, relecture et essai sans outil."""
        c, v = client
        assert c.get("/v1/voice/profile").json()["enrolled"] is False, "aucun profil"
        sample = captures()[0]
        assert c.post("/v1/voice/profile/sample", json={**sample, "index": 0}).json()[
            "accepted"
        ], "capture valide"
        assert v.echantillons == 0, "validation sans écriture"
        r = c.put(
            "/v1/voice/profile", json={"revision": "absent", "samples": captures()}
        )
        assert r.status_code == 200 and r.json()["sampleCount"] == 8, (
            "confirmation persistée"
        )
        revision = r.json()["revision"]
        assert c.post("/v1/voice/profile/check", json=sample).json() == {
            "result": "recognized"
        }, "test seul"
        assert v.revision == revision, "le test ne change pas le profil"

    @pytest.mark.parametrize(
        ("methode", "chemin"),
        [("GET", ""), ("PUT", ""), ("POST", "/sample"), ("POST", "/check")],
    )
    def test_une_cle_locale_est_obligatoire(self, client, methode, chemin):
        """§78 : une route de profil ne devient pas une route de santé publique."""
        c, _ = client
        c.headers.clear()
        assert c.request(methode, "/v1/voice/profile" + chemin).status_code == 401, (
            "clé exigée"
        )

    @pytest.mark.parametrize(
        ("methode", "chemin"),
        [("GET", ""), ("PUT", ""), ("POST", "/sample"), ("POST", "/check")],
    )
    def test_le_telephone_ne_peut_pas_modifier_l_identite_du_mac(
        self, client, monkeypatch, methode, chemin
    ):
        """§78 : même une session d'appareil valide reste hors de ce pouvoir."""
        c, _ = client
        monkeypatch.setattr(
            "diapason.server.profil_vocal_routes.depuis_le_telephone", lambda: True
        )
        assert c.request(methode, "/v1/voice/profile" + chemin).status_code == 403, (
            "réservé au bureau"
        )

    @pytest.mark.parametrize(
        "audio", ["!!!!", base64.b64encode(b"x").decode(), "a" * 341340]
    )
    def test_les_captures_invalides_sont_bornees(self, client, audio):
        """§78 : PCM malformé ou trop long refusé avant ONNX."""
        c, v = client
        assert c.post("/v1/voice/profile/check", json={"audio": audio}).status_code in (
            400,
            422,
        ), "refus explicite"
        v.embed.assert_not_called()

    def test_l_echec_d_ecriture_est_un_echec_http(self, client, monkeypatch):
        """§100 : le client n'affiche pas enregistré sur une erreur disque."""
        c, _ = client
        monkeypatch.setattr(
            "diapason.speech.speaker_id.os.replace", Mock(side_effect=OSError())
        )
        r = c.put(
            "/v1/voice/profile", json={"revision": "absent", "samples": captures()}
        )
        assert r.status_code == 503, "pas de faux succès"
        assert r.json()["detail"]["reason"] == "saveFailed", (
            "motif utilisable sans trace interne"
        )
