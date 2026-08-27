"""Chat tool confirmations, answered through the existing approval bell.

The tool executor calls a synchronous ``confirm_callback(prompt) -> bool``
whenever a tool declares ``requires_confirmation``. Until now the server
either hardcoded ``lambda _prompt: True`` (managed-agents chat) or passed
nothing at all (main chat agent), so confirmation-gated tools ran silently
or failed outright. This bridge gives that callback a real answer path:

- ``agent.tool_approval = "auto"`` — legacy opt-in that confirms immediately.
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
import re
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

TOOL_CONFIRMATION_ACTION = "tool_confirmation"
TOOL_CONFIRMATION_KEY = "chat.tool_confirmation"

# The bell polls every second while a request waits; two minutes gives a
# present user ample slack
# while an absent one fails closed instead of holding the turn forever.
DEFAULT_WAIT_S = 120.0
_POLL_INTERVAL_S = 1.0


def current_mode() -> str:
    """The configured approval mode, defensively normalized."""
    try:
        from diapason.core.config import load_config

        mode = (load_config().agent.tool_approval or "ask").strip().lower()
        return mode if mode in ("auto", "ask") else "ask"
    except Exception:  # noqa: BLE001 - config trouble must fail closed
        return "ask"


# Le prompt reçu est bâti par le ToolExecutor sous la forme
# « Allow execution of tool 'X' with args {...}? » (tools/_stubs.py). Le nom
# de l'outil est ce qui compte dans une notification ; les arguments, déjà
# caviardés en amont, ne tiennent pas dans une bannière.
_NOM_OUTIL_RE = re.compile(r"tool '([^']+)'")


def resumer_la_demande(prompt: str) -> str:
    """La demande en une ligne lisible, pour le centre de notifications."""
    propre = " ".join(str(prompt or "").split())
    trouve = _NOM_OUTIL_RE.search(propre)
    if trouve:
        return f"Diapason veut utiliser {trouve.group(1)}"
    return propre[:110] or "Diapason demande une autorisation"


def announce_approval(title: str, body: str) -> None:
    """Poser une demande dans les notifications sans bloquer l'appelant.

    EN TÂCHE DE FOND, et c'est le point : notifier_macos attend osascript
    jusqu'à dix secondes (livraison.py), soit près du quart du budget vocal
    de quarante-cinq. L'attente d'approbation ne doit pas financer sa propre
    annonce. Best-effort et silencieuse : une notification ratée ne fait pas
    tomber le tour d'outil qu'elle accompagne.
    """

    def _poser() -> None:
        try:
            from diapason.heartbeat.livraison import notifier_macos

            notifier_macos(title, body)
        except Exception:  # noqa: BLE001 - l'annonce est un bonus, jamais une porte
            logger.debug("annonce d'approbation impossible", exc_info=True)

    threading.Thread(target=_poser, daemon=True, name="annonce-approbation").start()


def _annoncer_la_demande(prompt: str, *, restant_s: int | None = None) -> None:
    """Pose la demande d'approbation dans le centre de notifications."""
    resume = resumer_la_demande(prompt)
    corps = (
        f"{resume} — réponds dans Diapason ({restant_s} s)"
        if restant_s is not None
        else f"{resume} — réponds dans Diapason."
    )
    announce_approval("Diapason demande ton accord", corps)


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
        # La cloche n'existe que dans la fenêtre de l'app : app fermée ou
        # regard ailleurs, la demande expirait en silence — deux l'avaient
        # déjà fait (Atlas, 24 août 2026). Une notification macOS porte la
        # demande là où elle se voit, et le fail-closed cesse d'être muet.
        _annoncer_la_demande(prompt)
        deadline = time.monotonic() + wait_s
        mi_chemin = time.monotonic() + wait_s / 2
        relance_faite = False
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
            # Une seule relance, à mi-délai : assez pour rattraper un regard
            # distrait, pas assez pour harceler.
            if not relance_faite and time.monotonic() >= mi_chemin:
                relance_faite = True
                restant = max(1, int(deadline - time.monotonic()))
                _annoncer_la_demande(prompt, restant_s=restant)
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
    "announce_approval",
    "current_mode",
    "tool_confirm_callback",
]
