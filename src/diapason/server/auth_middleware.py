"""API key authentication middleware for the Diapason server."""

from __future__ import annotations

import logging
import os
import secrets
import stat
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from diapason.core.env import get as _env_get
from diapason.core.paths import get_config_dir
from diapason.security.rate_limiter import RateLimitConfig, RateLimiter

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates ``Authorization: Bearer <key>`` on ``/v1/*`` and ``/api/*`` routes.

    Webhook routes and health checks are exempt — they use
    per-channel signature verification instead.
    """

    def __init__(self, app, api_key: str = "") -> None:  # noqa: ANN001
        super().__init__(app)
        self._api_key = api_key or (_env_get("API_KEY") or "")

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        # An authenticated cross-origin request first sends an OPTIONS
        # preflight without credentials. CORS middleware must answer that
        # preflight before the browser is allowed to send the real Bearer
        # request. Authenticating OPTIONS made every Tauri/WebView fetch fail
        # at the browser boundary even when the desktop held the correct key.
        if request.method == "OPTIONS":
            return await call_next(request)

        if self._api_key and self._requires_auth(request.url.path):
            auth = request.headers.get("Authorization", "")
            if not auth:
                # A starting WebView can briefly poll before the native key
                # bridge resolves. Keep this evidence at diagnostic level so
                # it does not flood the normal service log every second.
                logger.debug(
                    "Rejected unauthenticated local API request: path=%s origin=%s",
                    request.url.path,
                    request.headers.get("origin", "(none)"),
                )
                return JSONResponse(
                    {"detail": "Missing Authorization header"},
                    status_code=401,
                )
            scheme, _, token = auth.partition(" ")
            # Constant-time comparison to avoid leaking the key via timing.
            if scheme.lower() != "bearer" or not secrets.compare_digest(
                token, self._api_key
            ):
                logger.warning(
                    "Rejected invalid local API credential: path=%s origin=%s",
                    request.url.path,
                    request.headers.get("origin", "(none)"),
                )
                return JSONResponse(
                    {"detail": "Invalid API key"},
                    status_code=401,
                )
        return await call_next(request)

    @staticmethod
    def _requires_auth(path: str) -> bool:
        """Protect API routes and operational metrics; leave the UI/health open.

        ``/metrics`` exposes request/token counters that should not be readable
        by unauthenticated clients, so it is gated alongside ``/v1`` and
        ``/api``. ``/health`` stays open for liveness probes.
        """
        return (
            path.startswith("/v1/")
            or path.startswith("/api/")
            or path == "/metrics"
            or path.startswith("/metrics/")
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Throttle authenticated API traffic per credential and client address."""

    def __init__(
        self,
        app,  # noqa: ANN001
        *,
        requests_per_minute: int = 60,
        burst_size: int = 10,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self._limiter = RateLimiter(
            RateLimitConfig(
                requests_per_minute=requests_per_minute,
                burst_size=burst_size,
                enabled=enabled,
            )
        )

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        # Preflight requests are browser permission checks, not data-plane API
        # calls. Let CORSMiddleware answer them and rate-limit the authenticated
        # request that follows.
        if request.method == "OPTIONS":
            return await call_next(request)

        # This small, read-only readiness response is polled while the voice
        # panel is open. It remains authenticated, but unrelated dashboard
        # traffic must not exhaust its rate-limit bucket and disable Start.
        if (
            AuthMiddleware._requires_auth(request.url.path)
            and request.url.path != "/v1/voice/live/health"
        ):
            auth = request.headers.get("Authorization", "")
            # Never retain the bearer token itself in limiter state or logs.
            credential = "unauthenticated"
            if auth:
                import hashlib

                credential = hashlib.sha256(auth.encode()).hexdigest()[:16]
            client = request.client.host if request.client else "unknown"
            allowed, wait_seconds = self._limiter.check(f"{client}:{credential}")
            if not allowed:
                retry_after = max(1, int(wait_seconds + 0.999))
                return JSONResponse(
                    {"detail": "Rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)


def generate_api_key() -> str:
    """Generate a 256-bit Diapason API key."""
    return f"diapason_sk_{secrets.token_urlsafe(32)}"


def _read_local_api_key(path: Path) -> str:
    """Read an existing key without following a swapped symlink."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    else:
        file_stat = path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError(f"Refusing unsafe local API key path: {path}")
    descriptor = os.open(path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError(f"Refusing unsafe local API key path: {path}")
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        else:
            path.chmod(0o600)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            return handle.read().strip()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def ensure_local_api_key(explicit_key: str = "") -> tuple[str, Path | None]:
    """Return an API key, creating a permission-restricted local key if needed.

    Precedence is an explicit configured value, ``DIAPASON_API_KEY`` (with
    legacy environment aliases), then ``<DIAPASON_HOME>/auth/local_api_key``.
    The generated file and its parent are owner-only and creation is atomic.
    """
    configured = explicit_key or (_env_get("API_KEY") or "")
    if configured:
        if len(configured.encode("utf-8")) < 32:
            raise ValueError(
                "DIAPASON_API_KEY must contain at least 32 bytes; "
                "generate one with 'diapason auth generate-key'."
            )
        return configured, None

    auth_dir = get_config_dir() / "auth"
    key_path = auth_dir / "local_api_key"
    auth_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        auth_dir.chmod(0o700)
    except OSError:
        pass

    try:
        existing = _read_local_api_key(key_path)
    except FileNotFoundError:
        existing = ""
    if existing:
        if len(existing.encode("utf-8")) < 32:
            raise RuntimeError(
                "Local API key is too short; rotate it with "
                f"'diapason auth create-key': {key_path}"
            )
        return existing, key_path

    generated = generate_api_key()
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(key_path, flags, 0o600)
    except FileExistsError:
        existing = _read_local_api_key(key_path)
        if len(existing.encode("utf-8")) < 32:
            raise RuntimeError(
                f"Local API key file is missing or too short: {key_path}"
            )
        return existing, key_path
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(generated + "\n")
    return generated, key_path


def check_bind_safety(host: str, *, api_key: str) -> None:
    """Refuse to bind non-loopback without an API key.

    Raises ``SystemExit`` if *host* is not a loopback address and
    *api_key* is empty.
    """
    import ipaddress
    import sys

    try:
        is_loop = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loop = host in ("localhost", "")

    if not is_loop and not api_key:
        logger.error(
            "Binding to %s requires DIAPASON_API_KEY to be set. "
            "Run: diapason auth generate-key",
            host,
        )
        sys.exit(1)


def check_cors_safety(host: str, origins: list[str]) -> None:
    """Reject credentialed wildcard CORS on a non-loopback listener."""
    import ipaddress

    try:
        is_loop = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loop = host in ("localhost", "")
    if not is_loop and "*" in origins:
        raise ValueError(
            "Wildcard CORS is forbidden on a non-loopback Diapason server. "
            "Configure explicit trusted origins in server.cors_origins."
        )


def websocket_authorized(websocket, expected_key: str) -> bool:  # noqa: ANN001
    """Return ``True`` if a WebSocket connection presents the expected key.

    ``AuthMiddleware`` is a ``BaseHTTPMiddleware`` and never sees WebSocket
    upgrade requests, so streaming endpoints must check the token themselves
    in the handshake before calling ``websocket.accept()``.

    When *expected_key* is empty, authentication is disabled (the loopback /
    local-only default, matching :class:`AuthMiddleware`) and all connections
    are allowed. The token may be supplied either as a ``?token=`` query
    parameter for backwards compatibility, via an ``Authorization: Bearer``
    header for programmatic clients, or as a ``diapason-auth.<key>`` offered
    subprotocol. The desktop uses the last form so access logs never contain
    its credential in the request URL.
    """
    if not expected_key:
        return True
    token = websocket.query_params.get("token", "")
    if not token:
        auth = websocket.headers.get("authorization", "")
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer":
            token = value
    if not token:
        offered = websocket.headers.get("sec-websocket-protocol", "")
        for protocol in (item.strip() for item in offered.split(",")):
            if protocol.startswith("diapason-auth."):
                token = protocol.removeprefix("diapason-auth.")
                break
    if not token:
        return False
    return secrets.compare_digest(token, expected_key)


def websocket_response_subprotocol(websocket) -> str | None:  # noqa: ANN001
    """Select the non-secret Diapason protocol when a browser offers it."""
    offered = websocket.headers.get("sec-websocket-protocol", "")
    protocols = {item.strip() for item in offered.split(",")}
    return "diapason" if "diapason" in protocols else None
