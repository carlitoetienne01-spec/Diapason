"""Carrying out a verified command on THIS device.

By the time anything here runs, the command has already survived every check
of spec §9. What remains is the narrowest possible action — and the
discipline of spec §34: a remote tool never touches storage directly, it
asks the same services the local UI asks. Otherwise the mesh becomes a second
source of truth, and the two drift.

Screens are opened by publishing an event the desktop shell listens to, not
by driving the window from here: the app already knows how to route
``success://…``, and duplicating that knowledge would guarantee the two
disagree eventually.
"""

from __future__ import annotations

import logging
from typing import Any

from diapason.mesh.commands import RemoteCommand

logger = logging.getLogger(__name__)

__all__ = ["local_executor", "pending_navigations", "push_navigation"]

# Routes waiting for the shell to pick up. Bounded: a UI that never collects
# them must not grow into a memory leak, and a stale route is worthless
# anyway — the user has moved on.
_MAX_PENDING = 16
_pending: list[dict[str, Any]] = []


def push_navigation(entry: dict[str, Any]) -> None:
    _pending.append(entry)
    del _pending[:-_MAX_PENDING]


def pending_navigations(*, drain: bool = True) -> list[dict[str, Any]]:
    """What the shell should open, oldest first."""
    items = list(_pending)
    if drain:
        _pending.clear()
    return items


def _navigate(command: RemoteCommand) -> dict[str, Any]:
    route = str(command.arguments.get("route") or "")
    push_navigation(
        {
            "route": route,
            "commandId": command.command_id,
            "originDeviceId": command.origin_device_id,
            "receivedAtMs": command.created_at_ms,
        }
    )
    return {"route": route, "userSafeMessage": f"Écran ouvert : {route}."}


def _show_resource(command: RemoteCommand) -> dict[str, Any]:
    kind = str(command.arguments.get("resourceType") or "")
    resource_id = str(command.arguments.get("resourceId") or "")
    # Universal routes (spec §25) are the app's stable vocabulary; the shell
    # translates them per platform.
    plural = {
        "task": "tasks",
        "project": "projects",
        "note": "notes",
        "habit": "habits",
    }
    route = f"success://{plural.get(kind, kind)}/{resource_id}"
    push_navigation(
        {
            "route": route,
            "commandId": command.command_id,
            "originDeviceId": command.origin_device_id,
            "resourceType": kind,
            "resourceId": resource_id,
            "receivedAtMs": command.created_at_ms,
        }
    )
    return {"route": route, "userSafeMessage": "L'élément est affiché."}


def _open(command: RemoteCommand) -> dict[str, Any]:
    push_navigation(
        {
            "route": "success://today",
            "commandId": command.command_id,
            "originDeviceId": command.origin_device_id,
            "focus": True,
            "receivedAtMs": command.created_at_ms,
        }
    )
    return {"userSafeMessage": "Succès est au premier plan."}


def _notify(command: RemoteCommand) -> dict[str, Any]:
    title = str(command.arguments.get("title") or "")
    body = str(command.arguments.get("body") or "")
    push_navigation(
        {
            "notification": {"title": title, "body": body},
            "commandId": command.command_id,
            "originDeviceId": command.origin_device_id,
            "receivedAtMs": command.created_at_ms,
        }
    )
    return {"userSafeMessage": "Notification affichée."}


# One handler per tool, resolved by exact name. No dynamic dispatch on a
# string the sender controls — that is how a narrow catalogue quietly
# becomes a universal one.
_HANDLERS = {
    "app.navigate": _navigate,
    "app.show_resource": _show_resource,
    "app.open": _open,
    "notifications.show": _notify,
}


def local_executor(command: RemoteCommand) -> dict[str, Any]:
    handler = _HANDLERS.get(command.tool)
    if handler is None:
        # Unreachable in practice — verify_command already rejects unknown
        # tools — but a missing handler must fail loudly, not silently
        # succeed, if the catalogue and this table ever drift apart.
        raise KeyError(f"Aucun exécuteur pour « {command.tool} ».")
    return handler(command)
