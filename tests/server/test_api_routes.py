"""Tests for extended API routes."""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from diapason.core.config import load_config as _load_config_reel  # noqa: E402
from diapason.server.api_routes import include_all_routes  # noqa: E402


def _make_app():
    app = FastAPI()
    include_all_routes(app)
    return app


class TestAgentRoutes:
    def test_list_agents(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert "registered" in data
        assert "running" in data

    def test_create_agent(self):
        client = TestClient(_make_app())
        resp = client.post("/v1/agents", json={"agent_type": "simple"})
        # May succeed or fail depending on agent_tools availability
        assert resp.status_code in (200, 501)

    def test_kill_nonexistent(self):
        client = TestClient(_make_app())
        resp = client.delete("/v1/agents/nonexistent")
        assert resp.status_code in (404, 501)


class TestMemoryRoutes:
    # 503 is the documented response when the native ``diapason_rust``
    # extension is absent from the venv (see TestMemoryRustMissing below).
    # These tests are only asserting "the route is wired up", so a backend
    # that cannot be built is tolerated the same way a 500 is.
    _BACKEND_OPTIONAL = (200, 500, 503)

    def test_search(self):
        client = TestClient(_make_app())
        resp = client.post("/v1/memory/search", json={"query": "test"})
        # May fail if SQLite not set up, that's ok
        assert resp.status_code in self._BACKEND_OPTIONAL

    def test_stats(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/memory/stats")
        assert resp.status_code in self._BACKEND_OPTIONAL


class TestMemoryRustMissing:
    """Regression for #502: when the native ``diapason_rust`` extension is
    missing from the serving venv, memory ops must surface a CLEAR, ACTIONABLE
    error — never the misleading "Failed to index path" or a 200 silent no-op.
    """

    @staticmethod
    def _client(monkeypatch):
        # Force the same failure mode as a venv without the compiled extension.
        def _boom():
            raise ImportError("No module named 'diapason_rust'")

        import diapason._rust_bridge as bridge

        monkeypatch.setattr(bridge, "get_rust_module", _boom)
        return TestClient(_make_app())

    def test_store_is_not_a_silent_noop(self, monkeypatch):
        client = self._client(monkeypatch)
        resp = client.post("/v1/memory/store", json={"content": "hi"})
        # Must NOT return the old 200 {"status":"stored","note":"no backend..."}.
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert "diapason_rust" in detail
        assert "maturin develop" in detail

    def test_index_surfaces_actionable_detail(self, monkeypatch, tmp_path):
        (tmp_path / "note.txt").write_text("hello world some content here")
        client = self._client(monkeypatch)
        resp = client.post("/v1/memory/index", json={"path": str(tmp_path)})
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        # The frontend reads this `detail`; it must point at the real cause,
        # not blame the indexed path.
        assert "diapason_rust" in detail
        assert detail != "Failed to index path"
        assert detail != "No memory backend available"

    def test_config_reports_unavailable(self, monkeypatch):
        client = self._client(monkeypatch)
        resp = client.get("/v1/memory/config")
        assert resp.status_code == 200
        data = resp.json()
        # Must not falsely report a healthy backend when none could be built.
        assert data["available"] is False
        assert "diapason_rust" in (data["detail"] or "")


class TestBudgetRoutes:
    def test_get_budget(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/budget")
        assert resp.status_code == 200
        data = resp.json()
        assert "limits" in data
        assert "usage" in data

    def test_set_limits(self):
        client = TestClient(_make_app())
        resp = client.put("/v1/budget/limits", json={"max_tokens_per_day": 100000})
        assert resp.status_code == 200
        assert resp.json()["limits"]["max_tokens_per_day"] == 100000


class TestMetricsRoute:
    def test_metrics_endpoint(self):
        client = TestClient(_make_app())
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "diapason" in resp.text or "No metrics" in resp.text


class TestSkillRoutes:
    def test_list_skills(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/skills")
        assert resp.status_code == 200
        assert "skills" in resp.json()


class TestSessionRoutes:
    def test_list_sessions(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/sessions")
        assert resp.status_code == 200


class TestTraceRoutes:
    def test_list_traces(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/traces")
        assert resp.status_code == 200


class TestLaListeDesCompetencesLitLeDisque:
    """28/09/2026 : GET /v1/skills rendait SkillRegistry.keys(), un registre
    que rien ne remplit — toujours {"skills": []}, même avec huit méthodes
    ECC importées (§5 : la route disait « rien » quand le disque disait
    « huit »). Et la lecture du disque se fait hors de la boucle : une
    route async qui lit en ligne fige la voix et le chat."""

    @pytest.fixture
    def disque(self, tmp_path, monkeypatch):
        # Le vrai load_config (lru_cache) : tests/server/conftest.py
        # l'enveloppe pour chaque test, et l'enveloppe n'a pas cache_clear.
        load_config = _load_config_reel

        skills = tmp_path / "skills"
        for source, nom in (
            ("ecc", "research-ops"),
            ("ecc", "growth-log"),
            ("hermes", "notes"),
        ):
            d = skills / source / nom
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: {nom}\ndescription: x\n---\nx\n")
            (d / ".source").write_text(
                f'source = "{source}:{nom}"\ncommit = "5064474abc"\norigine = "ECC"\n'
            )
        config = tmp_path / "config.toml"
        config.write_text(
            "[skills]\n"
            f'skills_dir = "{skills}"\n'
            "[[skills.sources]]\n"
            'source = "ecc"\n'
            "[skills.sources.filter]\n"
            'names = ["research-ops"]\n'
        )
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "home"))
        monkeypatch.setenv("DIAPASON_CONFIG", str(config))
        load_config.cache_clear()
        yield
        load_config.cache_clear()

    def test_les_competences_installees_sont_rendues(self, disque):
        client = TestClient(_make_app())
        par_nom = {s["name"]: s for s in client.get("/v1/skills").json()["skills"]}
        assert set(par_nom) == {"research-ops", "growth-log", "notes"}, par_nom
        assert par_nom["research-ops"] == {
            "name": "research-ops",
            "source": "ecc",
            "commit": "5064474abc",
            "origin": "ECC",
            "active": True,
            "reachedBy": "skill_guide",
            "allowListed": True,
        }
        assert par_nom["growth-log"]["active"] is False, (
            "installée mais hors liste : jamais servie, et la route le dit"
        )
        assert par_nom["growth-log"]["reachedBy"] is None
        assert par_nom["notes"]["reachedBy"] == "cli-agents", (
            "une compétence hors ecc n'atteint pas le chat : la route ne le prétend pas"
        )
        assert "path" not in str(par_nom), "aucun chemin du disque ne part au téléphone"

    def test_la_lecture_du_disque_se_fait_hors_de_la_boucle(self, monkeypatch):
        import asyncio as _asyncio

        from diapason.server import api_routes

        vus: list[bool] = []

        def espion():
            try:
                _asyncio.get_running_loop()
                vus.append(True)
            except RuntimeError:
                vus.append(False)
            return []

        monkeypatch.setattr(api_routes, "_installed_skills", espion)
        TestClient(_make_app()).get("/v1/skills")
        assert vus == [False], (
            "la lecture du disque a tourné sur la boucle d'événements"
        )
