"""Tests for tool wiring in AgentExecutor."""

from __future__ import annotations

from diapason.agents.executor import AgentExecutor
from diapason.agents.manager import AgentManager
from diapason.core.events import EventBus
from tests.agents.fake_engine import FakeEngine
from tests.agents.scenario_harness import FakeSystem


def _register_agent():
    """Re-register MonitorOperativeAgent (cleared by autouse fixture)."""
    from diapason.agents.monitor_operative import MonitorOperativeAgent
    from diapason.core.registry import AgentRegistry

    if not AgentRegistry.contains("monitor_operative"):
        AgentRegistry.register("monitor_operative")(MonitorOperativeAgent)


def test_executor_runs_with_tools_from_config(tmp_path):
    """Executor should resolve tool names from config and complete tick."""
    _register_agent()

    engine = FakeEngine([{"content": "test response"}])
    system = FakeSystem(engine=engine)

    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_agent(
        "test",
        agent_type="monitor_operative",
        config={
            "system_prompt": "You are a test agent.",
            "tools": ["think"],
            "instruction": "test",
        },
    )
    mgr.send_message(agent["id"], "hello", mode="immediate")

    executor = AgentExecutor(manager=mgr, event_bus=EventBus())
    executor.set_system(system)

    executor.execute_tick(agent["id"])
    result_agent = mgr.get_agent(agent["id"])
    assert result_agent["status"] == "idle"
    assert result_agent["total_runs"] == 1
    mgr.close()


def test_executor_handles_missing_tools(tmp_path):
    """Executor should not crash if tool names don't exist in registry."""
    _register_agent()

    engine = FakeEngine([{"content": "test response"}])
    system = FakeSystem(engine=engine)

    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_agent(
        "test",
        agent_type="monitor_operative",
        config={
            "system_prompt": "You are a test agent.",
            "tools": ["nonexistent_tool_xyz"],
            "instruction": "test",
        },
    )
    mgr.send_message(agent["id"], "hello", mode="immediate")

    executor = AgentExecutor(manager=mgr, event_bus=EventBus())
    executor.set_system(system)

    executor.execute_tick(agent["id"])
    result_agent = mgr.get_agent(agent["id"])
    assert result_agent["status"] == "idle"
    assert result_agent["total_runs"] == 1
    mgr.close()


def test_executor_handles_string_tools(tmp_path):
    """Executor should handle comma-separated tool string as well as list."""
    _register_agent()

    engine = FakeEngine([{"content": "test response"}])
    system = FakeSystem(engine=engine)

    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_agent(
        "test",
        agent_type="monitor_operative",
        config={
            "system_prompt": "You are a test agent.",
            "tools": "think,calculator",
            "instruction": "test",
        },
    )
    mgr.send_message(agent["id"], "hello", mode="immediate")

    executor = AgentExecutor(manager=mgr, event_bus=EventBus())
    executor.set_system(system)

    executor.execute_tick(agent["id"])
    result_agent = mgr.get_agent(agent["id"])
    assert result_agent["status"] == "idle"
    mgr.close()


class TestLesAnciensNomsDOutils:
    """Étape 7 du plan de la phase 1b (25/09/2026) : les outils succes_*
    s'appellent vie_*, et agents.db garde les listes d'avant."""

    def test_un_agent_qui_cite_succes_tasks_garde_ses_quatre_outils(
        self, tmp_path, monkeypatch, caplog
    ):
        import logging

        from diapason.core.registry import ToolRegistry
        from diapason.tools.vie_continuity import VieContinuityTool
        from diapason.tools.vie_finances import VieFinancesTool
        from diapason.tools.vie_tasks import VieTasksTool
        from diapason.tools.vie_workspace import VieWorkspaceTool

        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path))
        _register_agent()
        for nom, classe in (
            ("vie_tasks", VieTasksTool),
            ("vie_workspace", VieWorkspaceTool),
            ("vie_continuity", VieContinuityTool),
            ("vie_finances", VieFinancesTool),
        ):
            ToolRegistry.register_value(nom, classe)

        mgr = AgentManager(db_path=str(tmp_path / "agents.db"))
        agent = mgr.create_agent(
            "ancien",
            agent_type="monitor_operative",
            config={
                "system_prompt": "Agent d'avant le renommage.",
                "tools": [
                    "succes_tasks",
                    "succes_workspace",
                    "succes_continuity",
                    "succes_finances",
                ],
                "instruction": "test",
            },
        )
        mgr.send_message(agent["id"], "bonjour", mode="immediate")
        executor = AgentExecutor(manager=mgr, event_bus=EventBus())
        executor.set_system(FakeSystem(engine=FakeEngine([{"content": "ok"}])))

        with caplog.at_level(logging.INFO, logger="diapason.agents.executor"):
            executor.execute_tick(agent["id"])
        mgr.close()

        resolus = [
            r.getMessage() for r in caplog.records if "resolved" in r.getMessage()
        ]
        assert any("resolved 4/4 tools" in m for m in resolus), (
            f"les quatre anciens noms doivent donner quatre outils : {resolus}"
        )

    def test_un_nom_inconnu_se_dit_au_lieu_de_disparaitre(
        self, tmp_path, monkeypatch, caplog
    ):
        import logging

        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path))
        _register_agent()
        mgr = AgentManager(db_path=str(tmp_path / "agents.db"))
        agent = mgr.create_agent(
            "fantome",
            agent_type="monitor_operative",
            config={
                "system_prompt": "x",
                "tools": ["outil_disparu_789"],
                "instruction": "test",
            },
        )
        mgr.send_message(agent["id"], "bonjour", mode="immediate")
        executor = AgentExecutor(manager=mgr, event_bus=EventBus())
        executor.set_system(FakeSystem(engine=FakeEngine([{"content": "ok"}])))
        with caplog.at_level(logging.WARNING, logger="diapason.core.noms_outils"):
            executor.execute_tick(agent["id"])
        mgr.close()
        assert any("outil_disparu_789" in r.getMessage() for r in caplog.records), (
            "un outil écarté d'un agent doit se dire au niveau WARNING"
        )
