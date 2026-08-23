"""Le chat en flux du bureau atteint-il enfin les outils ?

C'est le test qui compte : ``/v1/chat/completions`` avec ``stream: true`` et
SANS ``tools`` — la requête exacte que compose ``frontend/src/lib/sse.ts``.
Avant le 22 août 2026, ce cas partait vers le moteur nu ; l'agent, et les
98 outils enregistrés avec lui, n'étaient jamais consultés. Ce test échoue
contre ce code-là : aucun événement ``tool_call_start`` n'y était émis.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from diapason.core.registry import ToolRegistry  # noqa: E402
from diapason.engine._stubs import StreamChunk  # noqa: E402
from diapason.server.app import create_app  # noqa: E402
from diapason.tools.calculator import CalculatorTool  # noqa: E402


@pytest.fixture(autouse=True)
def _reinscrire_les_outils():
    """Le conftest racine vide ToolRegistry avant chaque test.

    ``import diapason.tools`` ne le repeuple pas : Python garde le module en
    cache, donc les décorateurs d'enregistrement ne rejouent pas. En production
    le registre est peuplé une fois au démarrage et jamais vidé ; ici il faut
    le refaire à la main, sinon la trousse est vide et le chemin outillé n'est
    jamais pris — ce qui masquerait précisément ce qu'on veut prouver.
    """
    ToolRegistry.register_value("calculator", CalculatorTool)


def _config_avec_outils(outils: str):
    from diapason.core.config import DiapasonConfig

    cfg = DiapasonConfig()
    cfg.analytics.enabled = False
    cfg.traces.enabled = False
    cfg.agent.tools = outils
    # L'approbation automatique évite que la cloche bloque le test ; la
    # trousse ci-dessous ne contient de toute façon aucun outil sensible.
    cfg.agent.tool_approval = "auto"
    return cfg


def _moteur_qui_reclame(nom_outil: str, arguments: str):
    """Premier tour : un appel d'outil. Second : la réponse en clair."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    tours = {"n": 0}

    async def stream_full(messages, **kwargs):
        tours["n"] += 1
        if tours["n"] == 1:
            yield StreamChunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "c0",
                        "type": "function",
                        "function": {"name": nom_outil, "arguments": arguments},
                    }
                ]
            )
        else:
            yield StreamChunk(content="Cela fait 4.")

    async def stream(messages, **kwargs):
        # Le chemin SANS outils : s'il est emprunté, la réponse le dira.
        yield "aucun outil"

    engine.stream_full = stream_full
    engine.stream = stream
    return engine


def _evenements(corps: str) -> list[tuple[str, dict]]:
    """Découpe le flux SSE en (nom d'événement, données)."""
    sorties: list[tuple[str, dict]] = []
    nom = None
    for ligne in corps.splitlines():
        if ligne.startswith("event: "):
            nom = ligne[7:].strip()
        elif ligne.startswith("data: "):
            charge = ligne[6:]
            if charge == "[DONE]":
                continue
            try:
                sorties.append((nom or "chunk", json.loads(charge)))
            except json.JSONDecodeError:
                pass
            nom = None
    return sorties


def _texte(evts) -> str:
    morceaux = []
    for nom, donnees in evts:
        if nom != "chunk":
            continue
        for choix in donnees.get("choices") or []:
            morceaux.append((choix.get("delta") or {}).get("content") or "")
    return "".join(morceaux)


def test_le_chat_en_flux_execute_un_outil_sans_que_le_client_en_passe():
    engine = _moteur_qui_reclame("calculator", '{"expression": "2+2"}')
    app = create_app(engine, "test-model", config=_config_avec_outils("calculator"))
    client = TestClient(app)

    reponse = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "Combien font 2+2 ?"}],
            "stream": True,
        },
    )
    assert reponse.status_code == 200
    evts = _evenements(reponse.text)
    noms = [n for n, _ in evts]

    assert "tool_call_start" in noms, (
        "le chat du bureau n'a atteint aucun outil — c'est le défaut d'origine"
    )
    assert "tool_call_end" in noms

    debut = next(d for n, d in evts if n == "tool_call_start")
    assert debut["tool"] == "calculator"
    fin = next(d for n, d in evts if n == "tool_call_end")
    assert fin["success"] is True
    assert "4" in str(fin["result"])

    # …et la réponse finale est bien passée par le second tour.
    assert "Cela fait 4." in _texte(evts)


def test_un_outil_absent_de_la_trousse_ne_prive_pas_des_autres():
    engine = _moteur_qui_reclame("calculator", '{"expression": "2+2"}')
    app = create_app(
        engine,
        "test-model",
        config=_config_avec_outils("outil_qui_nexiste_pas,calculator"),
    )
    client = TestClient(app)
    reponse = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "2+2 ?"}],
            "stream": True,
        },
    )
    assert reponse.status_code == 200
    assert "tool_call_start" in [n for n, _ in _evenements(reponse.text)]


def test_la_trousse_est_resolue_une_seule_fois():
    """Résoudre la trousse importe tout diapason.tools : pas à chaque message."""
    engine = _moteur_qui_reclame("calculator", '{"expression": "2+2"}')
    app = create_app(engine, "test-model", config=_config_avec_outils("calculator"))
    client = TestClient(app)
    for _ in range(3):
        client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "2+2 ?"}],
                "stream": True,
            },
        )
    assert getattr(app.state, "_chat_tooling_cache", "absent") != "absent"


def test_quand_le_modele_n_appelle_rien_le_flux_reste_un_flux():
    """La trousse ne doit pas dégrader le cas nu : jetons du moteur, tels quels."""
    engine = _moteur_qui_reclame("calculator", "{}")

    async def stream_full(messages, **kwargs):
        for morceau in ("Deux", " et", " deux"):
            yield StreamChunk(content=morceau)

    engine.stream_full = stream_full
    app = create_app(engine, "test-model", config=_config_avec_outils("calculator"))
    client = TestClient(app)
    reponse = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "Combien font 2+2 ?"}],
            "stream": True,
        },
    )
    evts = _evenements(reponse.text)
    assert "tool_call_start" not in [n for n, _ in evts]
    # Trois morceaux distincts : le flux n'a pas été recollé puis redécoupé.
    morceaux = [
        (c.get("delta") or {}).get("content")
        for n, d in evts
        if n == "chunk"
        for c in (d.get("choices") or [])
    ]
    assert [m for m in morceaux if m] == ["Deux", " et", " deux"]


def test_un_bonjour_ne_paie_pas_les_schemas_d_outils():
    """Trois mille jetons de schémas sur « bonjour », c'est du temps pur perdu.

    Le chemin vocal avait déjà mesuré ce coût (core/tool_turn.py) ; le chat en
    hérite. On vérifie que le tour part par le chemin NU, sans trousse.
    """
    engine = _moteur_qui_reclame("calculator", "{}")
    vus: list[bool] = []

    async def stream_full(messages, **kwargs):
        vus.append("tools" in kwargs)
        yield StreamChunk(content="ne devrait pas servir")

    async def stream(messages, **kwargs):
        vus.append(False)
        yield "Bonjour Carlito."

    engine.stream_full = stream_full
    engine.stream = stream
    app = create_app(engine, "test-model", config=_config_avec_outils("calculator"))
    client = TestClient(app)
    reponse = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "Bonjour"}],
            "stream": True,
        },
    )
    assert _texte(_evenements(reponse.text)) == "Bonjour Carlito."
    assert vus == [False], "un salut ne doit pas payer la trousse"
