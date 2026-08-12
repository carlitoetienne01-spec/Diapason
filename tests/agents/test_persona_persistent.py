"""Persona files reach persistent agents, not just one-shot `diapason ask` (#376).

SOUL.md / MEMORY.md / USER.md are loaded by `diapason ask` via SystemPromptBuilder.
Persistent agents (monitor_operative, operative) assemble their own system
prompt and previously ignored these files entirely. These tests verify the
persona is now appended to their prompt without replacing their specialized
instructions.
"""

from __future__ import annotations

from diapason.core.config import MemoryFilesConfig, SystemPromptConfig
from diapason.prompt.builder import SystemPromptBuilder


def _builder_with_soul(tmp_path, text="You are Kira."):
    soul = tmp_path / "SOUL.md"
    soul.write_text(text, encoding="utf-8")
    mf = MemoryFilesConfig(
        soul_path=str(soul),
        memory_path=str(tmp_path / "MEMORY.md"),  # absent → ignored
        user_path=str(tmp_path / "USER.md"),  # absent → ignored
    )
    return SystemPromptBuilder(
        agent_template="AGENT_TEMPLATE",
        memory_files_config=mf,
        system_prompt_config=SystemPromptConfig(),
    )


class TestPersonaSections:
    def test_persona_sections_excludes_template(self, tmp_path):
        builder = _builder_with_soul(tmp_path)
        persona = builder.persona_sections()
        assert "You are Kira." in persona
        assert "AGENT_TEMPLATE" not in persona  # template is NOT in persona

    def test_full_build_still_includes_template_and_persona(self, tmp_path):
        builder = _builder_with_soul(tmp_path)
        full = builder.build()
        assert "AGENT_TEMPLATE" in full
        assert "You are Kira." in full

    def test_persona_sections_empty_when_no_files(self, tmp_path):
        mf = MemoryFilesConfig(
            soul_path=str(tmp_path / "nope.md"),
            memory_path=str(tmp_path / "nope2.md"),
            user_path=str(tmp_path / "nope3.md"),
        )
        builder = SystemPromptBuilder(agent_template="T", memory_files_config=mf)
        assert builder.persona_sections() == ""


class TestApplyPersona:
    def test_appends_to_base_prompt(self, tmp_path):
        from diapason.agents.simple import SimpleAgent

        agent = SimpleAgent(object(), "m", prompt_builder=_builder_with_soul(tmp_path))
        out = agent._apply_persona("MONITOR INSTRUCTIONS")
        assert out.startswith("MONITOR INSTRUCTIONS")
        assert "You are Kira." in out

    def test_noop_without_builder(self):
        from diapason.agents.simple import SimpleAgent

        agent = SimpleAgent(object(), "m")
        assert agent._apply_persona("BASE") == "BASE"


class TestPersistentAgentsReceivePromptBuilder:
    """The __init__ chain must forward prompt_builder through to BaseAgent."""

    def test_monitor_operative_forwards_prompt_builder(self, tmp_path):
        from diapason.agents.monitor_operative import MonitorOperativeAgent

        builder = _builder_with_soul(tmp_path)
        agent = MonitorOperativeAgent(object(), "m", prompt_builder=builder)
        assert agent._prompt_builder is builder
        applied = agent._apply_persona("MONITOR INSTRUCTIONS")
        assert "MONITOR INSTRUCTIONS" in applied
        assert "You are Kira." in applied

    def test_operative_forwards_prompt_builder(self, tmp_path):
        from diapason.agents.operative import OperativeAgent

        builder = _builder_with_soul(tmp_path)
        agent = OperativeAgent(object(), "m", prompt_builder=builder)
        assert agent._prompt_builder is builder
        assert "You are Kira." in agent._apply_persona("OP INSTRUCTIONS")

    def test_monitor_operative_without_builder_is_unaffected(self):
        from diapason.agents.monitor_operative import MonitorOperativeAgent

        agent = MonitorOperativeAgent(object(), "m")
        assert agent._prompt_builder is None
        assert agent._apply_persona("BASE") == "BASE"


def _engine_answering(content="Bonjour Carlito."):
    from unittest.mock import MagicMock

    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


def _system_text(engine):
    (messages,), _ = (
        engine.generate.call_args.args,
        engine.generate.call_args.kwargs,
    )
    if not isinstance(messages, list):  # messages passed as kwarg
        messages = engine.generate.call_args.kwargs["messages"]
    return next(m.content for m in messages if m.role.value == "system")


class TestOrchestratorReceivesPersona:
    """serve's default chat agent is the orchestrator; it must know the persona.

    The trap this guards: the orchestrator composes its own tool-aware system
    prompt, and _build_messages used to prefer a wired builder over any
    explicit prompt — wiring persona in would have REPLACED the tool
    instructions. Both halves must survive side by side.
    """

    def test_tool_prompt_and_persona_coexist(self, tmp_path):
        from diapason.agents.orchestrator import OrchestratorAgent

        engine = _engine_answering()
        agent = OrchestratorAgent(
            engine,
            "m",
            system_prompt="TOOL INSTRUCTIONS",
            prompt_builder=_builder_with_soul(tmp_path),
        )
        agent.run("comment je m'appelle ?")
        system = _system_text(engine)
        assert "TOOL INSTRUCTIONS" in system, "the explicit prompt must survive"
        assert "You are Kira." in system, "the persona must be appended"
        assert system.index("TOOL INSTRUCTIONS") < system.index("You are Kira.")

    def test_structured_mode_keeps_tool_prompt_and_persona(self, tmp_path):
        # Structured mode is the one where tool instructions live IN the
        # prompt text — the builder replacing them would break tool calling.
        from diapason.agents.orchestrator import OrchestratorAgent

        engine = _engine_answering("FINAL_ANSWER: Bonjour.")
        agent = OrchestratorAgent(
            engine,
            "m",
            mode="structured",
            max_turns=1,
            system_prompt="TOOL INSTRUCTIONS",
            prompt_builder=_builder_with_soul(tmp_path),
        )
        agent.run("salut")
        system = _system_text(engine)
        assert "TOOL INSTRUCTIONS" in system
        assert "You are Kira." in system

    def test_default_tool_prompt_also_gains_persona(self, tmp_path):
        from diapason.agents.orchestrator import OrchestratorAgent

        engine = _engine_answering()
        agent = OrchestratorAgent(
            engine, "m", prompt_builder=_builder_with_soul(tmp_path)
        )
        agent.run("salut")
        assert "You are Kira." in _system_text(engine)

    def test_without_builder_nothing_changes(self):
        from diapason.agents.orchestrator import OrchestratorAgent

        engine = _engine_answering()
        agent = OrchestratorAgent(engine, "m", system_prompt="TOOL INSTRUCTIONS")
        agent.run("salut")
        assert _system_text(engine) == "TOOL INSTRUCTIONS"


class TestExplicitPromptBeatsBuilder:
    """_build_messages: a caller-composed prompt wins over the wired builder.

    Before the flip the builder branch won, which would have silently
    discarded any specialized agent's own instructions the moment a builder
    was wired in — the persona would replace the tools, not join them.
    """

    def test_explicit_wins(self, tmp_path):
        from diapason.agents.simple import SimpleAgent

        agent = SimpleAgent(object(), "m", prompt_builder=_builder_with_soul(tmp_path))
        messages = agent._build_messages("hi", None, system_prompt="EXPLICIT")
        system = next(m.content for m in messages if m.role.value == "system")
        assert system == "EXPLICIT"

    def test_builder_still_used_when_no_explicit_prompt(self, tmp_path):
        from diapason.agents.simple import SimpleAgent

        agent = SimpleAgent(object(), "m", prompt_builder=_builder_with_soul(tmp_path))
        messages = agent._build_messages("hi", None)
        system = next(m.content for m in messages if m.role.value == "system")
        assert "AGENT_TEMPLATE" in system
        assert "You are Kira." in system
