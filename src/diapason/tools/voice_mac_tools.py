"""macOS-oriented tools for live voice (calendar, Spotify, files)."""

from __future__ import annotations

import logging
import os
import pathlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


def _run(cmd: list[str], *, timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


_JOURS_SEMAINE = {
    "lundi": 0, "monday": 0, "mardi": 1, "tuesday": 1, "mercredi": 2,
    "wednesday": 2, "jeudi": 3, "thursday": 3, "vendredi": 4, "friday": 4,
    "samedi": 5, "saturday": 5, "dimanche": 6, "sunday": 6,
}


def interpreter_quand(quand: str, aujourd_hui=None):
    """« jeudi », « semaine prochaine », « 2026-08-28 »… → (décalage, durée, étiquette).

    Rend None quand la formulation est illisible — l'outil l'AVOUE alors,
    au lieu de retomber en silence sur aujourd'hui et de donner le mauvais
    jour avec aplomb (Atlas, 24 août 2026 : seuls today/tomorrow étaient
    compris, tout le reste devenait « aujourd'hui »).
    """
    import datetime as _dt

    if aujourd_hui is None:
        aujourd_hui = _dt.date.today()
    w = (quand or "today").strip().lower().replace("'", "'")
    w = w.replace("l'agenda de ", "").replace("le ", "").strip()

    if w in ("today", "aujourd'hui", "aujourdhui", ""):
        return 0, 1, "aujourd'hui"
    if w in ("tomorrow", "demain"):
        return 1, 1, "demain"
    if w in ("après-demain", "apres-demain", "après demain", "apres demain"):
        return 2, 1, "après-demain"
    if w in ("semaine", "cette semaine", "week", "this week"):
        return 0, 7, "les 7 prochains jours"
    if w in ("semaine prochaine", "la semaine prochaine", "next week"):
        lundi = (7 - aujourd_hui.weekday()) % 7 or 7
        return lundi, 7, "la semaine prochaine"
    if w in ("week-end", "weekend", "ce week-end", "ce weekend"):
        samedi = (5 - aujourd_hui.weekday()) % 7
        return samedi, 2, "le week-end"
    for nom, cible in _JOURS_SEMAINE.items():
        if w == nom or w == f"{nom} prochain":
            ecart = (cible - aujourd_hui.weekday()) % 7
            if ecart == 0 and w.endswith("prochain"):
                ecart = 7
            return ecart, 1, nom
    try:
        cible_date = _dt.date.fromisoformat(w)
        return (cible_date - aujourd_hui).days, 1, cible_date.strftime("%d/%m")
    except ValueError:
        return None


def _calendar_events_applescript(
    offset_days: int, span_days: int, label: str
) -> str:
    """Return AppleScript that prints event lines for the given window."""
    # Sur plusieurs jours, chaque ligne porte sa date — sinon « la semaine
    # prochaine » rendait sept jours indiscernables.
    prefixe_date = (
        '((day of s as text) & "/" & ((month of s as integer) as text)) & " " & '
        if span_days > 1
        else ""
    )
    return f'''
set dayOffset to {int(offset_days)}
set calLabel to "{label}"
set nowDate to current date
set startOfDay to nowDate - (time of nowDate) + (dayOffset * days)
set endOfDay to startOfDay + ({int(span_days)} * days) - 1
set outLines to {{}}
tell application "Calendar"
  repeat with cal in calendars
    try
      set evs to (every event of cal whose start date ≥ startOfDay ¬
        and start date ≤ endOfDay)
      repeat with ev in evs
        set t to summary of ev
        set s to start date of ev
        set hh to hours of s as integer
        set mm to minutes of s as integer
        set timeStr to (hh as text) & ":" & text -2 thru -1 of ("0" & mm)
        set end of outLines to {prefixe_date}timeStr & " — " & t
      end repeat
    end try
  end repeat
end tell
if (count of outLines) is 0 then
  return "No events for " & calLabel & "."
end if
set AppleScript's text item delimiters to linefeed
return "Events for " & calLabel & ":" & linefeed & (outLines as text)
'''


@ToolRegistry.register("calendar_query")
class CalendarQueryTool(BaseTool):
    """Query macOS Calendar for today/tomorrow events (AppleScript)."""

    tool_id = "calendar_query"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calendar_query",
            description=(
                "List calendar events on this Mac for a day or a range: "
                "aujourd'hui, demain, après-demain, un jour de la semaine "
                "(jeudi, vendredi prochain), une date (2026-08-28), "
                "« semaine », « semaine prochaine », « week-end »."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "when": {
                        "type": "string",
                        "description": (
                            "aujourd'hui | demain | après-demain | jeudi | "
                            "vendredi prochain | 2026-08-28 | semaine | "
                            "semaine prochaine | week-end"
                        ),
                    },
                },
                "required": [],
            },
            category="system",
            timeout_seconds=40.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        when = str(params.get("when") or "today").strip()
        if sys.platform != "darwin":
            return ToolResult(
                tool_name="calendar_query",
                content="calendar_query is only implemented on macOS.",
                success=False,
            )
        fenetre = interpreter_quand(when)
        if fenetre is None:
            return ToolResult(
                tool_name="calendar_query",
                content=(
                    f"Je n'ai pas compris la date « {when} ». Dis un jour "
                    "(jeudi), une date (2026-08-28), demain, ou "
                    "« semaine prochaine »."
                ),
                success=False,
            )
        decalage, duree, etiquette = fenetre
        script = _calendar_events_applescript(decalage, duree, etiquette)
        try:
            r = _run(["osascript", "-e", script], timeout=40.0)
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "Calendar query failed").strip()
                return ToolResult(
                    tool_name="calendar_query",
                    content=(
                        f"{err}. Grant Calendar access in "
                        "System Settings → Privacy & Security → Calendar."
                    ),
                    success=False,
                )
            text = (r.stdout or "").strip() or "No events."
            return ToolResult(
                tool_name="calendar_query",
                content=text,
                success=True,
                metadata={"when": when},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(
                tool_name="calendar_query", content=str(exc), success=False
            )


@ToolRegistry.register("spotify_play")
class SpotifyPlayTool(BaseTool):
    """Search / play music via Spotify URI or AppleScript."""

    tool_id = "spotify_play"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="spotify_play",
            description=(
                "Play or search music on Spotify. Examples: query='rock', "
                "query='Daft Punk', or a spotify: URI. Opens Spotify on this Mac."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Song, artist, genre, or spotify: URI.",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["search", "play", "pause", "next"],
                        "description": "Default search (opens Spotify search results).",
                    },
                },
                "required": ["query"],
            },
            category="system",
            timeout_seconds=20.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        query = str(params.get("query") or "").strip()
        action = str(params.get("action") or "search").strip().lower() or "search"
        if not query and action in ("search", "play"):
            return ToolResult(
                tool_name="spotify_play", content="No query.", success=False
            )

        try:
            if action == "pause" and sys.platform == "darwin":
                r = _run(["osascript", "-e", 'tell application "Spotify" to pause'])
                ok = r.returncode == 0
                return ToolResult(
                    tool_name="spotify_play",
                    content="Paused Spotify" if ok else (r.stderr or "pause failed"),
                    success=ok,
                )
            if action == "next" and sys.platform == "darwin":
                r = _run(
                    [
                        "osascript",
                        "-e",
                        'tell application "Spotify" to next track',
                    ]
                )
                ok = r.returncode == 0
                return ToolResult(
                    tool_name="spotify_play",
                    content="Next track" if ok else (r.stderr or "next failed"),
                    success=ok,
                )

            uri = query
            if not query.startswith("spotify:"):
                uri = f"spotify:search:{quote(query)}"

            if sys.platform == "darwin":
                # `open -Ra` only ASKS whether the app exists. Without this,
                # a missing Spotify surfaced as an opaque Launch Services
                # error, and the voice model had nothing to chain on. The
                # message below is written FOR the model: it names the exact
                # follow-up call that still gets music playing.
                if _run(["open", "-Ra", "Spotify"]).returncode != 0:
                    return ToolResult(
                        tool_name="spotify_play",
                        content=(
                            "Spotify is not installed on this Mac. To play "
                            "music anyway, call open_anything with target="
                            f"'joue {query} sur youtube' (starts the top "
                            "YouTube result)."
                        ),
                        success=False,
                        metadata={"spotify_missing": True},
                    )
                r = _run(["open", "-a", "Spotify", uri])
                if r.returncode != 0:
                    r = _run(["open", uri])
            elif sys.platform == "win32":
                r = _run(["cmd", "/c", "start", "", uri])
            else:
                r = _run(["xdg-open", uri])

            if r.returncode != 0:
                return ToolResult(
                    tool_name="spotify_play",
                    content=(r.stderr or "Could not open Spotify").strip(),
                    success=False,
                )
            return ToolResult(
                tool_name="spotify_play",
                # Honest on purpose: a spotify:search: URI shows results,
                # it does NOT start playback. The old "Opened Spotify for:"
                # read as success-at-playing, so the model told the user the
                # music was on while nothing played.
                content=(
                    f"Opened Spotify search results for: {query}. Playback "
                    "does not start automatically — the user must pick a "
                    "result. Say so honestly."
                ),
                success=True,
                metadata={"uri": uri, "action": action},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(tool_name="spotify_play", content=str(exc), success=False)


@ToolRegistry.register("find_files")
class FindFilesTool(BaseTool):
    """Search files on the Mac (mdfind) or via recursive name match."""

    tool_id = "find_files"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="find_files",
            description=(
                "Search for files/folders by name on this computer. "
                "On macOS uses Spotlight (mdfind). Some folders need "
                "Full Disk Access in System Settings → Privacy & Security."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Name or keywords to find.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10, max 25).",
                    },
                    "scope": {
                        "type": "string",
                        "description": (
                            "Optional folder to search in (default home directory)."
                        ),
                    },
                },
                "required": ["query"],
            },
            category="system",
            timeout_seconds=30.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        query = str(params.get("query") or "").strip()
        if not query:
            return ToolResult(
                tool_name="find_files", content="No query.", success=False
            )
        limit = max(1, min(int(params.get("limit") or 10), 25))
        scope = str(params.get("scope") or "").strip()
        root = Path(scope).expanduser() if scope else Path.home()

        try:
            paths: list[str] = []
            if sys.platform == "darwin" and shutil.which("mdfind"):
                cmd = ["mdfind"]
                if root.exists():
                    cmd.extend(["-onlyin", str(root)])
                # Prefer display-name match; fall back to bare query
                safe = query.replace("\\", "\\\\").replace('"', '\\"')
                cmd.append(f'kMDItemDisplayName == "*{safe}*"cd || {safe}')
                r = _run(cmd, timeout=25.0)
                if r.returncode == 0 and r.stdout.strip():
                    paths = [
                        line.strip() for line in r.stdout.splitlines() if line.strip()
                    ][:limit]
                elif r.returncode != 0:
                    hint = (
                        " Spotlight search failed. Grant Full Disk Access to "
                        "Terminal/Diapason in System Settings → Privacy & Security."
                    )
                    return ToolResult(
                        tool_name="find_files",
                        content=(r.stderr or "mdfind failed").strip() + hint,
                        success=False,
                    )

            if not paths:
                # Slow fallback: shallow name walk under home/Documents/Desktop
                roots = [root]
                if not scope:
                    roots = [
                        Path.home() / "Documents",
                        Path.home() / "Desktop",
                        Path.home() / "Downloads",
                    ]
                needle = query.lower()
                for base in roots:
                    if not base.is_dir():
                        continue
                    for dirpath, dirnames, filenames in os.walk(base):
                        # prune heavy dirs
                        dirnames[:] = [
                            d
                            for d in dirnames
                            if d not in {".git", "node_modules", "Library", ".Trash"}
                        ]
                        for name in filenames + dirnames:
                            if needle in name.lower():
                                paths.append(str(Path(dirpath) / name))
                                if len(paths) >= limit:
                                    break
                        if len(paths) >= limit:
                            break
                    if len(paths) >= limit:
                        break

            if not paths:
                return ToolResult(
                    tool_name="find_files",
                    content=f"No files found for '{query}'.",
                    success=True,
                    metadata={"count": 0},
                )
            listing = "\n".join(f"- {p}" for p in paths)
            return ToolResult(
                tool_name="find_files",
                content=f"Found {len(paths)} item(s):\n{listing}",
                success=True,
                metadata={"count": len(paths), "paths": paths},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(tool_name="find_files", content=str(exc), success=False)


def _as_escape(text: str) -> str:
    """Escape a string for embedding in an AppleScript double-quoted literal."""
    return (text or "").replace("\\", "\\\\").replace('"', '\\"')


def _looks_like_email(value: str) -> bool:
    v = (value or "").strip()
    return "@" in v and "." in v.split("@")[-1] and " " not in v


def _looks_like_phone(value: str) -> bool:
    digits = re.sub(r"[^\d+]", "", (value or "").strip())
    bare = digits.lstrip("+")
    return bare.isdigit() and 7 <= len(bare) <= 15


# « Envoie un message à Maman » (Atlas, 24 août 2026) : le destinataire
# arrivait BRUT — sms:maman — et Messages haussait les épaules. Les fiches
# vivent déjà dans knowledge.db (121 contacts Google + Contacts Apple),
# téléphones dans le CONTENT (jamais dans metadata). La résolution vit ICI,
# dans les outils, parce que c'est le seul endroit qui couvre les trois
# chemins : le modèle vocal, le chat, et la dictée déterministe qui
# n'appelle AUCUN LLM (desktop/voice_commands.py). SQL pur — pas d'Ollama,
# le créneau -np 1 appartient à la voix.
_PARENTE_FR_EN = {
    "maman": ("mom", "mother", "mère", "maman"),
    "mamane": ("mom", "mother", "mère", "maman"),
    "papa": ("dad", "father", "père", "papa"),
    "frère": ("brother", "frère", "bro"),
    "soeur": ("sister", "sœur", "soeur", "sis"),
    "sœur": ("sister", "sœur", "soeur", "sis"),
}

# Deux dialectes constatés sur la vraie base (24 août 2026) : gcontacts
# écrit « Phone: +509… », apple_contacts « Phone +1941… » — SANS deux-points,
# label optionnel (« Phone Mobile: … »). On capte le numéro lui-même.
_LIGNE_PHONE_RE = re.compile(r"^Phone[^\n]*?[\s:](\+?[\d][\d\s.\-()]*)$", re.M)
_LIGNE_EMAIL_RE = re.compile(r"^Email[^\n]*?[\s:]\s*(\S+@\S+)$", re.M)


def _normaliser_numero(brut: str) -> str:
    return re.sub(r"[\s.\-()]", "", brut.strip())


def _rang_de_correspondance(terme: str, titre: str) -> int:
    """0 = titre exact (hors émojis/ponctuation), 1 = mot entier, 2 = sous-chaîne."""
    bas, titre_bas = terme.lower(), titre.lower()
    lettres = re.sub(r"[^a-zà-ÿ0-9 ]", "", titre_bas).strip()
    if lettres == bas:
        return 0
    if re.search(rf"(?<![a-zà-ÿ0-9]){re.escape(bas)}(?![a-zà-ÿ0-9])", titre_bas):
        return 1
    return 2


def _ne_garder_que_les_plus_exacts(
    terme: str, lignes: "list[tuple[str, str]]"
) -> "list[tuple[str, str]]":
    if not lignes:
        return lignes
    rangs = [(_rang_de_correspondance(terme, titre), titre, contenu) for titre, contenu in lignes]
    meilleur = min(r for r, _t, _c in rangs)
    return [(t_, c) for r, t_, c in rangs if r == meilleur]


def _remede_fda() -> str:
    from diapason.channels.imessage_status import remede_fda

    return remede_fda()


def _constater_l_envoi(recipient: str, envoye_apres, *, essais: int = 6):
    """La rangée sortante réelle, en sondant chat.db ~3 s au plus.

    Connexion rouverte à chaque essai (la base bouge sous nos pieds). Bien
    sous le timeout_seconds=30 de la spec — et sans rapport avec les 45 s
    d'approbation : ici le message est déjà accepté par Messages.
    """
    import time as _time

    from diapason.channels.imessage_status import Constat, find_outgoing

    dernier = Constat(issue="not_found")
    for _ in range(max(1, essais)):
        dernier = find_outgoing(recipient, envoye_apres)
        if dernier.issue == "unreadable" or (
            dernier.issue == "found" and (dernier.is_sent or dernier.error)
        ):
            return dernier
        _time.sleep(0.5)
    return dernier


def _resolve_contact(name: str, *, db_path: str | None = None) -> list[dict]:
    """Les fiches locales qui répondent à un petit nom — [] si rien.

    Lecture seule de knowledge.db. Chaque fiche : {title, phone, email},
    phone préférant la forme internationale « + » quand la fiche en a
    plusieurs. Les surnoms de parenté français passent par un petit
    dictionnaire (« maman » → « Mom💫 ») ; les surnoms libres (« le boss »)
    vivent dans USER.md et c'est le modèle qui les traduit en nom de fiche.
    """
    import sqlite3

    if db_path is None:
        from diapason.core.paths import get_config_dir

        db_path = str(get_config_dir() / "knowledge.db")
    chemin = pathlib.Path(db_path) if isinstance(db_path, str) else db_path
    if not chemin.exists():
        return []

    candidats = [name.strip()]
    candidats.extend(_PARENTE_FR_EN.get(name.strip().lower(), ()))

    fiches: dict[str, dict] = {}
    try:
        with sqlite3.connect(f"file:{chemin}?mode=ro", uri=True) as db:
            for terme in candidats:
                lignes = db.execute(
                    "SELECT title, content FROM knowledge_chunks "
                    "WHERE doc_type = 'contact' AND deleted_at IS NULL "
                    "AND title LIKE ? COLLATE NOCASE",
                    (f"%{terme}%",),
                ).fetchall()
                # LIKE %mom% attrape aussi « JOSCHAVIA MOMPREMIER » (constaté
                # sur la vraie base, 24 août 2026). On classe : titre exact
                # (émojis et ponctuation retirés) > mot entier > sous-chaîne,
                # et on ne garde que le meilleur rang présent.
                lignes = _ne_garder_que_les_plus_exacts(terme, lignes)
                for titre, contenu in lignes:
                    if titre in fiches:
                        continue
                    telephones = [
                        _normaliser_numero(m)
                        for m in _LIGNE_PHONE_RE.findall(contenu or "")
                    ]
                    telephones = [n for n in telephones if n]
                    # La forme « + » d'abord : send_imessage veut du E.164.
                    telephones.sort(key=lambda n: not n.startswith("+"))
                    emails = _LIGNE_EMAIL_RE.findall(contenu or "")
                    fiches[titre] = {
                        "title": titre,
                        "phone": telephones[0] if telephones else "",
                        "email": emails[0].strip() if emails else "",
                    }
                if fiches:
                    break  # le nom exact prime sur les synonymes de parenté
    except Exception:  # noqa: BLE001 - une base illisible = aucune fiche
        logger.debug("résolution de contact impossible", exc_info=True)
        return []
    return list(fiches.values())


def _resoudre_ou_avouer(
    recipient: str, tool_name: str, *, veut: str = "phone"
) -> "tuple[str, str, ToolResult | None]":
    """(destinataire résolu, fiche nommée, ou le ToolResult d'aveu).

    Convention de la maison : zéro ou plusieurs candidats, on AVOUE avec la
    liste — jamais un premier-de-la-liste silencieux.
    """
    if _looks_like_email(recipient) or _looks_like_phone(recipient):
        return recipient, "", None
    fiches = _resolve_contact(recipient)
    utilisables = [f for f in fiches if f.get(veut)]
    if len(utilisables) == 1:
        fiche = utilisables[0]
        return fiche[veut], fiche["title"], None
    if not utilisables:
        detail = (
            " Contacts found but none has an email on file."
            if fiches and veut == "email"
            else ""
        )
        return recipient, "", ToolResult(
            tool_name=tool_name,
            success=False,
            content=(
                f"No local contact matches '{recipient}'.{detail} "
                "Ask the user for the exact name, a phone number, or an email."
            ),
            metadata={"resolved": False, "candidates": []},
        )
    noms = ", ".join(f["title"] for f in utilisables[:5])
    return recipient, "", ToolResult(
        tool_name=tool_name,
        success=False,
        content=(
            f"Several contacts match '{recipient}': {noms}. "
            "Ask the user which one, then call again with that exact name."
        ),
        metadata={"resolved": False, "candidates": [f["title"] for f in utilisables[:5]]},
    )


def _mail_compose_script(
    *, to: str = "", subject: str = "", body: str = "", cc: str = ""
) -> str:
    props = ["visible:true"]
    if subject:
        props.append(f'subject:"{_as_escape(subject)}"')
    # trailing return helps caret sit after body in Mail
    content = body if body.endswith("\n") or not body else body + "\n"
    props.append(f'content:"{_as_escape(content)}"')
    prop_str = ", ".join(props)
    lines = [
        'tell application "Mail"',
        "  activate",
        f"  set newMessage to make new outgoing message with properties {{{prop_str}}}",
        "  tell newMessage",
    ]
    if to:
        lines.append(
            f'    make new to recipient with properties {{address:"{_as_escape(to)}"}}'
        )
    if cc:
        lines.append(
            f'    make new cc recipient with properties {{address:"{_as_escape(cc)}"}}'
        )
    lines.extend(["  end tell", "end tell", 'return "ok"'])
    return "\n".join(lines)


def _mailto_uri(
    *, to: str = "", subject: str = "", body: str = "", cc: str = ""
) -> str:
    from urllib.parse import quote, urlencode

    query = urlencode(
        {k: v for k, v in (("subject", subject), ("body", body), ("cc", cc)) if v},
        quote_via=quote,
    )
    base = f"mailto:{quote(to, safe='@.+-_')}" if to else "mailto:"
    return f"{base}?{query}" if query else base


def _messages_compose_uri(*, recipient: str, body: str = "") -> str:
    """Build sms:/imessage: URL that opens a draft (does not send)."""
    from urllib.parse import quote

    handle = (recipient or "").strip()
    text = body or ""
    if _looks_like_email(handle):
        uri = f"imessage:{quote(handle, safe='@.+-_')}"
        if text:
            uri += f"?body={quote(text)}"
        return uri
    # phones and bare handles: sms scheme
    uri = f"sms:{quote(handle, safe='+')}"
    if text:
        uri += f"&body={quote(text)}"
    return uri


@ToolRegistry.register("mail_compose")
class MailComposeTool(BaseTool):
    """Open a Mail.app draft (compose only — never auto-sends)."""

    tool_id = "mail_compose"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="mail_compose",
            description=(
                "Compose an email draft in macOS Mail.app. Does NOT send. "
                "Use for « écris un mail à… », « email John about… ». "
                "Ask for missing recipient or topic if unclear. "
                "After opening, tell the user the draft is ready — "
                "they send it themselves."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address.",
                    },
                    "subject": {"type": "string", "description": "Subject line."},
                    "body": {"type": "string", "description": "Message body."},
                    "cc": {"type": "string", "description": "Optional CC address."},
                },
                "required": [],
            },
            category="system",
            timeout_seconds=25.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        # Live voice and callers must never auto-send; ignore any send flag.
        to = str(params.get("to") or "").strip()
        subject = str(params.get("subject") or "").strip()
        body = str(params.get("body") or "").strip()
        cc = str(params.get("cc") or "").strip()

        if sys.platform != "darwin":
            return ToolResult(
                tool_name="mail_compose",
                content="mail_compose is only implemented on macOS.",
                success=False,
            )

        if not any((to, subject, body)):
            return ToolResult(
                tool_name="mail_compose",
                content=(
                    "Need at least a recipient, subject, or body. "
                    "Ask the user who to write to and what about."
                ),
                success=False,
            )

        script = _mail_compose_script(to=to, subject=subject, body=body, cc=cc)
        try:
            r = _run(["osascript", "-e", script], timeout=8.0)
            if r.returncode == 0:
                who = to or "(no recipient yet)"
                return ToolResult(
                    tool_name="mail_compose",
                    content=(
                        f"Draft open in Mail for {who}. "
                        "Not sent — user must click Send."
                    ),
                    success=True,
                    metadata={"to": to, "subject": subject, "sent": False},
                )
            # Fallback: mailto: (still compose-only)
            uri = _mailto_uri(to=to, subject=subject, body=body, cc=cc)
            r2 = _run(["open", uri], timeout=5.0)
            if r2.returncode != 0:
                err = (r.stderr or r2.stderr or "Mail compose failed").strip()
                return ToolResult(
                    tool_name="mail_compose",
                    content=(
                        f"{err}. Grant Automation access for Mail in "
                        "System Settings → Privacy & Security → Automation."
                    ),
                    success=False,
                )
            return ToolResult(
                tool_name="mail_compose",
                content=(f"Opened mailto draft for {to or 'new message'}. Not sent."),
                success=True,
                metadata={
                    "to": to,
                    "subject": subject,
                    "sent": False,
                    "via": "mailto",
                },
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(tool_name="mail_compose", content=str(exc), success=False)


@ToolRegistry.register("messages_compose")
class MessagesComposeTool(BaseTool):
    """Open a Messages.app draft (compose only — never auto-sends)."""

    tool_id = "messages_compose"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="messages_compose",
            description=(
                "Compose an iMessage/SMS draft in macOS Messages. Does NOT send. "
                "Use for « envoie un message à… », « text Mom saying… ». "
                "Recipient can be a phone number, an iMessage email, or a contact "
                "name as spoken — names are resolved from local contacts. "
                "After opening, tell the user the draft is ready — they hit Send."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": (
                            "Phone (E.164), iMessage email, or a contact NAME "
                            "as spoken (« maman », « Gaël ») — names are "
                            "resolved from the local contacts."
                        ),
                    },
                    "body": {
                        "type": "string",
                        "description": "Message text to prefill.",
                    },
                },
                "required": ["recipient"],
            },
            category="system",
            timeout_seconds=20.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        recipient = str(params.get("recipient") or "").strip()
        body = str(params.get("body") or "").strip()
        if not recipient:
            return ToolResult(
                tool_name="messages_compose",
                content="Need a recipient (phone or iMessage email).",
                success=False,
            )
        if sys.platform != "darwin":
            return ToolResult(
                tool_name="messages_compose",
                content="messages_compose is only implemented on macOS.",
                success=False,
            )

        demande = recipient
        recipient, fiche, aveu = _resoudre_ou_avouer(recipient, "messages_compose")
        if aveu is not None:
            return aveu

        # Prefer URL scheme — opens draft, does not send (unlike send_imessage).
        uri = _messages_compose_uri(recipient=recipient, body=body)
        try:
            r = _run(["open", uri], timeout=5.0)
            if r.returncode != 0:
                # Soft fallback: just activate Messages
                _run(["open", "-a", "Messages"], timeout=5.0)
                return ToolResult(
                    tool_name="messages_compose",
                    content=(
                        f"Could not open draft URI ({(r.stderr or '').strip()}). "
                        "Messages opened — ask user to pick the contact. Not sent."
                    ),
                    success=False,
                    metadata={"recipient": recipient, "sent": False},
                )
            qui = f"{fiche} ({recipient})" if fiche else recipient
            return ToolResult(
                tool_name="messages_compose",
                content=(
                    f"Draft open in Messages for {qui}. "
                    "Not sent — user must tap Send."
                ),
                success=True,
                metadata={
                    "recipient": recipient,
                    "resolved_from": demande if fiche else "",
                    "contact": fiche,
                    "sent": False,
                    "uri": uri,
                },
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(
                tool_name="messages_compose", content=str(exc), success=False
            )


def _truthy_confirm(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str) and value.strip().lower() in ("true", "1", "yes"):
        return True
    return False


def _mail_send_frontmost_script() -> str:
    return "\n".join(
        [
            'tell application "Mail"',
            "  activate",
            "  set msgs to (every outgoing message whose visible is true)",
            "  if (count of msgs) is 0 then",
            '    return "no_draft"',
            "  end if",
            "  set theMsg to item 1 of msgs",
            "  send theMsg",
            '  return "sent"',
            "end tell",
        ]
    )


@ToolRegistry.register("mail_send")
class MailSendTool(BaseTool):
    """Send the frontmost Mail draft — only when confirm=true (spoken yes)."""

    tool_id = "mail_send"
    # is_local décrit le trajet de la DONNÉE, pas celui du code. Cet outil
    # s'exécute bien sur la machine — il pilote Mail.app par osascript — mais
    # son effet est de faire partir le contenu chez un serveur de courrier.
    # Déclaré local, il échappait au garde-frontière de ToolExecutor comme au
    # mode local : c'est l'envoi le plus explicite qui soit, il ne peut pas
    # être le seul non couvert.
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="mail_send",
            description=(
                "Send the currently open Mail.app draft. REQUIRES confirm=true. "
                "Only call after the user clearly says to send (envoie / send it). "
                "Never call on first compose — use mail_compose first."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true; user confirmed send orally.",
                    },
                },
                "required": ["confirm"],
            },
            category="system",
            timeout_seconds=25.0,
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        if not _truthy_confirm(params.get("confirm")):
            return ToolResult(
                tool_name="mail_send",
                content=(
                    "Refused: confirm=true required. Ask the user to say "
                    "« envoie » / « send it », then call again with confirm=true."
                ),
                success=False,
                metadata={"sent": False},
            )
        if sys.platform != "darwin":
            return ToolResult(
                tool_name="mail_send",
                content="mail_send is only implemented on macOS.",
                success=False,
            )
        try:
            r = _run(["osascript", "-e", _mail_send_frontmost_script()], timeout=20.0)
            out = (r.stdout or "").strip().lower()
            if r.returncode != 0:
                err = (r.stderr or "Mail send failed").strip()
                return ToolResult(
                    tool_name="mail_send",
                    content=err,
                    success=False,
                    metadata={"sent": False},
                )
            if "no_draft" in out:
                return ToolResult(
                    tool_name="mail_send",
                    content="No visible Mail draft to send. Compose first.",
                    success=False,
                    metadata={"sent": False},
                )
            return ToolResult(
                tool_name="mail_send",
                content="Email sent.",
                success=True,
                metadata={"sent": True},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(tool_name="mail_send", content=str(exc), success=False)


@ToolRegistry.register("messages_send")
class MessagesSendTool(BaseTool):
    """Send an iMessage/SMS — only when confirm=true (spoken yes)."""

    tool_id = "messages_send"
    # is_local décrit le trajet de la DONNÉE, pas celui du code. Cet outil
    # s'exécute bien sur la machine — il pilote Messages.app par osascript — mais
    # son effet est de faire partir le contenu chez les serveurs iMessage/SMS.
    # Déclaré local, il échappait au garde-frontière de ToolExecutor comme au
    # mode local : c'est l'envoi le plus explicite qui soit, il ne peut pas
    # être le seul non couvert.
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="messages_send",
            description=(
                "Actually send an iMessage/SMS. REQUIRES confirm=true. "
                "Only after the user clearly says to send. Prefer messages_compose "
                "for drafts; use this only when they confirm send."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": (
                            "Phone (E.164), iMessage email, or a contact NAME "
                            "as spoken (« maman », « Gaël ») — names are "
                            "resolved from the local contacts."
                        ),
                    },
                    "body": {"type": "string", "description": "Message text."},
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true; user confirmed send orally.",
                    },
                },
                "required": ["recipient", "body", "confirm"],
            },
            category="system",
            timeout_seconds=30.0,
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        if not _truthy_confirm(params.get("confirm")):
            return ToolResult(
                tool_name="messages_send",
                content=(
                    "Refused: confirm=true required. Ask the user to confirm "
                    "send, then call again with confirm=true."
                ),
                success=False,
                metadata={"sent": False},
            )
        recipient = str(params.get("recipient") or "").strip()
        body = str(params.get("body") or "").strip()
        if not recipient or not body:
            return ToolResult(
                tool_name="messages_send",
                content="Need recipient and body.",
                success=False,
            )
        if sys.platform != "darwin":
            return ToolResult(
                tool_name="messages_send",
                content="messages_send is only implemented on macOS.",
                success=False,
            )
        demande = recipient
        recipient, fiche, aveu = _resoudre_ou_avouer(recipient, "messages_send")
        if aveu is not None:
            return aveu
        try:
            from datetime import datetime, timedelta, timezone

            from diapason.channels.imessage_daemon import send_imessage

            # Le moment AVANT l'envoi, avec 5 s de marge d'horloge : c'est la
            # borne de recherche du constat dans chat.db.
            envoye_apres = datetime.now(timezone.utc) - timedelta(seconds=5)
            ok = bool(send_imessage(recipient, body))
            if not ok:
                return ToolResult(
                    tool_name="messages_send",
                    content=(
                        "Send failed. Prefer phone/+E.164 or iMessage email. "
                        "Grant Automation for Messages if prompted."
                    ),
                    success=False,
                    metadata={"sent": False, "recipient": recipient},
                )
            qui = f"{fiche} ({recipient})" if fiche else recipient
            # Constater, ne pas proclamer (Atlas, 24 août 2026) : le code
            # retour d'osascript dit « Messages a accepté », pas « c'est
            # parti » — le « Not Delivered » est silencieux. On regarde la
            # rangée réelle dans chat.db, quelques secondes au plus.
            constat = _constater_l_envoi(recipient, envoye_apres)
            if constat.issue == "found" and constat.error:
                return ToolResult(
                    tool_name="messages_send",
                    content=(
                        f"Messages reported a send FAILURE to {qui} "
                        f"(Not Delivered, error {constat.error}). Tell the "
                        "user; suggest checking the number or using SMS."
                    ),
                    success=False,
                    metadata={
                        "sent": False,
                        "verified": True,
                        "recipient": recipient,
                        "guid": constat.guid,
                        "error": constat.error,
                    },
                )
            if constat.issue == "found" and constat.is_sent:
                return ToolResult(
                    tool_name="messages_send",
                    content=f"Message sent to {qui} (confirmed in Messages).",
                    success=True,
                    metadata={
                        "sent": True,
                        "verified": True,
                        "recipient": recipient,
                        "guid": constat.guid,
                        "resolved_from": demande if fiche else "",
                    },
                )
            if constat.issue == "found":
                return ToolResult(
                    tool_name="messages_send",
                    content=(
                        f"Handed to Messages for {qui}, still sending — "
                        "call messages_status to confirm if asked."
                    ),
                    success=True,
                    metadata={
                        "sent": True,
                        "verified": False,
                        "recipient": recipient,
                        "guid": constat.guid,
                    },
                )
            raison = (
                "chat.db unreadable — " + _remede_fda()
                if constat.issue == "unreadable"
                else "row not visible yet"
            )
            return ToolResult(
                tool_name="messages_send",
                content=(
                    f"Handed to Messages for {qui}; could not verify delivery "
                    f"({raison})."
                ),
                success=True,
                metadata={
                    "sent": True,
                    "verified": False,
                    "recipient": recipient,
                    "reason": constat.issue,
                },
            )
        except Exception as exc:
            return ToolResult(
                tool_name="messages_send", content=str(exc), success=False
            )



@ToolRegistry.register("messages_status")
class MessagesStatusTool(BaseTool):
    """L'état réel d'un envoi iMessage — lu dans chat.db, jamais inventé."""

    tool_id = "messages_status"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="messages_status",
            description=(
                "Check in the local Messages database whether an iMessage "
                "actually went out. Call it when the user asks « c'est "
                "parti ? », or on the next turn after messages_send returned "
                "verified=false. Pass the guid from messages_send when you "
                "have it, else the recipient."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "guid": {
                        "type": "string",
                        "description": "The message guid from messages_send.",
                    },
                    "recipient": {
                        "type": "string",
                        "description": "Phone/email if no guid is known.",
                    },
                },
            },
            category="system",
            requires_confirmation=False,
            timeout_seconds=15.0,
            metadata={"risk": "read_only", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        if sys.platform != "darwin":
            return ToolResult(
                tool_name="messages_status",
                content="messages_status is only implemented on macOS.",
                success=False,
            )
        from datetime import datetime, timedelta, timezone

        from diapason.channels.imessage_status import (
            find_outgoing,
            remede_fda,
            status_by_guid,
        )

        guid = str(params.get("guid") or "").strip()
        recipient = str(params.get("recipient") or "").strip()
        if guid:
            constat = status_by_guid(guid)
        elif recipient:
            constat = find_outgoing(
                recipient, datetime.now(timezone.utc) - timedelta(minutes=10)
            )
        else:
            return ToolResult(
                tool_name="messages_status",
                content="Need a guid or a recipient.",
                success=False,
            )
        if constat.issue == "unreadable":
            return ToolResult(
                tool_name="messages_status",
                content=f"Cannot read the Messages database — {remede_fda()}",
                success=False,
                metadata={"reason": "unreadable"},
            )
        if constat.issue == "not_found":
            return ToolResult(
                tool_name="messages_status",
                content=(
                    "No recent outgoing message found for that — it may not "
                    "have been handed to Messages at all."
                ),
                success=True,
                metadata={"found": False},
            )
        if constat.error:
            verdict = f"NOT delivered (error {constat.error}) — tell the user."
        elif constat.is_delivered:
            verdict = "delivered."
        elif constat.is_sent:
            verdict = "sent (delivery receipt not seen yet)."
        else:
            verdict = "still in Messages' outbox."
        return ToolResult(
            tool_name="messages_status",
            content=f"That message is {verdict}",
            success=True,
            metadata={
                "found": True,
                "guid": constat.guid,
                "is_sent": constat.is_sent,
                "is_delivered": constat.is_delivered,
                "error": constat.error,
            },
        )

__all__ = [
    "MessagesStatusTool",
    "CalendarQueryTool",
    "SpotifyPlayTool",
    "FindFilesTool",
    "MailComposeTool",
    "MessagesComposeTool",
    "MailSendTool",
    "MessagesSendTool",
]
