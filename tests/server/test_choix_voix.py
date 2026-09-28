"""§100 : le choix vocal est durable et n'ouvre pas le reste de la configuration."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.server.config_routes import create_config_router


def test_seule_une_voix_installee_peut_devenir_le_choix_par_defaut(
    tmp_path, monkeypatch
):
    cible = tmp_path / "config.toml"
    monkeypatch.setattr("diapason.server.config_routes._config_path", lambda: cible)
    monkeypatch.setattr(
        "diapason.speech.realtime.voix_expressive.voix_disponibles",
        lambda: ["qwen3-b"],
    )
    app = FastAPI()
    app.include_router(create_config_router())
    with TestClient(app) as client:
        for voix in ("qwen3-b",):
            r = client.post(
                "/v1/config/set", json={"key": "speech.realtime.voice", "value": voix}
            )
            assert r.status_code == 200, (
                "la voix masculine installée reste sélectionnable"
            )
            assert voix in cible.read_text(), "le choix est durable"
        for cle, valeur in (
            ("speech.realtime.voice", "inconnue"),
            ("speech.realtime.voice", "qwen3-a"),
            ("speech.realtime.voice", "ff_siwis"),
            ("speech.realtime.voice_lock", False),
        ):
            r = client.post("/v1/config/set", json={"key": cle, "value": valeur})
            assert r.status_code == 400, (
                "le choix de timbre n'ouvre aucun autre réglage"
            )
