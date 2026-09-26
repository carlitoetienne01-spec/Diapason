"""Les réglages du Mac lus hors de l'app de bureau — vrais, et sans secret.

Échec évité (26/09/2026, phase 3 du chantier mobile, étape 4) : hors de
Tauri, le bundle inventait « aucune clé cloud » et « source ollama ». Le
téléphone aurait affiché une source qui contredit celle du Mac (§5, §100).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from diapason.core import cloud_keys  # noqa: E402
from diapason.server.lecture_reglages import (  # noqa: E402
    MOTEUR_PAR_DEFAUT,
    NOMS_DE_CLES_GERES,
    create_lecture_reglages_router,
    lire_source_inference,
    nom_de_cle_du_moteur,
    noms_de_cles_geres,
)

LIB_RS = (
    Path(__file__).resolve().parents[2] / "frontend" / "src-tauri" / "src" / "lib.rs"
)
SECRET = "sk-ceci-ne-doit-jamais-sortir"


@pytest.fixture
def maison(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path))
    for nom in NOMS_DE_CLES_GERES:
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.delenv("LM_STUDIO_API_KEY", raising=False)
    # Jamais le vrai trousseau dans un test.
    monkeypatch.setattr(cloud_keys, "_read_keychain", lambda _nom: None)
    cloud_keys._cache.clear()
    return tmp_path


@pytest.fixture
def client(maison):
    app = FastAPI()
    app.include_router(create_lecture_reglages_router())
    return TestClient(app)


class TestLesClesCloud:
    def test_dit_presente_ou_absente_sans_jamais_rendre_la_valeur(
        self, client, monkeypatch
    ):
        """Le téléphone doit savoir qu'une clé existe, pas la lire."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
        reponse = client.get("/v1/cloud/keys")
        assert reponse.status_code == 200
        assert SECRET not in reponse.text, "la valeur d'une clé est sortie du serveur"
        etats = {ligne["key"]: ligne["set"] for ligne in reponse.json()["keys"]}
        assert etats["ANTHROPIC_API_KEY"] is True
        assert etats["OPENAI_API_KEY"] is False
        assert set(etats) == set(NOMS_DE_CLES_GERES)

    def test_une_cle_du_trousseau_compte_comme_presente(self, client, monkeypatch):
        """Le serveur launchd lit le trousseau quand l'environnement est vide."""
        monkeypatch.setattr(
            cloud_keys,
            "_read_keychain",
            lambda nom: SECRET if nom == "GEMINI_API_KEY" else None,
        )
        reponse = client.get("/v1/cloud/keys")
        assert SECRET not in reponse.text
        etats = {ligne["key"]: ligne["set"] for ligne in reponse.json()["keys"]}
        assert etats["GEMINI_API_KEY"] is True

    def test_une_source_personnalisee_ajoute_la_cle_de_son_moteur(self, maison, client):
        """Comme `managed_cloud_key_names` : le moteur choisi a sa clé."""
        (maison / "inference.json").write_text(
            json.dumps({"kind": "custom", "engine": "lm-studio"}), encoding="utf-8"
        )
        noms = [ligne["key"] for ligne in client.get("/v1/cloud/keys").json()["keys"]]
        assert "LM_STUDIO_API_KEY" in noms
        assert noms == sorted(noms), "l'ordre doit être celui de l'app de bureau (trié)"

    def test_la_liste_est_celle_de_l_app_de_bureau(self):
        """Une clé ajoutée dans lib.rs seulement serait tue au téléphone."""
        source = LIB_RS.read_text(encoding="utf-8")
        bloc = re.search(
            r"const MANAGED_CLOUD_KEY_NAMES: &\[&str\] = &\[(.*?)\];", source, re.S
        )
        assert bloc, "MANAGED_CLOUD_KEY_NAMES introuvable dans lib.rs"
        cote_rust = re.findall(r'"([A-Z0-9_]+)"', bloc.group(1))
        assert tuple(cote_rust) == NOMS_DE_CLES_GERES, (
            "les deux listes de clés divergent"
        )
        repli = re.search(r'const CUSTOM_FALLBACK_ENGINE: &str = "([^"]+)";', source)
        assert repli and repli.group(1) == MOTEUR_PAR_DEFAUT


class TestLeNomDeCleDuMoteur:
    def test_suit_engine_api_key_name(self):
        assert nom_de_cle_du_moteur("lmstudio") == "LMSTUDIO_API_KEY"
        assert nom_de_cle_du_moteur("lm-studio") == "LM_STUDIO_API_KEY"
        assert nom_de_cle_du_moteur("__") == "LMSTUDIO_API_KEY"

    def test_sans_moteur_on_prend_celui_par_defaut(self):
        assert "LMSTUDIO_API_KEY" in noms_de_cles_geres({"kind": "custom"})
        assert "LMSTUDIO_API_KEY" not in noms_de_cles_geres({"kind": "ollama"})


class TestLaSourceDInference:
    def test_sans_fichier_c_est_ollama_comme_dans_l_app(self, client):
        assert client.get("/v1/inference/source").json() == {"kind": "ollama"}

    def test_rend_le_choix_ecrit_par_l_app_de_bureau(self, maison, client):
        (maison / "inference.json").write_text(
            json.dumps(
                {
                    "kind": "custom",
                    "model": "qwen3.5:9b",
                    "host": "http://127.0.0.1:1234",
                    "engine": "lmstudio",
                }
            ),
            encoding="utf-8",
        )
        assert client.get("/v1/inference/source").json() == {
            "kind": "custom",
            "model": "qwen3.5:9b",
            "host": "http://127.0.0.1:1234",
            "engine": "lmstudio",
        }

    def test_un_fichier_illisible_vaut_ollama(self, maison):
        """Même verdict que `parse_inference_config` : jamais bloqué sans source."""
        chemin = maison / "inference.json"
        for brut in ("{pas du json", "[]", json.dumps({"kind": "nuage"})):
            chemin.write_text(brut, encoding="utf-8")
            assert lire_source_inference(chemin) == {"kind": "ollama"}, brut

    def test_l_hote_perd_ses_identifiants(self, maison):
        """Un hôte `user:mot@…` porterait un secret jusqu'au téléphone."""
        chemin = maison / "inference.json"
        chemin.write_text(
            json.dumps(
                {
                    "kind": "custom",
                    "host": f"https://moi:{SECRET}@serveur.local:8443/base",
                }
            ),
            encoding="utf-8",
        )
        source = lire_source_inference(chemin)
        assert SECRET not in json.dumps(source)
        assert source["host"] == "https://serveur.local:8443/base"


class TestLesRoutesSontMonteesEtEnLectureSeule:
    def test_create_app_les_sert(self, maison):
        from diapason.server.app import create_app

        client = TestClient(create_app(MagicMock(), "test-model"))
        assert client.get("/v1/inference/source").status_code == 200
        assert client.get("/v1/cloud/keys").status_code == 200

    def test_aucune_ecriture_n_est_exposee(self, client):
        """Choisir une source ou poser une clé reste à l'app de bureau."""
        assert (
            client.post("/v1/inference/source", json={"kind": "custom"}).status_code
            == 405
        )
        assert client.post("/v1/cloud/keys", json={}).status_code == 405
