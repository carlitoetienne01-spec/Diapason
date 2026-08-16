"""HTTPS relay helpers for Succès multi-device sync.

The Mac stays the source of truth. A guest device (another Diapason instance)
talks to a user-chosen base URL that reaches the host — LAN, Tailscale,
Cloudflare Tunnel, or any reverse proxy. Pairing and exchange authenticate
with one-time / long-lived sync tokens, not the local Diapason API key.
"""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from diapason.succes.store import SuccesError

_METADATA_HOSTS = frozenset(
    {
        "169.254.169.254",
        "metadata.google.internal",
        "metadata.google.com",
        "100.100.100.200",
    }
)


def normalize_relay_url(raw: str) -> str:
    """Validate and normalize a user-provided sync relay base URL."""
    cleaned = (raw or "").strip().rstrip("/")
    if not cleaned:
        raise SuccesError("Indiquez l'URL HTTPS (ou HTTP sur le réseau local) du relais.")
    if len(cleaned) > 500:
        raise SuccesError("L'URL du relais est trop longue.")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"}:
        raise SuccesError("Le relais doit utiliser http:// ou https://.")
    if not parsed.netloc:
        raise SuccesError("L'URL du relais est incomplète.")
    if parsed.username or parsed.password:
        raise SuccesError("L'URL du relais ne doit pas contenir d'identifiants.")
    host = parsed.hostname or ""
    if host.lower() in _METADATA_HOSTS:
        raise SuccesError("Cette adresse de relais n'est pas autorisée.")
    try:
        ip = ipaddress.ip_address(host)
        if ip in ipaddress.ip_network("169.254.169.254/32"):
            raise SuccesError("Cette adresse de relais n'est pas autorisée.")
    except ValueError:
        pass
    # Drop fragment/query; keep path if the user fronts Diapason under a prefix.
    normalized = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", "")
    )
    return normalized.rstrip("/")


def relay_post(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST JSON to ``{base}{path}`` without a Diapason API key.

    Guarded by the local-only contract: unlike opening a URL in the user's
    own browser, this ships the user's OWN DATA (tasks, notes, habits) to a
    remote host. ``local_only`` may never be overridden by a per-feature
    switch, so syncing to a non-loopback relay requires turning it off — a
    deliberate, informed decision, surfaced here in plain French rather than
    failing with an opaque network error.
    """
    url = f"{normalize_relay_url(base_url)}{path}"
    from diapason.core.local_mode import LocalOnlyError, assert_may_leave

    try:
        assert_may_leave("les données Succès", destination=url)
    except LocalOnlyError as exc:
        raise SuccesError(
            "Le mode local-only est actif : rien ne quitte ce Mac, donc la "
            "synchronisation multi-appareils est refusée. Pour l'activer, "
            "mettez local_only = false dans la section [privacy] de "
            "~/.diapason/config.toml."
        ) from exc
    try:
        response = httpx.post(url, json=payload, timeout=30.0)
    except httpx.TimeoutException as exc:
        raise SuccesError(
            "Le relais ne répond pas à temps. Vérifiez l'URL et la connectivité."
        ) from exc
    except httpx.HTTPError as exc:
        raise SuccesError(
            f"Impossible de joindre le relais : {exc.__class__.__name__}."
        ) from exc
    if response.status_code >= 400:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = str(body.get("detail") or body.get("message") or "")
        except Exception:
            detail = (response.text or "")[:200]
        raise SuccesError(
            detail
            or f"Le relais a renvoyé une erreur HTTP {response.status_code}."
        )
    data = response.json()
    if not isinstance(data, dict):
        raise SuccesError("La réponse du relais est illisible.")
    return data


__all__ = ["normalize_relay_url", "relay_post"]
