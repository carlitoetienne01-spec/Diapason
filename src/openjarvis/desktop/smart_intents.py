"""Diapason-style smart browser/app intents (pattern matching, FR + EN).

Ports the fast heuristics from jarvis-ai-assistant SmartBrowserService /
AICommandParser.tryFastParse — no cloud AI required for obvious commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote, quote_plus

from openjarvis.core.types import ToolResult


@dataclass(slots=True)
class SmartIntent:
    """Resolved open/search/play intent."""

    kind: str  # see KIND_* constants
    query: str = ""
    url: str = ""
    app: str = ""
    to: str = ""
    subject: str = ""
    body: str = ""
    confidence: float = 0.0
    reasoning: str = ""


KIND_YOUTUBE = "youtube"
KIND_SPOTIFY = "spotify"
KIND_AMAZON = "amazon"
KIND_NETFLIX = "netflix"
KIND_GMAIL = "gmail"
KIND_MAIL_COMPOSE = "mail_compose"
KIND_MESSAGES_COMPOSE = "messages_compose"
KIND_URL = "url"
KIND_APP = "app"
KIND_WEB_SEARCH = "web_search"
KIND_NONE = "none"

_WEBSITES: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com",
    "gmail": "https://mail.google.com",
    "outlook": "https://outlook.live.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com",
    "github": "https://github.com",
    "notion": "https://www.notion.so",
    "drive": "https://drive.google.com",
    "google drive": "https://drive.google.com",
    "dropbox": "https://www.dropbox.com",
    "whatsapp web": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai/new",
}

_NATIVE_APPS: dict[str, str] = {
    "safari": "Safari",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "firefox": "Firefox",
    "arc": "Arc",
    "mail": "Mail",
    "apple mail": "Mail",
    "messages": "Messages",
    "whatsapp": "WhatsApp",
    "discord": "Discord",
    "slack": "Slack",
    "zoom": "zoom.us",
    "notes": "Notes",
    "spotify": "Spotify",
    "spotify app": "Spotify",
    "cursor": "Cursor",
    "terminal": "Terminal",
    "finder": "Finder",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "code": "Visual Studio Code",
}


def _clean_query(text: str, *strip_words: str) -> str:
    q = text
    for w in strip_words:
        q = re.sub(rf"\b{re.escape(w)}\b", " ", q, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", q).strip(" .,!?;:")


def parse_smart_intent(command: str) -> SmartIntent:
    """Parse a spoken/typed command into a SmartIntent (best-effort)."""
    raw = (command or "").strip()
    if not raw:
        return SmartIntent(kind=KIND_NONE)

    low = raw.lower().strip()

    # --- YouTube ---
    if "youtube" in low:
        for pat, action in (
            (
                r"(?:ouvre|open)\s+youtube\s+(?:et|and)\s+(?:cherche|search(?:\s+for)?)\s+(.+)",
                "search",
            ),
            (r"youtube\s+(?:cherche|search(?:\s+for)?)\s+(.+)", "search"),
            (r"(?:cherche|search(?:\s+for)?)\s+(.+?)\s+(?:sur|on)\s+youtube", "search"),
            (r"(?:joue|play|regarde|watch)\s+(.+?)\s+(?:sur|on)\s+youtube", "play"),
            (r"youtube\s+(.+)", "search"),
        ):
            m = re.search(pat, low, re.IGNORECASE)
            if m:
                q = m.group(1).strip()
                q = _clean_query(q, "for", "the", "le", "la", "les", "des")
                if q:
                    return SmartIntent(
                        kind=KIND_YOUTUBE,
                        query=q,
                        url=(
                            "https://www.youtube.com/results?search_query="
                            + quote_plus(q)
                        ),
                        confidence=0.92,
                        reasoning=f"YouTube {action}",
                    )
        return SmartIntent(
            kind=KIND_URL,
            url="https://www.youtube.com",
            confidence=0.9,
            reasoning="YouTube home",
        )

    # --- Spotify ---
    if "spotify" in low or re.search(
        r"\b(?:écoute|ecoute|listen(?:\s+to)?|joue|play)\b.+\b(?:musique|music|song|chanson)\b",
        low,
    ):
        for pat in (
            r"(?:ouvre|open)\s+spotify\s+(?:et|and)\s+(?:cherche|search(?:\s+for)?|joue|play)\s+(.+)",
            r"(?:joue|play|écoute|ecoute|listen(?:\s+to)?)\s+(.+?)\s+(?:sur|on)\s+spotify",
            r"spotify\s+(?:cherche|search(?:\s+for)?|joue|play)\s+(.+)",
            r"spotify\s+(.+)",
            r"(?:joue|play|écoute|ecoute)\s+(.+)",
        ):
            m = re.search(pat, low, re.IGNORECASE)
            if m:
                q = _clean_query(
                    m.group(1),
                    "for",
                    "the",
                    "le",
                    "la",
                    "de",
                    "du",
                    "music",
                    "musique",
                    "song",
                    "chanson",
                )
                if q and q not in {"spotify", "app"}:
                    return SmartIntent(
                        kind=KIND_SPOTIFY,
                        query=q,
                        url=f"spotify:search:{quote(q)}",
                        confidence=0.9,
                        reasoning="Spotify search/play",
                    )
        if "spotify" in low:
            return SmartIntent(
                kind=KIND_APP,
                app="Spotify",
                confidence=0.88,
                reasoning="Open Spotify app",
            )

    # --- Amazon ---
    if "amazon" in low:
        for pat in (
            r"(?:cherche|search(?:\s+for)?|achète|achete|buy|shop(?:\s+for)?)\s+(.+?)\s+(?:sur|on)\s+amazon",
            r"amazon\s+(?:cherche|search(?:\s+for)?)\s+(.+)",
            r"amazon\s+(.+)",
        ):
            m = re.search(pat, low, re.IGNORECASE)
            if m:
                q = _clean_query(m.group(1), "for", "the", "le", "la", "un", "une")
                if q and q != "amazon":
                    return SmartIntent(
                        kind=KIND_AMAZON,
                        query=q,
                        url=("https://www.amazon.com/s?k=" + quote_plus(q)),
                        confidence=0.9,
                        reasoning="Amazon search",
                    )
        return SmartIntent(
            kind=KIND_URL,
            url="https://www.amazon.com",
            confidence=0.85,
            reasoning="Amazon home",
        )

    # --- Netflix ---
    if "netflix" in low:
        m = re.search(
            r"(?:cherche|search(?:\s+for)?|joue|play|regarde|watch)\s+(.+?)\s+(?:sur|on)\s+netflix|"
            r"netflix\s+(.+)",
            low,
            re.IGNORECASE,
        )
        if m:
            q = _clean_query((m.group(1) or m.group(2) or ""), "for", "the")
            if q and q != "netflix":
                return SmartIntent(
                    kind=KIND_NETFLIX,
                    query=q,
                    url="https://www.netflix.com/search?q=" + quote_plus(q),
                    confidence=0.88,
                    reasoning="Netflix search",
                )
        return SmartIntent(
            kind=KIND_URL,
            url="https://www.netflix.com",
            confidence=0.9,
            reasoning="Netflix home",
        )

    # --- Mail / Messages compose (drafts only; before open-Gmail) ---
    mail_m = re.search(
        r"(?:écris|ecris|rédige|redige|compose|write|envoie|envoyer|send)\s+"
        r"(?:un\s+|an?\s+)?(?:mail|e-?mail|courriel)\s+"
        r"(?:à|a|to)\s+(?P<to>\S+)"
        r"(?:\s+(?:au sujet de|sujet|about|re|subject)\s+(?P<subject>.+?))?"
        r"(?:\s+(?:disant|saying|pour dire|body|:)\s+(?P<body>.+))?$",
        low,
        re.IGNORECASE,
    )
    if not mail_m:
        mail_m = re.search(
            r"(?:email|e-mail)\s+(?P<to>\S+)\s+(?:about|re|sujet)\s+(?P<subject>.+)$",
            low,
            re.IGNORECASE,
        )
    if mail_m:
        to = (mail_m.groupdict().get("to") or "").strip(" .,!?;:")
        subject = (mail_m.groupdict().get("subject") or "").strip(" .,!?;:")
        body = (mail_m.groupdict().get("body") or "").strip()
        if to:
            return SmartIntent(
                kind=KIND_MAIL_COMPOSE,
                to=to,
                subject=subject,
                body=body or subject,
                confidence=0.9,
                reasoning="Mail compose draft",
            )

    msg_m = re.search(
        r"(?:envoie|envoyer|send)\s+(?:un\s+|an?\s+)?(?:message|sms|imessage|texto)\s+"
        r"(?:à|a|to)\s+(?P<to>.+?)"
        r"(?:\s+(?:disant|saying|pour dire|:)\s+(?P<body>.+))?$",
        low,
        re.IGNORECASE,
    )
    if not msg_m:
        msg_m = re.search(
            r"(?:message|text|texte|imessage)\s+(?:à|a|to\s+)?(?P<to>\S+)"
            r"(?:\s+(?:disant|saying|pour dire|:)\s+(?P<body>.+))?$",
            low,
            re.IGNORECASE,
        )
    if msg_m:
        to = (msg_m.group("to") or "").strip(" .,!?;:")
        body = (msg_m.groupdict().get("body") or "").strip()
        # Don't steal bare "messages" / "message" app opens
        if to and to not in {"messages", "message", "sms"}:
            return SmartIntent(
                kind=KIND_MESSAGES_COMPOSE,
                to=to,
                body=body,
                confidence=0.88,
                reasoning="Messages compose draft",
            )

    # --- Gmail / email web ---
    if "gmail" in low or re.search(
        r"\b(?:check(?:\s+my)?\s+email|ouvre\s+(?:mes\s+)?mails?|check\s+mail)\b",
        low,
    ):
        if "apple mail" not in low:
            return SmartIntent(
                kind=KIND_GMAIL,
                url="https://mail.google.com",
                confidence=0.9,
                reasoning="Gmail",
            )

    # --- WhatsApp Web ---
    if "whatsapp" in low and any(w in low for w in ("web", "chrome", "browser", "navigateur")):
        return SmartIntent(
            kind=KIND_URL,
            url="https://web.whatsapp.com",
            confidence=0.95,
            reasoning="WhatsApp Web",
        )

    # --- Social homes ---
    for name, url in (
        ("facebook", "https://www.facebook.com"),
        ("instagram", "https://www.instagram.com"),
        ("linkedin", "https://www.linkedin.com"),
        ("reddit", "https://www.reddit.com"),
        ("twitter", "https://x.com"),
    ):
        if re.search(
            rf"\b(?:ouvre|open|go to|va sur|check|vérifie)\s+{name}\b|\b{name}\b$",
            low,
        ):
            # Don't steal "open twitter and search …" if we add later
            if "search" in low or "cherche" in low:
                continue
            return SmartIntent(
                kind=KIND_URL, url=url, confidence=0.9, reasoning=f"{name} home"
            )

    # --- Explicit website map / open X.com ---
    m = re.search(
        r"(?:ouvre|open|go to|va sur)\s+(?:le site |the (?:site|page) )?(?P<site>[\w.-]+\.(?:com|org|net|io|ai|co|fr|dev))\b",
        low,
    )
    if m:
        host = m.group("site")
        return SmartIntent(
            kind=KIND_URL,
            url=f"https://{host}",
            confidence=0.95,
            reasoning="Navigate domain",
        )

    # --- Open native app / known website alias ---
    m = re.search(
        r"^\s*(?:please\s+)?(?:ouvre|ouvrir|open|lance|lancer|launch|start|démarre|"
        r"show|montre)\s+(?:l['’]|le |la |les |the |app |application )?(?P<target>.+?)\s*$",
        low,
        re.IGNORECASE,
    )
    if m:
        target = m.group("target").strip().strip(".!?")
        # "youtube and search for cats" already handled above if youtube in string
        if target in _NATIVE_APPS:
            return SmartIntent(
                kind=KIND_APP,
                app=_NATIVE_APPS[target],
                confidence=0.95,
                reasoning="Native app",
            )
        if target in _WEBSITES:
            return SmartIntent(
                kind=KIND_URL,
                url=_WEBSITES[target],
                confidence=0.92,
                reasoning="Website shortcut",
            )
        # "spotify app"
        if target.endswith(" app") and target[:-4] in _NATIVE_APPS:
            return SmartIntent(
                kind=KIND_APP,
                app=_NATIVE_APPS[target[:-4]],
                confidence=0.93,
                reasoning="Native app suffix",
            )

    # Bare website alias
    if low in _WEBSITES:
        return SmartIntent(
            kind=KIND_URL, url=_WEBSITES[low], confidence=0.9, reasoning="Bare site"
        )
    if low in _NATIVE_APPS:
        return SmartIntent(
            kind=KIND_APP, app=_NATIVE_APPS[low], confidence=0.9, reasoning="Bare app"
        )

    return SmartIntent(kind=KIND_NONE, reasoning="No smart match")


def execute_smart_intent(intent: SmartIntent, *, browser: str = "") -> Optional[ToolResult]:
    """Execute a SmartIntent via desktop helpers. Returns None if KIND_NONE."""
    if intent.kind == KIND_NONE:
        return None

    from openjarvis.tools.desktop_tools import (
        open_application,
        open_in_browser,
    )

    if intent.kind == KIND_MAIL_COMPOSE:
        from openjarvis.tools.voice_mac_tools import MailComposeTool

        return MailComposeTool().execute(
            to=intent.to,
            subject=intent.subject,
            body=intent.body,
        )

    if intent.kind == KIND_MESSAGES_COMPOSE:
        from openjarvis.tools.voice_mac_tools import MessagesComposeTool

        return MessagesComposeTool().execute(
            recipient=intent.to,
            body=intent.body,
        )

    if intent.kind == KIND_SPOTIFY and intent.query:
        # Prefer native Spotify URI (app), fall back to web search URL
        from openjarvis.tools.voice_mac_tools import SpotifyPlayTool

        return SpotifyPlayTool().execute(query=intent.query, action="search")

    if intent.kind == KIND_APP and intent.app:
        return open_application(intent.app)

    if intent.url:
        return open_in_browser(intent.url, browser=browser)

    if intent.kind == KIND_WEB_SEARCH and intent.query:
        from openjarvis.tools.desktop_tools import web_search_url

        return open_in_browser(web_search_url(intent.query), browser=browser)

    return ToolResult(
        tool_name="smart_intent",
        content=f"Unhandled intent kind={intent.kind}",
        success=False,
    )


def try_execute_smart_command(command: str, *, browser: str = "") -> Optional[ToolResult]:
    """Parse + execute in one shot. None if no rich intent matched."""
    intent = parse_smart_intent(command)
    if intent.kind == KIND_NONE:
        return None
    result = execute_smart_intent(intent, browser=browser)
    if result is None:
        return None
    # Annotate metadata
    meta = dict(getattr(result, "metadata", None) or {})
    meta.update(
        {
            "smart_kind": intent.kind,
            "smart_reasoning": intent.reasoning,
            "smart_confidence": intent.confidence,
        }
    )
    return ToolResult(
        tool_name=result.tool_name or "smart_intent",
        content=result.content,
        success=result.success,
        metadata=meta,
    )


__all__ = [
    "SmartIntent",
    "parse_smart_intent",
    "execute_smart_intent",
    "try_execute_smart_command",
    "KIND_YOUTUBE",
    "KIND_SPOTIFY",
    "KIND_AMAZON",
    "KIND_MAIL_COMPOSE",
    "KIND_MESSAGES_COMPOSE",
    "KIND_NONE",
]
