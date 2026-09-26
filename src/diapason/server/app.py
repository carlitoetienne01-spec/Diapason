"""FastAPI application factory for the Diapason API server."""

from __future__ import annotations

import asyncio
import logging
import pathlib
import time
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from diapason.server.analytics_routes import router as analytics_router
from diapason.server.api_routes import include_all_routes
from diapason.server.comparison import comparison_router
from diapason.server.compte_routes import AccesCompte, create_compte_router
from diapason.server.config_routes import create_config_router
from diapason.server.connectors_router import create_connectors_router
from diapason.server.conversations_routes import create_conversations_router
from diapason.server.conversations_store import ConversationsStore
from diapason.server.dashboard import dashboard_router
from diapason.server.dictation_routes import create_dictation_router
from diapason.server.digest_routes import create_digest_router
from diapason.server.lecture_reglages import create_lecture_reglages_router
from diapason.server.research_router import router as research_router
from diapason.server.routes import router
from diapason.server.screen_share_routes import create_screen_share_router
from diapason.server.trigger_routes import create_trigger_router
from diapason.server.upload_router import router as upload_router

logger = logging.getLogger(__name__)


class _VeilleurSynchro:
    """Tout ce qui existe du moteur de synchronisation tant qu'aucun compte
    n'est déverrouillé : une référence au magasin et un réveil.

    24/09/2026 (étape 10 de compte-chiffre.md) : les comptes sont FERMÉS
    sur l'appareil (``service.COMPTES_OUVERTS``) et le resteront jusqu'à
    l'étape 13. Un moteur qui sonderait, importerait ``cryptography`` ou
    ouvrirait ``compte/`` au démarrage ferait payer à chaque lancement — et
    à chaque fermeture de l'app — une synchronisation que personne n'a. Ce
    veilleur ne fait rien : la tâche du lifespan attend son ``asyncio.Event``
    sans délai, et seul le service du compte, une fois une serrure ouverte,
    le déclenche (``ServiceCompte.sur_ouverture``).
    """

    def __init__(self, magasin) -> None:  # noqa: ANN001
        self.magasin = magasin
        self.service = None
        self.urgent = False
        self.reveils = 0
        self.tours = 0
        self._boucle: asyncio.AbstractEventLoop | None = None
        self._reveil: asyncio.Event | None = None

    def attacher(
        self, boucle: asyncio.AbstractEventLoop, reveil: asyncio.Event
    ) -> None:
        self._boucle, self._reveil = boucle, reveil

    def detacher(self) -> None:
        self._boucle = self._reveil = None

    def reveiller(self, *, urgent: bool = True) -> None:
        """Depuis n'importe quel fil. ``urgent`` : un geste (ouverture,
        consentement) — pas de calme à attendre, contrairement à une
        écriture du chat."""
        boucle, reveil = self._boucle, self._reveil
        if boucle is None or reveil is None:
            return
        self.reveils += 1
        if urgent:
            self.urgent = True
        try:
            boucle.call_soon_threadsafe(reveil.set)
        except RuntimeError:
            # La boucle est fermée : le serveur s'arrête, rien à réveiller.
            pass

    def arreter(self) -> None:
        moteur = getattr(self.service, "moteur", None)
        if moteur is not None:
            moteur.arreter()

    def compte_sur_le_disque(self) -> bool:
        """Le signe qu'un compte existe, sans rien importer : le fichier
        ``compte/etat.key`` à côté de la base des conversations — la règle
        même du magasin (``conversations_store._compte_present``), qui
        n'existe qu'avec un compte (``compte/etat.py``)."""
        chemin = getattr(self.magasin, "chemin", "")
        if not isinstance(chemin, str) or not chemin or chemin == ":memory:":
            return False
        return (pathlib.Path(chemin).parent / "compte" / "etat.key").is_file()


async def _synchroniser_le_compte(application: FastAPI) -> None:
    """La tâche du lifespan (compte-chiffre.md §4.3), ENDORMIE sans compte.

    Sans ``compte/etat.key`` : un seul ``await`` sur un événement que rien
    ne pose — aucune requête, aucun fil, aucun import du paquet ``compte``,
    et l'annulation à la fermeture la termine sur-le-champ. Le moteur
    (``diapason.compte.synchro``) n'est importé qu'au premier réveil.
    """
    veilleur: _VeilleurSynchro = application.state.synchro_compte
    reveil = asyncio.Event()
    veilleur.attacher(asyncio.get_running_loop(), reveil)
    try:
        # Un seul ``stat``, sur la boucle et non dans un fil : sans compte,
        # ``asyncio.to_thread`` aurait démarré l'exécuteur par défaut — un fil
        # qui existerait pour rien à chaque lancement.
        if veilleur.compte_sur_le_disque():
            # Un compte existe : construire le service rouvre l'AMK
            # mémorisée (§2.11, « au démarrage suivant, il relit lui-même
            # l'AMK »), et l'ouverture réveille le moteur. Sur le Mac de
            # Carlito, le serveur launchd synchronise ainsi même app fermée
            # (§4.10). Dans un fil : Argon2id n'y tourne pas, mais le
            # trousseau de session et SQLite bloquent.
            await asyncio.to_thread(_ouvrir_le_compte, application)
        await reveil.wait()
        veilleur.tours += 1
        from diapason.compte.synchro import servir

        await servir(veilleur, reveil)
    finally:
        veilleur.detacher()


def _ouvrir_le_compte(application: FastAPI) -> None:
    # Comptes fermés (§6 bis) : un ``etat.key`` hérité d'un banc ne fait
    # construire ni le service ni le moteur au démarrage (24/09/2026). Lu
    # ici, dans le fil, et seulement quand ce fichier existe : sans compte,
    # rien de ``diapason.compte`` n'est importé.
    from diapason.compte import service as module_service

    if not module_service.COMPTES_OUVERTS:
        return
    try:
        service = application.state.compte()
        service.etat  # noqa: B018 - la préparation rouvre l'AMK mémorisée
    except Exception:  # noqa: BLE001 - un compte illisible n'empêche pas de servir
        logger.exception("compte : ouverture au démarrage impossible")


def _service_compte(config, conversations_store):  # noqa: ANN001, ANN202
    """Le service du compte, relié au magasin des conversations.

    Le nombre de conversations (P3 : « Cet appareil a déjà 3
    conversations ») est lu par une connexion en LECTURE SEULE, à part :
    ``store.list()`` décode tous les messages de toutes les conversations,
    et ``/v1/account/status`` est sondé par chaque vue. Les conversations
    vierges (``messages = '[]'``) ne comptent pas, comme dans la liste du
    bundle (``discussions.ts:57``).
    """
    import sqlite3

    from diapason.compte.service import ServiceCompte

    chemin = getattr(conversations_store, "chemin", "")

    def compter() -> int:
        if not chemin or chemin == ":memory:":
            return 0
        # ``as_uri`` échappe les espaces (« Application Support ») qu'une
        # URI ``file:`` écrite à la main aurait laissés casser le chemin.
        uri = pathlib.Path(chemin).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=1.0)
        try:
            (nombre,) = conn.execute(
                "SELECT COUNT(*) FROM conversations "
                "WHERE deleted_at IS NULL AND messages != '[]'"
            ).fetchone()
        finally:
            conn.close()
        return int(nombre)

    return ServiceCompte(config=config, compter_conversations=compter)


def _service_synchronise(config, conversations_store, veilleur):  # noqa: ANN001, ANN202
    """Le service du compte, plus son moteur de synchronisation.

    Comptes FERMÉS (``COMPTES_OUVERTS``, §6 bis) : pas de moteur du tout —
    ``diapason.compte.synchro`` n'est pas importé, le statut dit
    ``disabled`` et ``sync-now`` ``syncUnavailable``. 24/09/2026 : le
    premier sondage de ``/v1/account/status`` par une vue importait le
    moteur et le construisait, alors que sa docstring jurait le contraire.

    Comptes ouverts, le service existe : ``cryptography`` est déjà chargé,
    et le moteur ne coûte plus qu'un objet. Il reste endormi tant que la
    serrure ne s'ouvre pas (``sur_ouverture``). Séparé de
    :func:`_service_compte`, que des tests remplacent par un service relié à
    leur serveur de comptes en mémoire : le moteur s'y branche pareil.
    """
    service = _service_compte(config, conversations_store)
    if not getattr(service, "comptes_ouverts", False):
        return service
    chemin = getattr(conversations_store, "chemin", "")
    if isinstance(chemin, str) and chemin and chemin != ":memory:":
        from diapason.compte.collections.conversations import (
            CollectionConversations,
        )
        from diapason.compte.synchro import MoteurSynchro

        service.moteur = MoteurSynchro(
            service, [CollectionConversations(conversations_store)]
        )
        service.sur_ouverture = veilleur.reveiller
        veilleur.service = service
    return service


async def _mesh_heartbeat(app: FastAPI) -> None:
    """Tell the paired devices, at a steady beat, that this machine is here.

    Without this the fleet only learns we exist when we happen to send
    something, so a laptop that is merely *on* looks offline — and every
    other device would then correctly refuse to send it anything.

    Deliberately quiet: a peer that cannot be reached is not an error worth
    logging every fifteen seconds, it is the normal state of a fleet whose
    devices come and go. The loop never raises, so a networking problem can
    never take the API server down with it.
    """
    from diapason.mesh.presence import HEARTBEAT_INTERVAL_MS

    interval = max(5.0, HEARTBEAT_INTERVAL_MS / 1000)
    while True:
        try:
            await asyncio.sleep(interval)
            from diapason.mesh.beacon import announce_to_fleet
            from diapason.mesh.dispatch import flush_pending

            await asyncio.to_thread(announce_to_fleet, app_state="foreground")
            # And drain whatever was waiting for a device that has come back.
            # Without this pass, « partira dès son retour » is a promise
            # nobody keeps: a command for a sleeping laptop stays queued
            # until it expires, and the user was told it would arrive.
            await asyncio.to_thread(flush_pending)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a beacon failure is never fatal
            logger.debug("battement mesh échoué", exc_info=True)


async def _prewarm_local_model(app: FastAPI) -> None:
    """Load Ollama's model in the background without delaying API startup."""
    config = getattr(app.state, "config", None)
    lightning = getattr(getattr(config, "desktop", None), "lightning", None)
    if lightning is not None and not lightning.preload_model:
        return
    # 20/09/2026 : l'ancien déballage ne suivait que ``_inner`` et s'arrêtait
    # sur le MultiEngine que fait naître un moteur cloud — aucun
    # /api/generate n'a jamais atteint Ollama au démarrage sur ce Mac.
    from diapason.server.prechauffage import moteur_local

    inner = moteur_local(app.state)
    if inner is None or not app.state.model:
        return
    keep_alive = str(getattr(inner, "_keep_alive", "30m") or "30m")
    try:
        prewarm = getattr(inner, "prewarm", None)
        if prewarm is None:
            return
        loaded = await asyncio.to_thread(prewarm, app.state.model)
        if loaded:
            logger.info(
                "Prewarmed local model %s (keep_alive=%s)",
                app.state.model,
                keep_alive,
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - warmup is an optimization only
        logger.debug("Local model prewarm skipped: %s", exc)


def _restore_sendblue_bindings(app: FastAPI) -> None:
    """Restore SendBlue channel bindings from the database on startup.

    If a SendBlue binding was created via the Messaging tab and the server
    restarts, this ensures the ChannelBridge + DeepResearchAgent are wired
    up so incoming webhooks continue to work.
    """
    try:
        mgr = getattr(app.state, "agent_manager", None)
        if mgr is None:
            return

        # Check all agents for sendblue bindings
        for agent in mgr.list_agents():
            agent_id = agent.get("id", agent.get("agent_id", ""))
            bindings = mgr.list_channel_bindings(agent_id)
            for b in bindings:
                if b.get("channel_type") != "sendblue":
                    continue
                config = b.get("config", {})
                api_key_id = config.get("api_key_id", "")
                api_secret_key = config.get("api_secret_key", "")
                from_number = config.get("from_number", "")
                if not api_key_id or not api_secret_key:
                    continue

                from diapason.channels.sendblue import SendBlueChannel

                sb = SendBlueChannel(
                    api_key_id=api_key_id,
                    api_secret_key=api_secret_key,
                    from_number=from_number,
                )
                sb.connect()
                app.state.sendblue_channel = sb

                # Create ChannelBridge if none exists
                bridge = getattr(app.state, "channel_bridge", None)
                if bridge and hasattr(bridge, "_channels"):
                    bridge._channels["sendblue"] = sb
                else:
                    from diapason.server.channel_bridge import ChannelBridge
                    from diapason.server.session_store import SessionStore

                    session_store = SessionStore()
                    engine = getattr(app.state, "engine", None)
                    dr_agent = None
                    if engine:
                        from diapason.server.agent_manager_routes import (
                            _build_deep_research_tools,
                        )

                        tools = _build_deep_research_tools(engine=engine, model="")
                        if tools:
                            from diapason.agents.deep_research import (
                                DeepResearchAgent,
                            )

                            model_name = getattr(app.state, "model", "") or getattr(
                                engine, "_model", ""
                            )
                            dr_agent = DeepResearchAgent(
                                engine=engine,
                                model=model_name,
                                tools=tools,
                            )

                    bus = getattr(app.state, "bus", None)
                    if bus is None:
                        from diapason.core.events import EventBus

                        bus = EventBus()

                    app.state.channel_bridge = ChannelBridge(
                        channels={"sendblue": sb},
                        session_store=session_store,
                        bus=bus,
                        agent_manager=mgr,
                        deep_research_agent=dr_agent,
                    )

                logger.info(
                    "Restored SendBlue channel binding: %s",
                    from_number,
                )
                return  # Only need one SendBlue binding
    except Exception as exc:
        logger.debug("SendBlue binding restore skipped: %s", exc)


# No-cache headers applied to static file responses
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


class _NoCacheStaticFiles(StaticFiles):
    """StaticFiles subclass that adds no-cache headers to every response."""

    async def __call__(self, scope, receive, send):
        async def _send_with_headers(message):
            if message["type"] == "http.response.start":
                extra = [(k.encode(), v.encode()) for k, v in _NO_CACHE_HEADERS.items()]
                # Remove etag and last-modified
                existing = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in (b"etag", b"last-modified")
                ]
                message = {**message, "headers": existing + extra}
            await send(message)

        await super().__call__(scope, receive, _send_with_headers)


def create_app(
    engine,
    model: str,
    *,
    agent=None,
    bus=None,
    engine_name: str = "",
    agent_name: str = "",
    channel_bridge=None,
    config=None,
    memory_backend=None,
    memory_service=None,
    speech_backend=None,
    agent_manager=None,
    agent_scheduler=None,
    api_key: str = "",
    webhook_config: dict | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    engine:
        The inference engine to use for completions.
    model:
        Default model name.
    agent:
        Optional agent instance for agent-mode completions.
    bus:
        Optional event bus for telemetry.
    channel_bridge:
        Optional channel bridge for multi-platform messaging.
    config:
        Optional DiapasonConfig for other settings.
    """

    @asynccontextmanager
    async def _lifespan(application: FastAPI):
        prewarm_task = asyncio.create_task(_prewarm_local_model(application))
        heartbeat_task = asyncio.create_task(_mesh_heartbeat(application))
        from diapason.mesh.discovery import run_discovery
        from diapason.server.prechauffage import entretenir_le_prefixe

        discovery_task = asyncio.create_task(run_discovery())
        # 20/09/2026 : le préfixe du chat (identité + trousse) coûte 24 s à
        # froid et meurt avec le runner d'Ollama après 30 min de silence ;
        # le rejouer toutes les dix minutes le garde chaud pour la question
        # qui suivra la pause. Voir server/prechauffage.py.
        prefixe_task = asyncio.create_task(entretenir_le_prefixe(application))
        # La synchronisation du compte (compte-chiffre.md §4.3) : endormie
        # tant qu'aucun compte n'est déverrouillé, voir _VeilleurSynchro.
        synchro_task = asyncio.create_task(_synchroniser_le_compte(application))
        application.state.tache_synchro = synchro_task
        try:
            yield
        finally:
            # Le cycle en cours rend la main au prochain lot plutôt que de
            # tenir la fermeture jusqu'au bout d'un envoi.
            application.state.synchro_compte.arreter()
            for task in (
                prewarm_task,
                heartbeat_task,
                discovery_task,
                prefixe_task,
                synchro_task,
            ):
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            bridge = getattr(application.state, "analytics_bridge", None)
            if bridge is not None:
                try:
                    bridge.stop()
                except Exception:
                    pass
            client = getattr(application.state, "analytics_client", None)
            if client is not None:
                try:
                    client.shutdown()
                except Exception:
                    pass
            service = getattr(application.state, "memory_service", None)
            if service is not None:
                try:
                    service.stop()
                except Exception:
                    pass
            conversations = getattr(application.state, "conversations_store", None)
            if conversations is not None:
                try:
                    conversations.close()
                except Exception:
                    pass
            compte = getattr(application.state, "compte", None)
            if compte is not None:
                try:
                    compte.fermer()
                except Exception:
                    pass

    app = FastAPI(
        title="Diapason API",
        description="OpenAI-compatible API server for Diapason",
        version="1.0.0",
        lifespan=_lifespan,
    )

    from fastapi.middleware.cors import CORSMiddleware

    _origins = (
        cors_origins
        if cors_origins is not None
        else [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            # Tauri 2 production webview origins:
            #   macOS / Linux / iOS  -> tauri://localhost
            #   Windows / Android    -> http://tauri.localhost (default),
            #                           https://tauri.localhost when
            #                           windows.useHttpsScheme is enabled
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store dependencies in app state
    app.state.engine = engine
    app.state.model = model
    app.state.agent = agent
    app.state.bus = bus
    app.state.engine_name = engine_name
    app.state.agent_name = agent_name or (
        getattr(agent, "agent_id", None) if agent else None
    )
    app.state.channel_bridge = channel_bridge
    app.state.config = config
    app.state.memory_backend = memory_backend
    app.state.memory_service = memory_service
    app.state.speech_backend = speech_backend
    app.state.agent_manager = agent_manager
    app.state.agent_scheduler = agent_scheduler
    from diapason.actions import LightningActionService

    app.state.lightning_actions = LightningActionService(config)
    app.state.session_start = time.time()
    # Exposed so WebSocket handlers can authenticate the handshake (the HTTP
    # AuthMiddleware never sees WS upgrade requests). Empty = auth disabled.
    app.state.api_key = api_key

    # Wire up trace store if traces are enabled.
    #
    # We deliberately do NOT subscribe the trace store to the bus. The chat
    # endpoints persist through a TraceCollector that calls store.save()
    # directly (mirroring system/orchestrator.py), and the collector ALSO
    # publishes TRACE_COMPLETE. A store subscribed to that same bus would
    # therefore save every agent trace twice — the second INSERT hitting the
    # UNIQUE constraint on trace_id (a 500 on every completion). Keeping the
    # collector the single writer is what makes the dual code path safe; only
    # the telemetry store is bus-subscribed (see system/builder.py).
    app.state.trace_store = None
    try:
        from diapason.core.config import load_config
        from diapason.traces.store import TraceStore

        cfg = config if config is not None else load_config()
        if cfg.traces.enabled:
            app.state.trace_store = TraceStore(db_path=cfg.traces.db_path)
    except Exception:
        pass  # traces are optional; don't block server startup

    # Wire up external analytics if enabled (PostHog) — never block startup.
    # Note: we do NOT fire app_opened here. The frontend owns that event
    # because "server started" (this code path) is not the same as "user
    # opened the app" — the server can run headless via cron, daemons,
    # or test suites.
    app.state.analytics_client = None
    app.state.analytics_bridge = None
    try:
        from diapason.analytics import (
            AnalyticsClient,
            EventBridge,
            is_analytics_enabled,
        )
        from diapason.core.config import load_config

        _cfg = config if config is not None else load_config()
        if is_analytics_enabled(_cfg.analytics):
            _client = AnalyticsClient(_cfg.analytics)
            app.state.analytics_client = _client
            _bus_ref = getattr(app.state, "bus", None)
            if _bus_ref is not None:
                _bridge = EventBridge(_bus_ref, _client)
                _bridge.start()
                app.state.analytics_bridge = _bridge

    except Exception as _exc:
        logger.debug("Analytics init skipped: %s", _exc)

    app.include_router(router)
    app.include_router(dashboard_router)
    app.include_router(comparison_router)
    app.include_router(create_connectors_router())
    app.include_router(create_digest_router())
    app.include_router(create_dictation_router())
    app.include_router(create_config_router())
    app.include_router(create_lecture_reglages_router())
    # Les conversations du chat. Sur l'app localhost UNIQUEMENT, jamais sur
    # la sous-app lan : ce sont des transcriptions privées. Avant ce magasin
    # (16 sept. 2026), l'historique vivait dans le localStorage du bundle,
    # cloisonné par origine — la fenêtre principale et le mini-panneau
    # montraient chacun le sien.
    conversations_store = ConversationsStore()
    app.state.conversations_store = conversations_store
    app.include_router(create_conversations_router(conversations_store))
    # Le compte chiffré (compte-chiffre.md §3.8), à côté des conversations et
    # derrière la même clé locale ; jamais sur la sous-app lan. Le service
    # n'est construit qu'à la première requête : ce constructeur tourne dans
    # chaque test du serveur, et aucun ne doit toucher compte/ ni le
    # trousseau sans l'avoir demandé.
    app.state.synchro_compte = _VeilleurSynchro(conversations_store)
    app.state.compte = AccesCompte(
        lambda: _service_synchronise(
            config, conversations_store, app.state.synchro_compte
        )
    )
    app.include_router(create_compte_router(app.state.compte))
    app.include_router(create_screen_share_router())
    app.include_router(create_trigger_router())
    app.include_router(upload_router)
    # 22/09/2026 : lire un document JOINT à un message, qui n'est pas
    # l'ingérer dans le corpus — « regarde ce PDF » et « ajoute ce PDF à
    # ta bibliothèque » sont deux gestes différents.
    from diapason.server.documents_routes import router as documents_router

    app.include_router(documents_router)
    app.include_router(research_router)
    app.include_router(analytics_router)
    include_all_routes(app)

    # Restore SendBlue channel bindings from database on startup
    _restore_sendblue_bindings(app)

    # Add security headers middleware
    try:
        from diapason.server.middleware import create_security_middleware

        middleware_cls = create_security_middleware()
        if middleware_cls is not None:
            app.add_middleware(middleware_cls)
    except Exception as exc:
        logger.debug("Security middleware init skipped: %s", exc)

    # API key authentication middleware
    if api_key:
        try:
            from diapason.server.auth_middleware import (
                AuthMiddleware,
                RateLimitMiddleware,
            )

            _rate = getattr(config, "security", None)
            if _rate is not None:
                app.add_middleware(
                    RateLimitMiddleware,
                    requests_per_minute=_rate.rate_limit_rpm,
                    burst_size=_rate.rate_limit_burst,
                    enabled=_rate.rate_limit_enabled,
                )

            app.add_middleware(AuthMiddleware, api_key=api_key)
        except Exception as exc:
            logger.debug("Auth middleware init skipped: %s", exc)

    # Mount webhook routes (always — SendBlue may be configured dynamically)
    if webhook_config:
        try:
            from diapason.server.webhook_routes import (
                create_webhook_router,
            )

            webhook_router = create_webhook_router(
                bridge=channel_bridge,
                twilio_auth_token=webhook_config.get("twilio_auth_token", ""),
                bluebubbles_password=webhook_config.get("bluebubbles_password", ""),
                whatsapp_verify_token=webhook_config.get("whatsapp_verify_token", ""),
                whatsapp_app_secret=webhook_config.get("whatsapp_app_secret", ""),
            )
            app.include_router(webhook_router)
        except Exception as exc:
            logger.debug("Webhook routes init skipped: %s", exc)

    # Serve static frontend assets if the static/ directory exists
    static_dir = pathlib.Path(__file__).parent / "static"
    if static_dir.is_dir():
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            app.mount(
                "/assets",
                _NoCacheStaticFiles(directory=assets_dir),
                name="static-assets",
            )

        @app.get("/{full_path:path}")
        async def spa_catch_all(full_path: str):
            """Serve static files directly, fall back to index.html for SPA routes."""
            if full_path:
                candidate = (static_dir / full_path).resolve()
                # Path traversal prevention
                resolved_root = static_dir.resolve()
                if candidate.is_relative_to(resolved_root) and candidate.is_file():
                    return FileResponse(candidate, headers=_NO_CACHE_HEADERS)
            return FileResponse(
                static_dir / "index.html",
                headers=_NO_CACHE_HEADERS,
            )

    return app


# Les NEUF portes qui ont le droit d'exister sur le réseau local.
#
# Exactement celles que `_requires_auth` exempte de la clé d'API — et ce
# n'est pas une coïncidence : une route exempte l'est parce qu'elle porte une
# créance PLUS FORTE que la clé (signature Ed25519 de l'appareil, invitation
# à usage unique, jeton de session). Ce sont donc les seules qu'un pair
# puisse honnêtement franchir, et les seules qui aient besoin du LAN.
#
# Les seize autres routes de `/v1/mesh` — émettre une invitation, envoyer une
# commande, révoquer un appareil, lister la flotte — sont le plan de contrôle
# de CE poste. Elles n'ont rien à faire sur un Wi-Fi.
_PORTES_LAN: frozenset[str] = frozenset(
    {
        "/v1/mesh/pairings/redeem",
        "/v1/mesh/commands/deliver",
        "/v1/mesh/commands/poll",
        "/v1/mesh/commands/ack",
        "/v1/mesh/presence",
        "/v1/mesh/files/offer",
        "/v1/mesh/files/{session_id}/chunk",
        "/v1/mesh/files/{session_id}/finish",
        "/v1/mesh/files/{session_id}/status",
    }
)


def create_lan_app() -> FastAPI:
    """L'application exposée au réseau local — et rien d'autre.

    **La garantie est structurelle, pas déclarative.** Un middleware qui
    filtrerait par chemin serait une quatrième liste à tenir à jour à côté de
    trois qui ont déjà dérivé (voir le commentaire de `auth_middleware` sur ce
    que deux listes désynchronisées ont coûté), et son mode de défaillance
    serait silencieux : un `startswith` trop large, et le rattrape-tout SPA
    rend cent quatre-vingt-cinq routes plus l'arborescence statique.

    Ici, `POST /v1/chat/completions` depuis le LAN ne rend pas 401 ni 403 : il
    rend **404**, parce que la route N'EXISTE PAS dans cette application. Le
    port ne sait pas ce qu'est le chat. Aucune liste ne peut se désynchroniser
    d'un handler qui n'est pas monté.

    Un seul PROCESSUS, deux sockets — impérativement. La boîte de réception
    (`mesh/executor.py`) et les sessions de transfert (`mesh/files_routes.py`)
    vivent dans des globales en mémoire : deux processus, et une commande
    reçue sur le LAN n'apparaîtrait jamais dans l'inbox lue en loopback, et un
    morceau rendrait 404 parce que l'offre a ouvert la session ailleurs.

    Pas de clé d'API ici, et c'est délibéré : les neuf routes s'authentifient
    par signature d'appareil, invitation ou jeton de session. Une clé partagée
    prouverait MOINS — elle ne dit ni quel appareil parle, ni ce qu'il prétend.
    """
    from diapason.mesh.files_routes import router as files_router
    from diapason.mesh.routes import router as mesh_router
    from diapason.server.auth_middleware import RateLimitMiddleware

    lan = FastAPI(
        title="Diapason — maillage",
        description="Les portes du maillage, et rien d'autre.",
        # Ni docs ni schéma : ce port n'a personne à renseigner, et une
        # énumération de routes est un cadeau fait au réseau.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # Le seau de débit vient AVEC les routes : hors du mur ne veut pas dire
    # hors du limiteur — c'est précisément la confusion que l'invariant
    # réciproque de tests/contract/ existe pour interdire.
    lan.add_middleware(RateLimitMiddleware)
    lan.include_router(mesh_router)
    lan.include_router(files_router)

    # Et on RETIRE tout ce qui n'est pas une porte. Monter puis retrancher
    # plutôt que de découper les routeurs : les deux routeurs restent une
    # seule vérité, et l'écart entre ce qui est monté ici et ce que le mur
    # exempte devient une comparaison d'ensembles qu'un test lit d'un coup.
    #
    # Le filtre porte sur le CHEMIN seul. Il a porté un temps sur le chemin
    # « ou l'absence de méthodes HTTP », et cette seconde moitié gardait
    # silencieusement tout ce qui n'est pas une route REST : un
    # `@router.websocket(...)` ajouté à `mesh/routes.py` par une session
    # future se serait retrouvé exposé sur 0.0.0.0 — hors du mur (il n'y a
    # pas d'AuthMiddleware ici) et hors du seau de débit (une poignée de main
    # WebSocket ne traverse pas un BaseHTTPMiddleware). Elle ne gardait rien
    # d'autre : les dix portes sont dix APIRoute. Une clause qui ne sert
    # qu'aux cas qu'on n'a pas prévus n'est pas une commodité, c'est une
    # porte dérobée en attente.
    lan.router.routes = [
        route
        for route in lan.router.routes
        if getattr(route, "path", None) in _PORTES_LAN
    ]
    return lan


__all__ = ["create_app", "create_lan_app"]
