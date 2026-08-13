"""Diapason-style smart browser/app intents (pattern matching, FR + EN).

Ports the fast heuristics from jarvis-ai-assistant SmartBrowserService /
AICommandParser.tryFastParse — no cloud AI required for obvious commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote, quote_plus

from diapason.core.types import ToolResult


@dataclass(slots=True)
class SmartIntent:
    """Resolved open/search/play intent."""

    kind: str  # see KIND_* constants
    # "play" when the user asked to PLAY something (vs merely search): the
    # executor turns a YouTube play into the top result's watch URL so the
    # video actually starts, instead of stranding the user on a results page.
    action: str = ""
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


# Playback-control vocabulary: a "play" whose whole query is one of these
# is a control command, not a request to play content by that name.
_CONTROL_WORDS = frozenset(
    {"pause", "en pause", "stop", "play", "la vidéo en pause", "vidéo en pause"}
)


# Words that never carry meaning at the head of a media query.
_FILLER_WORDS = frozenset(
    {"vidéo", "video", "clip", "chanson", "musique", "music", "song", "for"}
)
_ARTICLE_WORDS = frozenset(
    {"le", "la", "les", "des", "un", "une", "de", "d", "du", "the"}
)


def _clean_query(text: str, *strip_words: str) -> str:
    """Strip leading filler from a captured media query, carefully.

    Three generations of this function got it wrong in three ways:
    stripping everywhere mutilated titles (« La Vie en Rose » → "Vie en
    Rose"); a blind head-cascade decapitated titles that START with such a
    word (« La La Land » → "land", « Video Club » → "club"). The rule that
    survives both: filler nouns ("vidéo", "chanson"…) are dropped from the
    head; a run of leading ARTICLES is dropped only when it leads to a
    filler noun ("la vidéo X", "de la musique kompa") — an article leading
    anything else is part of the title.
    """
    fillers = {w for w in strip_words if w in _FILLER_WORDS}
    articles = {w for w in strip_words if w in _ARTICLE_WORDS}

    def norm(tok: str) -> str:
        return tok.strip(" .,!?;:'’").lower()

    tokens = text.split()
    i = 0
    while i < len(tokens):
        t = norm(tokens[i])
        if t in fillers:
            i += 1
            continue
        if t in articles:
            j = i
            while j < len(tokens) and norm(tokens[j]) in articles:
                j += 1
            if j < len(tokens) and norm(tokens[j]) in fillers:
                i = j
                continue
        break
    return re.sub(r"\s+", " ", " ".join(tokens[i:])).strip(" .,!?;:")


# The results page embeds its initial data as JSON; the first videoRenderer
# in document order is the top organic result (ads use promotedVideoRenderer
# or adSlotRenderer and never match this pattern).
_YT_TOP_RESULT = re.compile(
    r'"videoRenderer"\s*:\s*\{\s*"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"'
)


def resolve_youtube_watch_url(
    query: str,
    *,
    timeout: float = 4.0,
    fetch=None,
) -> str:
    """Top YouTube search hit as a watch URL, or "" when resolution fails.

    No API key: one GET on the public results page. Failure is a normal
    state (offline, layout change, consent wall) — the caller falls back to
    opening the results page, which is what happened before this existed.
    """
    url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
    if fetch is None:
        from diapason.core.local_mode import LocalOnlyError, assert_may_leave

        try:
            assert_may_leave("the YouTube search query", destination=url)
        except LocalOnlyError:
            return ""
    try:
        if fetch is None:

            def fetch(u: str) -> str:
                import urllib.request

                req = urllib.request.Request(
                    u,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept-Language": "fr,en;q=0.8",
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read(2_000_000).decode("utf-8", "replace")

        m = _YT_TOP_RESULT.search(fetch(url))
        if m:
            return "https://www.youtube.com/watch?v=" + m.group(1)
    except Exception:  # noqa: BLE001 - resolution is best-effort by design
        pass
    return ""


def parse_smart_intent(command: str) -> SmartIntent:
    """Parse a spoken/typed command into a SmartIntent (best-effort)."""
    raw = (command or "").strip()
    if not raw:
        return SmartIntent(kind=KIND_NONE)

    low = raw.lower().strip()

    # A target that already IS a URL must pass through untouched. Before
    # this check, an LLM-built https://www.youtube.com/results?search_query=…
    # entered the YouTube block ("youtube" in low), matched none of the
    # phrase regexes, and was silently replaced by the YouTube home page.
    if re.match(r"^(?:https?://|www\.)\S+$", raw, re.IGNORECASE):
        return SmartIntent(
            kind=KIND_URL,
            url=raw if raw.lower().startswith("http") else f"https://{raw}",
            confidence=0.98,
            reasoning="Direct URL",
        )

    # --- YouTube ---
    if "youtube" in low:
        for pat, action in (
            (
                r"(?:ouvre|open)\s+youtube\s+(?:et|and)\s+(?:cherche|search(?:\s+for)?)\s+(.+)",
                "search",
            ),
            (r"youtube\s+(?:cherche|search(?:\s+for)?)\s+(.+)", "search"),
            (r"(?:cherche|search(?:\s+for)?)\s+(.+?)\s+(?:sur|on)\s+youtube", "search"),
            (
                r"(?:joue|play|regarde|watch|écoute|ecoute|mets|lance)"
                r"\s+(.+?)\s+(?:sur|on)\s+youtube",
                "play",
            ),
            (r"youtube\s+(.+)", "search"),
        ):
            m = re.search(pat, low, re.IGNORECASE)
            if m:
                q = m.group(1).strip()
                q = _clean_query(
                    q,
                    "for",
                    "the",
                    "le",
                    "la",
                    "les",
                    "des",
                    "un",
                    "une",
                    "de",
                    "d",
                    "vidéo",
                    "video",
                    "clip",
                    "chanson",
                    "musique",
                    "music",
                    "song",
                )
                # « mets la vidéo en pause sur youtube » must not PLAY a
                # video titled "pause" — control words are not queries.
                if q and (action != "play" or q not in _CONTROL_WORDS):
                    return SmartIntent(
                        kind=KIND_YOUTUBE,
                        action=action,
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
        # Search patterns come FIRST and each pattern carries its own
        # action: sniffing play-verbs anywhere in the phrase turned
        # « cherche listen de beyoncé sur spotify » into an autoplay.
        for pat, action in (
            (
                r"(?:ouvre|open)\s+spotify\s+(?:et|and)\s+"
                r"(?:cherche|search(?:\s+for)?)\s+(.+)",
                "search",
            ),
            (r"(?:cherche|search(?:\s+for)?)\s+(.+?)\s+(?:sur|on)\s+spotify", "search"),
            (r"spotify\s+(?:cherche|search(?:\s+for)?)\s+(.+)", "search"),
            (
                r"(?:ouvre|open)\s+spotify\s+(?:et|and)\s+(?:joue|play)\s+(.+)",
                "play",
            ),
            (
                r"(?:joue|play|écoute|ecoute|listen(?:\s+to)?)\s+(.+?)\s+(?:sur|on)\s+spotify",
                "play",
            ),
            (r"spotify\s+(?:joue|play)\s+(.+)", "play"),
            (r"spotify\s+(.+)", "search"),
            (r"(?:joue|play|écoute|ecoute)\s+(.+)", "play"),
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
                        action=action,
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
    if "whatsapp" in low and any(
        w in low for w in ("web", "chrome", "browser", "navigateur")
    ):
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
        r"(?:ouvre|open|go to|va sur)\s+"
        r"(?:le site |the (?:site|page) )?"
        r"(?P<site>[\w.-]+\.(?:com|org|net|io|ai|co|fr|dev))\b",
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
        r"show|montre)\s+"
        r"(?:l['’]|le |la |les |the |app |application )?"
        r"(?P<target>.+?)\s*$",
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


def execute_smart_intent(
    intent: SmartIntent, *, browser: str = ""
) -> Optional[ToolResult]:
    """Execute a SmartIntent via desktop helpers. Returns None if KIND_NONE."""
    if intent.kind == KIND_NONE:
        return None

    from diapason.tools.desktop_tools import (
        open_application,
        open_in_browser,
    )

    if intent.kind == KIND_MAIL_COMPOSE:
        from diapason.tools.voice_mac_tools import MailComposeTool

        return MailComposeTool().execute(
            to=intent.to,
            subject=intent.subject,
            body=intent.body,
        )

    if intent.kind == KIND_MESSAGES_COMPOSE:
        from diapason.tools.voice_mac_tools import MessagesComposeTool

        return MessagesComposeTool().execute(
            recipient=intent.to,
            body=intent.body,
        )

    if intent.kind == KIND_YOUTUBE and intent.action == "play" and intent.query:
        watch = resolve_youtube_watch_url(intent.query)
        if watch:
            res = open_in_browser(watch, browser=browser)
            if res.success:
                return ToolResult(
                    tool_name=res.tool_name,
                    content=(
                        f"Playing top YouTube result for '{intent.query}': {watch}"
                    ),
                    success=True,
                    metadata={"watch_url": watch, "query": intent.query},
                )
        res = open_in_browser(intent.url, browser=browser)
        return ToolResult(
            tool_name=res.tool_name,
            content=(
                f"Opened YouTube SEARCH RESULTS for '{intent.query}' (could not "
                "resolve the top video; the user must click one to play)."
            ),
            success=res.success,
            metadata={"query": intent.query},
        )

    if intent.kind == KIND_SPOTIFY and intent.query:
        # Prefer native Spotify URI (app), fall back to web search URL
        from diapason.tools.voice_mac_tools import SpotifyPlayTool

        result = SpotifyPlayTool().execute(
            query=intent.query, action=intent.action or "search"
        )
        if result.success or not (getattr(result, "metadata", None) or {}).get(
            "spotify_missing"
        ):
            return result
        # Spotify is not installed on this machine: the user still asked to
        # HEAR something, so play the top YouTube result instead of reading
        # an installation error out loud. Only for a PLAY intent — a mere
        # search must never turn into an unexpected autoplay.
        if intent.action != "play":
            return result
        watch = resolve_youtube_watch_url(intent.query)
        if watch:
            res = open_in_browser(watch, browser=browser)
            if res.success:
                return ToolResult(
                    tool_name="spotify_play",
                    content=(
                        "Spotify is not installed; playing the top YouTube "
                        f"result for '{intent.query}' instead: {watch}"
                    ),
                    success=True,
                    metadata={"fallback": "youtube", "watch_url": watch},
                )
        return result

    if intent.kind == KIND_APP and intent.app:
        return open_application(intent.app)

    if intent.url:
        return open_in_browser(intent.url, browser=browser)

    if intent.kind == KIND_WEB_SEARCH and intent.query:
        from diapason.tools.desktop_tools import web_search_url

        return open_in_browser(web_search_url(intent.query), browser=browser)

    return ToolResult(
        tool_name="smart_intent",
        content=f"Unhandled intent kind={intent.kind}",
        success=False,
    )


def try_execute_smart_command(
    command: str, *, browser: str = ""
) -> Optional[ToolResult]:
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
    "resolve_youtube_watch_url",
    "execute_smart_intent",
    "try_execute_smart_command",
    "KIND_YOUTUBE",
    "KIND_SPOTIFY",
    "KIND_AMAZON",
    "KIND_MAIL_COMPOSE",
    "KIND_MESSAGES_COMPOSE",
    "KIND_NONE",
]
