"""Getting a signed command to the device it names — LAN first.

Ordering follows spec §12: the closest usable path wins, because latency and
privacy improve together. Today that means loopback and the local network;
the relay transport slots in later behind the same interface without any
caller changing.

This module also owns the one privacy exemption the mesh is allowed
(documented in ``core/local_mode``): a TRUSTED, paired device at a PRIVATE
address is the user's own other computer, not "elsewhere". Anything failing
either half of that — unknown device, revoked device, public address — is
refused exactly as before.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any, Mapping
from urllib.parse import urlparse

from diapason.mesh.commands import RemoteCommand

logger = logging.getLogger(__name__)

__all__ = [
    "RemoteRefusal",
    "TransportError",
    "assert_may_reach_device",
    "address_is_private",
    "deliver",
]

DELIVER_PATH = "/v1/mesh/commands/deliver"
DELIVER_TIMEOUT_S = 6.0


class TransportError(RuntimeError):
    """Delivery failed. The command is not lost — the queue still holds it."""


class RemoteRefusal(TransportError):
    """The device ANSWERED, and it said no. This is not a network fault.

    26 August 2026. Both cases lived under one name, so the caller — which
    could not tell them apart — said "could not be reached" for both. A
    ``desktop.open`` refused by the Windows PC therefore sent its owner to
    check a Wi-Fi that was working perfectly, while the PC's own sentence,
    the ONLY one that explained the refusal, was captured into ``str(exc)``
    and then dropped without even reaching the log.

    ``retryable`` separates "it refused" from "it cannot right now": a 4xx is
    a verdict, a 429 or a 5xx is a hiccup. Confusing them costs in both
    directions — retrying a verdict forever, or giving up on a server that
    was merely restarting.
    """

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = status_code == 429 or status_code >= 500


def address_is_private(address: str) -> bool:
    """True for loopback and RFC1918 — the network the user is standing on.

    A hostname we cannot resolve to a private literal is treated as public:
    a destination we cannot vouch for is not one we quietly trust.
    """
    raw = (address or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw if "//" in raw else f"//{raw}")
        host = (parsed.hostname or "").strip().lower()
    except Exception:  # noqa: BLE001
        return False
    if not host:
        return False
    if host in {"localhost"} or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private) and not ip.is_link_local


def assert_may_reach_device(device: Mapping[str, Any], address: str) -> None:
    """The mesh's narrow exemption to local-only. Both halves are required.

    Refusing here rather than at the socket keeps the reason legible: the
    user learns whether the problem is trust or reachability, not a bare
    connection error.
    """
    from diapason.core.local_mode import LocalOnlyError, local_only

    if not local_only():
        return
    if (device or {}).get("trustLevel") != "TRUSTED":
        raise LocalOnlyError(
            "Le mode local-only est actif et cet appareil n'est pas appairé : "
            "rien ne lui sera envoyé."
        )
    if not address_is_private(address):
        raise LocalOnlyError(
            "Le mode local-only est actif : seuls les appareils appairés "
            "joignables sur le réseau local peuvent être commandés. "
            "Pour passer par Internet, mettez local_only = false dans la "
            "section [privacy] de ~/.diapason/config.toml."
        )


def deliver(
    command: RemoteCommand,
    device: Mapping[str, Any],
    *,
    timeout_s: float = DELIVER_TIMEOUT_S,
    post=None,
) -> dict[str, Any]:
    """Push a signed command to *device* and return its result envelope.

    ``post`` is injectable so the whole path can be tested without a socket;
    production passes nothing and gets httpx.
    """
    address = str((device or {}).get("address") or "").strip()
    if not address:
        raise TransportError("L'adresse de cet appareil est inconnue.")
    assert_may_reach_device(device, address)

    url = f"{address.rstrip('/')}{DELIVER_PATH}"
    payload = command.to_dict()

    if post is None:

        def post(target: str, body: dict) -> tuple[int, dict]:
            import httpx

            response = httpx.post(target, json=body, timeout=timeout_s)
            try:
                parsed = response.json()
            except ValueError:
                parsed = {}
            return response.status_code, parsed

    try:
        status_code, body = post(url, payload)
    except Exception as exc:  # noqa: BLE001 - every transport failure is one case
        # Deliberately vague to the user, precise to the log: a connection
        # error should not teach a bystander the shape of the network.
        logger.info("mesh delivery failed for %s: %s", command.command_id, exc)
        raise TransportError(
            "Cet appareil n'a pas pu être joint sur le réseau local."
        ) from exc

    if status_code >= 400:
        message = ""
        if isinstance(body, Mapping):
            message = str(body.get("detail") or body.get("userSafeMessage") or "")
        # Logged HERE because this is the last place that still knows the
        # status code: further up, only a sentence survives.
        logger.info(
            "mesh delivery refused for %s: HTTP %s %s",
            command.command_id,
            status_code,
            message,
        )
        raise RemoteRefusal(
            message or f"L'appareil a répondu {status_code}.",
            status_code=status_code,
        )
    if not isinstance(body, Mapping):
        raise TransportError("La réponse de l'appareil est illisible.")
    return dict(body)
