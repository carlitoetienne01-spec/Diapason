"""Device Mesh — this Diapason installation among the user's other devices.

The mesh sits ABOVE the domain, never inside it: Succès remains the single
source of truth for tasks, projects and notes (spec §34), and the mesh only
answers three questions the domain cannot — which devices exist, which are
reachable, and what may be asked of them.

Layers, built in this order:
  * ``identity`` — this device's Ed25519 key pair and derived device id.
  * (next) ``registry`` — the devices this one has paired with.
  * (next) ``presence`` / ``commands`` — reachability and the signed bus.
"""

from diapason.mesh.identity import (
    DeviceIdentity,
    device_identity,
    public_identity,
    sign_envelope,
    verify_envelope,
)

__all__ = [
    "DeviceIdentity",
    "device_identity",
    "public_identity",
    "sign_envelope",
    "verify_envelope",
]
