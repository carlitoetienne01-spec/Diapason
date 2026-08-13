"""Typed contracts shared by the lightning action pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionRisk(str, Enum):
    """Security impact of a deterministic action."""

    OBSERVE = "observe"
    LOCAL = "local"
    EXTERNAL_DRAFT = "external_draft"
    EXTERNAL_COMMIT = "external_commit"
    SYSTEM = "system"


@dataclass(slots=True, frozen=True)
class ActionPlan:
    """A high-confidence action parsed directly from the current user turn."""

    kind: str
    target: str = ""
    text: str = ""
    confidence: float = 0.0
    risk: ActionRisk = ActionRisk.LOCAL
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass(slots=True)
class ActionOutcome:
    """Result returned to chat, voice and telemetry consumers."""

    handled: bool
    success: bool = False
    message: str = ""
    action: str = ""
    target: str = ""
    risk: ActionRisk = ActionRisk.LOCAL
    verified: bool = False
    route_ms: float = 0.0
    execute_ms: float = 0.0
    total_ms: float = 0.0
    error_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_metadata(self) -> dict[str, Any]:
        """Privacy-safe diagnostics: never expose dictated text or file data."""
        return {
            "handled": self.handled,
            "success": self.success,
            "action": self.action,
            "risk": self.risk.value,
            "verified": self.verified,
            "route_ms": round(self.route_ms, 2),
            "execute_ms": round(self.execute_ms, 2),
            "total_ms": round(self.total_ms, 2),
            **({"error_type": self.error_type} if self.error_type else {}),
        }
