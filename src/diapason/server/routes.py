"""Route handlers for the OpenAI-compatible API server."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from diapason.core.paths import get_config_dir
from diapason.core.tool_turn import text_needs_tools
from diapason.core.types import Message, Role
from diapason.server.models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ChoiceMessage,
    ComplexityInfo,
    DeltaMessage,
    ModelListResponse,
    ModelObject,
    StreamChoice,
    UsageInfo,
)

router = APIRouter()


# La trousse du chat, résolue une fois puis gardée sur l'état de l'app.
# Sans elle, le chat en flux parlait au moteur nu : l'agent — et avec lui les
# 98 outils enregistrés — était contourné, si bien que Diapason pouvait décrire
# un agenda sans jamais le lire. Voir server/agentic_stream.py.
#
# Cette liste est le défaut d'un assistant personnel : lire l'heure et l'agenda,
# consulter Succès, chercher, se souvenir, regarder l'écran. Elle exclut
# délibérément shell_exec, file_write et apply_patch — un assistant de salon
# n'a pas à écrire sur le disque pour répondre à une question. ``[agent] tools``
# dans la configuration la remplace entièrement quand elle est renseignée.
_TROUSSE_ASSISTANT: tuple[str, ...] = (
    "current_time",
    "calendar_query",
    "succes_tasks",
    "succes_workspace",
    "succes_continuity",
    "succes_finances",
    "succes_delete_task",
    "succes_delete_item",
    # memory_manage écrit dans ~/.diapason/MEMORY.md, que le constructeur de
    # prompt relit à chaque session : c'est le seul circuit de mémoire qui
    # boucle réellement. memory_search, memory_store et retrieval visent un
    # magasin vectoriel désactivé ([memory] enabled = false) et ne savent que
    # répondre « No memory backend configured » — trois outils qui coûtent du
    # préremplissage pour ne rendre que des échecs.
    "memory_manage",
    "user_profile_manage",
    # Le savoir personnel (Obsidian, Apple Notes, documents ingérés) était
    # indexé ET embarqué dans knowledge.db — mais seul le mode recherche
    # profonde y avait accès. Le chat le lit désormais aussi (23 août 2026).
    "knowledge_search",
    # « J'ai reçu quoi ? » en direct — mails non lus, messages, agenda —
    # au lieu de réserver ce talent au brief du matin (Atlas, 24/08/2026).
    "digest_collect",
    "web_search",
    "find_files",
    "open_anything",
    "app_search",
    "app_install",
    "notes_write",
    "reminders_write",
    "calendar_add",
    # Le chat rattrape la voix (Atlas, 24 août 2026) : musique, mails et
    # messages marchent aussi au clavier. Les envois passent par la cloche
    # d'approbation, comme partout.
    "spotify_play",
    "mail_compose",
    "messages_compose",
    "mail_send",
    "messages_send",
    "screen_describe",
    "calculator",
)


def _chat_tooling(app_state: Any, config: Any) -> Optional[tuple[list, Any]]:
    """(outils, exécuteur) pour le chat, ou None si aucun outil n'est utilisable.

    Le cache vit sur l'état de l'app : résoudre la trousse coûte l'import de
    tout ``diapason.tools``, et une requête de chat ne peut pas le payer.
    ``None`` est mis en cache aussi — une installation sans outils ne doit pas
    retenter l'import à chaque message.
    """
    sentinelle = getattr(app_state, "_chat_tooling_cache", "absent")
    if sentinelle != "absent":
        return sentinelle

    resultat: Optional[tuple[list, Any]] = None
    try:
        import diapason.tools  # noqa: F401  # déclenche les enregistrements
        from diapason.core.registry import ToolRegistry
        from diapason.server.approval_bridge import tool_confirm_callback
        from diapason.tools._stubs import BaseTool, ToolExecutor

        configures = getattr(getattr(config, "agent", None), "tools", "") or ""
        if isinstance(configures, str):
            voulus = [t.strip() for t in configures.split(",") if t.strip()]
        else:
            voulus = [str(t).strip() for t in configures if str(t).strip()]
        noms = voulus or list(_TROUSSE_ASSISTANT)

        outils = []
        for nom in noms:
            if not ToolRegistry.contains(nom):
                # Un outil nommé mais absent (dépendance non installée) ne doit
                # pas priver le chat des autres.
                logging.getLogger("diapason.server").debug(
                    "outil de chat inconnu, ignoré : %s", nom
                )
                continue
            classe = ToolRegistry.get(nom)
            if isinstance(classe, type) and issubclass(classe, BaseTool):
                outils.append(classe())
            elif isinstance(classe, BaseTool):
                outils.append(classe)

        if outils:
            executeur = ToolExecutor(
                outils,
                getattr(app_state, "bus", None),
                interactive=True,
                confirm_callback=tool_confirm_callback(),
                agent_id="chat",
            )
            resultat = (outils, executeur)
    except Exception:
        logging.getLogger("diapason.server").warning(
            "trousse du chat indisponible — réponse sans outils",
            exc_info=True,
        )
        resultat = None

    app_state._chat_tooling_cache = resultat
    return resultat


_JOURS = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)
_MOIS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def _host_actions_allowed(request: Request, config) -> bool:
    """Allow desktop control from loopback unless remote access is explicit."""
    lightning = getattr(getattr(config, "desktop", None), "lightning", None)
    if bool(getattr(lightning, "allow_remote", False)):
        return True
    client = getattr(request, "client", None)
    host = str(getattr(client, "host", "") or "").strip()
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _to_messages(chat_messages) -> list[Message]:
    """Convert Pydantic ChatMessage objects to core Message objects."""
    messages = []
    for m in chat_messages:
        role = Role(m.role) if m.role in {r.value for r in Role} else Role.USER
        messages.append(
            Message(
                role=role,
                content=m.content or "",
                name=m.name,
                tool_call_id=m.tool_call_id,
            )
        )
    return messages


def _now_anchor() -> str:
    """L'instant présent, écrit pour un modèle qui n'en a aucune idée.

    Sans cette ligne, le seul repère temporel du contexte est ce qui traîne
    dans les fichiers de mémoire — et l'assistant répond « le 12 août 2026 »
    parce que c'est la date qu'il y lit, pas parce qu'il se trompe de calcul.
    Il ne devine pas au hasard : il prend le repère qu'on lui a laissé.

    Le fuseau est nommé et le décalage donné, sinon « 14:30 » ne désigne rien.
    """
    from datetime import datetime

    stamp = datetime.now().astimezone()
    raw = stamp.strftime("%z")
    offset = f"{raw[:3]}:{raw[3:]}" if raw else "?"
    # ``strftime('%A %d %B')`` rendait « Saturday 22 August 2026 » : une date
    # ANGLAISE au milieu d'une phrase française, dans l'ancre même qui fait
    # autorité sur le contexte. Un modèle qu'on prie de répondre en français
    # lit d'abord ça. ``setlocale`` corrigerait au prix d'un état global au
    # processus — deux tables suffisent et ne dépendent d'aucun environnement.
    jour = _JOURS[stamp.weekday()]
    mois = _MOIS[stamp.month - 1]
    return (
        "=== MAINTENANT ===\n"
        f"Nous sommes le {jour} {stamp.day} {mois} {stamp.year}, il est "
        f"{stamp.strftime('%H:%M')} ({stamp.tzname()}, UTC{offset}). "
        f"ISO : {stamp.isoformat(timespec='seconds')}\n"
        "Ceci fait autorité sur toute autre date présente dans ce contexte : "
        "les dates citées dans la mémoire ou les documents sont des dates "
        "PASSÉES, jamais aujourd'hui. Pour l'heure exacte après un long "
        "échange, relis l'horloge avec l'outil current_time."
    )


def _ensure_identity_prompt(
    messages: list[Message],
    app_config,
    *,
    client_supplied_system: bool | None = None,
) -> list[Message]:
    """Prepend Diapason's identity system prompt when the client omits one.

    The desktop UI's chat backend posts only user/assistant turns to
    ``/v1/chat/completions`` (see ``frontend/.../Chat/InputArea.tsx``), so
    nothing grounds the model's identity. Without a system prompt the model
    answers from its training identity (e.g. "I'm Claude", "I am Qwen"),
    which is what #540 reported. The CLI paths inject this via
    ``SystemPromptBuilder`` / ``BaseAgent``; the engine-direct server paths
    did not. This mirrors the agent fallback in ``agents/_stubs.py``.

    If any message already carries a system role, the caller has supplied
    their own grounding and we leave the list untouched (no double-prompting).

    Resolution of the identity text: the config comes from ``app.state`` when
    wired, otherwise ``load_config()``; the prompt itself is assembled by
    ``SystemPromptBuilder`` from ``agent.default_system_prompt`` plus the
    persona files (SOUL.md/MEMORY.md/USER.md), matching
    ``_build_managed_system_prompt`` in ``agent_manager_routes.py``. Config
    resolution is wrapped so a broken/missing config degrades to "no
    injection" rather than crashing the endpoint, but the failure is logged
    (per REVIEW.md — never silently swallow).
    """
    # L'heure d'abord, et quoi qu'il arrive. Le retour anticipé ci-dessous
    # existe pour ne pas doubler l'IDENTITÉ quand l'appelant fournit la
    # sienne ; laisser l'horloge sauter avec elle est ce qui faisait répondre
    # une date lue dans la mémoire.
    ancre = _now_anchor()
    # Le cliché du bureau rejoint l'ancre (Atlas, 24 août 2026) : le chat
    # sait ce qui tourne et ce qui est devant, comme la voix. L'ancre est
    # déjà volatile à la minute — l'état n'y coûte rien de plus.
    try:
        from diapason.desktop.etat_bureau import decrire, dernier_etat_connu

        cliche = dernier_etat_connu()
        if cliche is not None:
            ancre = f"{ancre}\n{decrire(cliche)}"
    except Exception:  # noqa: BLE001 - la perception est un bonus
        pass
    anchored = [Message(role=Role.SYSTEM, content=ancre), *messages]

    # Le retour anticipé n'a de sens que si le CLIENT a fourni son propre
    # cadrage. Il testait la liste telle qu'elle arrive ici — or le serveur y
    # a peut-être glissé son propre message système entre-temps : dès qu'une
    # recherche mémoire ramenait un seul résultat, ce message déclenchait le
    # test et l'identité de Diapason, MEMORY.md et USER.md disparaissaient
    # tous les trois. Le modèle repartait sur son identité d'entraînement et
    # inventait le nom de l'utilisateur — exactement le défaut que ce code
    # documente vouloir empêcher.
    supplied = (
        client_supplied_system
        if client_supplied_system is not None
        else any(m.role == Role.SYSTEM for m in messages)
    )
    if supplied:
        return anchored

    prompt = ""
    try:
        cfg = app_config
        if cfg is None:
            from diapason.core.config import load_config

            cfg = load_config()

        from diapason.prompt.builder import SystemPromptBuilder
        from diapason.prompt.regles_ecrites import habiller_pour_le_chat

        # La voix a ses règles orales (oral_prompt.py) ; le chat a les
        # siennes — même identité, manière propre à l'écrit (23 août 2026).
        builder = SystemPromptBuilder(
            agent_template=habiller_pour_le_chat(
                cfg.agent.default_system_prompt or ""
            ),
            memory_files_config=getattr(cfg, "memory_files", None),
            system_prompt_config=getattr(cfg, "system_prompt", None),
        )
        prompt = builder.build()
    except Exception:
        logging.getLogger("diapason.server").debug(
            "Identity system prompt resolution failed; "
            "serving request without identity grounding",
            exc_info=True,
        )
        return anchored

    if not prompt:
        return anchored

    return [Message(role=Role.SYSTEM, content=prompt), *anchored]


@router.post("/v1/chat/completions")
async def chat_completions(request_body: ChatCompletionRequest, request: Request):
    """Handle chat completion requests (streaming and non-streaming)."""
    engine = request.app.state.engine
    agent = getattr(request.app.state, "agent", None)
    model = request_body.model
    config = getattr(request.app.state, "config", None)

    # Le cliché du bureau se rafraîchit en parallèle de la requête (~100 ms
    # d'osascript) ; l'ancre du prompt ne lit que le cache — même mécanique
    # que la voix (Atlas, 24 août 2026).
    try:
        from diapason.desktop.etat_bureau import etat_du_bureau

        asyncio.get_running_loop().run_in_executor(None, etat_du_bureau)
    except Exception:  # noqa: BLE001 - la perception est un bonus
        pass

    # Trusted desktop fast path.  It runs BEFORE memory retrieval, complexity
    # scoring and inference, turning explicit low-risk commands into one local
    # OS call.  action_mode defaults to off and tools disable the path, so the
    # OpenAI-compatible API cannot unexpectedly control the host.
    query_text_for_action = ""
    for _message in reversed(request_body.messages):
        if _message.role == "user" and _message.content:
            query_text_for_action = _message.content
            break
    if (
        request_body.action_mode == "auto"
        and not request_body.tools
        and query_text_for_action
        and _host_actions_allowed(request, config)
    ):
        service = getattr(request.app.state, "lightning_actions", None)
        if service is not None:

            def generate_action_text(instruction: str) -> str:
                messages = _to_messages(request_body.messages)
                messages.insert(
                    0,
                    Message(
                        role=Role.SYSTEM,
                        content=(
                            "Create only the polished content that should be "
                            "inserted into the requested application. Follow the "
                            "user's language and instruction. Do not add commentary, "
                            "quotes, or a preface."
                        ),
                    ),
                )
                result = engine.generate(
                    messages,
                    model=model,
                    temperature=min(request_body.temperature, 0.7),
                    max_tokens=min(max(request_body.max_tokens, 128), 2048),
                )
                return str(result.get("content") or "")

            outcome = await asyncio.to_thread(
                service.handle,
                query_text_for_action,
                text_generator=generate_action_text,
            )
            if outcome.handled:
                if request_body.stream:
                    return _handle_lightning_stream(model, outcome)
                return ChatCompletionResponse(
                    model=model,
                    choices=[
                        Choice(
                            message=ChoiceMessage(
                                role="assistant",
                                content=outcome.message,
                            ),
                            finish_reason="stop",
                        )
                    ],
                    usage=UsageInfo(),
                    lightning=outcome.public_metadata(),
                )

    # Relevé AVANT toute injection : après, on ne peut plus distinguer le
    # cadrage du client de celui que le serveur vient d'ajouter.
    client_system = any(m.role == "system" for m in request_body.messages)

    # Inject memory context into messages before dispatching
    memory_backend = getattr(request.app.state, "memory_backend", None)
    if (
        config is not None
        and memory_backend is not None
        and config.agent.context_from_memory
        and request_body.messages
    ):
        try:
            from diapason.tools.storage.context import ContextConfig, inject_context

            # Extract query from the last user message
            query_text = ""
            for m in reversed(request_body.messages):
                if m.role == "user" and m.content:
                    query_text = m.content
                    break

            if query_text:
                messages = _to_messages(request_body.messages)
                ctx_cfg = ContextConfig(
                    top_k=config.memory.context_top_k,
                    min_score=config.memory.context_min_score,
                    max_context_tokens=config.memory.context_max_tokens,
                )
                enriched = inject_context(
                    query_text,
                    messages,
                    memory_backend,
                    config=ctx_cfg,
                )
                # Rebuild request messages from enriched Message objects
                if len(enriched) > len(messages):
                    from diapason.server.models import ChatMessage

                    new_msgs = []
                    for msg in enriched:
                        new_msgs.append(
                            ChatMessage(
                                role=msg.role.value,
                                content=msg.content,
                                name=msg.name,
                                tool_call_id=getattr(msg, "tool_call_id", None),
                            )
                        )
                    request_body.messages = new_msgs
        except Exception:
            logging.getLogger("diapason.server").debug(
                "Memory context injection failed",
                exc_info=True,
            )

    # Run complexity analysis on the last user message
    complexity_info = None
    query_text_for_complexity = ""
    for m in reversed(request_body.messages):
        if m.role == "user" and m.content:
            query_text_for_complexity = m.content
            break
    if query_text_for_complexity:
        try:
            from diapason.learning.routing.complexity import (
                adjust_tokens_for_model,
                score_complexity,
            )

            cr = score_complexity(query_text_for_complexity)
            suggested = adjust_tokens_for_model(
                cr.suggested_max_tokens,
                model,
            )
            complexity_info = ComplexityInfo(
                score=cr.score,
                tier=cr.tier,
                suggested_max_tokens=suggested,
            )
            # Bump max_tokens when complexity suggests more than what
            # the client requested — never reduce below the request value.
            if suggested > request_body.max_tokens:
                request_body.max_tokens = suggested
        except Exception:
            logging.getLogger("diapason.server").debug(
                "Complexity analysis failed",
                exc_info=True,
            )

    if request_body.stream:
        # When the client passes `tools`, stream the model's raw
        # OpenAI-compat function-calling decision directly from the engine
        # (bypassing the agent) — the streaming mirror of the non-streaming
        # #454 fix.  Routing tools through the agent stream bridge ignored
        # `request_body.tools`, ran the agent's own tool loop, and
        # word-split generic filler content into fake token deltas, so the
        # caller's tool_calls were dropped entirely (the streaming analog of
        # #414).  For plain chat (no tools), stream token-by-token directly
        # from the engine for true real-time output.
        if request_body.tools:
            return await _handle_stream_tools(
                engine,
                model,
                request_body,
                complexity_info,
                app_config=config,
                bus=getattr(request.app.state, "bus", None),
                memory_service=getattr(request.app.state, "memory_service", None),
                client_system=client_system,
            )
        return await _handle_stream(
            engine,
            model,
            request_body,
            complexity_info,
            trace_store=getattr(request.app.state, "trace_store", None),
            app_config=config,
            bus=getattr(request.app.state, "bus", None),
            memory_service=getattr(request.app.state, "memory_service", None),
            client_system=client_system,
            # Sans cette trousse, le chat du bureau parlait au moteur nu et
            # Diapason ne pouvait rien LIRE — ni l'heure, ni l'agenda, ni une
            # tâche Succès. C'est le fil qui manquait entre les 98 outils
            # enregistrés et la seule interface qui sert vraiment.
            tooling=_chat_tooling(request.app.state, config),
        )

    # Non-streaming: use agent if available, otherwise direct engine call.
    #
    # EXCEPTION: when the client explicitly passed `tools`, they're asking
    # for raw OpenAI-compat function-calling — return the model's
    # tool_call decision verbatim. Routing through `_handle_agent` would
    # call `agent.run(input_text)`, which IGNORES `request_body.tools`,
    # runs the agent's own internal tool loop with its own (different)
    # tool spec, and returns only `result.content` — so the model's
    # tool_calls vanish and the user sees a generic acknowledgement
    # (e.g. "Understood. If you have another request...") that the
    # agent's re-prompted LLM produced. See #414.
    #
    # If a future caller needs agent orchestration WITH client-supplied
    # tools (e.g. injecting MCP tools through this endpoint and wanting
    # the agent to execute them), add an explicit opt-in header rather
    # than removing this guard — silent re-routing is what produced #414.
    # ``_handle_agent`` (sync ``agent.run()``) and ``_handle_direct`` (sync
    # ``engine.generate()``) both make blocking upstream calls; run them in a
    # worker thread so a slow/wedged non-streaming request can't stall the
    # event loop and every other concurrent request with it.
    if agent is not None and not request_body.tools:
        response = await asyncio.to_thread(
            _handle_agent,
            agent,
            model,
            request_body,
            complexity_info,
            trace_store=getattr(request.app.state, "trace_store", None),
            bus=getattr(request.app.state, "bus", None),
        )
    else:
        bus = getattr(request.app.state, "bus", None)
        response = await asyncio.to_thread(
            _handle_direct,
            engine,
            model,
            request_body,
            bus=bus,
            complexity_info=complexity_info,
            app_config=config,
            client_system=client_system,
        )

    # Hand the completed exchange to the background memory service.
    _remember_exchange(
        getattr(request.app.state, "memory_service", None),
        query_text_for_complexity,
        response,
        bus=getattr(request.app.state, "bus", None),
        source="server.chat",
    )
    return response


def _handle_lightning_stream(model: str, outcome) -> StreamingResponse:
    """Emit a completed action using the normal OpenAI SSE shape."""
    import json

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    async def generate():
        role = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
        )
        yield f"data: {role.model_dump_json()}\n\n"
        content = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(content=outcome.message))],
        )
        yield f"data: {content.model_dump_json()}\n\n"
        finish = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(), finish_reason="stop")],
        )
        payload = json.loads(finish.model_dump_json())
        payload["lightning"] = outcome.public_metadata()
        payload["usage"] = UsageInfo().model_dump()
        yield f"data: {json.dumps(payload)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/v1/actions/metrics")
async def action_metrics(request: Request):
    """Privacy-safe latency distribution for deterministic actions."""
    from diapason.actions.metrics import METRICS

    return METRICS.snapshot()


@router.get("/v1/actions/capabilities")
async def action_capabilities(request: Request):
    service = getattr(request.app.state, "lightning_actions", None)
    return service.capabilities() if service is not None else {"enabled": False}


def _response_content(response) -> str:
    """Extract assistant text from an OpenAI-compatible response object."""
    content = ""
    choices = getattr(response, "choices", None)
    if choices:
        content = getattr(choices[0].message, "content", "") or ""
    return content


def _record_completed_exchange(
    memory_service,
    user_text: str,
    assistant_text: str,
    *,
    bus=None,
    source: str = "server.chat",
) -> None:
    """Publish or submit a completed exchange without blocking a reply."""
    if not user_text:
        return
    try:
        if bus is not None:
            from diapason.memory import publish_completed_exchange

            publish_completed_exchange(
                bus,
                user_text,
                assistant_text,
                source=source,
            )
        elif memory_service is not None:
            memory_service.submit(user_text, assistant_text)
    except Exception:  # noqa: BLE001 — memory is best-effort, never fail a reply
        logging.getLogger("diapason.server").debug(
            "Memory submit failed",
            exc_info=True,
        )


def _remember_exchange(
    memory_service,
    user_text: str,
    response,
    *,
    bus=None,
    source: str = "server.chat",
) -> None:
    """Record a completed non-streaming exchange."""
    _record_completed_exchange(
        memory_service,
        user_text,
        _response_content(response),
        bus=bus,
        source=source,
    )


def _handle_direct(
    engine,
    model: str,
    req: ChatCompletionRequest,
    bus=None,
    complexity_info=None,
    app_config=None,
    client_system: bool = False,
) -> ChatCompletionResponse:
    """Direct engine call without agent."""
    messages = _to_messages(req.messages)
    messages = _ensure_identity_prompt(
        messages, app_config, client_supplied_system=client_system
    )
    kwargs: dict[str, Any] = {}
    if req.tools:
        kwargs["tools"] = req.tools
    if bus:
        from diapason.telemetry.instrumented_engine import InstrumentedEngine
        from diapason.telemetry.wrapper import instrumented_generate

        # `app.state.engine` may already be an InstrumentedEngine (the
        # common case when telemetry is wired in). If we then wrap it
        # with `instrumented_generate`, BOTH layers fire a
        # TELEMETRY_RECORD per call:
        #
        #   - InstrumentedEngine.generate() publishes a FULL record
        #     (energy_joules, GPU stats, token_counting_version, ...).
        #   - instrumented_generate() publishes a BARE record (timing +
        #     tokens only; no energy meter, no version stamp).
        #
        # The doubled count was the dominant driver of the bimodal
        # Wh/token distribution on the local savings dashboard.
        #
        # The fix below is NOT "unwrap and call instrumented_generate":
        # that would have replaced "doubled records" with "every
        # request emits only a bare record with no energy / no version",
        # which the savings `current_methodology_only=True` filter
        # would then drop entirely. Instead, when the engine is already
        # an InstrumentedEngine, skip the wrapper and call `generate`
        # directly — InstrumentedEngine publishes the full per-record
        # event itself with energy + version intact. Only fall back to
        # the lightweight wrapper for engines that aren't already
        # instrumented.
        if isinstance(engine, InstrumentedEngine):
            result = engine.generate(
                messages,
                model=model,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                **kwargs,
            )
        else:
            result = instrumented_generate(
                engine,
                messages,
                model=model,
                bus=bus,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                **kwargs,
            )
    else:
        result = engine.generate(
            messages,
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            **kwargs,
        )
    content = result.get("content", "")
    usage = result.get("usage", {})

    choice_msg = ChoiceMessage(role="assistant", content=content)
    # Include tool calls if present
    tool_calls = result.get("tool_calls")
    if tool_calls:
        choice_msg.tool_calls = [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": tc.get("arguments", "{}"),
                },
            }
            for tc in tool_calls
        ]

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=choice_msg,
                finish_reason=result.get("finish_reason", "stop"),
            )
        ],
        usage=UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ),
        complexity=complexity_info,
    )


def _handle_agent(
    agent,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    *,
    trace_store=None,
    bus=None,
) -> ChatCompletionResponse:
    """Run through agent.

    When *trace_store* is set, the agent run is wrapped in a
    ``TraceCollector`` (mirroring ``system/orchestrator.py``) so every
    completion records a ``Trace`` to ``traces.db``. Previously this endpoint
    called ``agent.run()`` raw, so the server never produced traces:
    ``traces.db`` stayed empty and spec_search's cold-start gate
    (``check_readiness``, min 20 traces) could never open.
    """
    from diapason.agents._stubs import AgentContext

    # Build context from prior messages
    ctx = AgentContext()
    if len(req.messages) > 1:
        prior = _to_messages(req.messages[:-1])
        for m in prior:
            ctx.conversation.add(m)

    # Last message is the input
    input_text = req.messages[-1].content if req.messages else ""

    # Override agent model for this request if the caller specified one
    original_model = agent._model
    if model:
        agent._model = model
    try:
        if trace_store is not None:
            from diapason.traces.collector import TraceCollector

            collector = TraceCollector(agent, store=trace_store, bus=bus)
            result = collector.run(input_text, context=ctx)
        else:
            result = agent.run(input_text, context=ctx)
    finally:
        agent._model = original_model

    usage = UsageInfo(
        prompt_tokens=result.metadata.get("prompt_tokens", 0),
        completion_tokens=result.metadata.get("completion_tokens", 0),
        total_tokens=result.metadata.get("total_tokens", 0),
    )

    # Include audio metadata if the agent produced audio (e.g. morning digest)
    audio_meta = None
    audio_path = result.metadata.get("audio_path", "")
    if audio_path:
        from pathlib import Path

        from diapason.server.models import AudioMeta

        if Path(audio_path).exists():
            audio_meta = AudioMeta(url="/api/digest/audio")

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=ChoiceMessage(
                    role="assistant",
                    content=result.content,
                    audio=audio_meta,
                ),
                finish_reason="stop",
            )
        ],
        usage=usage,
        complexity=complexity_info,
    )


async def _handle_stream_tools(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    *,
    app_config=None,
    bus=None,
    memory_service=None,
    client_system: bool = False,
):
    """Stream a raw OpenAI-compat function-calling response via SSE.

    Used when the client passes `tools` together with `stream:true`.  Sources
    tool_calls from ``engine.stream_full()`` (which forwards the tools to the
    backend and parses tool_calls out of the streamed response) and emits them
    as SSE deltas, bypassing the agent entirely.  This is the streaming mirror
    of the non-streaming ``_handle_direct`` tool path.

    Engines without a tool-aware ``stream_full`` override fall back to the
    base-class default (content tokens + a ``stop`` finish_reason, no
    tool_calls) — identical to the prior plain-stream behaviour, so this never
    regresses non-tool-capable engines.
    """
    from diapason.server.cloud_router import is_cloud_model

    messages = _to_messages(req.messages)
    messages = _ensure_identity_prompt(
        messages, app_config, client_supplied_system=client_system
    )
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    use_cloud = is_cloud_model(model)
    query_text = ""
    for _m in reversed(req.messages):
        if _m.role == "user" and _m.content:
            query_text = _m.content
            break

    async def generate():
        full_content = ""
        # Send the role chunk first (OpenAI convention).
        first_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        finish_reason = "stop"
        try:
            async for sc in engine.stream_full(
                messages,
                model=model,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                tools=req.tools,
            ):
                if sc.content:
                    full_content += sc.content
                    content_chunk = ChatCompletionChunk(
                        id=chunk_id,
                        model=model,
                        choices=[StreamChoice(delta=DeltaMessage(content=sc.content))],
                    )
                    yield f"data: {content_chunk.model_dump_json()}\n\n"
                if sc.tool_calls:
                    tc_chunk = ChatCompletionChunk(
                        id=chunk_id,
                        model=model,
                        choices=[
                            StreamChoice(delta=DeltaMessage(tool_calls=sc.tool_calls))
                        ],
                    )
                    yield f"data: {tc_chunk.model_dump_json()}\n\n"
                if sc.finish_reason:
                    finish_reason = sc.finish_reason
        except Exception as exc:
            import logging

            logging.getLogger("diapason.server").error(
                "Tool stream error: %s",
                exc,
                exc_info=True,
            )
            error_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(
                            content=f"\n\nError during generation: {exc}",
                        ),
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return

        import json as _json

        finish_data = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(), finish_reason=finish_reason)],
        )
        finish_dict = _json.loads(finish_data.model_dump_json())
        # Tag the finish chunk with the engine label, matching _handle_stream
        # so UI/telemetry consumers see the same field on the tools path.
        finish_dict.setdefault("telemetry", {})
        finish_dict["telemetry"]["engine"] = "cloud" if use_cloud else "ollama"
        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()
        yield f"data: {_json.dumps(finish_dict)}\n\n"
        if full_content:
            _record_completed_exchange(
                memory_service,
                query_text,
                full_content,
                bus=bus,
                source="server.chat.stream",
            )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def _handle_stream(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    *,
    trace_store=None,
    app_config=None,
    bus=None,
    memory_service=None,
    client_system: bool = False,
    tooling=None,
):
    """Stream response using SSE format.

    This path streams straight from the engine, bypassing the agent /
    ``TraceCollector``. When *trace_store* is set we accumulate the streamed
    tokens and record a minimal ``Trace`` once the stream completes
    successfully — otherwise streamed chats (the desktop GUI's main path)
    would never populate ``traces.db``.
    """
    import time

    from diapason.server.cloud_router import (
        is_cloud_model,
        stream_cloud,
        stream_local,
    )

    messages = _to_messages(req.messages)
    messages = _ensure_identity_prompt(
        messages, app_config, client_supplied_system=client_system
    )
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Last user message — recorded as the trace query.
    query_text = ""
    for _m in reversed(req.messages):
        if _m.role == "user" and _m.content:
            query_text = _m.content
            break

    # Route directly to the right backend — bypasses engine routing entirely
    # so broken MultiEngine state can never misdirect requests.
    use_cloud = is_cloud_model(model)

    async def generate():
        started_at = time.time()
        full_content = ""
        # Send role chunk first
        first_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(role="assistant"),
                )
            ],
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        try:
            # Cloud models → direct cloud API (reads keys from disk).
            # Local models → engine.stream() first so mock engines work in
            # tests.  Fall back to stream_local() only when the engine would
            # mis-route the request to a cloud backend (MultiEngine routing
            # confusion), which is detected by checking the routed engine's
            # is_cloud attribute.
            token_iter = None
            if use_cloud:
                token_iter = stream_cloud(
                    model, messages, req.temperature, req.max_tokens
                )
            else:
                # Use engine.stream() by default (preserves mock-engine
                # compatibility in tests).  Only fall back to stream_local()
                # when a real MultiEngine would mis-route the local model to a
                # cloud backend — detected via isinstance so mocks are not
                # accidentally matched.
                _use_local_fallback = False
                try:
                    from diapason.engine.multi import MultiEngine

                    _inner = getattr(engine, "_inner", engine)
                    if isinstance(_inner, MultiEngine):
                        _routed = _inner._engine_for(model)
                        if _routed is not None and getattr(_routed, "is_cloud", False):
                            _use_local_fallback = True
                except Exception:
                    pass
                if _use_local_fallback:
                    token_iter = stream_local(
                        model, messages, req.temperature, req.max_tokens
                    )
                elif tooling is not None and text_needs_tools(query_text):
                    # Les schémas des dix-sept outils pèsent près de trois mille
                    # jetons que le modèle relit avant de répondre. Sur « merci »
                    # c'est du temps pur perdu ; le chemin vocal l'avait déjà
                    # mesuré (voir core/tool_turn.py). Par défaut on les envoie :
                    # seule une parole sans demande en est dispensée.
                    token_iter = None
                else:
                    # Les questions analytiques passent par le brouillon-
                    # critique (server/reflexion.py) : silence le temps d'un
                    # premier jet, puis la version relue arrive en flux —
                    # éventuellement d'un modèle plus grand ([reflexion]).
                    from diapason.server import reflexion as _reflexion

                    if _reflexion.est_activee(app_config) and _reflexion.meriter_reflexion(
                        query_text
                    ):
                        token_iter = _reflexion.repondre_en_reflechissant(
                            engine,
                            _reflexion.modele_de_reflexion(app_config, model),
                            messages,
                            temperature=req.temperature,
                            max_tokens=req.max_tokens,
                            modele_de_secours=model,
                        )
                    else:
                        token_iter = engine.stream(
                            messages,
                            model=model,
                            temperature=req.temperature,
                            max_tokens=req.max_tokens,
                        )

            if token_iter is None:
                # Chemin outillé : mêmes jetons, au même rythme, mais le
                # modèle peut s'interrompre pour lire l'heure ou l'agenda.
                # Les événements tool_call_* sont ceux que le chat affiche
                # déjà (voir Chat/InputArea.tsx).
                import json as _json_outils

                from diapason.server.agentic_stream import stream_with_tools

                _outils, _executeur = tooling
                async for _evt in stream_with_tools(
                    engine,
                    model,
                    messages,
                    tools=_outils,
                    executor=_executeur,
                    temperature=req.temperature,
                    max_tokens=req.max_tokens,
                ):
                    if _evt.kind == "token":
                        full_content += _evt.data
                        chunk = ChatCompletionChunk(
                            id=chunk_id,
                            model=model,
                            choices=[
                                StreamChoice(
                                    delta=DeltaMessage(content=_evt.data),
                                )
                            ],
                        )
                        yield f"data: {chunk.model_dump_json()}\n\n"
                    else:
                        _nom = (
                            "tool_call_start"
                            if _evt.kind == "tool_start"
                            else "tool_call_end"
                        )
                        yield (
                            f"event: {_nom}\n"
                            f"data: {_json_outils.dumps(_evt.data)}\n\n"
                        )
            else:
                async for token in token_iter:
                    full_content += token
                    chunk = ChatCompletionChunk(
                        id=chunk_id,
                        model=model,
                        choices=[
                            StreamChoice(
                                delta=DeltaMessage(content=token),
                            )
                        ],
                    )
                    yield f"data: {chunk.model_dump_json()}\n\n"
        except Exception as exc:
            # Surface errors as a content chunk so the frontend can
            # display them instead of silently failing.
            import logging

            logging.getLogger("diapason.server").error(
                "Stream error: %s",
                exc,
                exc_info=True,
            )
            error_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(
                            content=f"\n\nError during generation: {exc}",
                        ),
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Record a trace for the completed stream (best-effort; never breaks
        # the response). Mirrors the agent path so streamed chats also
        # populate traces.db.
        if trace_store is not None and full_content:
            from diapason.traces.collector import record_response_trace

            record_response_trace(
                trace_store,
                query=query_text,
                result=full_content,
                model=model,
                engine="cloud" if use_cloud else "ollama",
                started_at=started_at,
                ended_at=time.time(),
            )

        if full_content:
            _record_completed_exchange(
                memory_service,
                query_text,
                full_content,
                bus=bus,
                source="server.chat.stream",
            )

        # Send finish chunk with usage data if available
        import json as _json

        finish_data = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(),
                    finish_reason="stop",
                )
            ],
        )
        finish_dict = _json.loads(finish_data.model_dump_json())

        # Tag the finish chunk with the correct engine label.
        # We use the routing decision (use_cloud) directly rather than
        # unwrapping the engine chain, which can be in a broken state.
        finish_dict.setdefault("telemetry", {})
        finish_dict["telemetry"]["engine"] = "cloud" if use_cloud else "ollama"

        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()

        yield f"data: {_json.dumps(finish_dict)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# model_id -> context window; None is cached too (an unknown model stays
# unknown for the process lifetime rather than re-asking Ollama every call).
_CTX_CACHE: dict[str, Optional[int]] = {}


async def _context_length_of(model_id: str) -> Optional[int]:
    """Max context window: builtin catalog first, then Ollama /api/show."""
    if model_id in _CTX_CACHE:
        return _CTX_CACHE[model_id]
    try:
        from diapason.intelligence.model_catalog import BUILTIN_MODELS

        for spec in BUILTIN_MODELS:
            if spec.model_id == model_id:
                value = int(spec.context_length)
                _CTX_CACHE[model_id] = value
                return value
    except Exception:  # noqa: BLE001 - a broken catalog still has Ollama
        pass
    try:
        import httpx

        from diapason.server.cloud_router import _ollama_host

        host = _ollama_host()
        from diapason.core.local_mode import assert_may_leave

        assert_may_leave("the model metadata request", destination=host)
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(f"{host}/api/show", json={"model": model_id})
            resp.raise_for_status()
            info = resp.json().get("model_info") or {}
            for key, val in info.items():
                if key.endswith(".context_length"):
                    value = int(val)
                    _CTX_CACHE[model_id] = value
                    return value
        # Definitive answer without the field: this model just does not
        # advertise a window — THAT is worth remembering.
        _CTX_CACHE[model_id] = None
    except Exception:  # noqa: BLE001 - Ollama down/slow is TRANSIENT:
        # do not memorize the outage, ask again on the next /v1/models.
        pass
    return None


def _est_modele_embedding(nom: str) -> bool:
    """Vrai pour les modèles d'embeddings — ils ne savent pas discuter.

    Constaté le 23 août 2026 : l'app de bureau choisit le PREMIER modèle de
    cette liste comme modèle de chat par défaut, et Ollama trie ses modèles
    par date de modification — nomic-embed-text est passé en tête et chaque
    « Salut » répondait « does not support chat », HTTP 400.
    """
    bas = (nom or "").lower()
    return "embed" in bas or bas.startswith("bge-")


@router.get("/v1/models")
async def list_models(request: Request) -> ModelListResponse:
    """List locally installed models (Ollama).

    Cloud models are not included here — they live in the Cloud Models tab
    of the UI and are selected there, not from this endpoint. Embedding
    models are not included either — offering a model that cannot chat in
    a chat-model picker is a loaded footgun (see _est_modele_embedding).
    The server's own default model comes first: it is what the desktop app
    picks when nothing is selected yet.
    """
    from diapason.server.cloud_router import is_cloud_model, list_local_models

    # Prefer engine.list_models() so mock engines work in tests.
    # Filter out any cloud model IDs that may appear via MultiEngine.
    # Fall back to direct Ollama query only when the engine returns nothing.
    engine = request.app.state.engine
    all_ids = await asyncio.to_thread(engine.list_models)
    model_ids = [
        m for m in all_ids if not is_cloud_model(m) and not _est_modele_embedding(m)
    ]
    if not model_ids:
        model_ids = [m for m in await list_local_models() if not _est_modele_embedding(m)]

    defaut = str(getattr(request.app.state, "model", "") or "")
    if defaut in model_ids:
        model_ids = [defaut, *[m for m in model_ids if m != defaut]]

    lengths = await asyncio.gather(*(_context_length_of(mid) for mid in model_ids))
    return ModelListResponse(
        data=[
            ModelObject(id=mid, context_length=length)
            for mid, length in zip(model_ids, lengths)
        ],
    )


@router.post("/v1/models/prewarm")
async def prewarm_model(request: Request):
    """Keep a local Ollama model resident without generating any content."""
    body = await request.json()
    model_name = str(body.get("model") or "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="model is required")

    engine = request.app.state.engine
    for _ in range(5):
        candidate = getattr(engine, "__dict__", {}).get("_inner")
        if candidate is None:
            break
        engine = candidate
    # MultiEngine can identify the concrete backend for this exact model.
    from diapason.engine.multi import MultiEngine

    if isinstance(engine, MultiEngine):
        selected = engine._engine_for(model_name)
        if selected is not None:
            engine = selected

    from diapason.core.local_mode import host_is_local

    if str(getattr(engine, "engine_id", "")).lower() != "ollama" or not host_is_local(
        str(getattr(engine, "_host", ""))
    ):
        raise HTTPException(
            status_code=409,
            detail="Model prewarm is available only for local Ollama models.",
        )
    prewarm = getattr(engine, "prewarm", None)
    if not callable(prewarm):
        raise HTTPException(status_code=501, detail="Engine cannot prewarm models.")
    loaded = await asyncio.to_thread(prewarm, model_name)
    if not loaded:
        raise HTTPException(
            status_code=503,
            detail="Ollama could not preload the model.",
        )
    return {
        "status": "ready",
        "model": model_name,
        "keep_alive": str(getattr(engine, "_keep_alive", "30m")),
    }


@router.post("/v1/models/pull")
async def pull_model(request: Request):
    """Pull / download a model from the Ollama registry."""
    body = await request.json()
    model_name = body.get("model", "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="'model' field is required")

    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    # Only Ollama supports pulling
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(
            status_code=501,
            detail="Model pulling is only supported with the Ollama engine",
        )

    import httpx as _httpx

    host = getattr(engine, "_host", "http://localhost:11434")
    try:
        from diapason.core.local_mode import LocalOnlyError, assert_may_leave

        assert_may_leave("the model pull request", destination=host)
        async with _httpx.AsyncClient(base_url=host, timeout=600.0) as client:
            resp = await client.post(
                "/api/pull",
                json={"name": model_name, "stream": False},
            )
        resp.raise_for_status()
    except LocalOnlyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )

    return {"status": "ok", "model": model_name}


@router.delete("/v1/models/{model_name:path}")
async def delete_model(model_name: str, request: Request):
    """Delete a model from Ollama."""
    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(status_code=501, detail="Only supported with Ollama engine")

    import httpx as _httpx

    host = getattr(engine, "_host", "http://localhost:11434")
    try:
        from diapason.core.local_mode import LocalOnlyError, assert_may_leave

        assert_may_leave("the model deletion request", destination=host)
        async with _httpx.AsyncClient(base_url=host, timeout=30.0) as client:
            resp = await client.request(
                "DELETE",
                "/api/delete",
                json={"name": model_name},
            )
        resp.raise_for_status()
    except LocalOnlyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )

    return {"status": "deleted", "model": model_name}


@router.post("/v1/cloud/reload")
async def reload_cloud_engine(request: Request):
    """Hot-reload cloud API keys and (re-)initialize the cloud engine.

    Called by the desktop app immediately after the user saves a cloud API
    key so that cloud models become available without a full app restart.
    """
    import os

    submitted_keys: dict[str, str] | None = None
    try:
        body = await request.json()
        raw_keys = body.get("keys") if isinstance(body, dict) else None
        if isinstance(raw_keys, dict):
            submitted_keys = {
                str(k): str(v)
                for k, v in raw_keys.items()
                if str(k).endswith("_API_KEY")
            }
    except Exception:
        submitted_keys = None

    if submitted_keys is not None:
        for key, value in submitted_keys.items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
    else:
        # Compatibility fallback for non-desktop/manual configurations.
        keys_path = get_config_dir() / "cloud-keys.env"
        if keys_path.exists():
            for raw_line in keys_path.read_text().splitlines():
                line = raw_line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()

    # Try to build a fresh CloudEngine.
    try:
        from diapason.engine.cloud import CloudEngine
        from diapason.engine.multi import MultiEngine

        cloud = CloudEngine()
        if not cloud.health():
            return {
                "status": "no_cloud",
                "message": "No cloud models available (check API keys)",
            }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    # Locate the innermost engine, working through InstrumentedEngine layers.
    outer = request.app.state.engine
    inner = getattr(outer, "_inner", outer)

    if isinstance(inner, MultiEngine):
        # Replace or insert the cloud entry in the existing MultiEngine.
        new_engines = [(k, e) for k, e in inner._engines if k != "cloud"]
        new_engines.append(("cloud", cloud))
        inner._engines = new_engines
        inner._refresh_map()
    else:
        # Wrap the existing engine (which may be security-wrapped) with a new
        # MultiEngine that includes the cloud engine.
        engine_name = getattr(request.app.state, "engine_name", "local")
        new_multi = MultiEngine([(engine_name, inner), ("cloud", cloud)])
        if hasattr(outer, "_inner"):
            outer._inner = new_multi
        else:
            request.app.state.engine = new_multi
        request.app.state.engine_name = "multi"

    return {"status": "ok", "message": "Cloud engine reloaded"}


@router.get("/v1/savings")
async def savings(request: Request):
    """Return savings summary compared to cloud providers.

    Only includes telemetry from the current server session so that
    counters start at zero each time a new model + agent is launched.
    """
    from diapason.core.config import DEFAULT_CONFIG_DIR
    from diapason.server.savings import compute_savings, savings_to_dict
    from diapason.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        empty = compute_savings(0, 0, 0)
        return savings_to_dict(empty)

    session_start = getattr(request.app.state, "session_start", None)

    agg = TelemetryAggregator(db_path)
    try:
        # current_methodology_only excludes pre-fix legacy rows from
        # the leaderboard's per-token efficiency numerator/denominator
        # — see the comment on _time_filter for the bimodal-Wh/token
        # background.
        summary = agg.summary(since=session_start, current_methodology_only=True)
        # Exclude cloud model tokens from savings — only local
        # inference counts toward cost savings.
        _cloud_prefixes = (
            "gpt-",
            "o1-",
            "o3-",
            "o4-",
            "claude-",
            "gemini-",
            "openrouter/",
        )
        local_models = [
            m
            for m in summary.per_model
            if not any(m.model_id.startswith(p) for p in _cloud_prefixes)
        ]
        result = compute_savings(
            prompt_tokens=sum(m.prompt_tokens for m in local_models),
            completion_tokens=sum(m.completion_tokens for m in local_models),
            total_calls=sum(m.call_count for m in local_models),
            session_start=session_start if session_start else 0.0,
            prompt_tokens_evaluated=sum(
                m.prompt_tokens_evaluated for m in local_models
            ),
        )
        return savings_to_dict(result)
    finally:
        agg.close()


@router.post("/v1/telemetry/reset")
async def reset_telemetry():
    """Clear all stored telemetry records.

    Useful after updating token-counting methodology — clears
    historical records that were computed under the old rules so
    that the savings dashboard and leaderboard submissions start
    fresh with corrected values.
    """
    from diapason.core.config import DEFAULT_CONFIG_DIR
    from diapason.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        return {"status": "ok", "records_cleared": 0}

    agg = TelemetryAggregator(db_path)
    try:
        count = agg.clear()
    finally:
        agg.close()
    return {"status": "ok", "records_cleared": count}


@router.get("/v1/info")
async def server_info(request: Request):
    """Return server configuration: model, agent, engine."""
    agent = getattr(request.app.state, "agent", None)
    agent_id = getattr(agent, "agent_id", None) if agent else None
    # Fall back to configured agent name if agent didn't instantiate
    if agent_id is None:
        agent_id = getattr(request.app.state, "agent_name", None)
    from diapason.engine.ollama import _default_num_ctx

    return {
        "model": getattr(request.app.state, "model", ""),
        "agent": agent_id,
        "engine": getattr(request.app.state, "engine_name", ""),
        # Effective context window for LOCAL models: the engine sends this
        # num_ctx on every Ollama call, so a model's theoretical maximum is
        # capped by it in practice.
        "num_ctx": _default_num_ctx(),
    }


@router.get("/health")
async def health(request: Request):
    """Health check endpoint."""
    engine = request.app.state.engine
    healthy = engine.health()
    if not healthy:
        raise HTTPException(status_code=503, detail="Engine unhealthy")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Channel endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/channels")
async def list_channels(request: Request):
    """List available messaging channels."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"channels": [], "message": "Channel bridge not configured"}
    channels = bridge.list_channels()
    return {"channels": channels, "status": bridge.status().value}


@router.post("/v1/channels/send")
async def channel_send(request: Request):
    """Send a message to a channel."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="Channel bridge not configured")

    body = await request.json()
    channel_name = body.get("channel", "")
    content = body.get("content", "")
    conversation_id = body.get("conversation_id", "")

    if not channel_name or not content:
        raise HTTPException(
            status_code=400,
            detail="'channel' and 'content' are required",
        )

    ok = bridge.send(channel_name, content, conversation_id=conversation_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to send message")
    return {"status": "sent", "channel": channel_name}


@router.get("/v1/channels/status")
async def channel_status(request: Request):
    """Return channel bridge connection status."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"status": "not_configured"}
    return {"status": bridge.status().value}


# ---------------------------------------------------------------------------
# Security scan endpoint
# ---------------------------------------------------------------------------


@router.get("/v1/security/scan")
async def security_scan():
    """Run a read-only security environment audit and return findings."""
    from diapason.cli.scan_cmd import PrivacyScanner

    scanner = PrivacyScanner()
    results = scanner.run_all()
    return {
        "has_warnings": any(r.status == "warn" for r in results),
        "has_failures": any(r.status == "fail" for r in results),
        "findings": [
            {
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "platform": r.platform,
            }
            for r in results
        ],
    }


__all__ = ["router"]
