"""Discover already-paired Diapason devices without publishing identity.

mDNS is a hint, never a credential. Anyone on the current Wi-Fi can publish
an SRV record, so this module neither enrols a device nor writes a discovered
address to the registry. It only contacts a candidate whose rotating service
name can be derived from a public key learned during pairing. The peer then
answers with its own signed presence beacon; ``beacon.verify_beacon`` remains
the sole path that may retain the address.

The record deliberately contains no device id, hostname, owner id, platform,
version or capability. Its instance label rotates hourly, which prevents the
same laptop from advertising one durable tracking token in every café it
visits.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import logging
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DISCOVERY_TYPE = "_diapason-mesh._tcp.local."
DISCOVERY_VERSION = 1

# Une heure relie les observations d'un même séjour, pas celles de deux lieux
# visités ensuite. Cinq minutes multiplieraient les annonces par douze sans
# empêcher un observateur présent de relier la machine à son adresse réseau.
DISCOVERY_EPOCH_MS = 3_600_000

# Le heartbeat du Mesh bat toutes les quinze secondes. Réévaluer sur le même
# rythme répare un socket mDNS après veille ou changement de Wi-Fi sans trois
# implémentations natives de notifications réseau.
DISCOVERY_REFRESH_S = 15.0

# Un même ajout et sa mise à jour peuvent arriver dos à dos. Recontacter la
# machine à chaque paquet gaspille le réseau et avance inutilement l'horloge
# anti-rejeu de présence.
CONTACT_COOLDOWN_MS = 10_000


class DiscoveryUnavailable(RuntimeError):
    """The optional cross-platform mDNS implementation is not installed."""


@dataclass(frozen=True, slots=True)
class Advertisement:
    """The complete public record — intentionally tiny and inspectable."""

    token: str
    address: str
    port: int
    properties: Mapping[bytes, bytes]

    @property
    def name(self) -> str:
        return f"{self.token}.{DISCOVERY_TYPE}"


def _epoch(now_ms: int) -> int:
    return int(now_ms) // DISCOVERY_EPOCH_MS


def service_token(public_key: bytes, *, now_ms: int, offset: int = 0) -> str:
    """A 16-character rotating label known to already-paired devices only."""
    if not public_key:
        raise ValueError("A public key is required for discovery.")
    period = _epoch(now_ms) + int(offset)
    digest = hmac.new(
        bytes(public_key),
        f"diapason-mdns-v1|{period}".encode(),
        hashlib.sha256,
    ).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=").lower()[:16]


def expected_names(registry: Any, *, now_ms: int) -> dict[str, str]:
    """Map rotating labels to trusted local device ids.

    The previous and next periods tolerate clock skew around the hour. A
    revoked device disappears because ``public_key_of`` refuses to return its
    key, even if an old row still exists in the database.
    """
    expected: dict[str, str] = {}
    for device in registry.list_devices(include_revoked=False):
        if device.get("trustLevel") != "TRUSTED":
            continue
        device_id = str(device.get("deviceId") or "")
        key = registry.public_key_of(device_id)
        if not key:
            continue
        for offset in (-1, 0, 1):
            expected[service_token(key, now_ms=now_ms, offset=offset)] = device_id
    return expected


def txt_properties() -> dict[bytes, bytes]:
    """Protocol version, and absolutely no identifying metadata."""
    return {b"v": str(DISCOVERY_VERSION).encode("ascii")}


def current_advertisement(*, now_ms: int | None = None) -> Advertisement | None:
    """Build what this process may truthfully advertise, or nothing.

    No endpoint means the server has not promised a socket. Loopback,
    link-local and non-IP hosts are not advertised: a peer could not reach
    them through the transport policy, so publishing them would be a lie.
    """
    from diapason.mesh.beacon import local_address, local_endpoint

    if local_endpoint() is None:
        return None
    parsed = urlparse(local_address())
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError:
        return None
    if (
        address.version != 4
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or not address.is_private
    ):
        return None
    port = parsed.port
    if port is None or not 0 < port < 65_536:
        return None

    from diapason.mesh.identity import device_identity

    raw_key = base64.b64decode(device_identity().public_key_b64, validate=True)
    stamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    return Advertisement(
        token=service_token(raw_key, now_ms=stamp),
        address=str(address),
        port=port,
        properties=txt_properties(),
    )


def _token_from_name(name: str) -> str:
    suffix = DISCOVERY_TYPE.casefold()
    folded = str(name or "").casefold()
    if not folded.endswith(suffix):
        return ""
    return folded[: -len(suffix)].rstrip(".")


def _private_ipv4(addresses: Iterable[str]) -> str:
    for raw in addresses:
        try:
            address = ipaddress.ip_address(str(raw).split("%", 1)[0])
        except ValueError:
            continue
        if (
            address.version == 4
            and address.is_private
            and not address.is_loopback
            and not address.is_link_local
            and not address.is_multicast
            and not address.is_unspecified
            and not address.is_reserved
        ):
            return str(address)
    return ""


def consider_candidate(
    *,
    name: str,
    addresses: Iterable[str],
    port: int,
    properties: Mapping[bytes, bytes] | None,
    registry: Any,
    announce: Callable[..., bool],
    now_ms: int,
) -> bool:
    """Contact one authenticated-by-pairing candidate, without retaining it."""
    properties = properties or {}
    version = properties.get(b"v", properties.get("v"))  # type: ignore[arg-type]
    if version not in {b"1", "1"}:
        return False
    token = _token_from_name(name)
    device_id = expected_names(registry, now_ms=now_ms).get(token)
    if not device_id:
        return False
    if not 0 < int(port) < 65_536:
        return False
    address = _private_ipv4(addresses)
    if not address:
        return False
    device = registry.find(device_id)
    if not device or device.get("trustLevel") != "TRUSTED":
        return False

    candidate = f"http://{address}:{int(port)}"
    # A copy only: the registry is changed later by the peer's signed return
    # beacon, never by this unauthenticated mDNS record.
    return bool(
        announce(
            {**device, "address": candidate},
            address=_our_address(),
        )
    )


def _our_address() -> str:
    from diapason.mesh.beacon import local_address

    return local_address()


def _enabled() -> bool:
    try:
        from diapason.core.config import load_config

        return bool(load_config().mesh.discovery)
    except Exception:  # noqa: BLE001 - malformed config fails closed here
        logger.warning("mesh discovery disabled: configuration is unreadable")
        return False


def _imports():
    try:
        from zeroconf import ServiceInfo, ServiceStateChange
        from zeroconf.asyncio import (
            AsyncServiceBrowser,
            AsyncServiceInfo,
            AsyncZeroconf,
        )
    except ImportError as exc:
        raise DiscoveryUnavailable(
            "La découverte locale demande le paquet zeroconf. "
            "Réinstalle les dépendances serveur de Diapason."
        ) from exc
    return (
        ServiceInfo,
        ServiceStateChange,
        AsyncServiceBrowser,
        AsyncServiceInfo,
        AsyncZeroconf,
    )


def _service_info(ServiceInfo: Any, advertisement: Advertisement):
    return ServiceInfo(
        DISCOVERY_TYPE,
        advertisement.name,
        addresses=[socket.inet_aton(advertisement.address)],
        port=advertisement.port,
        properties=dict(advertisement.properties),
        server=f"{advertisement.token}.local.",
    )


async def run_discovery(
    *,
    registry: Any = None,
    announce: Callable[..., bool] | None = None,
) -> None:
    """Advertise and browse until the server lifespan cancels this task."""
    # The feature flag and a genuinely reachable Mesh socket are cumulative.
    # In particular, constructing a FastAPI app in a test must not open a
    # multicast socket, and a loopback-only server has no truthful address to
    # give a peer anyway.
    if not _enabled() or current_advertisement() is None:
        return
    try:
        (
            ServiceInfo,
            ServiceStateChange,
            AsyncServiceBrowser,
            AsyncServiceInfo,
            AsyncZeroconf,
        ) = _imports()
    except DiscoveryUnavailable as exc:
        logger.info("mesh discovery unavailable: %s", exc)
        return

    from diapason.mesh.beacon import announce_to
    from diapason.mesh.registry import DeviceRegistry

    registry = registry or DeviceRegistry()
    announce = announce or announce_to
    azc = AsyncZeroconf()
    registered: Any = None
    contacts: dict[tuple[str, str, int], int] = {}
    tasks: set[asyncio.Task[Any]] = set()

    async def inspect(service_type: str, name: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        if not await info.async_request(azc.zeroconf, 3_000):
            return
        addresses = info.parsed_scoped_addresses()
        key = (name, addresses[0] if addresses else "", int(info.port or 0))
        stamp = int(time.time() * 1000)
        if stamp - contacts.get(key, 0) < CONTACT_COOLDOWN_MS:
            return
        contacts[key] = stamp
        await asyncio.to_thread(
            consider_candidate,
            name=name,
            addresses=addresses,
            port=int(info.port or 0),
            properties=info.properties,
            registry=registry,
            announce=announce,
            now_ms=stamp,
        )

    def changed(_zc: Any, service_type: str, name: str, state: Any) -> None:
        if state not in {ServiceStateChange.Added, ServiceStateChange.Updated}:
            return
        task = asyncio.create_task(inspect(service_type, name))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    browser = AsyncServiceBrowser(
        azc.zeroconf,
        [DISCOVERY_TYPE],
        handlers=[changed],
    )
    try:
        while True:
            advertisement = current_advertisement()
            next_info = (
                _service_info(ServiceInfo, advertisement) if advertisement else None
            )
            if registered is not None and (
                next_info is None
                or registered.name != next_info.name
                or registered.port != next_info.port
                or registered.addresses != next_info.addresses
            ):
                await azc.async_unregister_service(registered)
                registered = None
            if registered is None and next_info is not None:
                await azc.async_register_service(next_info)
                registered = next_info
            await asyncio.sleep(DISCOVERY_REFRESH_S)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - discovery never takes down Diapason
        logger.warning("mesh discovery stopped after an error", exc_info=True)
    finally:
        await browser.async_cancel()
        for task in tuple(tasks):
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if registered is not None:
            try:
                await azc.async_unregister_service(registered)
            except Exception:  # noqa: BLE001
                logger.debug("mDNS service was already gone", exc_info=True)
        await azc.async_close()


__all__ = [
    "Advertisement",
    "DISCOVERY_EPOCH_MS",
    "DISCOVERY_TYPE",
    "DISCOVERY_VERSION",
    "DiscoveryUnavailable",
    "consider_candidate",
    "current_advertisement",
    "expected_names",
    "run_discovery",
    "service_token",
    "txt_properties",
]
