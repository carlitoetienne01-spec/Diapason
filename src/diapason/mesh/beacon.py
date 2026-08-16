"""How a device says « je suis là » to the rest of the fleet.

Until now presence could only be recorded by whoever held this machine's API
key — which is to say, by this machine about itself. That made every remote
device's presence a fiction, and the whole honest-about-offline machinery
had nothing true to stand on: a command could be reported as sent to a
device that had been unplugged for a week.

A device announces itself with the same credential it uses to command:
an Ed25519 signature over the envelope, verified against the public key
recorded when it was paired. No API key is involved, because a joining
device never has one.

Replay is stopped by monotonicity rather than by nonces. A heartbeat every
fifteen seconds would mint 5 760 nonces per device per day to protect a
message whose entire content is "still here"; storing one integer per device
and refusing anything not strictly newer costs nothing and refuses the same
attack — an attacker replaying a captured beacon cannot make a device that
is off look on.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "PRESENCE_VERSION",
    "PresenceRejected",
    "build_beacon",
    "sign_beacon",
    "verify_beacon",
    "announce_to",
    "announce_to_fleet",
]

PRESENCE_VERSION = 1
PRESENCE_PATH = "/v1/mesh/presence"

# A beacon older than this is stale whatever its signature says. Shorter than
# the command window: presence is a claim about *now*, so tolerating minutes
# of skew would mean tolerating minutes of lie.
MAX_BEACON_SKEW_MS = 30_000

# Fields that are signed. Listed explicitly rather than "everything but the
# signature", so adding a field later is a deliberate act with a version
# bump, not an accident that silently changes what is protected.
_SIGNED_FIELDS = (
    "version",
    "ownerId",
    "deviceId",
    "appState",
    "transport",
    "address",
    "capabilities",
    "appVersion",
    "sentAtMs",
)


class PresenceRejected(Exception):
    """A beacon that will not be believed, with the reason in French."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now_ms() -> int:
    from diapason.mesh.commands import now_ms

    return now_ms()


def build_beacon(
    *,
    owner_id: str,
    device_id: str,
    app_state: str = "",
    transport: str = "lan",
    address: str = "",
    capabilities: tuple[str, ...] | list[str] | None = None,
    app_version: str = "",
    now: int | None = None,
) -> dict[str, Any]:
    """The unsigned envelope, with keys in the order they are signed."""
    return {
        "version": PRESENCE_VERSION,
        "ownerId": str(owner_id),
        "deviceId": str(device_id),
        "appState": str(app_state or ""),
        "transport": str(transport or ""),
        "address": str(address or ""),
        "capabilities": sorted(str(c) for c in (capabilities or [])),
        "appVersion": str(app_version or ""),
        "sentAtMs": _now_ms() if now is None else int(now),
    }


def _signable(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {field: payload.get(field) for field in _SIGNED_FIELDS}


def sign_beacon(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Sign with THIS device's private key."""
    from diapason.mesh.identity import sign_envelope

    body = dict(payload)
    body["signature"] = sign_envelope(_signable(body))
    return body


def verify_beacon(
    raw: Mapping[str, Any],
    *,
    registry: Any,
    local_owner_id: str,
    local_device_id: str,
    now: int | None = None,
) -> dict[str, Any]:
    """Decide whether to believe *raw*, and return the accepted device row.

    Check order mirrors ``verify_command``: cheap structural checks first,
    cryptography once the envelope is plausible, and the monotonicity clock
    advanced LAST — a beacon rejected for another reason must not move the
    watermark that the legitimate device still needs to clear.
    """
    stamp = _now_ms() if now is None else int(now)

    if int(raw.get("version") or 0) != PRESENCE_VERSION:
        raise PresenceRejected(
            "UNSUPPORTED", "Cette annonce utilise une version non prise en charge."
        )

    owner = str(raw.get("ownerId") or "")
    if not owner or owner != local_owner_id:
        raise PresenceRejected(
            "DENIED", "Cette annonce vient d'un autre ensemble d'appareils."
        )

    device_id = str(raw.get("deviceId") or "")
    if not device_id:
        raise PresenceRejected("DENIED", "Cette annonce ne dit pas qui l'envoie.")
    if device_id == local_device_id:
        raise PresenceRejected("DENIED", "Un appareil ne s'annonce pas à lui-même.")

    # A revoked device holds no key here, so revocation stops it at once —
    # the same single choke point revocation already uses for commands.
    public_key = registry.public_key_of(device_id)
    if public_key is None:
        raise PresenceRejected(
            "DENIED", "Cet appareil n'est pas autorisé sur cette machine."
        )

    sent_at = int(raw.get("sentAtMs") or 0)
    if sent_at - MAX_BEACON_SKEW_MS > stamp:
        raise PresenceRejected("DENIED", "Cette annonce est datée du futur.")
    if sent_at + MAX_BEACON_SKEW_MS < stamp:
        raise PresenceRejected("EXPIRED", "Cette annonce est trop ancienne.")

    from diapason.mesh.identity import verify_envelope

    signature = str(raw.get("signature") or "")
    if not signature:
        raise PresenceRejected("DENIED", "Cette annonce n'est pas signée.")
    if not verify_envelope(_signable(raw), signature, public_key):
        raise PresenceRejected("DENIED", "La signature de cette annonce est invalide.")

    # Monotonicity, checked last and enforced by the registry in the same
    # statement that records the heartbeat: two beacons racing cannot both
    # pass, because only one UPDATE can see the older watermark.
    accepted = registry.heartbeat_signed(
        device_id,
        app_state=str(raw.get("appState") or ""),
        transport=str(raw.get("transport") or ""),
        address=str(raw.get("address") or ""),
        app_version=str(raw.get("appVersion") or ""),
        sent_at_ms=sent_at,
    )
    if accepted is None:
        raise PresenceRejected(
            "DENIED", "Cette annonce a déjà été vue ou est dépassée."
        )

    declared = raw.get("capabilities")
    if declared:
        # The platform ceiling still applies — a device cannot grant itself
        # anything by announcing it (spec §6).
        try:
            accepted = registry.declare_capabilities(device_id, list(declared))
        except Exception:  # noqa: BLE001 - a bad claim must not deny presence
            logger.info("capacités refusées pour %s", device_id)
    return accepted


# ── the outgoing half ────────────────────────────────────────────────────


def announce_to(
    device: Mapping[str, Any],
    *,
    address: str = "",
    app_state: str = "",
    timeout_s: float = 4.0,
    post=None,
) -> bool:
    """Tell one peer we are here. False on any failure — never raises.

    A beacon that does not arrive is not an error the user should hear
    about: the peer will simply consider us offline, which is what the
    honest-presence rules are designed to handle.
    """
    from diapason.mesh.identity import device_identity, owner_id
    from diapason.mesh.transport import assert_may_reach_device

    peer_address = str(device.get("address") or "").strip()
    if not peer_address:
        return False
    try:
        assert_may_reach_device(device, peer_address)
    except Exception as exc:  # noqa: BLE001 - a refused peer is simply skipped
        logger.debug("annonce non envoyée à %s : %s", device.get("deviceId"), exc)
        return False

    identity = device_identity()
    beacon = sign_beacon(
        build_beacon(
            owner_id=owner_id(),
            device_id=identity.device_id,
            app_state=app_state,
            address=address or local_address(),
            capabilities=_local_capabilities(),
        )
    )

    if post is None:

        def post(url: str, body: dict) -> int:
            import httpx

            return httpx.post(url, json=body, timeout=timeout_s).status_code

    try:
        status = post(f"{peer_address.rstrip('/')}{PRESENCE_PATH}", beacon)
    except Exception as exc:  # noqa: BLE001
        logger.debug("annonce échouée vers %s : %s", device.get("deviceId"), exc)
        return False
    return 200 <= int(status) < 300


def announce_to_fleet(
    *,
    registry=None,
    app_state: str = "",
    post=None,
) -> dict[str, int]:
    """Announce to every trusted peer whose address we know."""
    from diapason.mesh.registry import DeviceRegistry

    registry = registry or DeviceRegistry()
    reached = 0
    skipped = 0
    for device in registry.list_devices(include_revoked=False):
        if device.get("trustLevel") != "TRUSTED":
            skipped += 1
            continue
        if announce_to(device, app_state=app_state, post=post):
            reached += 1
        else:
            skipped += 1
    return {"reached": reached, "skipped": skipped}


# Where this process is actually listening, recorded by the server at
# startup. Guessing instead — reading the config port and probing the LAN
# interface — produces an address the process may not answer on: a second
# instance on --port 8100 would advertise 8000, and a server bound to
# loopback would advertise its LAN address to peers that cannot reach it.
# An address is a promise; this is how the promise is kept.
_endpoint: tuple[str, int] | None = None


def set_local_endpoint(host: str, port: int) -> None:
    """Record the host and port uvicorn was actually given."""
    global _endpoint
    _endpoint = (str(host or "127.0.0.1"), int(port))


def local_address() -> str:
    """The address at which peers can really reach this machine.

    A server bound to loopback advertises loopback, even though a LAN
    address would look more useful: peers off this machine genuinely cannot
    reach it, and telling them otherwise would send commands into the void
    and have them reported as delivered.
    """
    host, port = _endpoint or (_configured_host(), _configured_port())

    # Only a wildcard bind means "reachable on every interface" — that is the
    # one case where the LAN address is the truthful thing to advertise.
    if host in {"0.0.0.0", "::", ""}:  # noqa: S104 - matching, not binding
        host = _lan_address() or "127.0.0.1"
    return f"http://{host}:{port}"


def _configured_host() -> str:
    try:
        from diapason.core.config import load_config

        return str(getattr(load_config().server, "host", "") or "127.0.0.1")
    except Exception:  # noqa: BLE001 - a missing config is not a failure here
        return "127.0.0.1"


def _configured_port() -> int:
    try:
        from diapason.core.config import load_config

        return int(getattr(load_config().server, "port", None) or 8000)
    except Exception:  # noqa: BLE001
        return 8000


def _lan_address() -> str:
    """Which local interface would be used to reach the LAN. No packet is
    sent — this only consults the routing table."""
    import socket

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.168.1.1", 1))
            candidate = str(probe.getsockname()[0] or "")
            return candidate if candidate and not candidate.startswith("0.") else ""
        finally:
            probe.close()
    except Exception:  # noqa: BLE001
        return ""


def _local_capabilities() -> list[str]:
    from diapason.mesh.capabilities import effective_capabilities
    from diapason.mesh.identity import device_identity
    from diapason.mesh.tools import list_remote_tools

    declared = [tool["capability"] for tool in list_remote_tools()]
    return list(effective_capabilities(device_identity().platform, declared))
