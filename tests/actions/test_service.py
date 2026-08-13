from __future__ import annotations

from unittest.mock import MagicMock

from diapason.actions.models import ActionPlan, ActionRisk
from diapason.actions.service import LightningActionService
from diapason.core.config import DiapasonConfig
from diapason.desktop.app_writer import WriteResult


class StubRouter:
    def __init__(self, plan):
        self.plan = plan

    def route(self, text):
        return self.plan


def test_low_confidence_is_not_executed():
    plan = ActionPlan(kind="voice.focus_app", target="Notes", confidence=0.2)
    result = LightningActionService(DiapasonConfig(), router=StubRouter(plan)).handle(
        "x"
    )
    assert result.handled is False


def test_system_risk_is_never_executed():
    plan = ActionPlan(
        kind="system.admin",
        confidence=1.0,
        risk=ActionRisk.SYSTEM,
    )
    result = LightningActionService(DiapasonConfig(), router=StubRouter(plan)).handle(
        "x"
    )
    assert result.handled is False


def test_disabled_setting_stops_fast_path():
    cfg = DiapasonConfig()
    cfg.desktop.lightning.enabled = False
    plan = ActionPlan(kind="voice.focus_app", target="Notes", confidence=1.0)
    result = LightningActionService(cfg, router=StubRouter(plan)).handle("x")
    assert result.handled is False


def test_generated_content_is_written_without_enter(monkeypatch):
    plan = ActionPlan(
        kind="app.generate_and_type",
        target="Notes",
        text="un résumé professionnel",
        confidence=0.99,
    )
    write = MagicMock(
        return_value=WriteResult(
            success=True,
            method="accessibility",
            app="Notes",
            verified=True,
        )
    )
    monkeypatch.setattr("diapason.desktop.app_writer.write_text", write)
    generator = MagicMock(return_value="Voici le résumé généré.")

    result = LightningActionService(DiapasonConfig(), router=StubRouter(plan)).handle(
        "x", text_generator=generator
    )

    assert result.success is True
    assert result.action == "app.generate_and_type"
    generator.assert_called_once_with("un résumé professionnel")
    write.assert_called_once_with(
        "Voici le résumé généré.",
        app_name="Notes",
        timeout_s=2.0,
    )
