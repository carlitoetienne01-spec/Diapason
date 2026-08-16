"""Sending a command, and telling the truth about what happened.

This is the layer the assistant talks to. It brings together the registry
(who), presence (is it there), the tool catalogue (is this allowed), the
queue (durability) and the transport (how) — and it is deliberately the only
place that decides what the user is told.

The rule it exists to keep is spec §57, restated as code: a command that was
merely queued must never be reported as done. Each terminal status carries a
French sentence that is true of that status and no other.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from diapason.mesh.commands import (
    CommandRejected,
    RemoteCommand,
    build_command,
    sign_command,
)
from diapason.mesh.presence import is_reachable, presence_of
from diapason.mesh.queue import CommandQueue
from diapason.mesh.registry import DeviceRegistry
from diapason.mesh.tools import get_remote_tool
from diapason.mesh.transport import TransportError, deliver

logger = logging.getLogger(__name__)

__all__ = ["dispatch_command", "DispatchResult"]

DispatchResult = dict[str, Any]


def dispatch_command(
    *,
    target_device_id: str,
    tool: str,
    arguments: Mapping[str, Any] | None = None,
    registry: DeviceRegistry | None = None,
    queue: CommandQueue | None = None,
    idempotency_key: str = "",
    transport=None,
) -> DispatchResult:
    """Send *tool* to *target_device_id*, or explain precisely why not."""
    from diapason.mesh.identity import device_identity, owner_id

    registry = registry or DeviceRegistry()
    queue = queue or CommandQueue()
    send = transport or deliver

    # 1. The tool must exist. An assistant asking for something outside the
    #    catalogue gets nothing — there is no fallback path (spec §21).
    spec = get_remote_tool(tool)
    if spec is None:
        return _refused(
            "UNSUPPORTED",
            f"L'outil « {tool} » n'existe pas.",
            tool=tool,
            target=target_device_id,
        )

    # 2. The target must be a device we know and still trust.
    device = registry.find(target_device_id)
    if device is None:
        return _refused(
            "DENIED",
            "Cet appareil n'est pas appairé.",
            tool=tool,
            target=target_device_id,
        )
    if device.get("trustLevel") != "TRUSTED":
        return _refused(
            "DENIED",
            f"L'appareil « {device.get('name')} » n'est plus autorisé.",
            tool=tool,
            target=target_device_id,
        )

    # 3. Capabilities are checked BEFORE sending, so an impossible request
    #    fails here with an explanation instead of on the far side with a
    #    shrug (spec §6).
    granted = set(device.get("capabilities") or [])
    if spec.capability not in granted:
        return _refused(
            "UNSUPPORTED",
            f"« {device.get('name')} » ne peut pas faire cela.",
            tool=tool,
            target=target_device_id,
        )

    # 4. Build, validate locally, sign. Validating before signing means a
    #    malformed command never travels at all.
    identity = device_identity()
    command = build_command(
        owner_id=owner_id(),
        origin_device_id=identity.device_id,
        target_device_id=target_device_id,
        tool=tool,
        arguments=arguments or {},
        requires_confirmation=spec.requires_confirmation,
        idempotency_key=idempotency_key,
    )
    try:
        spec.validate(command.arguments)
    except CommandRejected as exc:
        return _refused(exc.code, exc.message, tool=tool, target=target_device_id)

    # 5. Idempotency: the same intent, already sent, returns what we know
    #    rather than doing it twice (spec §45).
    if idempotency_key:
        known = queue.find_by_idempotency(idempotency_key)
        if known is not None and known["status"] not in {"PENDING", "QUEUED"}:
            return known

    signed = sign_command(command)
    # 6. Recorded BEFORE the wire (transactional outbox, spec §16): a command
    #    that left without a row behind it is one nobody can report on.
    queue.enqueue(signed)

    # 7. Reachability decides the policy, and the policy decides the wording.
    if not is_reachable(device):
        presence = presence_of(device)
        return _apply_offline_policy(queue, signed, device, spec, presence)

    # 8. Deliver.
    queue.record_attempt(signed.command_id)
    try:
        response = send(signed, device)
    except TransportError as exc:
        return _apply_offline_policy(
            queue, signed, device, spec, presence_of(device), reason=str(exc)
        )
    except Exception as exc:  # noqa: BLE001 - never let a transport bug lie
        logger.exception("mesh dispatch failed")
        return queue.mark(
            signed.command_id,
            "FAILED",
            user_message="L'envoi de la commande a échoué.",
            error_code=type(exc).__name__,
        )

    status = str(response.get("status") or "FAILED").upper()
    return queue.mark(
        signed.command_id,
        status,
        user_message=str(response.get("userSafeMessage") or ""),
        result=response.get("result"),
        error_code=str(response.get("errorCode") or ""),
    )


def _apply_offline_policy(
    queue: CommandQueue,
    command: RemoteCommand,
    device: Mapping[str, Any],
    spec,
    presence: Mapping[str, Any],
    *,
    reason: str = "",
) -> DispatchResult:
    """What an unreachable device means, per tool (spec §44).

    Never "it worked". The wording distinguishes "will happen later" from
    "will not happen", because a user who is told the wrong one acts on it —
    and it distinguishes "asleep" from "awake but unreachable", because those
    two call for different things from the user: waiting, versus checking the
    network.
    """
    name = device.get("name") or "cet appareil"
    state = presence.get("state", "OFFLINE")

    if reason:
        # Presence said reachable and the wire disagreed. Saying "hors ligne"
        # here would send the user to look at a device that is in fact on.
        absence = "n'a pas pu être joint"
    elif state == "BACKGROUND":
        absence = "est en arrière-plan"
    else:
        absence = "est hors ligne"

    if spec.offline_policy == "REQUIRE_ONLINE":
        return queue.mark(
            command.command_id,
            "OFFLINE",
            user_message=(
                f"{name} {absence} : cette action demande un appareil actif, "
                "elle n'a pas été effectuée."
            ),
            error_code=_error_code(reason),
        )
    if spec.offline_policy == "DROP_IF_OFFLINE":
        return queue.mark(
            command.command_id,
            "EXPIRED",
            user_message=f"{name} {absence} : la commande a été abandonnée.",
            error_code=_error_code(reason),
        )
    # QUEUE_UNTIL_EXPIRATION — the only case where waiting is useful.
    return queue.mark(
        command.command_id,
        "QUEUED",
        user_message=(
            f"{name} {absence} : la commande est en attente et partira dès son retour."
        ),
        error_code=_error_code(reason),
    )


def _error_code(reason: str) -> str:
    return "TRANSPORT_FAILED" if reason else "TARGET_OFFLINE"


def _refused(code: str, message: str, *, tool: str, target: str) -> DispatchResult:
    """A refusal that never reached the queue — nothing to record, nothing done."""
    return {
        "commandId": None,
        "targetDeviceId": target,
        "tool": tool,
        "status": code,
        "result": None,
        "errorCode": code,
        "userSafeMessage": message,
        "attempts": 0,
    }


def receive_command(
    raw: Mapping[str, Any],
    *,
    registry: DeviceRegistry | None = None,
    queue: CommandQueue | None = None,
    nonces=None,
    executor=None,
) -> DispatchResult:
    """Verify an inbound command and run it. The far end of the wire."""
    from diapason.mesh.commands import NonceStore, verify_command
    from diapason.mesh.identity import device_identity, owner_id

    registry = registry or DeviceRegistry()
    queue = queue or CommandQueue()
    nonces = nonces or NonceStore()
    identity = device_identity()

    try:
        command = verify_command(
            raw,
            registry=registry,
            local_device_id=identity.device_id,
            local_owner_id=owner_id(),
            nonces=nonces,
        )
    except CommandRejected as exc:
        return {
            "commandId": str(raw.get("commandId") or ""),
            "targetDeviceId": identity.device_id,
            "status": exc.code,
            "errorCode": exc.code,
            "userSafeMessage": exc.message,
        }

    # Idempotency on the receiving side too: a redelivered command replays
    # its recorded result rather than acting twice (spec §17).
    known = queue.find_by_idempotency(command.idempotency_key)
    if known is not None and known["status"] not in {"PENDING", "QUEUED"}:
        return known

    queue.enqueue(command, status="RUNNING")
    if executor is None:
        return queue.mark(
            command.command_id,
            "UNSUPPORTED",
            user_message="Cet appareil ne sait pas encore exécuter cette commande.",
            error_code="NO_EXECUTOR",
        )
    try:
        result = executor(command)
    except Exception as exc:  # noqa: BLE001
        logger.exception("mesh command execution failed")
        return queue.mark(
            command.command_id,
            "FAILED",
            user_message="L'exécution de la commande a échoué sur cet appareil.",
            error_code=type(exc).__name__,
        )
    return queue.mark(
        command.command_id,
        "SUCCESS",
        user_message=str((result or {}).get("userSafeMessage") or "C'est fait."),
        result=result,
    )
