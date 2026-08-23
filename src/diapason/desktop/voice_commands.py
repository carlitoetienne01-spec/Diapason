"""Parse spoken commands into desktop tool actions."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_OPEN_RE = re.compile(
    r"^\s*(?:please\s+)?(?:ouvre(?:s)?(?:[- ]moi)?|ouvrez(?:[- ]moi)?|ouvrir|"
    r"open|lance(?:z)?(?:[- ]moi)?|lancer|launch|start|démarre|"
    r"show|montre|affiche)\s+"
    r"(?P<target>.+?)\s*$",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
_BROWSE_RE = re.compile(
    r"^\s*(?:go to|va sur|ouvre (?:le )?site|open (?:the )?(?:site|page|url))\s+"
    r"(?P<target>.+?)\s*$",
    re.IGNORECASE,
)
_SEARCH_RE = re.compile(
    # « recherche-moi des jeux » est la formulation NATURELLE à l'oral — elle
    # tombait dans le vide, le motif ne connaissant que « cherche » nu.
    r"^\s*(?:search(?:\s+for)?|(?:re)?cherche(?:r|z)?(?:[- ]moi)?"
    r"|trouve(?:z)?(?:[- ]moi)?|google|duckduckgo|bing)\s+"
    r"(?P<query>.+?)\s*$",
    re.IGNORECASE,
)

_APP_ALIASES = {
    "cursor": "Cursor",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "safari": "Safari",
    "firefox": "Firefox",
    "arc": "Arc",
    "spotify": "Spotify",
    "notes": "Notes",
    "note": "Notes",
    "terminal": "Terminal",
    "iterm": "iTerm",
    "finder": "Finder",
    "mail": "Mail",
    "mails": "Mail",
    "mes mails": "Mail",
    "courrier": "Mail",
    "messages": "Messages",
    "imessage": "Messages",
    "calendar": "Calendar",
    "calendrier": "Calendar",
    "photos": "Photos",
    "music": "Music",
    "musique": "Music",
    "maps": "Maps",
    "cartes": "Maps",
    "settings": "System Settings",
    "réglages": "System Settings",
    "system settings": "System Settings",
    "slack": "Slack",
    "discord": "Discord",
    "notion": "Notion",
    "figma": "Figma",
    "zoom": "zoom.us",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "obsidian": "Obsidian",
    "docker": "Docker",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "code": "Visual Studio Code",
    "xcode": "Xcode",
    "preview": "Preview",
    "aperçu": "Preview",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "claude": "https://claude.ai/new",
    "chatgpt": "https://chatgpt.com",
    "gmail": "https://mail.google.com",
    "youtube": "https://www.youtube.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "github": "https://github.com",
    "binance": "https://www.binance.com/en/trade/BTC_USDT",
    "google": "https://www.google.com",
}


@dataclass
class VoiceAction:
    # focus_app | open_uri | search | open_anything | spotify | mail/messages
    kind: str
    target: str = ""
    raw: str = ""
    extra: dict[str, Any] | None = None


def parse_voice_command(text: str) -> VoiceAction:
    raw = (text or "").strip()
    if not raw:
        return VoiceAction(kind="none", raw=raw)

    # Diapason-style rich intents first (YouTube / Spotify / Amazon / …)
    try:
        from diapason.desktop.smart_intents import KIND_NONE, parse_smart_intent

        intent = parse_smart_intent(raw)
        if intent.kind != KIND_NONE:
            if intent.kind == "app" and intent.app:
                return VoiceAction(kind="focus_app", target=intent.app, raw=raw)
            if intent.kind == "spotify" and intent.query:
                return VoiceAction(kind="spotify", target=intent.query, raw=raw)
            if intent.kind == "mail_compose":
                return VoiceAction(
                    kind="mail_compose",
                    target=intent.to,
                    raw=raw,
                    extra={
                        "to": intent.to,
                        "subject": intent.subject,
                        "body": intent.body,
                    },
                )
            if intent.kind == "messages_compose":
                return VoiceAction(
                    kind="messages_compose",
                    target=intent.to,
                    raw=raw,
                    extra={"recipient": intent.to, "body": intent.body},
                )
            if (
                intent.kind == "youtube"
                and intent.action in ("play", "play_mix")
                and intent.query
            ):
                # « joue X sur youtube » must PLAY, not strand the user on a
                # results page. This fast path used to discard the play
                # intent and open intent.url raw — the LLM was never even
                # consulted, so no prompt could fix it. play_mix : « de la
                # musique » sans titre — la radio YouTube (list=RD…) démarre
                # et s'enchaîne toute seule.
                from diapason.desktop.smart_intents import resolve_youtube_watch_url

                en_radio = intent.action == "play_mix"
                watch = resolve_youtube_watch_url(intent.query, mix=en_radio)
                return VoiceAction(
                    kind="open_uri",
                    target=watch or intent.url,
                    raw=raw,
                    extra={
                        "play": bool(watch),
                        "spoken": (
                            "de la musique sur YouTube"
                            if en_radio
                            else f"{intent.query} sur YouTube"
                        ),
                    },
                )
            if intent.url:
                return VoiceAction(kind="open_uri", target=intent.url, raw=raw)
            # Fallback: let open_anything re-parse
            return VoiceAction(kind="open_anything", target=raw, raw=raw)
    except Exception:
        logger.debug("smart intent parse failed", exc_info=True)

    url_m = _URL_RE.search(raw)
    if url_m:
        url = url_m.group(1)
        if url.startswith("www."):
            url = "https://" + url
        return VoiceAction(kind="open_uri", target=url, raw=raw)

    search_m = _SEARCH_RE.match(raw)
    if search_m:
        query = search_m.group("query").strip().strip(".!?")
        # « cherche des jeux SUR L'APP STORE » : la destination est dans la
        # phrase. Sans cette découpe, la recherche partait sur Google — la
        # mauvaise fenêtre s'ouvrait et l'utilisateur voyait un échec.
        porte = re.match(
            r"^(?P<quoi>.+?)\s+(?:sur|dans)\s+"
            r"(?:l['’]\s*|le\s+|la\s+|mon\s+|mes\s+)?(?P<ou>.+)$",
            query,
            re.IGNORECASE,
        )
        if porte:
            from diapason.tools.app_actions import _normaliser_app

            if _normaliser_app(porte.group("ou")) is not None:
                return VoiceAction(
                    kind="app_search",
                    target=porte.group("quoi").strip(),
                    raw=raw,
                    extra={"app": porte.group("ou").strip()},
                )
        return VoiceAction(kind="search", target=query, raw=raw)

    for pattern in (_OPEN_RE, _BROWSE_RE):
        m = pattern.match(raw)
        if not m:
            continue
        target = m.group("target").strip().strip(".!?,")
        # Whisper commonly renders « ouvre-moi l'application Notes » as
        # « ouvres-moi l'application note ». Strip the spoken wrapper before
        # alias/app-index resolution; passing "application note" to Launch
        # Services guarantees a false "app not found" response.
        target = re.sub(
            r"^(?:l['’]\s*)?(?:application|app)\s+",
            "",
            target,
            flags=re.IGNORECASE,
        )
        target = re.sub(
            r"^(?:le|la|les|the|site|page)\s+",
            "",
            target,
            flags=re.IGNORECASE,
        )
        # « l'application DE ChatGPT » : l'article tombait, le « de » restait,
        # et la cible devenait « de ChatGPT » — introuvable. Constaté sur la
        # machine de Carlito le 23 août 2026.
        target = re.sub(r"^(?:de\s+|d['’]\s*|du\s+)", "", target, flags=re.IGNORECASE)
        key = target.lower()
        mapped = _APP_ALIASES.get(key)
        if mapped and mapped.startswith("http"):
            return VoiceAction(kind="open_uri", target=mapped, raw=raw)
        if mapped:
            return VoiceAction(kind="focus_app", target=mapped, raw=raw)
        if "." in target and " " not in target:
            url = target if target.startswith("http") else f"https://{target}"
            return VoiceAction(kind="open_uri", target=url, raw=raw)
        # TOUTE application réellement installée part en chemin rapide :
        # 0,3 s au lieu de deux tours de modèle. L'alias écrit à la main ne
        # couvrait qu'une poignée de noms ; l'index couvre le disque entier,
        # accents et noms français compris.
        from diapason.desktop.app_index import APP_INDEX

        installee = APP_INDEX.lookup(target)
        if installee is not None:
            return VoiceAction(kind="focus_app", target=installee, raw=raw)
        # Delegate to open_anything for fuzzy app / search resolution
        return VoiceAction(kind="open_anything", target=target, raw=raw)

    # Bare alias: "cursor", "spotify"
    key = raw.lower().strip(".!?")
    if key in _APP_ALIASES:
        mapped = _APP_ALIASES[key]
        if mapped.startswith("http"):
            return VoiceAction(kind="open_uri", target=mapped, raw=raw)
        return VoiceAction(kind="focus_app", target=mapped, raw=raw)

    return VoiceAction(kind="none", raw=raw)


def is_explicit_voice_command(text: str) -> bool:
    """True only when the user actually uttered an action verb.

    A bare app name may be a valid follow-up, but it may also be Whisper's
    favourite silence hallucination. The realtime fast path therefore acts
    only on explicit imperatives such as « ouvre Notes ».
    """
    raw = (text or "").strip()
    if raw.lower().strip(".!?") in _APP_ALIASES:
        return False
    return bool(_OPEN_RE.match(raw) or _BROWSE_RE.match(raw) or _SEARCH_RE.match(raw))


def execute_voice_action(action: VoiceAction) -> dict[str, Any]:
    import diapason.tools  # noqa: F401
    from diapason.tools.desktop_tools import (
        OpenAnythingTool,
        OpenUriTool,
        open_application,
        open_in_browser,
        web_search_url,
    )

    if action.kind == "open_uri":
        result = OpenUriTool().execute(uri=action.target)
        return {
            "handled": True,
            "kind": action.kind,
            "target": action.target,
            "success": result.success,
            "detail": result.content,
        }
    if action.kind == "app_search":
        from diapason.tools.app_actions import AppSearchTool

        result = AppSearchTool().execute(
            app=str((action.extra or {}).get("app") or ""), query=action.target
        )
        return {
            "handled": True,
            "kind": action.kind,
            "target": action.target,
            "success": result.success,
            "detail": result.content,
        }
    if action.kind == "focus_app":
        # Launch Services already activates the app. Avoid the historical
        # second osascript process, which added noticeable latency to the most
        # common command ("ouvre Notes").
        result = open_application(action.target)
        return {
            "handled": True,
            "kind": action.kind,
            "target": action.target,
            # « déjà devant » / « remise devant » / « lancée » — la voix
            # choisit sa phrase d'après la réalité constatée, pas l'inverse.
            "etat": str((result.metadata or {}).get("etat") or ""),
            "success": result.success,
            "detail": result.content,
        }
    if action.kind == "spotify":
        from diapason.tools.voice_mac_tools import SpotifyPlayTool

        result = SpotifyPlayTool().execute(query=action.target, action="search")
        return {
            "handled": True,
            "kind": action.kind,
            "target": action.target,
            "success": result.success,
            "detail": result.content,
        }
    if action.kind == "mail_compose":
        from diapason.tools.voice_mac_tools import MailComposeTool

        params = dict(action.extra or {})
        if action.target and not params.get("to"):
            params["to"] = action.target
        result = MailComposeTool().execute(**params)
        return {
            "handled": True,
            "kind": action.kind,
            "target": action.target,
            "success": result.success,
            "detail": result.content,
        }
    if action.kind == "messages_compose":
        from diapason.tools.voice_mac_tools import MessagesComposeTool

        params = dict(action.extra or {})
        if action.target and not params.get("recipient"):
            params["recipient"] = action.target
        result = MessagesComposeTool().execute(**params)
        return {
            "handled": True,
            "kind": action.kind,
            "target": action.target,
            "success": result.success,
            "detail": result.content,
        }
    if action.kind == "search":
        result = open_in_browser(web_search_url(action.target))
        return {
            "handled": True,
            "kind": action.kind,
            "target": action.target,
            "success": result.success,
            "detail": result.content,
        }
    if action.kind == "open_anything":
        result = OpenAnythingTool().execute(target=action.target, kind="auto")
        return {
            "handled": True,
            "kind": action.kind,
            "target": action.target,
            "success": result.success,
            "detail": result.content,
        }
    return {
        "handled": False,
        "kind": "none",
        "target": "",
        "success": False,
        "detail": "",
    }


def finalize_dictation(
    raw: str,
    *,
    polish: bool = True,
    llm_polish: bool | None = None,
    email_mode: bool | None = None,
    use_dictionary: bool | None = None,
) -> dict[str, Any]:
    """Decide command vs paste; polish only on the paste path.

    Command detection runs on raw STT first, then on locally filler-stripped
    text (no dictionary / LLM) so « um open Spotify » still routes as a command.
    """
    from diapason.speech.dictate_polish import polish_dictation, polish_pipeline

    cfg_dict = True
    cfg_llm = False
    cfg_email = False
    cfg_timeout = 2000
    cfg_auto_learn = True
    dict_path = ""
    do_polish = bool(polish)
    try:
        from diapason.core.config import load_config

        d = load_config().dictation
        # Request polish=False always wins; polish=True also needs config on
        do_polish = bool(polish) and bool(d.polish)
        cfg_dict = (
            bool(d.dictionary) if use_dictionary is None else bool(use_dictionary)
        )
        cfg_llm = bool(d.llm_polish) if llm_polish is None else bool(llm_polish)
        mode = (d.email_mode or "off").strip().lower()
        if email_mode is None:
            if mode in ("on", "true", "1", "yes"):
                cfg_email = True
            elif mode == "auto":
                try:
                    from diapason.desktop.frontmost import is_email_composer_context

                    cfg_email = is_email_composer_context()
                except Exception:
                    cfg_email = False
            else:
                cfg_email = False
        else:
            cfg_email = bool(email_mode)
        cfg_timeout = int(d.llm_timeout_ms or 2000)
        dict_path = (d.dictionary_path or "").strip()
        cfg_auto_learn = bool(getattr(d, "auto_learn", True))
    except Exception:
        do_polish = bool(polish)
        if use_dictionary is not None:
            cfg_dict = bool(use_dictionary)
        if llm_polish is not None:
            cfg_llm = bool(llm_polish)
        if email_mode is not None:
            cfg_email = bool(email_mode)

    if not polish:
        do_polish = False

    text_gate = True
    try:
        from diapason.core.config import load_config as _lc

        text_gate = bool(_lc().speech.wakeword.text_gate)
    except Exception:
        text_gate = True

    from diapason.speech.wake_phrases import has_wake_word, strip_wake_word

    wake_hit = bool(text_gate and has_wake_word(raw))
    stripped = strip_wake_word(raw) if wake_hit else (raw or "").strip()

    action = parse_voice_command(raw)
    if action.kind == "none" and wake_hit and stripped:
        action = parse_voice_command(stripped)
    if action.kind == "none":
        cleaned_for_cmd = polish_dictation(
            stripped if wake_hit else raw, aggressive=True
        )
        if cleaned_for_cmd and cleaned_for_cmd != (raw or "").strip():
            action = parse_voice_command(cleaned_for_cmd)

    if action.kind != "none":
        exec_result = execute_voice_action(action)
        return {
            "mode": "command",
            "original": raw,
            "text": stripped if wake_hit and stripped else raw,
            "action": exec_result,
            "meta": {"wake_word": wake_hit},
        }

    # Bare wake (« Hey Diapason ») → hint UI to open Talk
    if wake_hit and not stripped:
        return {
            "mode": "wake",
            "original": raw,
            "text": "",
            "action": None,
            "meta": {"wake_word": True, "suggest": "talk_open"},
        }

    paste_source = stripped if wake_hit and stripped else raw
    text = polish_pipeline(
        paste_source,
        polish=do_polish,
        use_dictionary=cfg_dict and do_polish,
        llm_polish=cfg_llm and do_polish,
        email_mode=cfg_email,
        llm_timeout_ms=cfg_timeout,
        dictionary_path=dict_path or None,
    )

    learned = 0
    if (
        cfg_auto_learn
        and do_polish
        and cfg_dict
        and (paste_source or "").strip()
        and text.strip()
        and text.strip() != (paste_source or "").strip()
    ):
        try:
            from diapason.speech.dictation_dictionary import learn_from_correction

            entries = learn_from_correction(paste_source, text, path=dict_path or None)
            learned = len(entries)
        except Exception:
            learned = 0

    return {
        "mode": "paste",
        "original": raw,
        "text": text,
        "action": None,
        "meta": {
            "dictionary": cfg_dict and do_polish,
            "llm_polish": cfg_llm and do_polish,
            "email_mode": cfg_email,
            "wake_word": wake_hit,
            "auto_learn": cfg_auto_learn,
            "learned": learned,
        },
    }
