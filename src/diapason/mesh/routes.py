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


class Heartbeat(BaseModel):
    appState: str = Field(default="", max_length=40)
    transport: str = Field(default="", max_length=40)


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
    # The new device needs OUR identity to verify what we send it later:
    # enrolment is mutual, not one-way.
    from diapason.mesh.identity import public_identity

    return {"device": device, "host": public_identity()}


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
            device_id, app_state=body.appState, transport=body.transport
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
