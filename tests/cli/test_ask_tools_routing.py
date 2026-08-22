"""`--tools` doit atteindre un agent qui exécute des outils.

L'agent par défaut est « simple », dont la docstring dit : « No tool
calling ». `ask.py` ne branchait les outils que si l'agent les acceptait —
sinon il les construisait puis les jetait, en silence. Le chemin le plus
naturel du monde, `diapason ask --tools calculator "combien font…"`,
laissait donc le modèle inventer un nombre de tête. Mesuré : 48273 × 91847
rendait 4433560431 (faux), zéro appel d'outil dans les traces, jamais.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from diapason.cli import cli

# `diapason.cli.ask` résout vers la COMMANDE Click (ré-exportée par le
# paquet), pas vers le module. importlib contourne l'ombrage.
_ask_mod = importlib.import_module("diapason.cli.ask")


def _mock_engine():
    engine = MagicMock()
    engine.generate.return_value = {"content": "ok", "usage": {}}
    engine.chat.return_value = {"content": "ok", "usage": {}}
    return engine


@dataclass
class _EngineSetup:
    engine: MagicMock
    config: object


@pytest.fixture
def agent_setup():
    """Autonome : la fixture homonyme de test_ask_agent.py n'est pas dans un
    conftest, donc pas partageable sans copier."""
    from diapason.core.config import DiapasonConfig

    engine = _mock_engine()
    config = DiapasonConfig()
    config.intelligence.default_model = "test-model"
    config.agent.max_turns = 2

    # Le conftest de la suite VIDE les registres entre les tests, et les
    # décorateurs @register ne rejouent pas à la réimportation. Sans ceci,
    # « Unknown agent » part avant même le routage — le test échouerait pour
    # une raison qui n'a rien à voir avec ce qu'il teste.
    from diapason.agents.native_react import NativeReActAgent
    from diapason.agents.simple import SimpleAgent
    from diapason.core.registry import AgentRegistry, ToolRegistry
    from diapason.tools.calculator import CalculatorTool

    AgentRegistry.register_value("simple", SimpleAgent)
    AgentRegistry.register_value("native_react", NativeReActAgent)
    ToolRegistry.register_value("calculator", CalculatorTool)

    with (
        patch.object(_ask_mod, "load_config", return_value=config),
        patch.object(_ask_mod, "get_engine", return_value=("mock", engine)),
        patch.object(_ask_mod, "discover_engines", return_value=[("mock", engine)]),
        patch.object(
            _ask_mod, "discover_models", return_value={"mock": ["test-model"]}
        ),
        patch.object(_ask_mod, "register_builtin_models"),
        patch.object(_ask_mod, "merge_discovered_models"),
    ):
        yield _EngineSetup(engine=engine, config=config)


@pytest.fixture
def runner():
    return CliRunner()


def _route(runner, setup, args):
    result = runner.invoke(cli, ["ask", *args, "test question"])
    return result


class TestLeRoutageAutomatique:
    def test_tools_sans_agent_route_vers_native_react(
        self, runner, agent_setup, monkeypatch
    ):
        """Sans --agent explicite, --tools doit choisir un agent capable —
        et le dire, pas le faire en douce."""
        agent_setup.config.agent.default_agent = "simple"
        vu = {}

        from diapason.core.registry import AgentRegistry

        vraie = AgentRegistry.get

        def espion(name):
            vu["agent"] = name
            return vraie(name)

        monkeypatch.setattr(AgentRegistry, "get", espion)
        result = _route(runner, agent_setup, ["--tools", "calculator"])
        assert vu.get("agent") == "native_react", result.output
        assert "native_react" in result.output, "le routage doit être annoncé"

    def test_un_agent_explicite_sans_outils_est_respecte_avec_avertissement(
        self, runner, agent_setup
    ):
        """--agent simple --tools X : la personne a choisi ; on prévient au
        lieu d'écraser son choix, mais on ne se tait plus."""
        result = _route(
            runner, agent_setup, ["--agent", "simple", "--tools", "calculator"]
        )
        assert "n'appelle pas d'outils" in result.output, result.output

    def test_un_agent_capable_ne_declenche_rien(self, runner, agent_setup):
        """--agent native_react --tools X marchait déjà : aucun message."""
        result = _route(
            runner, agent_setup, ["--agent", "native_react", "--tools", "calculator"]
        )
        assert "routé vers" not in result.output
        assert "n'appelle pas d'outils" not in result.output

    def test_sans_tools_rien_ne_change(self, runner, agent_setup, monkeypatch):
        """`diapason ask "question"` sans --tools garde l'agent par défaut."""
        agent_setup.config.agent.default_agent = "simple"
        vu = {}

        from diapason.core.registry import AgentRegistry

        vraie = AgentRegistry.get

        def espion(name):
            vu["agent"] = name
            return vraie(name)

        monkeypatch.setattr(AgentRegistry, "get", espion)
        _route(runner, agent_setup, [])
        assert vu.get("agent") == "simple"
