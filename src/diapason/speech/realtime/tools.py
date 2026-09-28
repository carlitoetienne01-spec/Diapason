"""Safe desktop tools for realtime voice sessions (capped step budget)."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

# Diapason-parity allow-list for live voice.
DEFAULT_VOICE_TOOL_IDS: tuple[str, ...] = (
    # current_time, memory_manage et user_profile_manage manquaient. Le modèle
    # RÉCLAMAIT current_time à « quelle heure est-il ? » et se voyait répondre
    # « Tool not allowed in voice mode » — il s'en tirait grâce à l'horloge
    # collée dans le prompt, mais tout ce qui dépend de « maintenant » sans y
    # figurer (« dans combien de jours », « c'était quand ») restait hors
    # d'atteinte. Et surtout : à la voix, « retiens que… » n'écrivait nulle
    # part, exactement le défaut corrigé pour le chat le même jour.
    "calculator",
    "current_time",
    "memory_manage",
    "user_profile_manage",
    # « Qu'est-ce que j'ai noté sur… » les mains prises : le savoir
    # personnel (Obsidian, Apple Notes) répond aussi à la voix (23/08/2026).
    "knowledge_search",
    "knowledge_get_document",
    # « Qu'est-ce que j'ai manqué ? » les mains prises (Atlas, 24/08/2026).
    "digest_collect",
    "open_anything",
    "open_uri",
    "focus_app",
    "open_browser_on_monitor",
    "run_voice_command",
    "calendar_query",
    "spotify_play",
    "web_search",
    # 21/09/2026 : la voix lit la page d'un poste après une recherche, comme
    # le chat (actualite_vocale) — sans elle, « Justin Trudeau » à la voix.
    "web_read",
    "find_files",
    "mail_compose",
    "messages_compose",
    "mail_send",
    "messages_send",
    "messages_status",
    "browser_tabs",
    "file_trash",
    "gmail_search",
    "mail_archive",
    "mail_trash",
    "imessage_conversation",
    "screen_describe",
    "screen_read_text",
    "screen_share_start",
    "screen_share_stop",
    "screen_share_status",
    "vie_tasks",
    "vie_workspace",
    "vie_continuity",
    "vie_finances",
    # La suppression, demandée le 23 août 2026 — dans Diapason SEULEMENT.
    # Les trois outils déclarent requires_confirmation : l'ordre part à la
    # cloche d'approbation et attend le clic de l'utilisateur (45 s à la
    # voix). Supprimer un fichier du disque, envoyer, exécuter du code
    # restent hors de portée de la voix, quoi qu'on lui dise.
    # Agir DANS une application — chercher, écrire — demandé le 23 août 2026 :
    # « des fois mes mains ne sont pas libres ». Ouvrir ne suffit pas.
    "app_search",
    "app_install",
    "notes_write",
    "reminders_write",
    "calendar_add",
    "vie_delete_task",
    "vie_delete_item",
    "vie_delete_continuity",
    # Les gestes d'une seconde (Atlas, 24 août 2026) : « monte le son »,
    # « mets pause », « qu'est-ce que j'ai copié ? » — des réflexes, pas des
    # projets. Tous visibles, réversibles et 100 % locaux.
    "volume_control",
    "media_control",
    "clipboard_read",
    "screen_snap",
    "system_vitals",
    # Le geste, terminé à la voix (25 août 2026) : « envoie ça sur mon
    # téléphone », ou la réponse à la question « vers lequel ? » que le
    # serveur a posée. Contrairement à `mesh_send` — délibérément absent
    # d'ici — il ne choisit ni ce qu'il envoie (c'est la main) ni l'action
    # (elle découle du type de l'objet), et quand une question est en
    # attente il tranche dans une liste FERMÉE que le serveur a mesurée.
    # Une transcription approximative ne peut donc pas inventer une cible.
    "geste_deposer",
)

# (module, [(registry_key, attribute_name), ...])
# Les gestes qui méritent un accusé OPTIMISTE (Atlas, 24 août 2026) : tous
# locaux, sans confirmation, exécution sous la seconde — un « Ça marche. »
# pré-rendu part pendant que le geste s'exécute, et la deuxième passe LLM se
# déroule pendant qu'il joue. JAMAIS un envoi, une suppression ou un outil à
# cloche : là, seul le constat a droit de parole.
FAST_ACK_TOOL_IDS = frozenset(
    {
        "volume_control",
        "media_control",
        "clipboard_read",
        "system_vitals",
        "current_time",
        "screen_snap",
        "focus_app",
    }
)

_TOOL_MODULES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("diapason.tools.calculator", (("calculator", "CalculatorTool"),)),
    (
        "diapason.tools.gestes_spatiaux",
        (("geste_deposer", "GesteDeposerTool"),),
    ),
    (
        "diapason.tools.knowledge_search",
        (
            ("knowledge_search", "KnowledgeSearchTool"),
            ("knowledge_get_document", "KnowledgeGetDocumentTool"),
        ),
    ),
    (
        "diapason.tools.gmail_live",
        (
            ("gmail_search", "GmailSearchTool"),
            ("mail_archive", "MailArchiveTool"),
            ("mail_trash", "MailTrashTool"),
        ),
    ),
    (
        "diapason.tools.imessage_tools",
        (("imessage_conversation", "IMessageConversationTool"),),
    ),
    (
        "diapason.tools.digest_collect",
        (("digest_collect", "DigestCollectTool"),),
    ),
    (
        "diapason.tools.desktop_tools",
        (
            ("open_anything", "OpenAnythingTool"),
            ("open_uri", "OpenUriTool"),
            ("focus_app", "FocusAppTool"),
            ("open_browser_on_monitor", "OpenBrowserOnMonitorTool"),
            ("run_voice_command", "RunVoiceCommandTool"),
        ),
    ),
    (
        "diapason.tools.voice_mac_tools",
        (
            ("calendar_query", "CalendarQueryTool"),
            ("spotify_play", "SpotifyPlayTool"),
            ("find_files", "FindFilesTool"),
            ("mail_compose", "MailComposeTool"),
            ("messages_compose", "MessagesComposeTool"),
            ("mail_send", "MailSendTool"),
            ("messages_send", "MessagesSendTool"),
            ("messages_status", "MessagesStatusTool"),
            ("file_trash", "FileTrashTool"),
        ),
    ),
    (
        "diapason.tools.screen_vision_tools",
        (
            ("screen_describe", "ScreenDescribeTool"),
            ("screen_read_text", "ScreenReadTextTool"),
            ("screen_share_start", "ScreenShareStartTool"),
            ("screen_share_stop", "ScreenShareStopTool"),
            ("screen_share_status", "ScreenShareStatusTool"),
        ),
    ),
    (
        "diapason.tools.web_search",
        (("web_search", "WebSearchTool"),),
    ),
    (
        "diapason.tools.web_read",
        (("web_read", "WebReadTool"),),
    ),
    (
        "diapason.tools.vie_tasks",
        (("vie_tasks", "VieTasksTool"),),
    ),
    (
        "diapason.tools.vie_workspace",
        (("vie_workspace", "VieWorkspaceTool"),),
    ),
    (
        "diapason.tools.vie_continuity",
        (("vie_continuity", "VieContinuityTool"),),
    ),
    (
        "diapason.tools.vie_finances",
        (("vie_finances", "VieFinancesTool"),),
    ),
    (
        "diapason.tools.browser_tabs",
        (("browser_tabs", "BrowserTabsTool"),),
    ),
    (
        "diapason.tools.gestes",
        (
            ("volume_control", "VolumeControlTool"),
            ("media_control", "MediaControlTool"),
            ("clipboard_read", "ClipboardReadTool"),
            ("screen_snap", "ScreenSnapTool"),
            ("system_vitals", "SystemVitalsTool"),
        ),
    ),
)


def _ensure_desktop_tools_loaded() -> None:
    """Import and (re)register voice tools — safe after ToolRegistry.clear()."""
    from diapason.core.registry import ToolRegistry

    for mod_name, entries in _TOOL_MODULES:
        try:
            mod = __import__(mod_name, fromlist=[name for _, name in entries])
        except Exception:
            logger.debug("could not load %s", mod_name, exc_info=True)
            continue
        for key, attr in entries:
            if ToolRegistry.contains(key):
                continue
            cls = getattr(mod, attr, None)
            if cls is None:
                continue
            try:
                ToolRegistry.register_value(key, cls)
            except Exception:
                logger.debug("could not register %s", key, exc_info=True)


def list_voice_tool_ids(
    allowed: Optional[Sequence[str]] = None,
) -> list[str]:
    _ensure_desktop_tools_loaded()
    from diapason.core.noms_outils import noms_canoniques, signaler_outil_inconnu
    from diapason.core.registry import ToolRegistry

    # 25/09/2026 : `allowed` vient de la configuration ([speech.realtime]
    # tools) et peut encore citer succes_tasks ; traduit avant de filtrer.
    wanted = noms_canoniques(allowed) if allowed else DEFAULT_VOICE_TOOL_IDS
    available = set(ToolRegistry.keys())
    retenus = []
    for tid in wanted:
        if tid in available:
            retenus.append(tid)
        else:
            # Écarté en silence jusqu'au 25/09/2026 : la voix perdait un outil
            # (dépendance absente, nom resté ancien) sans que rien ne le dise.
            signaler_outil_inconnu("voix", tid)
    return retenus


def outils_vocaux_du_telephone(
    allowed: Optional[Sequence[str]] = None,
) -> list[str]:
    """La trousse de la voix quand la séance vient du téléphone (26/09/2026).

    Le plafond du téléphone (core/origine_telephone.py) refuse déjà, dans
    l'exécuteur, tout outil hors de OUTILS_DU_TELEPHONE. Mais le modèle
    voyait encore les schémas de open_anything, screen_read_text ou
    clipboard_read : il promettait d'ouvrir une app sur le Mac, puis
    échouait. On lui retire ce qu'on lui refuserait de toute façon.

    Rend la liste EXPLICITE, jamais None : ailleurs, une liste vide ou None
    veut dire « le défaut », c'est-à-dire tout DEFAULT_VOICE_TOOL_IDS. Une
    liste vide ici veut dire « aucun outil » — l'appelant coupe les outils.
    """
    from diapason.core.noms_outils import noms_canoniques
    from diapason.core.origine_telephone import outil_permis_au_telephone

    base = noms_canoniques(allowed) if allowed else list(DEFAULT_VOICE_TOOL_IDS)
    return [tid for tid in base if outil_permis_au_telephone(tid)]


def gemini_function_declarations(
    allowed: Optional[Sequence[str]] = None,
) -> list[dict[str, Any]]:
    """Gemini Live ``functionDeclarations`` list."""
    _ensure_desktop_tools_loaded()
    from diapason.core.registry import ToolRegistry

    decls: list[dict[str, Any]] = []
    for tid in list_voice_tool_ids(allowed):
        try:
            tool = ToolRegistry.create(tid)
        except Exception:
            continue
        spec = tool.spec
        decls.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters or {"type": "object", "properties": {}},
            }
        )
    return decls


def openai_tools_schema(
    allowed: Optional[Sequence[str]] = None,
) -> list[dict[str, Any]]:
    """OpenAI Realtime ``session.tools`` entries."""
    _ensure_desktop_tools_loaded()
    from diapason.core.registry import ToolRegistry

    out: list[dict[str, Any]] = []
    for tid in list_voice_tool_ids(allowed):
        try:
            tool = ToolRegistry.create(tid)
        except Exception:
            continue
        out.append(tool.to_openai_function())
    return out


# Attendre l'accord de l'utilisateur, à la voix.
#
# Le pont d'approbation laisse deux minutes au chat : la cloche est à l'écran,
# la fenêtre est ouverte, rien ne presse. Une conversation parlée ne supporte
# pas ce silence — deux minutes sans réponse, c'est une panne, pas une
# attente. Quarante-cinq secondes suffisent à porter le regard sur la cloche
# et à cliquer ; passé ce délai, le refus est franc et Diapason le DIT, ce
# qui vaut mieux qu'un blanc.
VOICE_APPROVAL_WAIT_S = 45.0

_executeurs: dict[tuple[str, ...], Any] = {}


def _executeur_pour(ids: Sequence[str]) -> Any:
    """Le ToolExecutor de la voix, construit une fois par liste d'outils.

    Le construire coûte le chargement de la configuration et des contrôles de
    sécurité ; une session vocale en appelle plusieurs par tour.
    """
    cle = tuple(ids)
    existant = _executeurs.get(cle)
    if existant is not None:
        return existant

    from diapason.core.registry import ToolRegistry
    from diapason.server.approval_bridge import tool_confirm_callback
    from diapason.tools._stubs import BaseTool, ToolExecutor

    instances = []
    for tid in ids:
        classe = ToolRegistry.get(tid)
        if isinstance(classe, type) and issubclass(classe, BaseTool):
            instances.append(classe())
        elif isinstance(classe, BaseTool):
            instances.append(classe)

    executeur = ToolExecutor(
        instances,
        None,
        interactive=True,
        confirm_callback=tool_confirm_callback(VOICE_APPROVAL_WAIT_S),
        agent_id="voice",
    )
    _executeurs[cle] = executeur
    return executeur


def execute_voice_tool(
    name: str,
    arguments: Optional[dict[str, Any]] = None,
    allowed: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Run an allow-listed tool through the executor; JSON-serializable payload.

    Cette fonction appelait ``tool.execute(**args)`` EN DIRECT. Elle sautait
    donc ``ToolExecutor``, et avec lui la politique de capacités, le
    garde-frontière, le limiteur de débit et — le plus grave — la confirmation
    des actions sensibles. Or ``mail_send`` et ``messages_send`` figurent dans
    la liste vocale : une phrase mal comprise pouvait envoyer un courriel ou un
    SMS au nom de l'utilisateur, sans que rien ne lui soit demandé.

    Le commentaire « never auto-send from live voice — drafts only » ne
    protégeait que ``mail_compose`` et ``messages_compose``. Les deux outils
    d'envoi, eux, passaient à côté.

    La liste d'autorisation reste la première barrière ; l'exécuteur est la
    seconde, et c'est celle qui demande l'accord.
    """
    _ensure_desktop_tools_loaded()
    from diapason.core.noms_outils import nom_canonique
    from diapason.core.types import ToolCall

    # Le modèle peut appeler l'ancien nom (SOUL.md le lui apprend encore) :
    # traduit AVANT la liste d'autorisation, qui ne connaît que les noms neufs.
    tid = nom_canonique((name or "").strip())
    ids = list_voice_tool_ids(allowed)
    if tid not in set(ids):
        return {"ok": False, "error": f"Tool not allowed in voice mode: {tid}"}
    try:
        args = dict(arguments or {})
        # Never auto-send from live voice — drafts only.
        if tid in ("mail_compose", "messages_compose"):
            args.pop("send", None)
        resultat = _executeur_pour(ids).execute(
            ToolCall(
                id=f"voice-{tid}", name=tid, arguments=json.dumps(args, default=str)
            )
        )
        return {
            "ok": bool(resultat.success),
            "content": resultat.content,
            "metadata": getattr(resultat, "metadata", None) or {},
        }
    except Exception as exc:
        logger.exception("voice tool %s failed", tid)
        return {"ok": False, "error": str(exc)}


class VoiceToolBudget:
    """Limit chained tool calls inside one TURN.

    The cap used to be per-session and never reset: after twelve tool calls
    spread over a long conversation, every later "joue X" silently failed
    with "budget exceeded" for the rest of the session. The loop bound it
    exists for (a model asking for tools forever) is a per-turn problem.
    """

    def __init__(self, max_steps: int = 12) -> None:
        self.max_steps = max(0, int(max_steps))
        self.used = 0

    def allow(self) -> bool:
        return self.used < self.max_steps

    def consume(self) -> None:
        self.used += 1

    def reset(self) -> None:
        self.used = 0


__all__ = [
    "DEFAULT_VOICE_TOOL_IDS",
    "VoiceToolBudget",
    "execute_voice_tool",
    "gemini_function_declarations",
    "list_voice_tool_ids",
    "openai_tools_schema",
    "outils_vocaux_du_telephone",
]
