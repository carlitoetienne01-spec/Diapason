"""La passerelle du tailnet : le seul chemin du téléphone vers le Mac.

26/09/2026, phase 2 du plan mobile (étape 3). ``tailscale serve`` relaie
HTTPS vers ``127.0.0.1:8002`` ; ce socket sert cette passerelle, qui
enveloppe l'application principale SANS la modifier.

Le défaut qu'elle évite : tailscaled se connecte depuis 127.0.0.1. Pointée
vers 8000, une requête du téléphone aurait hérité de tout ce que la boucle
locale accorde — la clé d'API n'y protège que ce qu'elle protège, et
``_host_actions_allowed`` donne le pilotage du bureau à toute adresse de
boucle locale. Ce n'est donc ni l'adresse IP ni un en-tête qui dit « ceci
vient du tailnet » : un processus local peut forger ``X-Forwarded-For`` ou
``Tailscale-User-Login``. C'est le SOCKET d'arrivée — le client ne choisit
pas le port sur lequel ``tailscale serve`` le dépose — plus une session
d'appareil (``mesh/sessions.py``) prouvée par un cookie ``HttpOnly``.

Ce que fait la passerelle, dans l'ordre :

1. refuse toute clé locale (``Authorization``, ``?token=``, sous-protocole
   ``diapason-auth.*``) : la clé partagée n'a rien à faire ici ;
2. classe la route que l'application servirait (``server/portee_tailnet.py``)
   — une route que personne n'a classée est refusée ;
3. contrôle l'``Origin`` des WebSockets et de tout ce qui n'est pas un GET ;
4. vérifie la session à CHAQUE requête, sans cache — une révocation coupe
   la requête suivante — et la revérifie toutes les 30 s au plus tant
   qu'une réponse ou un WebSocket reste ouvert ;
5. marque la portée : ``diapason.tailnet``, ``diapason.appareil``, un
   ``client`` qui n'est plus une adresse de boucle, ``scheme`` https — et
   le contexte d'exécution (``core/origine_telephone.py``), que
   l'exécuteur d'outils lit pour refuser au téléphone ce qui agit sur le
   Mac ou lit son écran ;
6. réécrit les en-têtes de permissions et la CSP pour l'origine https.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs

from starlette.requests import cookie_parser
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Match

from diapason.core.origine_telephone import marquer_le_telephone
from diapason.server.portee_tailnet import (
    OUVERTE,
    SESSION,
    classer,
    cle_de_route,
    motif_du_refus,
)

logger = logging.getLogger(__name__)

__all__ = [
    "COOKIE_APPAREIL",
    "INTERVALLE_DE_CONTROLE_S",
    "PasserelleTailnet",
    "adresse_du_tailnet",
]

COOKIE_APPAREIL = "diapason_appareil"

# Trente secondes au plus entre deux vérifications d'une session tenue par
# un WebSocket ou une réponse en flux (décidé au plan : « révocation qui
# coupe HTTP et WebSocket en 30 s au plus »). Plus court, chaque flux du
# chat ouvert écrirait sur mesh.db toutes les quelques secondes ; plus
# long, un téléphone perdu garderait la Discussion ouverte une minute après
# que Carlito l'a révoqué depuis le Mac.
INTERVALLE_DE_CONTROLE_S = 30.0

# L'enveloppe signée d'ouverture fait ~600 octets, le formulaire du ticket
# ~80. Seize kilo-octets laissent de la marge à un client verbeux sans
# laisser un inconnu faire lire des mégaoctets à une route sans session.
_CORPS_MAX = 16 * 1024

# Un nom d'hôte, éventuellement suivi d'un port — rien d'autre. L'hôte
# finit dans la CSP : un en-tête Host forgé avec « ; script-src * »
# réécrirait la politique qu'il est censé restreindre.
_HOTE_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}(?::\d{1,5})?$")

# Des en-têtes qu'un processus LOCAL peut poser en se connectant lui-même à
# 8002 : aucun ne doit atteindre l'application, pour qu'aucun code futur ne
# puisse s'y fier par mégarde. uvicorn les ignore déjà sur ce socket
# (proxy_headers=False) ; ceci ferme la porte aux handlers.
_ENTETES_RETIRES = frozenset(
    {b"x-forwarded-for", b"x-forwarded-proto", b"x-forwarded-host", b"forwarded"}
    | {b"x-forwarded-port", b"x-real-ip"}
)
_PREFIXE_TAILSCALE = b"tailscale-"

_PERMISSIONS = "camera=(self), microphone=(self), geolocation=()"

_PAGE_401 = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Diapason</title></head>
<body style="font-family: system-ui, sans-serif; background:#000; color:#eee;
padding:2rem; line-height:1.5">
<h1 style="font-size:1.4rem">Ouvre Diapason depuis l'app</h1>
<p>Cette adresse ne s'ouvre pas dans un navigateur : c'est l'application
Diapason du téléphone, appairée à ce Mac, qui ouvre la session.</p>
</body></html>
"""

Recevoir = Callable[[], Awaitable[dict]]
Envoyer = Callable[[dict], Awaitable[None]]


def adresse_du_tailnet(config: Any = None) -> str | None:
    """L'adresse https que Carlito a posée dans ``[tailnet] adresse``.

    JAMAIS devinée (décidé le 25/09/2026) : ni ``tailscale status``, ni le
    nom de la machine. Un nom deviné qui se trompe envoie le téléphone
    frapper à une porte qui n'existe pas, et l'erreur se lit « réseau ».
    Rend None quand la clé est vide ou n'est pas une adresse https — le
    téléphone passe toujours par https, même à la maison.
    """
    if config is None:
        try:
            from diapason.core.config import load_config

            config = load_config()
        except Exception:  # noqa: BLE001 - une config illisible ne dit rien
            return None
    brute = str(getattr(getattr(config, "tailnet", None), "adresse", "") or "")
    brute = brute.strip().rstrip("/")
    if not brute:
        return None
    if "://" not in brute:
        brute = f"https://{brute}"
    schema, _, reste = brute.partition("://")
    if schema.lower() != "https" or not _HOTE_RE.match(reste):
        return None
    return f"https://{reste.lower()}"


class _Coupure:
    """Ce qui relie la surveillance d'une session au flux qu'elle garde."""

    def __init__(self) -> None:
        self.evenement = asyncio.Event()

    @property
    def faite(self) -> bool:
        return self.evenement.is_set()


class PasserelleTailnet:
    """Application ASGI du socket 8002. Voir la docstring du module."""

    def __init__(
        self,
        app: Any,
        *,
        sessions: Any = None,
        registre: Any = None,
        nonces: Any = None,
        identite: Callable[[], tuple[str, str]] | None = None,
        adresse: str | None = None,
        intervalle_s: float = INTERVALLE_DE_CONTROLE_S,
    ) -> None:
        self.app = app
        self._sessions = sessions
        self._registre = registre
        self._nonces = nonces
        self._identite = identite
        self._adresse = adresse if adresse is not None else adresse_du_tailnet()
        self._intervalle_s = float(intervalle_s)

    # ── dépendances, résolues à l'appel (les tests posent leur registre) ──

    def _registre_courant(self) -> Any:
        if self._registre is not None:
            return self._registre
        from diapason.mesh.routes import get_registry

        return get_registry()

    def _sessions_courantes(self) -> Any:
        if self._sessions is not None:
            return self._sessions
        from diapason.mesh.sessions import DeviceSessions

        return DeviceSessions(self._registre_courant())

    def _nonces_courants(self) -> Any:
        if self._nonces is not None:
            return self._nonces
        from diapason.mesh.commands import NonceStore

        return NonceStore(self._registre_courant().db_path)

    def _identite_locale(self) -> tuple[str, str]:
        if self._identite is not None:
            return self._identite()
        from diapason.mesh.identity import device_identity, owner_id

        return device_identity().device_id, owner_id()

    # ── ASGI ─────────────────────────────────────────────────────────────

    async def __call__(self, scope: dict, receive: Recevoir, send: Envoyer) -> None:
        genre = scope.get("type")
        if genre == "lifespan":
            # uvicorn tourne ici avec lifespan="off". Si quelqu'un le
            # rallume, le cycle de vie de l'application principale ne doit
            # pas partir une seconde fois : deux battements du maillage,
            # deux tâches de synchronisation du compte, et le magasin des
            # conversations fermé deux fois. La passerelle répond seule.
            await self._cycle_de_vie_neutre(receive, send)
            return
        if genre not in ("http", "websocket"):
            return
        websocket = genre == "websocket"
        entetes = _Entetes(scope.get("headers") or [])
        hote = entetes.hote()
        if not websocket:
            send = self._reecrire_les_entetes(send, hote)

        if _porte_une_cle_locale(scope, entetes):
            await self._refuser(
                scope,
                receive,
                send,
                401,
                "La clé locale n'est pas acceptée par ce chemin : ouvre "
                "Diapason depuis l'app du téléphone.",
            )
            return

        chemin = scope.get("path", "")
        methode = str(scope.get("method", "GET")).upper()
        if not websocket and chemin in ("/v1/appareil/session", "/v1/appareil/ouvrir"):
            await self._porte_d_appareil(scope, receive, send, chemin, methode, entetes)
            return

        cle, correspondance = self._cle_servie(scope, websocket, methode)
        if cle is None:
            if correspondance == "partielle":
                await self._refuser(
                    scope, receive, send, 405, "Méthode non permise sur cette route."
                )
            else:
                await self._refuser(
                    scope, receive, send, 404, "Cette adresse n'existe pas."
                )
            return

        classe = classer(cle)
        if classe == OUVERTE:
            if not self._origine_toleree(entetes, hote):
                await self._refuser(
                    scope, receive, send, 403, "Origine refusée par la passerelle."
                )
                return
            with marquer_le_telephone():
                await self.app(self._marquer(scope, entetes, None), receive, send)
            return
        if classe != SESSION:
            await self._refuser(scope, receive, send, 403, motif_du_refus(cle))
            return

        if (websocket or methode not in ("GET", "HEAD")) and not self._origine_exacte(
            entetes, hote
        ):
            await self._refuser(
                scope, receive, send, 403, "Origine refusée par la passerelle."
            )
            return

        jeton = entetes.cookie(COOKIE_APPAREIL)
        sessions = self._sessions_courantes()
        session = await asyncio.to_thread(sessions.verify_session, jeton)
        if session is None:
            await self._refuser_sans_session(scope, receive, send, entetes, methode)
            return
        await self._servir_sous_surveillance(
            self._marquer(scope, entetes, str(session["deviceId"])),
            receive,
            send,
            sessions,
            jeton,
            int(session["expiresAtMs"]),
        )

    # ── classement ───────────────────────────────────────────────────────

    def _cle_servie(
        self, scope: dict, websocket: bool, methode: str
    ) -> tuple[str | None, str]:
        """La clé de la route que l'application SERVIRAIT, comme son routeur.

        Même algorithme que ``starlette.routing.Router.app`` : la première
        correspondance complète gagne ; sinon la première partielle (405).
        Classer le chemin reçu plutôt que la route servie laisserait un
        chemin inattendu — un rattrape-tout, un paramètre de chemin — passer
        sous une clé qui n'est pas la sienne.
        """
        routeur = getattr(self.app, "router", None)
        routes = getattr(routeur, "routes", None) or []
        partielle = None
        for route in routes:
            try:
                correspondance, _ = route.matches(scope)
            except Exception:  # noqa: BLE001 - une route exotique ne sert pas
                continue
            if correspondance == Match.FULL:
                return cle_de_route(route, methode, websocket=websocket), "complete"
            if correspondance == Match.PARTIAL and partielle is None:
                partielle = route
        return None, "partielle" if partielle is not None else "aucune"

    # ── contrôles ────────────────────────────────────────────────────────

    def _origines_propres(self, hote: str | None) -> set[str]:
        propres = set()
        if hote:
            propres.add(f"https://{hote.lower()}")
        if self._adresse:
            propres.add(self._adresse)
        return propres

    def _origine_exacte(self, entetes: "_Entetes", hote: str | None) -> bool:
        """Obligatoire et identique à la nôtre (WebSocket, écritures).

        Le cookie est SameSite=Strict, mais un WebSocket n'obéit pas à
        SameSite partout : l'Origin est le seul contrôle qu'un navigateur
        ne laisse pas forger à une page tierce.
        """
        origine = entetes.get(b"origin")
        return bool(origine) and origine.lower() in self._origines_propres(hote)

    def _origine_toleree(self, entetes: "_Entetes", hote: str | None) -> bool:
        """Absente, c'est un client natif (le Dart n'en envoie pas) : permis.
        Présente et étrangère, c'est une page tierce dans un navigateur."""
        origine = entetes.get(b"origin")
        if not origine:
            return True
        return origine.lower() in self._origines_propres(hote)

    # ── marquage ─────────────────────────────────────────────────────────

    def _marquer(self, scope: dict, entetes: "_Entetes", appareil: str | None) -> dict:
        """La portée telle que l'application la verra.

        ``client`` cesse d'être 127.0.0.1 : toute règle « boucle locale =
        confiance » (``_host_actions_allowed`` hier, une autre demain)
        tombe d'elle-même au lieu de s'ouvrir.
        """
        marquee = dict(scope)
        marquee["diapason.tailnet"] = True
        marquee["headers"] = entetes.nettoyes(COOKIE_APPAREIL)
        marquee["scheme"] = "wss" if scope.get("type") == "websocket" else "https"
        if appareil is not None:
            marquee["diapason.appareil"] = appareil
            marquee["client"] = (f"appareil:{appareil}", 0)
        else:
            marquee["client"] = ("tailnet", 0)
        return marquee

    # ── surveillance d'une session tenue ─────────────────────────────────

    async def _servir_sous_surveillance(
        self,
        scope: dict,
        receive: Recevoir,
        send: Envoyer,
        sessions: Any,
        jeton: str | None,
        expire_ms: int,
    ) -> None:
        """Sert la requête et revérifie la session tant qu'elle dure.

        Une requête courte finit avant le premier contrôle. Un WebSocket ou
        un flux du chat, lui, peut durer des heures : sans ce contrôle, une
        révocation n'atteindrait que la requête SUIVANTE, et un téléphone
        perdu garderait la Discussion ouverte aussi longtemps qu'il le veut.
        """
        coupure = _Coupure()
        websocket = scope.get("type") == "websocket"
        verrou = asyncio.Lock()
        etat = {"accepte": False, "ferme": False}

        async def envoyer(message: dict) -> None:
            async with verrou:
                if coupure.faite:
                    # Starlette traduit OSError en WebSocketDisconnect(1006)
                    # et uvicorn ferme la connexion HTTP : le handler sort
                    # au lieu d'écrire dans le vide.
                    raise OSError("session d'appareil fermée")
                genre = message.get("type")
                if genre == "websocket.accept":
                    etat["accepte"] = True
                elif genre == "websocket.close":
                    etat["ferme"] = True
                await send(message)

        attente_recue: asyncio.Task | None = None

        async def recevoir() -> dict:
            nonlocal attente_recue
            if coupure.faite:
                return _deconnexion(websocket)
            if attente_recue is None:
                attente_recue = asyncio.ensure_future(receive())
            attente_coupure = asyncio.ensure_future(coupure.evenement.wait())
            try:
                faites, _ = await asyncio.wait(
                    {attente_recue, attente_coupure},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                attente_coupure.cancel()
            if attente_recue in faites:
                message = attente_recue.result()
                attente_recue = None
                return message
            return _deconnexion(websocket)

        async def couper() -> None:
            async with verrou:
                if coupure.faite:
                    return
                coupure.evenement.set()
                if websocket and not etat["ferme"]:
                    etat["ferme"] = True
                    try:
                        # Acceptée ou non, un close 1008 : avant l'accept,
                        # uvicorn le traduit en refus de la poignée de main.
                        await send(
                            {
                                "type": "websocket.close",
                                "code": 1008,
                                "reason": "session d'appareil fermée",
                            }
                        )
                    except Exception:  # noqa: BLE001 - le client est peut-être parti
                        pass

        async def surveiller() -> None:
            echeance_ms = expire_ms
            while True:
                from diapason.mesh.registry import now_ms

                reste_s = max(0.05, (echeance_ms - now_ms()) / 1000)
                await asyncio.sleep(min(self._intervalle_s, reste_s))
                verdict = await asyncio.to_thread(sessions.verify_session, jeton)
                if verdict is None:
                    logger.info(
                        "passerelle : session d'appareil fermée pendant %s %s",
                        scope.get("type"),
                        scope.get("path"),
                    )
                    await couper()
                    return
                echeance_ms = int(verdict["expiresAtMs"])

        garde = asyncio.ensure_future(surveiller())
        try:
            # Le plafond des outils (core/origine_telephone.py) : posé par la
            # passerelle, donc par le SOCKET, et suivi par tout ce que
            # l'application lance dans ce contexte.
            with marquer_le_telephone():
                await self.app(scope, recevoir, envoyer)
        except OSError:
            if not coupure.faite:
                raise
        finally:
            garde.cancel()
            if attente_recue is not None and not attente_recue.done():
                attente_recue.cancel()

    # ── les deux portes d'appareil ───────────────────────────────────────

    async def _porte_d_appareil(
        self,
        scope: dict,
        receive: Recevoir,
        send: Envoyer,
        chemin: str,
        methode: str,
        entetes: "_Entetes",
    ) -> None:
        if methode != "POST":
            await self._refuser(
                scope, receive, send, 405, "Méthode non permise sur cette route."
            )
            return
        if not self._origine_toleree(entetes, entetes.hote()) and not (
            # La WebView d'Android poste le ticket par loadRequest, une
            # navigation sans document d'origine : son Origin peut valoir
            # « null ». Le ticket est la créance (usage unique, 60 s) ; une
            # page tierce n'en détient aucun à faire dépenser.
            chemin == "/v1/appareil/ouvrir" and entetes.get(b"origin") == "null"
        ):
            await self._refuser(
                scope, receive, send, 403, "Origine refusée par la passerelle."
            )
            return
        corps = await _lire_le_corps(receive, _CORPS_MAX)
        if corps is None:
            await self._refuser(scope, receive, send, 413, "Requête trop volumineuse.")
            return
        if chemin == "/v1/appareil/session":
            reponse = await self._ouvrir_une_session(corps)
        else:
            reponse = await self._poser_le_cookie(corps, entetes)
        await reponse(self._marquer(scope, entetes, None), _rien_a_recevoir, send)

    async def _ouvrir_une_session(self, corps: bytes) -> Response:
        """L'enveloppe signée contre un ticket de 60 s (étape 2 du plan)."""
        try:
            brut = json.loads(corps.decode("utf-8") or "null")
        except (UnicodeDecodeError, ValueError):
            return JSONResponse(
                {"detail": "Cette ouverture de session est illisible."}, status_code=400
            )
        from diapason.mesh.registry import MeshError
        from diapason.mesh.sessions import verify_session_request
        from diapason.mesh.signed import SignedRejected

        def verifier_puis_emettre() -> dict[str, Any]:
            registre = self._registre_courant()
            mac, proprietaire = self._identite_locale()
            appareil = verify_session_request(
                brut,
                registry=registre,
                local_device_id=mac,
                local_owner_id=proprietaire,
                nonces=self._nonces_courants(),
            )
            ticket = self._sessions_courantes().issue_ticket(appareil)
            return {**ticket, "deviceId": appareil}

        try:
            ticket = await asyncio.to_thread(verifier_puis_emettre)
        except SignedRejected as exc:
            return JSONResponse(
                {"status": exc.code, "detail": exc.message}, status_code=403
            )
        except MeshError as exc:
            return JSONResponse(
                {"status": "DENIED", "detail": str(exc)}, status_code=403
            )
        return JSONResponse(ticket, headers={"Cache-Control": "no-store"})

    async def _poser_le_cookie(self, corps: bytes, entetes: "_Entetes") -> Response:
        """Le ticket contre le cookie de session, puis 303 vers le bundle.

        Le jeton ne passe JAMAIS par le JavaScript : ni dans un corps, ni
        dans une URL, seulement dans un ``Set-Cookie`` HttpOnly.
        """
        ticket = _ticket_du_corps(corps, entetes.get(b"content-type") or "")
        sessions = self._sessions_courantes()
        session = await asyncio.to_thread(sessions.redeem_ticket, ticket)
        if session is None:
            return JSONResponse(
                {
                    "detail": "Ce ticket d'ouverture est inconnu, déjà utilisé "
                    "ou expiré : rouvre Diapason depuis l'app."
                },
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
        reponse = Response(
            status_code=303,
            headers={"Location": "/", "Cache-Control": "no-store"},
        )
        reponse.set_cookie(
            COOKIE_APPAREIL,
            session["sessionToken"],
            max_age=int(session["maxAgeSeconds"]),
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return reponse

    # ── réponses ─────────────────────────────────────────────────────────

    async def _refuser(
        self,
        scope: dict,
        receive: Recevoir,
        send: Envoyer,
        statut: int,
        phrase: str,
    ) -> None:
        if scope.get("type") == "websocket":
            # Lire la poignée de main avant de la refuser, comme l'exige
            # l'ASGI ; puis 1008, « violation de politique ».
            try:
                await receive()
            except Exception:  # noqa: BLE001
                pass
            await send(
                {"type": "websocket.close", "code": 1008, "reason": phrase[:120]}
            )
            return
        reponse = JSONResponse({"detail": phrase}, status_code=statut)
        await reponse(scope, receive, send)

    async def _refuser_sans_session(
        self,
        scope: dict,
        receive: Recevoir,
        send: Envoyer,
        entetes: "_Entetes",
        methode: str,
    ) -> None:
        if (
            scope.get("type") == "http"
            and methode in ("GET", "HEAD")
            and "text/html" in (entetes.get(b"accept") or "")
        ):
            # Un navigateur qui arrive ici par erreur lit une phrase, pas
            # un JSON : l'adresse est juste, c'est le chemin qui ne l'est pas.
            reponse = HTMLResponse(_PAGE_401, status_code=401)
            await reponse(scope, receive, send)
            return
        await self._refuser(
            scope,
            receive,
            send,
            401,
            "Aucune session d'appareil valide : ouvre Diapason depuis l'app.",
        )

    def _reecrire_les_entetes(self, send: Envoyer, hote: str | None) -> Envoyer:
        """Micro et caméra permis à NOTRE origine, et ``wss`` dans la CSP.

        Le socket 8000 garde ``microphone=()`` : seul ce chemin, qui porte
        une session d'appareil, s'ouvre au micro de la WebView — et c'est
        encore la coquille native qui décide d'accorder (§78).
        """
        hote_csp = None
        if self._adresse:
            hote_csp = self._adresse.removeprefix("https://")
        elif hote:
            hote_csp = hote.lower()

        async def envoyer(message: dict) -> None:
            if message.get("type") == "http.response.start":
                entetes = [
                    (nom, valeur)
                    for nom, valeur in message.get("headers", [])
                    if nom.lower()
                    not in (b"permissions-policy", b"content-security-policy")
                ]
                entetes.append((b"permissions-policy", _PERMISSIONS.encode("latin-1")))
                entetes.append(
                    (b"content-security-policy", _csp(hote_csp).encode("latin-1"))
                )
                message = {**message, "headers": entetes}
            await send(message)

        return envoyer

    async def _cycle_de_vie_neutre(self, receive: Recevoir, send: Envoyer) -> None:
        while True:
            message = await receive()
            genre = message.get("type")
            if genre == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif genre == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return


# ── auxiliaires ──────────────────────────────────────────────────────────


class _Entetes:
    """Les en-têtes bruts d'une portée ASGI, lus sans rien normaliser d'autre."""

    def __init__(self, bruts: list) -> None:
        self._bruts = [(bytes(n), bytes(v)) for n, v in bruts]

    def get(self, nom: bytes) -> str | None:
        for n, v in self._bruts:
            if n.lower() == nom:
                return v.decode("latin-1").strip()
        return None

    def hote(self) -> str | None:
        hote = self.get(b"host")
        if hote and _HOTE_RE.match(hote):
            return hote
        return None

    def cookie(self, nom: str) -> str | None:
        for n, v in self._bruts:
            if n.lower() == b"cookie":
                valeur = cookie_parser(v.decode("latin-1")).get(nom)
                if valeur:
                    return valeur
        return None

    def nettoyes(self, cookie_retire: str) -> list[tuple[bytes, bytes]]:
        """Sans en-têtes de relais, et sans le cookie de session.

        Le jeton n'a rien à faire dans l'application : elle ne le lit pas,
        et un journal de requêtes qui le recopierait en ferait une fuite.
        """
        propres = []
        for n, v in self._bruts:
            bas = n.lower()
            if bas in _ENTETES_RETIRES or bas.startswith(_PREFIXE_TAILSCALE):
                continue
            if bas == b"cookie":
                restes = [
                    morceau
                    for morceau in v.decode("latin-1").split(";")
                    if morceau.strip()
                    and morceau.strip().split("=", 1)[0].strip() != cookie_retire
                ]
                if not restes:
                    continue
                v = ";".join(restes).strip().encode("latin-1")
            propres.append((n, v))
        return propres


def _porte_une_cle_locale(scope: dict, entetes: _Entetes) -> bool:
    """Toutes les formes sous lesquelles la clé locale voyage ailleurs.

    ``websocket_authorized`` en lit trois ; les refuser toutes ici évite
    qu'un client qui détient la clé l'essaie sur le tailnet — elle y
    prouverait moins qu'une session : ni quel appareil, ni révocable seul.
    """
    if entetes.get(b"authorization"):
        return True
    requete = (scope.get("query_string") or b"").decode("latin-1")
    if "token" in parse_qs(requete):
        return True
    protocoles = entetes.get(b"sec-websocket-protocol") or ""
    return any(
        morceau.strip().startswith("diapason-auth.")
        for morceau in protocoles.split(",")
    )


def _csp(hote: str | None) -> str:
    connexions = "'self'" + (f" wss://{hote}" if hote else "")
    return (
        "default-src 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        f"connect-src {connexions}; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'"
    )


def _deconnexion(websocket: bool) -> dict:
    if websocket:
        return {"type": "websocket.disconnect", "code": 1008}
    return {"type": "http.disconnect"}


async def _rien_a_recevoir() -> dict:
    return {"type": "http.disconnect"}


async def _lire_le_corps(receive: Recevoir, plafond: int) -> bytes | None:
    morceaux: list[bytes] = []
    taille = 0
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            break
        morceau = message.get("body", b"") or b""
        taille += len(morceau)
        if taille > plafond:
            return None
        morceaux.append(morceau)
        if not message.get("more_body"):
            break
    return b"".join(morceaux)


def _ticket_du_corps(corps: bytes, type_de_contenu: str) -> str | None:
    """Le ticket, posté en formulaire (WebView) ou en JSON (client natif)."""
    texte = corps.decode("utf-8", errors="replace")
    if "json" in type_de_contenu.lower():
        try:
            donnees = json.loads(texte or "null")
        except ValueError:
            return None
        valeur = donnees.get("ticket") if isinstance(donnees, dict) else None
        return valeur if isinstance(valeur, str) else None
    valeurs = parse_qs(texte).get("ticket") or []
    return valeurs[0] if len(valeurs) == 1 else None
