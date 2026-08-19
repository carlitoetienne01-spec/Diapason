"""Policy and execution service for deterministic lightning actions."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from diapason.actions.metrics import METRICS
from diapason.actions.models import ActionOutcome, ActionPlan, ActionRisk
from diapason.actions.router import FastActionRouter

logger = logging.getLogger(__name__)

_SENSITIVE_FRONTMOST = {
    "terminal",
    "iterm",
    "iterm2",
    "powershell",
    "command prompt",
    "invite de commandes",
    "system settings",
    "réglages système",
}


class LightningActionService:
    """Parse, authorize, execute and measure a single explicit user command."""

    def __init__(
        self,
        config: Any = None,
        *,
        router: FastActionRouter | None = None,
    ) -> None:
        self._config = config
        self._router = router or FastActionRouter()
        try:
            from diapason.desktop.app_index import APP_INDEX

            APP_INDEX.ttl_s = max(1.0, float(self._get("app_cache_ttl_s", 300.0)))
        except (ImportError, TypeError, ValueError):
            pass

    @property
    def settings(self) -> Any:
        desktop = getattr(self._config, "desktop", None)
        return getattr(desktop, "lightning", None)

    def _get(self, name: str, default: Any) -> Any:
        settings = self.settings
        return getattr(settings, name, default) if settings is not None else default

    def _allowed(self, plan: ActionPlan) -> bool:
        if not bool(self._get("enabled", True)):
            return False
        if plan.confidence < float(self._get("min_confidence", 0.90)):
            return False
        if plan.risk in {ActionRisk.EXTERNAL_COMMIT, ActionRisk.SYSTEM}:
            return False
        if plan.risk == ActionRisk.EXTERNAL_DRAFT and not bool(
            self._get("allow_external_drafts", True)
        ):
            return False
        if plan.kind in {
            "app.type_text",
            "app.generate_and_type",
            "frontmost.type_text",
        } and not bool(self._get("allow_type", True)):
            return False
        if plan.kind.startswith("voice.") and not bool(self._get("allow_open", True)):
            return False
        return True

    def handle(
        self,
        text: str,
        *,
        text_generator: Callable[[str], str] | None = None,
    ) -> ActionOutcome:
        started = time.perf_counter()
        route_started = started
        plan = self._router.route(text)
        route_ms = (time.perf_counter() - route_started) * 1000
        if plan is None or not self._allowed(plan):
            return ActionOutcome(handled=False, route_ms=route_ms)

        execute_started = time.perf_counter()
        try:
            outcome = self._execute(plan, text_generator=text_generator)
        except Exception as exc:  # noqa: BLE001 - action failure must be a clean reply
            logger.exception("Lightning action %s failed", plan.kind)
            outcome = ActionOutcome(
                handled=True,
                success=False,
                message=f"L’action locale a échoué ({type(exc).__name__}).",
                action=plan.kind,
                target=plan.target,
                risk=plan.risk,
                error_type=type(exc).__name__,
            )
        outcome.route_ms = route_ms
        outcome.execute_ms = (time.perf_counter() - execute_started) * 1000
        outcome.total_ms = (time.perf_counter() - started) * 1000
        METRICS.record(outcome)
        return outcome

    def _execute(
        self,
        plan: ActionPlan,
        *,
        text_generator: Callable[[str], str] | None = None,
    ) -> ActionOutcome:
        if plan.kind in {
            "app.type_text",
            "app.generate_and_type",
            "frontmost.type_text",
        }:
            app_name = plan.target
            if not app_name:
                from diapason.desktop.frontmost import frontmost_app_name

                app_name = frontmost_app_name() or ""
                if app_name.casefold() in _SENSITIVE_FRONTMOST:
                    return ActionOutcome(handled=False)
            from diapason.desktop.app_writer import write_text

            text_to_write = plan.text
            if plan.kind == "app.generate_and_type":
                if text_generator is None:
                    return ActionOutcome(handled=False)
                text_to_write = (text_generator(plan.text) or "").strip()
                if not text_to_write:
                    return ActionOutcome(
                        handled=True,
                        success=False,
                        message="Le modèle n’a produit aucun texte à insérer.",
                        action=plan.kind,
                        target=plan.target,
                        risk=plan.risk,
                        error_type="EmptyGeneration",
                    )
            focus_timeout = (
                float(self._get("focus_timeout_s", 2.0))
                if bool(self._get("verify_actions", True))
                else 0.0
            )
            result = write_text(
                text_to_write,
                app_name=plan.target,
                timeout_s=focus_timeout,
            )
            target_label = result.app or app_name or "l’application active"
            message = (
                (
                    f"⚡ Contenu créé et écrit dans {target_label}."
                    if plan.kind == "app.generate_and_type"
                    else f"⚡ Texte écrit dans {target_label}."
                )
                if result.success
                else f"Impossible d’écrire dans {target_label} : {result.detail}"
            )
            return ActionOutcome(
                handled=True,
                success=result.success,
                message=message,
                action=plan.kind,
                target=target_label,
                risk=plan.risk,
                verified=result.verified,
                metadata={"method": result.method},
            )

        if plan.kind.startswith("voice."):
            from diapason.desktop.voice_commands import (
                VoiceAction,
                execute_voice_action,
            )

            voice_kind = plan.kind.removeprefix("voice.")
            result = execute_voice_action(
                VoiceAction(
                    kind=voice_kind,
                    target=plan.target,
                    extra=dict(plan.arguments),
                )
            )
            success = bool(result.get("success"))
            detail = str(result.get("detail") or "")
            verified = False
            if (
                success
                and voice_kind == "focus_app"
                and bool(self._get("verify_actions", True))
            ):
                from diapason.desktop.frontmost import wait_until_frontmost

                verified = wait_until_frontmost(
                    plan.target,
                    timeout_s=float(self._get("focus_timeout_s", 2.0)),
                )
            return ActionOutcome(
                handled=True,
                success=success,
                message=(
                    f"⚡ {detail}" if success else f"Action impossible : {detail}"
                ),
                action=plan.kind,
                target=plan.target,
                risk=plan.risk,
                verified=verified,
            )

        return ActionOutcome(handled=False)

    def capabilities(self) -> dict[str, Any]:
        import sys

        runtime: dict[str, Any] = {"platform": sys.platform}
        if sys.platform == "darwin":
            # Le test RÉEL, pas le drapeau : AXIsProcessTrusted peut
            # répondre True pendant que chaque appel rend -25204. Afficher
            # « accordé » dans ce cas envoie chercher le défaut partout
            # sauf là où il est.
            from diapason.desktop.accessibility import accessibility_works

            runtime["accessibility_granted"] = accessibility_works()
            runtime["clipboard_preserving_fallback"] = True
        return {
            "enabled": bool(self._get("enabled", True)),
            "mode": "deterministic-before-llm",
            "remote_allowed": bool(self._get("allow_remote", False)),
            "actions": [
                "open application",
                "open URL",
                "web/media search",
                "compose draft (never send)",
                "type into a requested or frontmost app",
                "generate content and type it into a requested app",
            ],
            "automatic_risk_levels": [
                ActionRisk.OBSERVE.value,
                ActionRisk.LOCAL.value,
                ActionRisk.EXTERNAL_DRAFT.value,
            ],
            "always_confirmed": [
                "send",
                "delete",
                "purchase/payment",
                "install/admin/system changes",
            ],
            "runtime": runtime,
        }


__all__ = ["LightningActionService"]
