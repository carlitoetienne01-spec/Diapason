"""Chat tool confirmations, answered through the existing approval bell.

The tool executor calls a synchronous ``confirm_callback(prompt) -> bool``
whenever a tool declares ``requires_confirmation``. Until now the server
either hardcoded ``lambda _prompt: True`` (managed-agents chat) or passed
nothing at all (main chat agent), so confirmation-gated tools ran silently
or failed outright. This bridge gives that callback a real answer path:

- ``agent.tool_approval = "auto"`` (default) — confirm immediately, which
  is exactly the behavior the chat had before this setting existed.
- ``agent.tool_approval = "ask"`` — queue the confirmation into the
  ApprovalStore that already feeds the frontend bell (GET
  /v1/approvals/pending + approve/deny), then wait for the user's
  decision. Timeout or denial refuses the tool.

The callback runs in the tool executor's worker thread, so blocking here
never blocks the event loop; the store is opened per call because sqlite
connections do not travel across threads.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)

TOOL_CONFIRMATION_ACTION = "tool_confirmation"
TOOL_CONFIRMATION_KEY = "chat.tool_confirmation"

# The bell polls every 10 s; two minutes gives a present user ample slack
# while an absent one fails closed instead of holding the turn forever.
DEFAULT_WAIT_S = 120.0
_POLL_INTERVAL_S = 1.0


def current_mode() -> str:
    """The configured approval mode, defensively normalized."""
    try:
        from diapason.core.config import load_config

        mode = (load_config().agent.tool_approval or "auto").strip().lower()
        return mode if mode in ("auto", "ask") else "auto"
    except Exception:  # noqa: BLE001 - config trouble must not kill the chat
        return "auto"


def _await_decision(prompt: str, wait_s: float) -> bool:
    from diapason.tools.approval_store import (
        STATUS_APPROVED,
        STATUS_DENIED,
        STATUS_EXECUTED,
        STATUS_EXPIRED,
        TIER_HIGH,
        ApprovalStore,
    )

    store = ApprovalStore()
    try:
        action = store.queue_action(
            action_type=TOOL_CONFIRMATION_ACTION,
            description=prompt,
            payload={"prompt": prompt},
            permission_key=TOOL_CONFIRMATION_KEY,
            # Confirmation-gated tools (shell, git push, send…) are the
            # risky ones by definition — surface them at the top of the bell.
            tier=TIER_HIGH,
            ttl_hours=1,
        )
        logger.info("tool confirmation %s queued for approval", action.id)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            current = store.get_action(action.id)
            if current is None:
                return False
            if current.status == STATUS_APPROVED:
                # Consume: without this the row sits in list_approved()
                # forever and execute_pending_actions chokes on an
                # action_type it has no executor for.
                store.update_status(action.id, STATUS_EXECUTED)
                return True
            if current.status in (STATUS_DENIED, STATUS_EXPIRED):
                return False
            time.sleep(_POLL_INTERVAL_S)
        # Fail closed, leave a trace: an unanswered dangerous action is a no.
        store.update_status(action.id, STATUS_EXPIRED)
        logger.info("tool confirmation %s timed out — denied", action.id)
        return False
    finally:
        store.close()


def tool_confirm_callback(wait_s: float = DEFAULT_WAIT_S) -> Callable[[str], bool]:
    """Build the confirm callback for chat agents.

    The mode is read at CALL time, not build time: flipping the composer
    chip applies to the very next tool, no server restart involved.
    """

    def confirm(prompt: str) -> bool:
        if current_mode() == "auto":
            return True
        try:
            return _await_decision(str(prompt or "Tool call"), wait_s)
        except Exception:  # noqa: BLE001 - a broken store must fail closed
            logger.exception("tool confirmation bridge failed")
            return False

    return confirm


__all__ = [
    "DEFAULT_WAIT_S",
    "TOOL_CONFIRMATION_ACTION",
    "TOOL_CONFIRMATION_KEY",
    "current_mode",
    "tool_confirm_callback",
]
