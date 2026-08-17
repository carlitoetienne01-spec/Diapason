"""REST API for the device mesh.

Everything here is authenticated by the local API key EXCEPT one route:
``POST /v1/mesh/pairings/redeem``. A device being enrolled does not have the
key yet — that is the whole point of enrolment — so it authenticates with
the one-time pairing token instead, exactly as Succès sync already does.
That route is rate-limited (unlike the Succès CRUD exemption), because it is
the mesh's front door.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from diapason.mesh.presence import presence_of
from diapason.mesh.queue import CommandQueue
from diapason.mesh.registry import DeviceRegistry, MeshError

router = APIRouter(prefix="/v1/mesh", tags=["mesh"])

_registry: DeviceRegistry | None = None


def get_registry() -> DeviceRegistry:
    global _registry
    if _registry is None:
        _registry = DeviceRegistry()
    return _registry


def set_registry_for_tests(registry: DeviceRegistry | None) -> None:
    global _registry
    _registry = registry


_queue: CommandQueue | None = None


def get_queue() -> CommandQueue:
    global _queue
    if _queue is None:
        _queue = CommandQueue()
    return _queue


def set_queue_for_tests(queue: CommandQueue | None) -> None:
    global _queue
    _queue = queue


def _fail(exc: MeshError) -> HTTPException:
    """Mesh errors are written for the user; pass them through verbatim."""
    return HTTPException(status_code=400, detail=str(exc))


# ── payloads ─────────────────────────────────────────────────────────────


class PairingCreate(BaseModel):
    deviceName: str = Field(min_length=1, max_length=80)


class PairingRedeem(BaseModel):
    pairingToken: str = Field(min_length=8, max_length=200)
    deviceId: str = Field(min_length=1, max_length=120)
    publicKey: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=80)
    platform: str = Field(min_length=2, max_length=40)
    deviceType: Literal["DESKTOP", "LAPTOP", "PHONE", "TABLET", "BROWSER"] = "DESKTOP"
    capabilities: list[str] = Field(default_factory=list, max_length=64)
    appVersion: str = Field(default="", max_length=40)
    # Where the joining device can be reached. Optional because a phone
    # behind NAT may have no address worth giving; without it the pairing
    # still succeeds and the device is simply command-able only once it has
    # announced itself.
    address: str = Field(default="", max_length=200)


class Heartbeat(BaseModel):
    appState: str = Field(default="", max_length=40)
    transport: str = Field(default="", max_length=40)
    address: str = Field(default="", max_length=200)


class DeviceRename(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class CapabilitiesDeclare(BaseModel):
    capabilities: list[str] = Field(default_factory=list, max_length=64)


# ── this device ──────────────────────────────────────────────────────────


@router.get("/me")
def whoami() -> dict[str, Any]:
    """This installation's own identity — public half only."""
    from diapason.mesh.identity import public_identity

    return public_identity()


# ── enrolment ────────────────────────────────────────────────────────────


@router.post("/pairings")
def create_pairing(body: PairingCreate) -> dict[str, Any]:
    try:
        return get_registry().create_pairing(body.deviceName)
    except MeshError as exc:
        raise _fail(exc) from exc


@router.post("/pairings/redeem")
def redeem_pairing(body: PairingRedeem) -> dict[str, Any]:
    """Enrol a device that presents a valid invitation.

    Deliberately outside the API-key wall: the joining device has no key.
    The invitation is the credential, and it is single-use and short-lived.
    """
    try:
        device = get_registry().redeem_pairing(
            body.pairingToken,
            device_id=body.deviceId,
            public_key_b64=body.publicKey,
            name=body.name,
            platform=body.platform,
            device_type=body.deviceType,
            declared_capabilities=body.capabilities,
            app_version=body.appVersion,
        )
    except MeshError as exc:
        raise _fail(exc) from exc
    # Addresses are exchanged here or not at all: until each side knows where
    # the other lives, neither can send anything, and neither can announce
    # itself either — a chicken-and-egg that pairing is the only moment able
    # to break.
    if body.address:
        try:
            # Re-read: the row returned by redeem_pairing predates this write,
            # and handing back a device whose address reads null would tell the
            # joining side its own address was refused.
            device = get_registry().heartbeat(
                body.deviceId, transport="lan", address=body.address
            )
        except MeshError:  # noqa: BLE001 - a bad address must not undo pairing
            pass

    # The new device needs OUR identity to verify what we send it later:
    # enrolment is mutual, not one-way.
    from diapason.mesh.beacon import local_address
    from diapason.mesh.identity import public_identity

    return {
        "device": device,
        "host": {**public_identity(), "address": local_address()},
    }


# ── the fleet ────────────────────────────────────────────────────────────


@router.get("/devices")
def list_devices(includeRevoked: bool = False) -> dict[str, Any]:
    registry = get_registry()
    devices = registry.list_devices(include_revoked=includeRevoked)
    return {
        "devices": [{**d, "presence": presence_of(d)} for d in devices],
        "count": len(devices),
    }


@router.get("/devices/{device_id}")
def get_device(device_id: str) -> dict[str, Any]:
    try:
        device = get_registry().get(device_id)
    except MeshError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**device, "presence": presence_of(device)}


@router.get("/devices/{device_id}/presence")
def get_presence(device_id: str) -> dict[str, Any]:
    try:
        device = get_registry().get(device_id)
    except MeshError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return presence_of(device)


@router.post("/devices/{device_id}/heartbeat")
def heartbeat(device_id: str, body: Heartbeat) -> dict[str, Any]:
    try:
        device = get_registry().heartbeat(
            device_id,
            app_state=body.appState,
            transport=body.transport,
            address=body.address,
        )
    except MeshError as exc:
        raise _fail(exc) from exc
    return presence_of(device)


@router.patch("/devices/{device_id}")
def rename_device(device_id: str, body: DeviceRename) -> dict[str, Any]:
    try:
        return get_registry().rename(device_id, body.name)
    except MeshError as exc:
        raise _fail(exc) from exc


@router.post("/devices/{device_id}/capabilities")
def declare_capabilities(device_id: str, body: CapabilitiesDeclare) -> dict[str, Any]:
    """Record what a device claims. The grant is computed, never taken."""
    try:
        return get_registry().declare_capabilities(device_id, body.capabilities)
    except MeshError as exc:
        raise _fail(exc) from exc


@router.post("/devices/{device_id}/revoke")
def revoke_device(device_id: str) -> dict[str, Any]:
    try:
        return get_registry().revoke(device_id)
    except MeshError as exc:
        raise _fail(exc) from exc


@router.delete("/devices/{device_id}")
def forget_device(device_id: str) -> dict[str, Any]:
    """Erase a device outright — the only way back from revocation."""
    get_registry().forget(device_id)
    return {"ok": True, "deviceId": device_id}


# ── commands ─────────────────────────────────────────────────────────────


class CommandSend(BaseModel):
    targetDeviceId: str = Field(min_length=1, max_length=120)
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotencyKey: str = Field(default="", max_length=120)


@router.get("/tools")
def list_tools() -> dict[str, Any]:
    """The remote catalogue, as the assistant's router should advertise it."""
    from diapason.mesh.tools import list_remote_tools

    return {"tools": list_remote_tools()}


@router.post("/commands")
def send_command(body: CommandSend) -> dict[str, Any]:
    """Send a command to another device. Authenticated by the local API key:
    this is the assistant or the UI on THIS machine asking."""
    from diapason.mesh.dispatch import dispatch_command

    return dispatch_command(
        target_device_id=body.targetDeviceId,
        tool=body.tool,
        arguments=body.arguments,
        registry=get_registry(),
        queue=get_queue(),
        idempotency_key=body.idempotencyKey,
    )


@router.post("/commands/deliver")
def deliver_command(body: dict[str, Any]) -> dict[str, Any]:
    """Receive a command from another device.

    Outside the API-key wall on purpose, and NOT unauthenticated: the
    envelope's Ed25519 signature is the credential, checked against the key
    recorded when the sender was paired. A stronger proof than a shared
    secret, since it also binds the exact arguments.
    """
    from diapason.mesh.dispatch import receive_command
    from diapason.mesh.executor import local_executor

    return receive_command(
        body,
        registry=get_registry(),
        queue=get_queue(),
        executor=local_executor,
    )


@router.post("/presence")
def receive_presence(body: dict[str, Any]) -> dict[str, Any]:
    """A paired device announcing itself.

    Outside the API-key wall for the same reason as ``/commands/deliver``:
    a device that joined this fleet never receives this machine's key, and
    its Ed25519 signature is a stronger credential anyway — it binds the
    exact claim, including the address commands will later be sent to.
    """
    from diapason.mesh.beacon import PresenceRejected, verify_beacon
    from diapason.mesh.identity import device_identity, owner_id

    try:
        device = verify_beacon(
            body,
            registry=get_registry(),
            local_owner_id=owner_id(),
            local_device_id=device_identity().device_id,
        )
    except PresenceRejected as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    return {"ok": True, "presence": presence_of(device)}


@router.post("/announce")
def announce(appState: str = "") -> dict[str, Any]:
    """Push our own presence to every peer we know how to reach.

    Behind the key wall: this is the local app asking to be seen, not a
    stranger asking to be believed.
    """
    from diapason.mesh.beacon import announce_to_fleet

    return announce_to_fleet(registry=get_registry(), app_state=appState)


@router.post("/commands/poll")
def poll_commands(body: dict[str, Any]) -> dict[str, Any]:
    """A device asking for whatever is waiting for it.

    Outside the API-key wall, like the other two device-signed surfaces. This
    is how a phone joins the mesh at all: it has no address to be dialled at,
    so it comes to fetch. The poll doubles as its heartbeat — asking for your
    commands proves you are awake better than any beacon.
    """
    from diapason.mesh.identity import device_identity, owner_id
    from diapason.mesh.pull import PullRejected, collect_for_device

    try:
        return collect_for_device(
            body,
            registry=get_registry(),
            queue=get_queue(),
            local_owner_id=owner_id(),
            local_device_id=device_identity().device_id,
        )
    except PullRejected as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc


@router.post("/commands/ack")
def ack_commands(body: dict[str, Any]) -> dict[str, Any]:
    """A device reporting what it did with what it collected.

    Without this half a polled command would stay PENDING forever and the
    user would never learn whether it happened — which is the same failure as
    claiming it did.
    """
    from diapason.mesh.identity import device_identity, owner_id
    from diapason.mesh.pull import PullRejected, record_ack

    try:
        return record_ack(
            body,
            registry=get_registry(),
            queue=get_queue(),
            local_owner_id=owner_id(),
            local_device_id=device_identity().device_id,
        )
    except PullRejected as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc


@router.get("/inbox")
def inbox(drain: bool = True) -> dict[str, Any]:
    """What the local shell should open or show, oldest first.

    Polled by the desktop app; draining on read means a screen is opened
    once, not on every poll.
    """
    from diapason.mesh.executor import pending_navigations

    return {"pending": pending_navigations(drain=drain)}


@router.get("/commands")
def command_history(limit: int = 50) -> dict[str, Any]:
    """Recent commands, newest first (spec §43)."""
    queue = get_queue()
    queue.expire_stale()
    return {"commands": queue.history(limit=max(1, min(int(limit), 200)))}


@router.get("/commands/{command_id}")
def command_status(command_id: str) -> dict[str, Any]:
    try:
        return get_queue().get(command_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Commande inconnue.") from exc
