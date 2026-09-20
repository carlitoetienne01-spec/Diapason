"""``diapason serve`` — OpenAI-compatible API server."""

from __future__ import annotations

import logging
import sys
import time
from typing import Callable

import click
from rich.console import Console

from diapason.cli._banner import print_banner
from diapason.core import ports
from diapason.core.config import load_config
from diapason.core.credentials import inject_credentials
from diapason.core.events import EventBus
from diapason.core.paths import get_config_dir
from diapason.engine import (
    discover_engines,
    discover_models,
    get_engine,
)
from diapason.intelligence import (
    merge_discovered_models,
    register_builtin_models,
)

logger = logging.getLogger(__name__)

# Le rythme du sondage pendant qu'un autre tient le port. Dix secondes, c'est
# le ThrottleInterval de launchd — le rythme même de la boucle qu'on remplace.
# Cinq bornent à cinq secondes le trou sans serveur après que l'app de bureau
# a quitté et rendu le port ; un `lsof` toutes les cinq secondes ne se mesure
# pas. Une seconde ferait douze fois plus de `lsof` pour un gain que personne
# ne remarquerait.
_ATTENTE_PORT_S = 5.0

# Délai de la sonde /health quand le port est tenu. Deux secondes suffisent à
# un serveur local qui répond ; un serveur qui met plus longtemps est traité
# comme « pas un Diapason sain », ce qui ne change que le message.
_SONDE_S = 2.0

DIAPASON_SAIN = "sain"
DIAPASON_CHARGE = "charge"


def sonder_diapason(host: str, port: int) -> str | None:
    """Qui répond sur ``/health`` : un Diapason sain, un qui charge, ou rien.

    ``DIAPASON_SAIN`` pour ``200 {"status": "ok"}``, ``DIAPASON_CHARGE`` pour
    un 503 (le moteur n'est pas prêt), ``None`` pour tout le reste — refus de
    connexion, délai dépassé, autre statut, corps qui n'est pas le nôtre.
    """
    import json
    import urllib.error
    import urllib.request

    # Une adresse d'écoute joker ne se sonde pas ; le loopback y répond.
    hote = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host  # noqa: S104
    try:
        with urllib.request.urlopen(  # noqa: S310 - hôte local, schéma http
            f"http://{hote}:{port}/health", timeout=_SONDE_S
        ) as reponse:
            if reponse.status != 200:
                return None
            corps = json.loads(reponse.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as erreur:
        return DIAPASON_CHARGE if erreur.code == 503 else None
    except (OSError, ValueError):
        return None
    if isinstance(corps, dict) and corps.get("status") == "ok":
        return DIAPASON_SAIN
    return None


def attendre_le_port(
    host: str,
    port: int,
    *,
    console: Console,
    etat_du_port: Callable[[int], tuple[str, str]] = ports.port_state,
    sonder: Callable[[str, int], str | None] = sonder_diapason,
    dormir: Callable[[float], None] = time.sleep,
) -> int:
    """Attendre que ``port`` soit libre AVANT de charger quoi que ce soit.

    Rend le nombre de sondages effectués — zéro quand le port était libre.

    Du 26 août au 20 septembre 2026, ce contrôle n'existait pas : `serve`
    chargeait moteur, mémoire et voix, puis mourait au bind (uvicorn sort 3
    sur EADDRINUSE) ; launchd (`KeepAlive.SuccessfulExit=false`, dix
    secondes de ThrottleInterval) le relançait, et ainsi de suite tant que
    l'autre tenait le port. serve.err.log en portait 837 cycles (1 674
    « Errno 48 », deux par cycle) sur 465 Mo, contre 67 démarrages réussis —
    et pendant chaque cycle le second socket, celui du maillage, n'existait
    pas. L'autre, c'était un `serve` sans `--lan-host` : celui que l'app de
    bureau lance quand sa sonde arrive avant notre bind, ou un terminal.

    Attendre plutôt que mourir garde UN processus sous launchd, aucune
    relance, une ligne de journal, et le maillage revient cinq secondes après
    que l'autre a quitté. Même politique que `diapason start` : tout auditeur
    sur le port compte, quelle que soit son adresse — deux serveurs sur un
    même port à des adresses différentes cohabitent sur macOS, et l'un des
    deux devient un zombie muet.
    """
    etat, detail = etat_du_port(port)
    if etat != ports.OCCUPE:
        # LIBRE, ou INCONNU : dans l'ignorance, le bind d'uvicorn reste
        # l'arbitre — refuser de démarrer sur une ignorance ferait boucler
        # launchd tout autant.
        if etat == ports.INCONNU:
            logger.debug(
                "port %s : état inconnu (%s), on laisse uvicorn trancher",
                port,
                detail,
            )
        return 0

    verdict = sonder(host, port)
    if verdict == DIAPASON_SAIN:
        qui = "un autre Diapason, qui répond"
    elif verdict == DIAPASON_CHARGE:
        qui = "un autre Diapason, dont le moteur charge encore"
    else:
        qui = "un processus qui n'est pas un Diapason"
    console.print(
        f"[yellow]Le port {port} est déjà tenu par {qui}[/yellow] ({detail}).\n"
        f"  On attend qu'il le rende, sondage toutes les {_ATTENTE_PORT_S:.0f} s, "
        "plutôt que mourir et être relancé par launchd toutes les dix secondes.\n"
        "  Pour l'arrêter : fermer l'app de bureau, Ctrl-C dans son terminal, "
        "ou diapason stop s'il vient de diapason start.\n"
        f"  Pour l'identifier : lsof -nP -iTCP:{port} -sTCP:LISTEN"
    )
    tours = 0
    while etat == ports.OCCUPE:
        dormir(_ATTENTE_PORT_S)
        tours += 1
        etat, detail = etat_du_port(port)
    console.print(
        f"[green]Le port {port} est libre[/green] après "
        f"{tours * _ATTENTE_PORT_S:.0f} s d'attente — démarrage."
    )
    return tours


def _unique_model_ids(model_ids: list[str]) -> list[str]:
    """Return model ids in first-seen order without duplicates."""
    unique: list[str] = []
    seen: set[str] = set()
    for model_id in model_ids:
        if model_id and model_id not in seen:
            seen.add(model_id)
            unique.append(model_id)
    return unique


def _safe_list_models(engine: object) -> list[str]:
    try:
        list_models = getattr(engine, "list_models")
        return list(list_models())
    except Exception as exc:
        logger.debug("Failed to list models for selected server engine: %s", exc)
        return []


def _resolve_server_model(
    requested_model: str | None,
    *,
    config: object,
    engine_name: str,
    engine: object,
    all_models: dict[str, list[str]],
) -> str:
    """Pick a startup model that is present on the active server engine.

    CLI ``--model`` remains authoritative. For config-driven startup, prefer the
    configured server/default model only when the active engine can actually
    serve it; otherwise use ``intelligence.fallback_model`` or the first
    reachable model. This prevents MLX-preferred configs from hiding a healthy
    Ollama fallback behind an empty/incorrect model map.
    """
    if requested_model:
        return requested_model

    candidates = [
        getattr(config.server, "model", ""),
        getattr(config.intelligence, "default_model", ""),
        getattr(config.intelligence, "fallback_model", ""),
    ]
    available = _unique_model_ids(
        _safe_list_models(engine) + list(all_models.get(engine_name, []))
    )

    for candidate in candidates:
        if candidate and (not available or candidate in available):
            return candidate

    return available[0] if available else ""


def _announce_exposure(bind_host: str, bind_port: int) -> None:
    """Say out loud what a non-loopback bind makes reachable, and by whom.

    Leaving the loopback is the one configuration change that turns a purely
    personal server into something anything on the same network can knock on.
    It is a legitimate choice — a phone cannot reach a mesh that only answers
    itself — but it must never be a silent one: the difference between « chez
    moi » and « sur le wifi du café » is the whole security model.

    Not a warning to dismiss. A statement of what is now true.
    """
    import ipaddress

    try:
        loopback = ipaddress.ip_address(bind_host).is_loopback
    except ValueError:
        loopback = bind_host in ("localhost", "")
    if loopback:
        return

    from diapason.mesh.beacon import local_address

    reachable = local_address()
    # stderr, comme le reste des messages de démarrage : ce canal survit à une
    # sortie redirigée vers un fichier de journal.
    Console(stderr=True).print(
        "\n[yellow]Ce serveur écoute au-delà de cette machine.[/yellow]\n"
        f"  Joignable à : [cyan]{reachable}[/cyan] par tout ce qui partage ce réseau.\n"
        "  Protégé par : la clé d'API locale sur toute l'API, et une signature\n"
        "                Ed25519 sur les cinq routes du maillage qui n'en ont pas.\n"
        "  À savoir    : sur un réseau que vous ne contrôlez pas — café, hôtel,\n"
        "                bureau partagé — revenez à 127.0.0.1.\n"
    )


def _servir_deux_sockets(
    app: object,
    host: str,
    port: int,
    lan_app: object,
    lan_host: str,
    lan_port: int,
    arret: object | None = None,
) -> None:
    """Deux sockets, UN SEUL PROCESSUS — et ce n'est pas un détail.

    La boîte de réception des commandes (`mesh/executor.py`) et les sessions
    de transfert (`mesh/files_routes.py`) vivent dans des globales en
    mémoire. Deux processus, et une commande reçue sur le réseau
    n'apparaîtrait jamais dans l'inbox lue en loopback ; un morceau de
    fichier rendrait 404 parce que son offre a ouvert la session ailleurs.
    """
    import asyncio

    import uvicorn

    async def _les_deux() -> None:
        principal = uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level="info")
        )
        reseau = uvicorn.Server(
            uvicorn.Config(lan_app, host=lan_host, port=lan_port, log_level="info")
        )
        if arret is None:
            await asyncio.gather(principal.serve(), reseau.serve())
            return
        # Le banc à deux sockets survivait à pytest : les serveurs étaient
        # enfermés ici, donc le test ne pouvait poser `should_exit` sur aucun
        # des deux. L'événement est injecté uniquement pour rendre leur cycle
        # de vie observable ; le service de production garde le même chemin.
        principal_task = asyncio.create_task(principal.serve())
        reseau_task = asyncio.create_task(reseau.serve())
        await asyncio.to_thread(arret.wait)
        principal.should_exit = True
        reseau.should_exit = True
        await asyncio.gather(principal_task, reseau_task)

    asyncio.run(_les_deux())


@click.command()
@click.option("--host", default=None, help="Bind address (default: config).")
@click.option(
    "--port",
    default=None,
    type=int,
    help="Port number (default: config).",
)
@click.option(
    "--lan-host",
    default=None,
    help=(
        "Adresse d'écoute du MAILLAGE seul, sur un second socket "
        "(ex. 0.0.0.0). Dix routes y sont exposées, pas une de plus : "
        "le chat, la voix et Succès restent sur --host."
    ),
)
@click.option(
    "--lan-port",
    default=8001,
    type=int,
    help="Port du second socket. Doit différer de --port.",
)
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Default model.")
@click.option(
    "-a",
    "--agent",
    "agent_name",
    default=None,
    help="Agent for non-streaming requests (simple, orchestrator, react, openhands).",
)
@click.pass_context
def serve(
    ctx: click.Context,
    host: str | None,
    port: int | None,
    lan_host: str | None,
    lan_port: int,
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
) -> None:
    """Start the OpenAI-compatible API server."""
    print_banner(quiet=(ctx.obj or {}).get("quiet", False))
    console = Console(stderr=True)

    # Check for server dependencies
    try:
        import uvicorn  # noqa: F401
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        console.print(
            "[red bold]Server dependencies not installed.[/red bold]\n\n"
            "Install the server extra:\n"
            "  [cyan]uv sync --extra server[/cyan]"
        )
        sys.exit(1)

    # Tool credentials saved through the browser UI live in the Diapason
    # credential store. Restore them before engines and tools are constructed
    # so availability checks and tool instances see the same environment.
    inject_credentials()

    config = load_config()

    # Resolve host/port from CLI args or config
    bind_host = host or config.server.host
    bind_port = port or config.server.port

    # Un argument impossible se refuse ici : les valeurs sont résolues (le
    # port peut venir de la configuration, pas seulement de la ligne de
    # commande) et rien n'a encore démarré. Ce contrôle vivait six cents
    # lignes plus bas, APRÈS la recherche d'un moteur d'inférence : sur une
    # machine sans moteur il n'était jamais atteint, et le test censé le
    # garder passait sur un tout autre échec — constaté le 26 août 2026.
    # Une erreur d'usage n'a pas besoin d'Ollama pour être une erreur.
    if lan_host and lan_port == bind_port:
        # macOS lie les deux sans broncher (SO_REUSEADDR), Linux refuse, et
        # la vérification de port unique du dépôt verrait deux auditeurs.
        console.print(
            "[red]--lan-port doit différer de --port : deux serveurs sur le "
            "même port se lient en silence sur macOS et échouent sur "
            "Linux.[/red]"
        )
        raise SystemExit(2)

    # AVANT le moteur, la mémoire et la voix : un port tenu se constate en
    # cinquante millisecondes de `lsof`, pas après trente secondes de
    # chargement. Voir la docstring d'attendre_le_port pour les 837 cycles.
    attendre_le_port(bind_host, bind_port, console=console)

    # Set up engine
    register_builtin_models()
    bus = EventBus(record_history=False)

    # Set up telemetry
    telem_store = None
    if config.telemetry.enabled:
        try:
            from pathlib import Path

            from diapason.telemetry.store import TelemetryStore

            db_path = Path(config.telemetry.db_path).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            telem_store = TelemetryStore(str(db_path))
            telem_store.subscribe_to_bus(bus)
        except Exception as exc:
            logger.debug("Telemetry store init failed: %s", exc)

    # Select with the model we'll actually serve so an engine that can't
    # serve it (e.g. the cloud fallback without the matching provider key) is
    # skipped rather than chosen and failing per-request later (see #532).
    selection_model = (
        model_name or config.server.model or config.intelligence.default_model or None
    )
    resolved = get_engine(config, engine_key, model=selection_model)
    if resolved is None:
        console.print(
            "[red bold]No inference engine available.[/red bold]\n\n"
            "Make sure an engine is running."
        )
        sys.exit(1)

    engine_name, engine = resolved

    # Apply security guardrails
    from diapason.security import setup_security

    sec = setup_security(config, engine, bus)
    engine = sec.engine

    # If cloud API keys are set, prepare a cloud engine. We build the
    # MultiEngine after local discovery so healthy local fallbacks such as
    # Ollama stay visible even when the configured preferred engine is MLX.
    import os

    cloud_engine = None
    _has_cloud = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
    )
    if _has_cloud and engine_name != "cloud":
        try:
            from diapason.engine.cloud import CloudEngine

            cloud_engine = CloudEngine()
            if cloud_engine.health():
                console.print("  Cloud:  [cyan]enabled[/cyan] (API keys detected)")
            else:
                console.print(
                    "  Cloud:  [yellow]keys set but packages missing[/yellow] "
                    "(run: uv sync --extra inference-cloud --extra inference-google)"
                )
        except Exception as exc:
            logger.debug("Cloud engine init failed: %s", exc)

    # Wrap engine with InstrumentedEngine for telemetry recording
    try:
        from diapason.telemetry.instrumented_engine import InstrumentedEngine

        energy_mon = None
        try:
            from diapason.telemetry.energy_monitor import create_energy_monitor

            energy_mon = create_energy_monitor()
            if energy_mon is not None:
                console.print(
                    f"  Energy: [cyan]{energy_mon.vendor().value}[/cyan] "
                    f"({energy_mon.energy_method()})"
                )
        except Exception as exc:
            logger.debug("Energy monitor creation failed: %s", exc)

        engine = InstrumentedEngine(engine, bus, energy_monitor=energy_mon)
    except Exception as exc:
        logger.debug("Engine instrumentation failed: %s", exc)

    # Discover models
    all_engines = discover_engines(config)
    all_models = discover_models(all_engines)
    for ek, model_ids in all_models.items():
        merge_discovered_models(ek, model_ids)

    multi_entries = [(engine_name, engine)]
    for discovered_name, discovered_engine in all_engines:
        if discovered_name != engine_name:
            multi_entries.append((discovered_name, discovered_engine))
    if cloud_engine is not None:
        multi_entries.append(("cloud", cloud_engine))

    if len(multi_entries) > 1:
        from diapason.engine.multi import MultiEngine

        engine = MultiEngine(multi_entries)
        engine_name = "multi"
        all_models[engine_name] = engine.list_models()
        merge_discovered_models(engine_name, all_models[engine_name])

    # Resolve model
    configured_model = (
        model_name or config.server.model or config.intelligence.default_model
    )
    model_name = _resolve_server_model(
        model_name,
        config=config,
        engine_name=engine_name,
        engine=engine,
        all_models=all_models,
    )
    if configured_model and model_name and model_name != configured_model:
        console.print(
            "[yellow]Configured model "
            f"{configured_model!r} is not reachable; using {model_name!r}.[/yellow]"
        )
    if not model_name:
        console.print(
            "[red]No model available on any reachable engine.[/red]\n\n"
            "Start an inference backend and make sure it lists at least one model.\n"
            "For Ollama: [cyan]ollama serve[/cyan] and "
            "[cyan]ollama pull qwen3.5:9b[/cyan].\n"
            "For MLX: start the MLX OpenAI-compatible server on the configured host."
        )
        sys.exit(1)

    # Resolve agent
    agent = None
    agent_key = agent_name or config.server.agent
    # Tool instances resolved for the primary agent are reused below to build
    # the scheduler's ToolExecutor — avoiding a second full SystemBuilder.build()
    # (which would re-discover the engine, re-resolve tools, re-open the channel,
    # etc.). See the scheduler block near the bottom of this function (#263).
    resolved_tools: list = []
    if agent_key:
        try:
            import diapason.agents  # noqa: F401
            from diapason.core.registry import AgentRegistry

            if AgentRegistry.contains(agent_key):
                agent_cls = AgentRegistry.get(agent_key)
                agent_kwargs = {"bus": bus}
                if sec.capability_policy is not None:
                    agent_kwargs["capability_policy"] = sec.capability_policy
                agent_kwargs["boundary_guard"] = sec.boundary_guard
                agent_kwargs["rate_limiter"] = sec.rate_limiter

                # MCP transports persisted on the agent at the bottom of
                # this block — initialise here so the reference is valid
                # even when accepts_tools is False (#461).
                mcp_clients: list = []

                # Load tools for agents that support them
                if getattr(agent_cls, "accepts_tools", False):
                    import diapason.tools  # noqa: F401  # trigger registration
                    from diapason.core.registry import ToolRegistry
                    from diapason.tools._stubs import BaseTool

                    _DEFAULT_TOOLS = {"think", "calculator", "web_search"}
                    configured = config.agent.tools
                    if configured:
                        if isinstance(configured, list):
                            allowed = {
                                t.strip()
                                for t in configured
                                if isinstance(t, str) and t.strip()
                            }
                        else:
                            allowed = {
                                t.strip() for t in configured.split(",") if t.strip()
                            }
                    else:
                        allowed = _DEFAULT_TOOLS

                    tools = []
                    for name in ToolRegistry.keys():
                        if name not in allowed:
                            continue
                        tool_cls = ToolRegistry.get(name)
                        if isinstance(tool_cls, type) and issubclass(
                            tool_cls, BaseTool
                        ):
                            tools.append(tool_cls())
                        elif isinstance(tool_cls, BaseTool):
                            tools.append(tool_cls)

                    # MCP server tools from config.tools.mcp.servers
                    # (#461 — these were silently dropped).
                    from diapason.mcp.loader import load_mcp_tools_from_config

                    mcp_tools, mcp_clients = load_mcp_tools_from_config(
                        config.tools.mcp,
                        allowed_names=allowed if configured else None,
                    )
                    if mcp_tools:
                        existing = {t.spec.name for t in tools}
                        for t in mcp_tools:
                            if t.spec.name not in existing:
                                tools.append(t)
                                existing.add(t.spec.name)

                    if tools:
                        agent_kwargs["tools"] = tools
                    # Reuse these for the scheduler's ToolExecutor (#263).
                    resolved_tools = tools

                if getattr(agent_cls, "accepts_tools", False):
                    agent_kwargs["max_turns"] = config.agent.max_turns

                # SOUL.md / MEMORY.md / USER.md ground this agent too. The
                # persistent-agent path gained this in #376, but the server's
                # default agent kept a memory-less prompt — the same question
                # then knew the user's name over the streaming path and denied
                # it over the agent path, from the same process.
                import inspect

                try:
                    accepted = set(inspect.signature(agent_cls.__init__).parameters)
                except (TypeError, ValueError):
                    accepted = set()
                if "confirm_callback" in accepted:
                    from diapason.server.approval_bridge import (
                        tool_confirm_callback,
                    )

                    # Without this, requires_confirmation tools failed with
                    # "no confirmation callback is available" on the server
                    # chat path — neither auto nor ask, just broken.
                    agent_kwargs["interactive"] = True
                    agent_kwargs["confirm_callback"] = tool_confirm_callback()
                if "prompt_builder" in accepted:
                    from diapason.prompt.builder import SystemPromptBuilder

                    agent_kwargs["prompt_builder"] = SystemPromptBuilder(
                        agent_template=config.agent.default_system_prompt or "",
                        memory_files_config=config.memory_files,
                        system_prompt_config=config.system_prompt,
                    )

                _accepts_kwargs = any(
                    p.kind is inspect.Parameter.VAR_KEYWORD
                    for p in inspect.signature(agent_cls.__init__).parameters.values()
                )
                if accepted and not _accepts_kwargs:
                    agent_kwargs = {
                        key: value
                        for key, value in agent_kwargs.items()
                        if key in accepted
                    }

                agent = agent_cls(engine, model_name, **agent_kwargs)
                # Pin MCP transports to the agent's lifetime so HTTP
                # connections don't close mid-request (#461).
                if mcp_clients:
                    agent._mcp_clients = mcp_clients
        except Exception as exc:
            import traceback

            console.print(f"[yellow]Agent '{agent_key}' failed to load: {exc}[/yellow]")
            traceback.print_exc()

    # Set up channel backend if enabled
    channel_bridge = None
    if config.channel.enabled and config.channel.default_channel:
        try:
            from diapason.system import SystemBuilder

            # Reuse _resolve_channel logic from SystemBuilder
            sb = SystemBuilder(config)
            sb._bus = bus
            channel_bridge = sb._resolve_channel(config, bus)
            if channel_bridge is not None:
                channel_bridge.connect()
                console.print(
                    f"  Channel: [cyan]{config.channel.default_channel}[/cyan]"
                )
        except Exception as exc:
            console.print(f"[yellow]Channel failed to start: {exc}[/yellow]")
            channel_bridge = None

    # Wire channel messages → agent / engine (per-chat session isolation)
    if channel_bridge is not None:
        from diapason.system import DiapasonSystem

        channel_agent = config.channel.default_agent or agent_key or "simple"

        _channel_tools: list = []
        # MCP transports persisted at function scope (= server-process
        # lifetime); see the comment near the channel-MCP-load block
        # below. Initialise here so it's always bound. #461.
        _channel_mcp_clients: list = []
        if channel_agent:
            try:
                import diapason.agents
                from diapason.core.registry import AgentRegistry

                if AgentRegistry.contains(channel_agent):
                    _ch_cls = AgentRegistry.get(channel_agent)
                    if getattr(_ch_cls, "accepts_tools", False):
                        import diapason.tools
                        from diapason.core.registry import ToolRegistry
                        from diapason.tools._stubs import BaseTool

                        _DEFAULT_TOOLS = {"think", "calculator", "web_search"}
                        configured = config.agent.tools
                        if configured:
                            if isinstance(configured, list):
                                _allowed = {
                                    t.strip()
                                    for t in configured
                                    if isinstance(t, str) and t.strip()
                                }
                            else:
                                _allowed = {
                                    t.strip()
                                    for t in configured.split(",")
                                    if t.strip()
                                }
                        else:
                            _allowed = _DEFAULT_TOOLS

                        for _tname in ToolRegistry.keys():
                            if _tname not in _allowed:
                                continue
                            _tcls = ToolRegistry.get(_tname)
                            if isinstance(_tcls, type) and issubclass(_tcls, BaseTool):
                                _channel_tools.append(_tcls())
                            elif isinstance(_tcls, BaseTool):
                                _channel_tools.append(_tcls)

                        # MCP tools for the channel agent too (#461).
                        from diapason.mcp.loader import (
                            load_mcp_tools_from_config,
                        )

                        _ch_mcp_tools, _ch_mcp_clients = load_mcp_tools_from_config(
                            config.tools.mcp,
                            allowed_names=_allowed if configured else None,
                        )
                        if _ch_mcp_tools:
                            _existing = {t.spec.name for t in _channel_tools}
                            for t in _ch_mcp_tools:
                                if t.spec.name not in _existing:
                                    _channel_tools.append(t)
                                    _existing.add(t.spec.name)
                        # Hold a reference at module / function scope —
                        # the channel agent is constructed inside
                        # DiapasonSystem below; we extend its lifetime by
                        # keeping the list bound here.
                        _channel_mcp_clients = _ch_mcp_clients
            except Exception as exc:
                logger.warning("Channel tools failed to load: %s", exc)
                _channel_mcp_clients = []

        _wire_system = DiapasonSystem(
            config=config,
            bus=bus,
            engine=engine,
            engine_key=engine_name,
            model=model_name,
            agent_name=channel_agent,
            tools=_channel_tools,
            capability_policy=sec.capability_policy,
            boundary_guard=sec.boundary_guard,
            rate_limiter=sec.rate_limiter,
        )
        _wire_system.wire_channel(channel_bridge)

    # Set up speech backend
    speech_backend = None
    try:
        from diapason.speech._discovery import get_speech_backend

        speech_backend = get_speech_backend(config)
        if speech_backend:
            console.print(f"  Speech: [cyan]{speech_backend.backend_id}[/cyan]")
    except Exception as exc:
        logger.debug("Speech backend discovery failed: %s", exc)

    # Create app
    from diapason.server.app import create_app

    # Set up memory backend for context injection. Built before the scheduler
    # block so the executor's DiapasonSystem can reference it (#263).
    memory_backend = None
    if config.agent.context_from_memory:
        try:
            import diapason.tools.storage  # noqa: F401
            from diapason.core.registry import MemoryRegistry

            mem_key = config.memory.default_backend
            if MemoryRegistry.contains(mem_key):
                memory_backend = MemoryRegistry.create(
                    mem_key,
                    db_path=config.memory.db_path,
                )
                console.print("  Memory:    [cyan]active[/cyan]")
        except Exception as exc:
            logger.debug("Memory backend init failed: %s", exc)

    # Automatic long-term memory service (background fact extraction).
    memory_service = None
    try:
        from diapason.memory import build_memory_service

        memory_service = build_memory_service(
            config,
            engine,
            model_name,
            event_bus=bus,
            # Le magasin que l'injection de contexte RELIT. Sans lui, les
            # faits extraits partaient dans un journal que personne
            # n'interroge.
            memory_backend=memory_backend,
        )
        if memory_service is not None:
            memory_service.start()
            console.print("  Memory svc: [cyan]active[/cyan]")
    except Exception as exc:
        logger.debug("Memory service init failed: %s", exc)
        memory_service = None

    # Set up agent manager
    agent_manager = None
    if config.agent_manager.enabled:
        try:
            from diapason.agents.manager import AgentManager

            am_db = config.agent_manager.db_path or str(get_config_dir() / "agents.db")
            # The server owns the scheduler and is the authoritative tick
            # runner — on boot it holds no locks, so it (and only it) sweeps
            # any zombie running→idle left by a previous crash.
            agent_manager = AgentManager(db_path=am_db, clear_stale_running=True)
        except Exception as exc:
            logger.debug("Agent manager init failed: %s", exc)

    # Set up agent scheduler for cron/interval agents
    agent_scheduler = None
    if agent_manager is not None:
        try:
            from diapason.agents.executor import AgentExecutor
            from diapason.agents.scheduler import AgentScheduler

            _trace_store = None
            try:
                if config.traces.enabled:
                    from diapason.traces.store import TraceStore

                    _trace_store = TraceStore(db_path=config.traces.db_path)
            except Exception:
                pass

            executor = AgentExecutor(
                manager=agent_manager,
                event_bus=bus,
                trace_store=_trace_store,
            )
            # Reuse the components already built inline above instead of a
            # second full SystemBuilder.build() — the original double-build
            # re-discovered the engine, re-instrumented it, re-resolved tools,
            # re-opened the channel and re-created the agent manager, costing
            # ~30-40s on top of an already-paid startup (#263). The executor
            # only reads engine/model/config/memory_backend/tool_executor/
            # session_store/channel_backend from the system (see
            # AgentExecutor), all of which are wired here.
            from diapason.sessions.session import SessionStore
            from diapason.system import DiapasonSystem
            from diapason.tools._stubs import ToolExecutor

            _sched_session_store = None
            if config.sessions.enabled:
                try:
                    from pathlib import Path as _SchedPath

                    _sched_session_store = SessionStore(
                        db_path=_SchedPath(config.sessions.db_path).expanduser(),
                        max_age_hours=config.sessions.max_age_hours,
                        consolidation_threshold=(
                            config.sessions.consolidation_threshold
                        ),
                    )
                except Exception as exc:
                    logger.debug("Scheduler session store init failed: %s", exc)

            _sched_tool_executor = (
                ToolExecutor(
                    resolved_tools,
                    bus,
                    capability_policy=sec.capability_policy,
                    boundary_guard=sec.boundary_guard,
                    rate_limiter=sec.rate_limiter,
                )
                if resolved_tools
                else None
            )

            system = DiapasonSystem(
                config=config,
                bus=bus,
                engine=engine,
                engine_key=engine_name,
                model=model_name,
                agent=agent,
                agent_name=agent_key or "",
                tools=resolved_tools,
                tool_executor=_sched_tool_executor,
                memory_backend=memory_backend,
                telemetry_store=telem_store,
                trace_store=_trace_store,
                session_store=_sched_session_store,
                capability_policy=sec.capability_policy,
                boundary_guard=sec.boundary_guard,
                rate_limiter=sec.rate_limiter,
                agent_manager=agent_manager,
                agent_executor=executor,
            )
            executor.set_system(system)

            agent_scheduler = AgentScheduler(
                manager=agent_manager,
                executor=executor,
                event_bus=bus,
            )
            for ag in agent_manager.list_agents():
                sched_type = ag.get("config", {}).get("schedule_type", "manual")
                if sched_type in ("cron", "interval") and ag["status"] not in (
                    "archived",
                    "error",
                ):
                    agent_scheduler.register_agent(ag["id"])
            agent_scheduler.start()
            console.print("  Scheduler: [cyan]active[/cyan]")
        except Exception as exc:
            logger.debug("Agent scheduler init failed: %s", exc)

    # --- Channel Gateway: API key, sessions, ChannelBridge ---
    import os as _os

    from diapason.core.env import get as _env_get

    api_key = _env_get("API_KEY") or ""
    if not api_key:
        try:
            import tomllib

            _cfg_path = str(get_config_dir() / "config.toml")
            with open(_cfg_path, "rb") as _f:
                _raw = tomllib.load(_f)
            api_key = _raw.get("server", {}).get("auth", {}).get("api_key", "")
        except (FileNotFoundError, ImportError):
            pass

    from diapason.server.auth_middleware import ensure_local_api_key

    api_key, generated_key_path = ensure_local_api_key(api_key)
    if generated_key_path is not None:
        logger.info("Local API authentication enabled using %s", generated_key_path)

    from diapason.server.auth_middleware import check_bind_safety, check_cors_safety

    check_bind_safety(bind_host, api_key=api_key)
    check_cors_safety(bind_host, config.server.cors_origins)

    # Enregistré ICI, et pas juste avant uvicorn.run : le maillage annonce
    # cette adresse aux appareils appairés, et l'avis ci-dessous la donne à
    # l'utilisateur pour qu'il la recopie sur son téléphone. Le faire plus
    # tard laissait les deux retomber sur le fichier de configuration —
    # 127.0.0.1 alors que le serveur écoute partout, soit exactement
    # l'adresse à laquelle un téléphone ne trouvera jamais rien.
    from diapason.mesh.beacon import set_local_endpoint

    # Quand un second socket existe, c'est LUI que les pairs joignent : le
    # premier n'écoute que la loopback. Annoncer le premier reviendrait à
    # donner à toute la flotte une adresse où elle ne trouvera jamais rien —
    # et chaque livraison et chaque transfert partirait dans le vide.
    set_local_endpoint(lan_host or bind_host, lan_port if lan_host else bind_port)
    _announce_exposure(bind_host, bind_port)
    if lan_host:
        console.print(
            f"  Maillage : [cyan]http://{lan_host}:{lan_port}[/cyan] — "
            "neuf routes, créance d'appareil exigée"
        )

    # Log credential status at startup
    from diapason.core.credentials import TOOL_CREDENTIALS, get_credential_status

    _cred_parts = []
    for _tool_name in sorted(TOOL_CREDENTIALS):
        _status = get_credential_status(_tool_name)
        _set = sum(1 for v in _status.values() if v)
        _total = len(_status)
        if _set > 0:
            _cred_parts.append(f"{_tool_name}: {_set}/{_total} keys")
    if _cred_parts:
        logger.info("Credentials loaded — %s", ", ".join(_cred_parts))

    webhook_config = {
        "twilio_auth_token": _os.environ.get("TWILIO_AUTH_TOKEN", ""),
        "bluebubbles_password": _os.environ.get("BLUEBUBBLES_PASSWORD", ""),
        "whatsapp_verify_token": _os.environ.get("WHATSAPP_VERIFY_TOKEN", ""),
        "whatsapp_app_secret": _os.environ.get("WHATSAPP_APP_SECRET", ""),
    }

    # Wrap existing channel in ChannelBridge orchestrator
    if channel_bridge is not None:
        try:
            from diapason.server.channel_bridge import (
                ChannelBridge,
            )
            from diapason.server.session_store import (
                SessionStore,
            )

            session_store = SessionStore()
            channels = {channel_bridge.channel_id: channel_bridge}
            channel_bridge = ChannelBridge(
                channels=channels,
                session_store=session_store,
                bus=bus,
                system=None,
                agent_manager=agent_manager,
            )
        except Exception as exc:
            logger.debug("ChannelBridge init skipped: %s", exc)

    app = create_app(
        engine,
        model_name,
        agent=agent,
        bus=bus,
        engine_name=engine_name,
        agent_name=agent_key or "",
        channel_bridge=channel_bridge,
        config=config,
        memory_backend=memory_backend,
        memory_service=memory_service,
        speech_backend=speech_backend,
        agent_manager=agent_manager,
        agent_scheduler=agent_scheduler,
        api_key=api_key,
        webhook_config=webhook_config,
        cors_origins=config.server.cors_origins,
    )

    console.print(
        f"[green]Starting Diapason API server[/green]\n"
        f"  Engine: [cyan]{engine_name}[/cyan]\n"
        f"  Model:  [cyan]{model_name}[/cyan]\n"
        f"  Agent:  [cyan]{agent_key or 'none'}[/cyan]\n"
        f"  URL:    [cyan]http://{bind_host}:{bind_port}[/cyan]"
    )

    import uvicorn

    if not lan_host:
        # Le chemin par défaut, mot pour mot comme avant. Un serveur qui
        # tourne ne doit pas changer de forme parce qu'une option existe.
        uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
        return

    from diapason.server.app import create_lan_app

    _servir_deux_sockets(
        app, bind_host, bind_port, create_lan_app(), lan_host, lan_port
    )
