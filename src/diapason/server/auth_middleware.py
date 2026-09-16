"""API key authentication middleware for the Diapason server."""

from __future__ import annotations

import logging
import os
import re
import secrets
import stat
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from diapason.core.env import get as _env_get
from diapason.core.paths import get_config_dir
from diapason.core.permissions import restreindre_au_proprietaire
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

        Succès multi-device sync authenticates with pairing / peer tokens in the
        request body, so pair + exchange stay reachable through a trusted HTTPS
        relay without exposing the local Diapason API key.
        """
        if path in {"/v1/succes/sync/pair", "/v1/succes/sync/exchange"}:
            return False
        # Les deux routes OAuth NAVIGUÉES par le navigateur (24 août 2026) :
        # la fenêtre qui s'ouvre vers /oauth/start ne peut pas porter la clé
        # locale, et Google redirige vers /oauth/callback sans elle non plus.
        # Ce qu'elles exposent est mesuré : start ne fait que rediriger vers
        # Google avec le client_id (public par nature) ; callback n'accepte
        # qu'un code émis par Google — c'est LUI la lettre de créance.
        if re.match(r"^/v1/connectors/[^/]+/oauth/(?:start|callback)$", path):
            return False
        # Mesh enrolment: a device being paired does not hold the API key yet
        # — the one-time invitation IS its credential. Everything else under
        # /v1/mesh (listing, revoking, sending) stays behind the wall.
        if path == "/v1/mesh/pairings/redeem":
            return False
        # Inbound commands and presence beacons carry their own, stronger
        # credential: an Ed25519 signature over the whole envelope, verified
        # against the key we recorded when that device was paired. A shared
        # API key would prove less — it says nothing about WHICH device, nor
        # about what is being claimed.
        # The poll and its acknowledgement join the same list: a phone has no
        # address to be dialled at, so fetching is the only way it can take
        # part at all, and it holds no API key either.
        if path in {
            "/v1/mesh/commands/deliver",
            "/v1/mesh/presence",
            "/v1/mesh/commands/poll",
            "/v1/mesh/commands/ack",
        }:
            return False
        # Le transfert de fichiers : même raison, créance plus forte que la
        # clé d'API — signature d'appareil pour l'offre, jeton de session
        # pour les morceaux.
        if est_route_de_transfert(path):
            return False
        return (
            path.startswith("/v1/")
            or path.startswith("/api/")
            or path == "/metrics"
            or path.startswith("/metrics/")
        )


# Les routes de TRANSFERT DE FICHIERS (Spatial Mesh, 25 août 2026). Elles
# portent un identifiant de session dans le chemin, donc elles ne peuvent pas
# vivre dans un ensemble de chemins exacts. Un seul prédicat, partagé entre le
# mur d'authentification et le limiteur : être hors du mur et être hors du
# limiteur ont été la même condition une fois, et personne n'avait voulu la
# seconde.
#
# Leur créance n'est pas la clé d'API — l'appareil qui envoie ne l'a pas :
# l'OFFRE est signée Ed25519 comme une commande, et elle rend un jeton de
# session à usage unique qui autorise les morceaux. Le vrai plafond de ces
# routes n'est d'ailleurs pas un débit mais un VOLUME, appliqué dans le
# routeur : octets par session, et sessions simultanées.
_TRANSFERT_RE = re.compile(
    r"^/v1/mesh/files/(?:offer|requests/[A-Za-z0-9_-]{1,64}/state|"
    r"[A-Za-z0-9_-]{1,64}/(?:chunk|finish|status))$"
)


# Le mode gestes (25 août 2026). Une image toutes les quatre-vingts
# millisecondes est un usage NORMAL, pas un abus : le seau ordinaire
# (soixante par minute, rafale de dix) était épuisé en moins d'une seconde,
# et les images suivantes revenaient en 429 — que la fenêtre affichait
# « Load failed », faute d'en-têtes CORS sur la réponse d'erreur. Deux
# défauts pour un symptôme.
_GESTES_RE = re.compile(r"^/v1/gestures/(?:arm|disarm|state|frame)$")


def est_route_de_gestes(path: str) -> bool:
    """Une route du mode gestes, dont le débit normal est élevé."""
    return bool(_GESTES_RE.match(path or ""))


def est_route_de_transfert(path: str) -> bool:
    """Une route de transfert de fichiers, authentifiée par session."""
    return bool(_TRANSFERT_RE.match(path or ""))


# The mesh routes that authenticate by signature or invitation rather than by
# the API key. Listed once, here, because being outside the key wall and being
# outside the limiter used to be the same condition — and nobody meant the
# second one.
_OPEN_MESH_ROUTES = frozenset(
    {
        "/v1/mesh/pairings/redeem",
        "/v1/mesh/commands/deliver",
        "/v1/mesh/presence",
        "/v1/mesh/commands/poll",
        "/v1/mesh/commands/ack",
    }
)


def _too_many(wait_seconds: float, request: Request | None = None) -> JSONResponse:
    """Un refus qui reste LISIBLE, y compris depuis la fenêtre.

    Constaté le 25 août 2026 : une réponse d'erreur émise par ce middleware
    court-circuite CORSMiddleware, qui n'a donc jamais l'occasion d'y poser
    ses en-têtes. Vu du navigateur, la réponse devient inaccessible et
    l'échec s'affiche « Load failed » — un message qui ne dit ni le code,
    ni la raison, ni où chercher. Le mode gestes en a fait les frais : le
    serveur criait « trop de requêtes », la fenêtre entendait un silence.

    Un refus doit pouvoir être lu par celui qu'il refuse.
    """
    entetes = {"Retry-After": str(max(1, int(wait_seconds + 0.999)))}
    origine = request.headers.get("origin") if request is not None else None
    if origine:
        entetes["Access-Control-Allow-Origin"] = origine
        entetes["Access-Control-Allow-Credentials"] = "true"
        entetes["Vary"] = "Origin"
    return JSONResponse(
        {"detail": "Trop de requêtes. Réessayez dans un instant."},
        status_code=429,
        headers=entetes,
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
        # A separate bucket for the mesh routes that carry no API key.
        #
        # The main limiter only ever ran for paths that require the key, so
        # every route deliberately opened to unauthenticated devices was also
        # opened to unlimited traffic — including the pairing front door,
        # whose own module claimed the opposite. Keyed on client address,
        # since there is no credential to key on before the body is parsed,
        # and parsing the body is the cost we are trying to bound.
        #
        # Roomier than the authenticated bucket on purpose: a paired device
        # legitimately polls every couple of seconds and beacons besides, and
        # throttling that would break the very devices this is protecting.
        self._open_limiter = RateLimiter(
            RateLimitConfig(
                requests_per_minute=max(120, requests_per_minute * 2),
                burst_size=max(20, burst_size * 2),
                enabled=enabled,
            )
        )

        # Le seau du TRANSFERT, à part (25 août 2026). Un morceau vaut un
        # mégaoctet : un fichier de 500 Mio, c'est cinq cents requêtes en
        # rafale, parfaitement légitimes. Les compter dans le seau du
        # maillage aurait fait tomber présence et relèves. Ce seau est donc
        # large en NOMBRE — le vrai plafond est en octets, et il vit dans le
        # routeur, là où l'on sait ce qu'une session a déjà reçu.
        # Le seau des GESTES. Douze images par seconde pendant dix minutes,
        # c'est sept mille deux cents requêtes — toutes légitimes. Ce seau
        # est large en nombre parce que le vrai garde-fou est ailleurs : la
        # session se désarme seule après quatre-vingt-dix secondes de
        # silence et dix minutes au total.
        self._gesture_limiter = RateLimiter(
            RateLimitConfig(
                requests_per_minute=max(1200, requests_per_minute * 20),
                burst_size=max(60, burst_size * 6),
                enabled=enabled,
            )
        )

        self._transfer_limiter = RateLimiter(
            RateLimitConfig(
                requests_per_minute=max(1200, requests_per_minute * 20),
                burst_size=max(200, burst_size * 20),
                enabled=enabled,
            )
        )

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        # Preflight requests are browser permission checks, not data-plane API
        # calls. Let CORSMiddleware answer them and rate-limit the authenticated
        # request that follows.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        # Local-first Succès CRUD is driven by dense UI interactions (lists,
        # toggles, autosave). Background polls already share the same bucket, so
        # throttling /v1/succes/* starves the product surface with 429s.
        #
        # The sync control plane is the exception to the exception: /sync/pair
        # and /sync/exchange are the only routes that skip the local API key
        # (they authenticate by token in the body), so exempting them from the
        # limiter too would leave the mesh's front door both unauthenticated
        # and unthrottled. Those keep their bucket.
        if path.startswith("/v1/succes") and not path.startswith("/v1/succes/sync/"):
            return await call_next(request)
        # La conversation elle-même. La fenêtre principale et le mini-panneau
        # de la réglette sont DEUX instances du bundle — même adresse, même
        # clé, donc MÊME seau : à l'ouverture du panneau, sa rafale de
        # démarrage (modèles, infos serveur, santé, économies) vidait le seau
        # commun (60/min, rafale 10) et le message que l'utilisateur venait de
        # taper rebondissait « 429 » en 8 ms (constaté le 16 sept. 2026).
        # Une frappe humaine n'est jamais une rafale ; la route reste derrière
        # le mur de la clé, et le vrai goulot est le créneau unique d'Ollama.
        if path == "/v1/chat/completions":
            return await call_next(request)
        if path == "/v1/voice/live/health":
            return await call_next(request)
        # Same shape, same reason, for the two mesh surfaces the local UI
        # polls: the inbox (another device asked us to open a screen) and the
        # device list (presence goes stale on its own, so the Appareils screen
        # has to re-read it). Sharing the 60/min bucket with the voice poller
        # meant the fleet screen failed to load on a busy app — a failure the
        # user would read as "le maillage est cassé", not as a rate limit.
        #
        # Reads only. Minting invitations, sending commands, revoking and
        # forgetting stay throttled: those are the routes worth abusing, and
        # none of them is polled.
        if request.method == "GET" and (
            path == "/v1/mesh/inbox"
            or path == "/v1/mesh/me"
            or path.startswith("/v1/mesh/devices")
        ):
            return await call_next(request)

        client = request.client.host if request.client else "unknown"

        # The mesh's key-less routes. Throttled on their own bucket rather
        # than left unlimited: they are the only surface a stranger on the
        # network can reach at all.
        if path in _OPEN_MESH_ROUTES:
            allowed, wait_seconds = self._open_limiter.check(f"{client}:mesh")
            if not allowed:
                return _too_many(wait_seconds, request)
            return await call_next(request)

        # Le transfert a SON seau. Partager celui du maillage était le piège
        # évident : un fichier découpé en mille morceaux aurait vidé le seau
        # commun et fait échouer les battements de présence et les relèves
        # des autres appareils — le maillage aurait paru cassé pendant qu'un
        # transfert légitime se déroulait.
        if est_route_de_gestes(path):
            allowed, wait_seconds = self._gesture_limiter.check(f"{client}:gestures")
            if not allowed:
                return _too_many(wait_seconds, request)
            return await call_next(request)

        if est_route_de_transfert(path):
            allowed, wait_seconds = self._transfer_limiter.check(f"{client}:transfer")
            if not allowed:
                return _too_many(wait_seconds, request)
            return await call_next(request)

        # This small, read-only readiness response is polled while the voice
        # panel is open. It remains authenticated, but unrelated dashboard
        # traffic must not exhaust its rate-limit bucket and disable Start.
        if AuthMiddleware._requires_auth(path):
            auth = request.headers.get("Authorization", "")
            # Never retain the bearer token itself in limiter state or logs.
            credential = "unauthenticated"
            if auth:
                import hashlib

                credential = hashlib.sha256(auth.encode()).hexdigest()[:16]
            allowed, wait_seconds = self._limiter.check(f"{client}:{credential}")
            if not allowed:
                return _too_many(wait_seconds, request)
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
        restreindre_au_proprietaire(descriptor)
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
