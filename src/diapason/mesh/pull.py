"""Reaching a device that cannot be dialled.

Everything until now assumed a command travels by knocking on the target's
door. That holds between two computers on one network and fails for exactly
the devices this mesh exists to include: a phone has no stable address, sits
behind a carrier NAT, and is put to sleep by the operating system whenever
the user looks away. Succès Flutter is where the mesh meets those devices.

So the direction flips. A phone asks « quelque chose pour moi ? », receives
what is waiting, does it, and says what happened. Three signed round trips,
no inbound connection, no address to publish.

Two things this buys beyond reachability:

The poll IS the heartbeat. A device asking for its commands has proved it is
awake more convincingly than any beacon could, so the same request records
presence — one round trip where a naive design would spend two.

And the honesty rules finally fit the device. A phone that is polling every
few seconds is not "hors ligne"; a command for it has not failed, it is
simply about to be collected. Telling the user « elle n'a pas été effectuée »
about a command that arrives four seconds later would be the exact lie §57
exists to forbid.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from diapason.mesh.signed import SignedRejected, sign_payload, verify_payload

logger = logging.getLogger(__name__)

__all__ = [
    "PULL_VERSION",
    "PullRejected",
    "build_poll",
    "sign_poll",
    "collect_for_device",
    "build_ack",
    "sign_ack",
    "record_ack",
    "device_collects_its_own",
]

PULL_VERSION = 1

POLL_PATH = "/v1/mesh/commands/poll"
ACK_PATH = "/v1/mesh/commands/ack"

# How many commands one poll may carry. A device that has been away for a
# while gets its backlog over several polls rather than one enormous
# response — and a queue that somehow grew unbounded cannot become a
# response that flattens a phone.
MAX_PER_POLL = 20

_POLL_FIELDS = (
    "version",
    "ownerId",
    "deviceId",
    "appState",
    "capabilities",
    "appVersion",
    "sentAtMs",
)

_ACK_FIELDS = (
    "version",
    "ownerId",
    "deviceId",
    "results",
    "sentAtMs",
)

# Statuses a device is allowed to report back. Anything else is a device
# inventing vocabulary, and the queue's own status ladder is not something a
# remote party gets to extend.
_REPORTABLE = frozenset({"SUCCESS", "FAILED", "UNSUPPORTED", "DENIED", "EXPIRED"})


class PullRejected(Exception):
    """A poll or acknowledgement that will not be honoured."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now_ms() -> int:
    from diapason.mesh.commands import now_ms

    return now_ms()


def device_collects_its_own(device: Mapping[str, Any]) -> bool:
    """True when this device comes and fetches, rather than being dialled.

    Read from what the device last told us, not inferred from what we do not
    know about it. The tempting shortcut — "no address means it must poll" —
    is wrong in a way that produces a lie: a desktop that has simply not
    announced yet also has no address, has no intention of polling, and would
    sit under « il le récupérera à son réveil » forever.

    ``transport`` is only ever set to ``pull`` by ``collect_for_device``, so
    this is evidence: the device has actually polled at least once. It is also
    self-correcting — a device that stops polling falls out of presence on its
    own and the ordinary offline rules take over again.
    """
    return str((device or {}).get("transport") or "").strip().lower() == "pull"


# ── the poll ─────────────────────────────────────────────────────────────


def build_poll(
    *,
    owner_id: str,
    device_id: str,
    app_state: str = "",
    capabilities: list[str] | tuple[str, ...] | None = None,
    app_version: str = "",
    now: int | None = None,
) -> dict[str, Any]:
    return {
        "version": PULL_VERSION,
        "ownerId": str(owner_id),
        "deviceId": str(device_id),
        "appState": str(app_state or ""),
        "capabilities": sorted(str(c) for c in (capabilities or [])),
        "appVersion": str(app_version or ""),
        "sentAtMs": _now_ms() if now is None else int(now),
    }


def sign_poll(payload: Mapping[str, Any]) -> dict[str, Any]:
    return sign_payload(payload, _POLL_FIELDS)


def collect_for_device(
    raw: Mapping[str, Any],
    *,
    registry: Any,
    queue: Any,
    local_owner_id: str,
    local_device_id: str,
    now: int | None = None,
) -> dict[str, Any]:
    """Hand a verified device whatever is waiting for it.

    Presence is recorded from the poll itself: asking for your commands is
    the strongest possible evidence that you are awake.
    """
    stamp = _now_ms() if now is None else int(now)
    try:
        device_id = verify_payload(
            raw,
            fields=_POLL_FIELDS,
            version=PULL_VERSION,
            registry=registry,
            local_owner_id=local_owner_id,
            local_device_id=local_device_id,
            now_ms=stamp,
            subject="relève",
        )
    except SignedRejected as exc:
        raise PullRejected(exc.code, exc.message) from exc

    # Monotonic, exactly as for beacons: a captured poll replayed later must
    # not keep a device that is off looking on. Note this is checked before
    # anything is handed over, so a replay learns nothing either.
    accepted = registry.heartbeat_signed(
        device_id,
        app_state=str(raw.get("appState") or ""),
        transport="pull",
        app_version=str(raw.get("appVersion") or ""),
        sent_at_ms=int(raw.get("sentAtMs") or 0),
    )
    if accepted is None:
        raise PullRejected("DENIED", "Cette relève a déjà été vue ou est dépassée.")

    declared = raw.get("capabilities")
    if declared:
        try:
            accepted = registry.declare_capabilities(device_id, list(declared))
        except Exception:  # noqa: BLE001 - a bad claim must not deny the poll
            logger.info("capacités refusées pour %s", device_id)

    waiting = queue.pending_envelopes_for(device_id, limit=MAX_PER_POLL)
    for entry in waiting:
        # Handed over, not yet done. The row only becomes terminal when the
        # device says what happened — until then a lost response leaves the
        # command collectable on the next poll rather than silently dropped.
        queue.record_attempt(entry["commandId"])

    return {
        "commands": [entry["envelope"] for entry in waiting],
        "presence": accepted,
        "count": len(waiting),
    }


# ── the acknowledgement ──────────────────────────────────────────────────


def build_ack(
    *,
    owner_id: str,
    device_id: str,
    results: list[Mapping[str, Any]],
    now: int | None = None,
) -> dict[str, Any]:
    return {
        "version": PULL_VERSION,
        "ownerId": str(owner_id),
        "deviceId": str(device_id),
        "results": [
            {
                "commandId": str(r.get("commandId") or ""),
                "status": str(r.get("status") or "").upper(),
                "userSafeMessage": str(r.get("userSafeMessage") or ""),
                "errorCode": str(r.get("errorCode") or ""),
            }
            for r in results
        ],
        "sentAtMs": _now_ms() if now is None else int(now),
    }


def sign_ack(payload: Mapping[str, Any]) -> dict[str, Any]:
    return sign_payload(payload, _ACK_FIELDS)


def record_ack(
    raw: Mapping[str, Any],
    *,
    registry: Any,
    queue: Any,
    local_owner_id: str,
    local_device_id: str,
    now: int | None = None,
) -> dict[str, Any]:
    """Record what a device says it did with the commands it collected."""
    stamp = _now_ms() if now is None else int(now)
    try:
        device_id = verify_payload(
            raw,
            fields=_ACK_FIELDS,
            version=PULL_VERSION,
            registry=registry,
            local_owner_id=local_owner_id,
            local_device_id=local_device_id,
            now_ms=stamp,
            subject="confirmation",
        )
    except SignedRejected as exc:
        raise PullRejected(exc.code, exc.message) from exc

    results = raw.get("results")
    if not isinstance(results, list):
        raise PullRejected("DENIED", "Cette confirmation est mal formée.")

    recorded = 0
    for item in results[:MAX_PER_POLL]:
        if not isinstance(item, Mapping):
            continue
        command_id = str(item.get("commandId") or "")
        status = str(item.get("status") or "").upper()
        if not command_id or status not in _REPORTABLE:
            continue

        # A device may only speak about commands addressed to it. Without
        # this a paired phone could mark another device's command done, and
        # the user would be told something happened on a machine that never
        # heard of it.
        try:
            existing = queue.get(command_id)
        except KeyError:
            continue
        if existing.get("targetDeviceId") != device_id:
            logger.info(
                "confirmation refusée : %s n'est pas la cible de %s",
                device_id,
                command_id,
            )
            continue
        if existing.get("status") in {"SUCCESS", "FAILED", "EXPIRED", "DENIED"}:
            # Already settled. Re-reporting is normal after a lost response,
            # and must not rewrite what the user was already told.
            continue

        queue.mark(
            command_id,
            status,
            user_message=str(item.get("userSafeMessage") or ""),
            error_code=str(item.get("errorCode") or ""),
        )
        recorded += 1

    return {"recorded": recorded}
