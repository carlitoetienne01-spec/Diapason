"""Agir DANS une application — chercher, écrire — pas seulement l'ouvrir.

Demandé de vive voix le 23 août 2026 : « quand je lui demande d'ouvrir
l'App Store, je peux lui demander ensuite de chercher des jeux… des fois mes
mains ne sont pas libres. » Ouvrir ne suffit pas à des mains occupées : il
faut pouvoir enchaîner dans ce qui vient de s'ouvrir.

Chaque destination utilise son mécanisme NATIF, mesuré avant d'être retenu :

- App Store : son lien profond de recherche. Le pilotage de l'interface
  (⌘F puis frapper) a été essayé d'abord et il ÉCHOUE en silence — capture
  d'écran à l'appui, le champ restait vide. Le lien, lui, affiche
  « Résultats pour … » à tous les coups.
- Spotify : son URI ``spotify:search:``.
- Notes : son dictionnaire AppleScript — pas de frappe simulée, des objets.
- YouTube, Amazon, le web : l'URL de résultats dans le navigateur.

Ce qui n'a pas de mécanisme fiable est REFUSÉ avec la liste de ce qui
marche : une recherche qui « part » dans le vide et un assistant qui affirme
l'avoir faite, c'est le mensonge déjà chassé deux fois de ce dépôt.

Le texte de l'utilisateur ne s'interpole JAMAIS dans un script : il passe en
``argv`` d'osascript, hors de portée de toute évasion.
"""

from __future__ import annotations

import subprocess
from typing import Any
from urllib.parse import quote, quote_plus

from diapason.core.registry import ToolRegistry
from diapason.tools._stubs import BaseTool, ToolResult, ToolSpec

_DELAI_S = 15.0


def _osascript(script: str, *args: str) -> tuple[bool, str]:
    """Exécute un script AppleScript, les valeurs utilisateur en argv."""
    try:
        r = subprocess.run(
            ["osascript", "-e", script, *args],
            capture_output=True,
            text=True,
            timeout=_DELAI_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "L'application n'a pas répondu à temps."
    except FileNotFoundError:
        return False, "osascript introuvable (hors macOS ?)."
    if r.returncode != 0:
        return False, (r.stderr or "").strip()[:200]
    return True, (r.stdout or "").strip()


def _ouvrir(url: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["open", url], capture_output=True, text=True, timeout=_DELAI_S, check=False
        )
    except subprocess.TimeoutExpired:
        return False, "open n'a pas rendu la main."
    if r.returncode != 0:
        return False, (r.stderr or "").strip()[:200]
    return True, ""


# Destination parlée → clé de mécanisme. Les variantes orales comptent : la
# transcription rend « app store », « l'App Store », « apple store »…
_DESTINATIONS: dict[str, str] = {
    "app store": "app_store",
    "appstore": "app_store",
    "apple store": "app_store",
    "magasin d'applications": "app_store",
    "spotify": "spotify",
    "notes": "notes",
    "note": "notes",
    "youtube": "youtube",
    "amazon": "amazon",
    "google": "web",
    "web": "web",
    "internet": "web",
    "navigateur": "web",
    "safari": "web",
    "browser": "web",
}


def _normaliser_app(app: str) -> str | None:
    import unicodedata

    cle = "".join(
        c
        for c in unicodedata.normalize("NFD", str(app or "").casefold())
        if not unicodedata.combining(c)
    )
    cle = " ".join(cle.replace("l'", "").replace("l’", "").split())
    # « dans LE navigateur », « sur MES notes » : l'article oral tombe.
    import re

    cle = re.sub(r"^(?:le|la|les|mon|ma|mes)\s+", "", cle)
    return _DESTINATIONS.get(cle)


@ToolRegistry.register("app_search")
class AppSearchTool(BaseTool):
    """Search INSIDE a named application, not just open it."""

    tool_id = "app_search"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="app_search",
            description=(
                "Search INSIDE an application: App Store, Spotify, Notes, "
                "YouTube, Amazon, or the web browser. Use for « recherche-moi "
                "des jeux sur l'App Store », « cherche X dans Notes », and for "
                "FOLLOW-UPS after opening an app — when the user just asked to "
                "open the App Store and now says « cherche des jeux », the app "
                "is the one from the conversation. Results appear on screen in "
                "that application."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "app": {
                        "type": "string",
                        "description": (
                            "Where to search: app store, spotify, notes, "
                            "youtube, amazon, or web."
                        ),
                    },
                    "query": {"type": "string", "description": "What to search for."},
                },
                "required": ["app", "query"],
            },
            category="system",
            timeout_seconds=20.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        app = str(params.get("app") or "")
        query = str(params.get("query") or "").strip()
        if not query:
            return ToolResult(
                tool_name="app_search",
                content="Il manque quoi chercher.",
                success=False,
            )
        mecanisme = _normaliser_app(app)
        if mecanisme is None:
            # Le refus sec laissait l'utilisateur sans rien — « certaines
            # recherches, il n'arrive pas à les faire » (23 août 2026). Le
            # repli : chercher sur le web EN LE DISANT. Une action annoncée
            # vaut mieux qu'une impasse, et l'honnêteté est sauve : la
            # réponse dit où la recherche est vraiment partie.
            from diapason.tools.desktop_tools import open_in_browser, web_search_url

            r = open_in_browser(web_search_url(f"{query} {app}".strip()))
            if not r.success:
                return ToolResult(
                    tool_name="app_search",
                    content=f"La recherche n'est pas partie : {r.content}",
                    success=False,
                )
            return ToolResult(
                tool_name="app_search",
                content=(
                    f"Je ne sais pas chercher directement dans « {app} » — "
                    f"j'ai lancé la recherche « {query} {app} » sur le web à "
                    "la place."
                ),
                success=True,
            )

        if mecanisme == "app_store":
            ok, detail = _ouvrir(
                "macappstore://search.itunes.apple.com/WebObjects/MZSearch.woa"
                f"/wa/search?q={quote_plus(query)}"
            )
            ou = "l'App Store"
        elif mecanisme == "spotify":
            ok, detail = _ouvrir(f"spotify:search:{quote(query)}")
            ou = "Spotify"
        elif mecanisme == "youtube":
            from diapason.tools.desktop_tools import open_in_browser

            r = open_in_browser(
                f"https://www.youtube.com/results?search_query={quote_plus(query)}"
            )
            ok, detail, ou = r.success, r.content if not r.success else "", "YouTube"
        elif mecanisme == "amazon":
            from diapason.tools.desktop_tools import open_in_browser

            r = open_in_browser(f"https://www.amazon.com/s?k={quote_plus(query)}")
            ok, detail, ou = r.success, r.content if not r.success else "", "Amazon"
        elif mecanisme == "notes":
            return self._chercher_dans_notes(query)
        else:  # web
            from diapason.tools.desktop_tools import open_in_browser, web_search_url

            r = open_in_browser(web_search_url(query))
            ok, detail, ou = (
                r.success,
                r.content if not r.success else "",
                "le navigateur",
            )

        if not ok:
            return ToolResult(
                tool_name="app_search",
                content=f"La recherche n'est pas partie : {detail}",
                success=False,
            )
        return ToolResult(
            tool_name="app_search",
            content=f"Recherche « {query} » lancée dans {ou} — résultats à l'écran.",
            success=True,
        )

    @staticmethod
    def _chercher_dans_notes(query: str) -> ToolResult:
        # Le dictionnaire AppleScript cherche titre ET contenu, puis MONTRE la
        # première trouvée : chercher sans afficher laisserait des mains
        # occupées devant une liste inerte.
        script = """
        on run argv
          set motif to item 1 of argv
          tell application "Notes"
            set trouvees to (every note whose name contains motif ¬
              or plaintext contains motif)
            if (count of trouvees) is 0 then return "0"
            show item 1 of trouvees
            set titres to ""
            repeat with n in trouvees
              set titres to titres & (name of n) & linefeed
            end repeat
            return (count of trouvees as text) & linefeed & titres
          end tell
        end run
        """
        ok, sortie = _osascript(script, query)
        if not ok:
            return ToolResult(
                tool_name="app_search",
                content=f"Notes n'a pas répondu : {sortie}",
                success=False,
            )
        lignes = [x for x in sortie.split("\n") if x.strip()]
        if not lignes or lignes[0] == "0":
            return ToolResult(
                tool_name="app_search",
                content=f"Aucune note ne contient « {query} ».",
                success=True,
                metadata={"count": 0},
            )
        titres = lignes[1:9]
        return ToolResult(
            tool_name="app_search",
            content=(
                f"{lignes[0]} note(s) trouvée(s), la première est ouverte : "
                + " · ".join(titres)
            ),
            success=True,
            metadata={"count": int(lignes[0]), "titles": titres},
        )


@ToolRegistry.register("notes_write")
class NotesWriteTool(BaseTool):
    """Create a note or append to one, through the Notes scripting dictionary."""

    tool_id = "notes_write"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="notes_write",
            description=(
                "Write in the Apple Notes app: create a new note, or append "
                "lines to an existing one found by its title. Use when the "
                "user dictates something to note down — « note dans Notes… », "
                "« ajoute à ma note courses… ». This edits the user's notes: "
                "only what they asked, nothing more."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["create", "append"]},
                    "title": {
                        "type": "string",
                        "description": "Note title (new, or the one to find).",
                    },
                    "text": {"type": "string", "description": "The text to write."},
                },
                "required": ["action", "title", "text"],
            },
            category="system",
            timeout_seconds=20.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        action = str(params.get("action") or "").strip()
        titre = str(params.get("title") or "").strip()
        texte = str(params.get("text") or "").strip()
        if not titre or not texte:
            return ToolResult(
                tool_name="notes_write",
                content="Il manque le titre ou le texte.",
                success=False,
            )
        if action == "create":
            script = """
            on run argv
              tell application "Notes"
                set n to make new note at folder "Notes" with properties ¬
                  {name:item 1 of argv, body:("<div>" & item 2 of argv & "</div>")}
                show n
                return "ok"
              end tell
            end run
            """
            ok, sortie = _osascript(script, titre, texte)
            if ok:
                return ToolResult(
                    tool_name="notes_write",
                    content=f"Note « {titre} » créée dans Notes.",
                    success=True,
                )
        elif action == "append":
            script = """
            on run argv
              set motif to item 1 of argv
              tell application "Notes"
                set trouvees to (every note whose name contains motif)
                if (count of trouvees) is 0 then return "absent"
                set n to item 1 of trouvees
                set body of n to (body of n) & "<div>" & item 2 of argv & "</div>"
                show n
                return name of n
              end tell
            end run
            """
            ok, sortie = _osascript(script, titre, texte)
            if ok and sortie == "absent":
                return ToolResult(
                    tool_name="notes_write",
                    content=(
                        f"Aucune note nommée « {titre} ». Dis-moi si je dois la créer."
                    ),
                    success=False,
                )
            if ok:
                return ToolResult(
                    tool_name="notes_write",
                    content=f"Ajouté à la note « {sortie} ».",
                    success=True,
                )
        else:
            return ToolResult(
                tool_name="notes_write",
                content="L'action doit être create ou append.",
                success=False,
            )
        return ToolResult(
            tool_name="notes_write",
            content=f"Notes n'a pas répondu : {sortie}",
            success=False,
        )


__all__ = ["AppSearchTool", "NotesWriteTool"]
