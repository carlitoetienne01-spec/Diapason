"""Deterministic, low-latency desktop actions.

The action layer intentionally sits in front of the LLM.  It handles only
explicit, high-confidence and reversible user requests; everything ambiguous
or risky continues through the normal agent and approval pipeline.
"""

from diapason.actions.models import ActionOutcome, ActionPlan, ActionRisk
from diapason.actions.service import LightningActionService

__all__ = ["ActionOutcome", "ActionPlan", "ActionRisk", "LightningActionService"]
