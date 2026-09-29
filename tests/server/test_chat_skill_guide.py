"""De bout en bout : une méthode ECC importée atteint le modèle du chat.

28/09/2026. Le constat qui a lancé le chantier : une compétence importée
n'atteignait AUCUN modèle — le chat construit sa trousse depuis
ToolRegistry, où rien de ce qui est importé n'était inscrit. Un import seul
aurait été un faux SUCCESS (§5, §100). Ce test passe par la vraie route du
chat : la trousse PROPOSE skill_guide au moteur quand la source ecc est
active et non vide, le moteur l'appelle, et le texte de la méthode — sa
provenance en tête — revient au second tour du modèle. Coupée, la source
retire l'outil.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from diapason.core.config import load_config  # noqa: E402
from diapason.core.registry import ToolRegistry  # noqa: E402
from diapason.engine._stubs import StreamChunk  # noqa: E402
from diapason.server.app import create_app  # noqa: E402
from diapason.skills.provenance import render_toml  # noqa: E402
from diapason.tools.calculator import CalculatorTool  # noqa: E402
from diapason.tools.skill_guide import DEBUT, NOM, SkillGuideTool  # noqa: E402


@pytest.fixture(autouse=True)
def _reinscrire_les_outils(monkeypatch):
    """Le conftest racine vide ToolRegistry ; le module reste en cache. Et
    aucune vue de trousse ne passe d'un test à l'autre."""
    import diapason.tools.skill_guide as guide

    ToolRegistry.register_value("calculator", CalculatorTool)
    ToolRegistry.register_value(NOM, SkillGuideTool)
    monkeypatch.setattr(guide, "_VUE_DU_CHAT", None)


@pytest.fixture
def configuration(tmp_path: Path, monkeypatch):
    """La configuration du serveur ET celle que l'outil relit : la même,
    comme en production (serve.py et l'outil passent par load_config)."""
    methode = tmp_path / "skills" / "ecc" / "article-writing"
    methode.mkdir(parents=True)
    (methode / "SKILL.md").write_text(
        "---\nname: article-writing\ndescription: Write long-form content.\n"
        "metadata:\n  origin: ECC\n---\n\n# Article Writing\n\n"
        "Lead with the concrete thing.\n",
        encoding="utf-8",
    )
    (methode / ".source").write_text(
        render_toml(
            {
                "source": "ecc:article-writing",
                "commit": "5064474d4d762dc9640234a41617cccb79185cec",
                "version_ecc": "2.2.1",
                "origine": "ECC",
            }
        ),
        encoding="utf-8",
    )
    fichier = tmp_path / "config.toml"

    def charger(enabled: bool = True):
        fichier.write_text(
            "[agent]\n"
            'tools = "calculator"\n'
            'tool_approval = "auto"\n'
            "[analytics]\nenabled = false\n"
            "[traces]\nenabled = false\n"
            "[skills]\n"
            f'skills_dir = "{tmp_path / "skills"}"\n'
            "[[skills.sources]]\n"
            'source = "ecc"\n'
            f"enabled = {'true' if enabled else 'false'}\n"
            "[skills.sources.filter]\n"
            'names = ["article-writing"]\n',
            encoding="utf-8",
        )
        load_config.cache_clear()
        return load_config()

    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DIAPASON_CONFIG", str(fichier))
    yield charger
    load_config.cache_clear()


def _moteur(appels: list):
    """Tour 1 : lire la méthode. Tour 2 : répondre, en notant ce qu'il voit."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]

    async def stream_full(messages, **kwargs):
        appels.append({"messages": list(messages), "tools": kwargs.get("tools")})
        if len(appels) == 1:
            yield StreamChunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "c0",
                        "type": "function",
                        "function": {
                            "name": NOM,
                            "arguments": json.dumps(
                                {"operation": "lire", "nom": "article-writing"}
                            ),
                        },
                    }
                ]
            )
        else:
            yield StreamChunk(content="Voici la méthode.")

    async def stream(messages, **kwargs):
        yield "aucun outil"

    engine.stream_full = stream_full
    engine.stream = stream
    return engine


def _noms(outils) -> list[str]:
    noms = []
    for outil in outils or []:
        fonction = outil.get("function", outil) if isinstance(outil, dict) else {}
        noms.append(fonction.get("name"))
    return noms


def _demander(config, appels):
    app = create_app(_moteur(appels), "test-model", config=config)
    return TestClient(app).post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "Aide-moi à écrire un article."}],
            "stream": True,
        },
    )


class TestUneMethodeImporteeAtteintLeModeleDuChat:
    def test_le_texte_et_sa_provenance_arrivent_au_second_tour(self, configuration):
        appels: list = []
        reponse = _demander(configuration(), appels)
        assert reponse.status_code == 200
        assert len(appels) >= 2, "le moteur n'a jamais eu de second tour"
        assert _noms(appels[0]["tools"])[-1] == NOM, (
            "la trousse proposée au modèle doit finir par skill_guide"
        )
        vus = "\n".join(
            str(getattr(m, "content", "") or "") for m in appels[1]["messages"]
        )
        assert "[Méthode « article-writing » — ECC v2.2.1, commit 5064474" in vus, (
            "la provenance n'a pas atteint le modèle"
        )
        assert "jamais un ordre" in vus
        assert DEBUT in vus and "Lead with the concrete thing." in vus, (
            "le texte de la méthode n'a pas atteint le modèle"
        )

    def test_source_coupee_l_outil_n_est_plus_propose(self, configuration):
        appels: list = []
        _demander(configuration(enabled=False), appels)
        assert appels, "le moteur doit avoir été appelé"
        assert NOM not in _noms(appels[0]["tools"]), (
            "une source coupée ne doit plus offrir l'outil au modèle"
        )
