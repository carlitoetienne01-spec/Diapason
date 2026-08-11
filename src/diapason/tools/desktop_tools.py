"""Desktop automation tools — open URI/apps, place Chrome, paste to frontmost."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?:/.*)?$",
    re.IGNORECASE,
)


def _run(cmd: list[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def resolve_mac_app_name(name: str) -> str | None:
    """Resolve a spoken/typed app name to an ``.app`` bundle name on macOS."""
    raw = (name or "").strip().strip(".app")
    if not raw:
        return None

    # Prefer exact / fuzzy match under /Applications and ~/Applications.
    needles = [raw.lower(), raw.lower().replace(" ", "")]
    roots = [
        Path("/Applications"),
        Path("/System/Applications"),
        Path.home() / "Applications",
    ]
    exact: list[str] = []
    partial: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for child in root.iterdir():
                if not child.name.endswith(".app"):
                    continue
                stem = child.stem
                low = stem.lower()
                compact = low.replace(" ", "")
                if low == needles[0] or compact == needles[1]:
                    exact.append(stem)
                elif needles[0] in low or needles[1] in compact:
                    partial.append(stem)
        except OSError:
            continue
    if exact:
        return exact[0]
    if partial:
        # Prefer shortest name (Chrome over Google Chrome Helper-like noise)
        partial.sort(key=len)
        return partial[0]

    # Last resort: ask Launch Services via `open -a` (caller will try).
    return raw


def looks_like_url(target: str) -> bool:
    t = (target or "").strip()
    if not t:
        return False
    low = t.lower()
    if low.startswith(("http://", "https://", "file://", "spotify:")):
        return True
    if low.startswith("www."):
        return True
    if " " in t:
        return False
    return bool(_DOMAIN_RE.match(t))


def normalize_url(target: str) -> str:
    t = (target or "").strip()
    if t.startswith("www."):
        return "https://" + t
    if looks_like_url(t) and not t.lower().startswith(
        ("http://", "https://", "file://", "spotify:")
    ):
        return "https://" + t
    return t


def web_search_url(query: str, *, engine: str = "google") -> str:
    from urllib.parse import quote_plus

    q = quote_plus((query or "").strip())
    eng = (engine or "google").lower()
    if eng in ("ddg", "duckduckgo"):
        return f"https://duckduckgo.com/?q={q}"
    if eng == "bing":
        return f"https://www.bing.com/search?q={q}"
    return f"https://www.google.com/search?q={q}"


def open_in_browser(url: str, *, browser: str = "") -> ToolResult:
    """Open a URL in a preferred browser or the system default."""
    url = normalize_url(url)
    browser = (browser or "").strip()
    try:
        if sys.platform == "darwin" and browser:
            app = resolve_mac_app_name(browser) or browser
            r = _run(["open", "-a", app, url])
            if r.returncode != 0:
                r = _run(["open", url])
        elif sys.platform == "darwin":
            r = _run(["open", url])
        elif sys.platform == "win32":
            if browser:
                _run(["cmd", "/c", "start", "", browser, url])
            else:
                os.startfile(url)  # type: ignore[attr-defined]
            return ToolResult(
                tool_name="open_anything",
                content=f"Opened {url}",
                success=True,
                metadata={"kind": "url", "url": url, "browser": browser},
            )
        else:
            r = _run(["xdg-open", url])
        if r.returncode != 0:
            return ToolResult(
                tool_name="open_anything",
                content=(r.stderr or r.stdout or "Failed to open URL").strip(),
                success=False,
            )
        return ToolResult(
            tool_name="open_anything",
            content=f"Opened {url}",
            success=True,
            metadata={"kind": "url", "url": url, "browser": browser},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ToolResult(tool_name="open_anything", content=str(exc), success=False)


def open_application(app_name: str) -> ToolResult:
    """Launch or focus an application by name."""
    name = (app_name or "").strip()
    if not name:
        return ToolResult(
            tool_name="open_anything", content="No app name.", success=False
        )
    try:
        if sys.platform == "darwin":
            resolved = resolve_mac_app_name(name) or name
            r = _run(["open", "-a", resolved])
            if r.returncode != 0:
                # Activate via AppleScript as fallback
                r2 = _run(
                    ["osascript", "-e", f'tell application "{resolved}" to activate']
                )
                if r2.returncode != 0:
                    return ToolResult(
                        tool_name="open_anything",
                        content=(
                            r.stderr or r2.stderr or f"Could not open app '{name}'"
                        ).strip(),
                        success=False,
                    )
            return ToolResult(
                tool_name="open_anything",
                content=f"Opened app {resolved}",
                success=True,
                metadata={"kind": "app", "app": resolved},
            )
        if sys.platform == "win32":
            r = _run(["cmd", "/c", "start", "", name])
            return ToolResult(
                tool_name="open_anything",
                content=f"Started {name}",
                success=r.returncode == 0,
                metadata={"kind": "app", "app": name},
            )
        # Linux: try binary then gtk-launch
        binary = shutil.which(name.lower().replace(" ", "-")) or shutil.which(
            name.lower()
        )
        if binary:
            subprocess.Popen(
                [binary],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return ToolResult(
                tool_name="open_anything",
                content=f"Launched {binary}",
                success=True,
                metadata={"kind": "app", "app": binary},
            )
        return ToolResult(
            tool_name="open_anything",
            content=f"Cannot find application '{name}'.",
            success=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ToolResult(tool_name="open_anything", content=str(exc), success=False)


def _chrome_executable() -> str | None:
    if sys.platform == "darwin":
        mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.isfile(mac):
            return mac
    if sys.platform == "win32":
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ):
            if not base:
                continue
            p = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.isfile(p):
                return p
    return shutil.which("google-chrome") or shutil.which("chrome") or shutil.which(
        "chromium"
    )


@ToolRegistry.register("open_anything")
class OpenAnythingTool(BaseTool):
    """Open any app, URL, file, or web search on the user's computer."""

    tool_id = "open_anything"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_anything",
            description=(
                "Open ANYTHING on the user's computer on demand: an installed "
                "application, a website, YouTube/Spotify/Amazon search-or-play, "
                "a local file/folder path, or a web search. Understands phrases "
                "like 'open YouTube and search for cats', 'play X on Spotify', "
                "'cherche X sur amazon'. Prefer this tool whenever the user asks "
                "to open, launch, play, go to, search, or show something."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": (
                            "App name, URL/domain, file path, or search text "
                            "(e.g. 'Cursor', 'youtube.com', 'weather in Paris')."
                        ),
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["auto", "app", "url", "search", "file"],
                        "description": (
                            "How to interpret target. Use 'auto' unless the user "
                            "clearly asked to search the web or open a file."
                        ),
                    },
                    "browser": {
                        "type": "string",
                        "description": (
                            "Optional browser app for url/search "
                            "(e.g. 'Google Chrome', 'Safari'). Empty = default."
                        ),
                    },
                    "search_engine": {
                        "type": "string",
                        "enum": ["google", "duckduckgo", "bing"],
                        "description": "Search engine when kind=search (default google).",
                    },
                },
                "required": ["target"],
            },
            category="system",
            timeout_seconds=20.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        target = str(params.get("target") or "").strip()
        kind = str(params.get("kind") or "auto").strip().lower() or "auto"
        browser = str(params.get("browser") or "").strip()
        engine = str(params.get("search_engine") or "google").strip().lower()
        if not target:
            return ToolResult(
                tool_name="open_anything",
                content="No target provided.",
                success=False,
            )

        # Diapason-style rich intents (YouTube / Spotify / Amazon / …)
        if kind in ("auto", "url", "search"):
            try:
                from diapason.desktop.smart_intents import try_execute_smart_command

                smart = try_execute_smart_command(target, browser=browser)
                if smart is not None:
                    return smart
            except Exception:
                pass

        # Explicit / inferred search
        search_prefixes = (
            "search:",
            "google:",
            "cherche:",
            "rechercher:",
            "search for ",
            "cherche ",
            "rechercher ",
            "google ",
        )
        low = target.lower()
        if kind == "search" or any(low.startswith(p) for p in search_prefixes):
            query = target
            for p in search_prefixes:
                if low.startswith(p):
                    query = target[len(p) :].strip()
                    break
            return open_in_browser(
                web_search_url(query, engine=engine), browser=browser
            )

        if kind == "file" or (
            kind == "auto"
            and (target.startswith("~") or target.startswith("/") or Path(target).exists())
        ):
            path = Path(target).expanduser()
            if not path.exists() and kind == "file":
                return ToolResult(
                    tool_name="open_anything",
                    content=f"Path not found: {path}",
                    success=False,
                )
            if path.exists():
                return OpenUriTool().execute(uri=str(path))

        if kind == "url" or (kind == "auto" and looks_like_url(target)):
            return open_in_browser(normalize_url(target), browser=browser)

        if kind in ("app", "auto"):
            # If it looks like a multi-word question / search, open as search
            if kind == "auto" and (
                "?" in target
                or target.lower().startswith(("what ", "who ", "how ", "où ", "quel "))
                or (len(target.split()) >= 4 and not Path(target).suffix)
            ):
                return open_in_browser(
                    web_search_url(target, engine=engine), browser=browser
                )
            return open_application(target)

        return ToolResult(
            tool_name="open_anything",
            content=f"Unknown kind '{kind}'",
            success=False,
        )


@ToolRegistry.register("open_uri")
class OpenUriTool(BaseTool):
    """Open a file, URL, or Spotify URI with the OS default handler."""

    tool_id = "open_uri"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_uri",
            description=(
                "Open a URI (https://, spotify:, file path) with the system "
                "default application (macOS open / Windows start / xdg-open)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "uri": {
                        "type": "string",
                        "description": "URI or path to open.",
                    },
                },
                "required": ["uri"],
            },
            category="system",
            timeout_seconds=15.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        uri = (params.get("uri") or "").strip()
        if not uri:
            return ToolResult(
                tool_name="open_uri", content="No uri provided.", success=False
            )
        try:
            if sys.platform == "darwin":
                r = _run(["open", uri])
            elif sys.platform == "win32":
                os.startfile(uri)  # type: ignore[attr-defined]
                return ToolResult(
                    tool_name="open_uri", content=f"Opened {uri}", success=True
                )
            else:
                r = _run(["xdg-open", uri])
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "").strip()
                return ToolResult(
                    tool_name="open_uri",
                    content=f"Failed to open URI: {err}",
                    success=False,
                )
            return ToolResult(
                tool_name="open_uri", content=f"Opened {uri}", success=True
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(
                tool_name="open_uri", content=str(exc), success=False
            )


@ToolRegistry.register("focus_app")
class FocusAppTool(BaseTool):
    """Bring a desktop application to the foreground (best-effort fullscreen)."""

    tool_id = "focus_app"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="focus_app",
            description=(
                "Focus an installed application by name (e.g. Cursor, "
                "Google Chrome). On macOS optionally toggle fullscreen "
                "(Ctrl+Cmd+F)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Application name as shown in Finder/Start.",
                    },
                    "fullscreen": {
                        "type": "boolean",
                        "description": "If true, send fullscreen shortcut after focus.",
                    },
                },
                "required": ["app_name"],
            },
            category="system",
            timeout_seconds=20.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        name = (params.get("app_name") or "").strip()
        fullscreen = bool(params.get("fullscreen", False))
        if not name:
            return ToolResult(
                tool_name="focus_app", content="No app_name.", success=False
            )

        try:
            if sys.platform == "darwin":
                # Launch if needed, then activate (handles any installed .app)
                resolved = resolve_mac_app_name(name) or name
                _run(["open", "-a", resolved])
                script = f'tell application "{resolved}" to activate\n'
                if fullscreen:
                    script += f'''
delay 0.35
tell application "System Events"
  tell process "{resolved}"
    set frontmost to true
    try
      keystroke "f" using {{control down, command down}}
    end try
  end tell
end tell
'''
                r = _run(["osascript", "-e", script])
                if r.returncode != 0:
                    return ToolResult(
                        tool_name="focus_app",
                        content=(r.stderr or f"focus failed for {resolved}").strip(),
                        success=False,
                    )
                return ToolResult(
                    tool_name="focus_app",
                    content=f"Focused {resolved}",
                    success=True,
                    metadata={"fullscreen": fullscreen, "app": resolved},
                )

            if sys.platform == "win32":
                # Best-effort via start
                r = _run(["cmd", "/c", "start", "", name])
                return ToolResult(
                    tool_name="focus_app",
                    content=f"Started/focused {name}",
                    success=r.returncode == 0,
                )

            # Linux
            if shutil.which(name.lower()):
                subprocess.Popen(
                    [name.lower()],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return ToolResult(
                    tool_name="focus_app", content=f"Launched {name}", success=True
                )
            return ToolResult(
                tool_name="focus_app",
                content=f"Cannot focus '{name}' on this platform.",
                success=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(tool_name="focus_app", content=str(exc), success=False)


@ToolRegistry.register("open_browser_on_monitor")
class OpenBrowserOnMonitorTool(BaseTool):
    """Open a URL in Chrome on a given 1-based monitor index."""

    tool_id = "open_browser_on_monitor"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_browser_on_monitor",
            description=(
                "Open a URL in a new Google Chrome window, optionally placing "
                "it on monitor N (1-based, left-to-right). macOS uses "
                "AppleScript; other platforms open a new Chrome window."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to open."},
                    "monitor": {
                        "type": "integer",
                        "description": "1-based monitor index (default 1).",
                    },
                    "fullscreen": {
                        "type": "boolean",
                        "description": "Try fullscreen after placing (macOS).",
                    },
                    "label": {
                        "type": "string",
                        "description": "Optional label for logging.",
                    },
                },
                "required": ["url"],
            },
            category="system",
            timeout_seconds=45.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        url = (params.get("url") or "").strip()
        if not url:
            return ToolResult(
                tool_name="open_browser_on_monitor",
                content="No url.",
                success=False,
            )
        monitor = int(params.get("monitor") or 1)
        fullscreen = bool(params.get("fullscreen", True))
        label = (params.get("label") or "").strip() or urlparse(url).netloc or "page"

        chrome = _chrome_executable()
        try:
            if chrome:
                args = [chrome, "--new-window", url]
                subprocess.Popen(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                OpenUriTool().execute(uri=url)

            if sys.platform == "darwin":
                from diapason.desktop.monitors import monitor_placement

                if fullscreen:
                    left, top, right, bottom = monitor_placement(monitor)
                else:
                    left, top, right, bottom = monitor_placement(
                        monitor, windowed=(1400, 900)
                    )
                needle = (urlparse(url).netloc or url)[:60].replace('"', "")
                script = f'''
tell application "Google Chrome"
  activate
  delay 1.0
  set targetWin to missing value
  repeat with w in windows
    try
      set t to (title of w) as text
      if t contains "{needle}" then
        set targetWin to w
        exit repeat
      end if
    end try
  end repeat
  if targetWin is missing value then
    if (count of windows) > 0 then set targetWin to window 1
  end if
  if targetWin is not missing value then
    set bounds of targetWin to {{{left}, {top}, {right}, {bottom}}}
  end if
end tell
'''
                if fullscreen:
                    script += """
delay 0.25
tell application "System Events"
  tell process "Google Chrome"
    set frontmost to true
    try
      keystroke "f" using {control down, command down}
    end try
  end tell
end tell
"""
                r = _run(["osascript", "-e", script], timeout=25.0)
                if r.returncode != 0:
                    logger.warning(
                        "Chrome place warning (%s): %s",
                        label,
                        (r.stderr or "").strip(),
                    )

            return ToolResult(
                tool_name="open_browser_on_monitor",
                content=f"Opened {label} on monitor {monitor}",
                success=True,
                metadata={"url": url, "monitor": monitor, "fullscreen": fullscreen},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(
                tool_name="open_browser_on_monitor",
                content=str(exc),
                success=False,
            )


@ToolRegistry.register("paste_to_frontmost")
class PasteToFrontmostTool(BaseTool):
    """Copy text to clipboard and paste into the frontmost application."""

    tool_id = "paste_to_frontmost"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="paste_to_frontmost",
            description=(
                "Put text on the clipboard and paste it into the frontmost "
                "app (macOS: pbcopy + Cmd+V via System Events; requires "
                "Accessibility permission)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to paste.",
                    },
                },
                "required": ["text"],
            },
            category="system",
            timeout_seconds=15.0,
            requires_confirmation=False,
        )

    def execute(self, **params: Any) -> ToolResult:
        text = params.get("text", "")
        if text is None:
            text = ""
        text = str(text)
        if not text:
            return ToolResult(
                tool_name="paste_to_frontmost",
                content="No text.",
                success=False,
            )

        try:
            if sys.platform == "darwin":
                # Preferred path: save the clipboard, paste, restore it. The
                # old pbcopy+osascript path below overwrote whatever the user
                # had copied and never put it back — a daily papercut for a
                # tool that fires dozens of times an hour. Falls back to that
                # path only if PyObjC is unavailable.
                try:
                    from diapason.desktop.clipboard import paste_text

                    if paste_text(text):
                        return ToolResult(
                            tool_name="paste_to_frontmost",
                            content=(
                                "Pasted into frontmost app "
                                "(clipboard preserved)"
                            ),
                            success=True,
                            metadata={"chars": len(text), "clipboard_restored": True},
                        )
                except ImportError:
                    pass  # PyObjC not installed — fall through to legacy path

                p = subprocess.run(
                    ["pbcopy"],
                    input=text.encode("utf-8"),
                    capture_output=True,
                    check=False,
                )
                if p.returncode != 0:
                    return ToolResult(
                        tool_name="paste_to_frontmost",
                        content="pbcopy failed",
                        success=False,
                    )
                r = _run(
                    [
                        "osascript",
                        "-e",
                        'tell application "System Events" to keystroke "v" using command down',
                    ]
                )
                if r.returncode != 0:
                    return ToolResult(
                        tool_name="paste_to_frontmost",
                        content=(
                            "Clipboard set but paste failed — grant Accessibility "
                            "to Terminal/Diapason. "
                            + (r.stderr or "").strip()
                        ),
                        success=False,
                        metadata={"clipboard": True, "pasted": False},
                    )
                return ToolResult(
                    tool_name="paste_to_frontmost",
                    content="Pasted into frontmost app",
                    success=True,
                    metadata={"chars": len(text)},
                )

            if sys.platform == "win32":
                # Clipboard via PowerShell + Ctrl+V
                encoded = text.replace("'", "''")
                ps = (
                    f"Set-Clipboard -Value '{encoded}'; "
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "[System.Windows.Forms.SendKeys]::SendWait('^v')"
                )
                r = _run(["powershell", "-NoProfile", "-Command", ps])
                return ToolResult(
                    tool_name="paste_to_frontmost",
                    content="Paste attempted (Windows)",
                    success=r.returncode == 0,
                )

            # Linux: xclip/wl-copy best-effort
            if shutil.which("wl-copy"):
                subprocess.run(["wl-copy"], input=text.encode(), check=False)
            elif shutil.which("xclip"):
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode(),
                    check=False,
                )
            else:
                return ToolResult(
                    tool_name="paste_to_frontmost",
                    content="No clipboard utility (wl-copy/xclip)",
                    success=False,
                )
            return ToolResult(
                tool_name="paste_to_frontmost",
                content="Copied to clipboard (paste manually if needed)",
                success=True,
                metadata={"pasted": False},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(
                tool_name="paste_to_frontmost", content=str(exc), success=False
            )


@ToolRegistry.register("play_audio_file")
class PlayAudioFileTool(BaseTool):
    """Play a local audio file through the system player."""

    tool_id = "play_audio_file"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="play_audio_file",
            description="Play an audio file path with the OS default player.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to audio file."},
                },
                "required": ["path"],
            },
            category="audio",
            timeout_seconds=10.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        path = Path((params.get("path") or "").strip()).expanduser()
        if not path.is_file():
            return ToolResult(
                tool_name="play_audio_file",
                content=f"File not found: {path}",
                success=False,
            )
        return OpenUriTool().execute(uri=str(path))


@ToolRegistry.register("run_voice_command")
class RunVoiceCommandTool(BaseTool):
    """Parse a spoken phrase and open an app or URL when it looks like a command."""

    tool_id = "run_voice_command"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_voice_command",
            description=(
                "Interpret a short spoken command such as 'open Cursor', "
                "'ouvre Spotify', or 'go to claude.ai' and execute it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Spoken command text.",
                    },
                },
                "required": ["text"],
            },
            category="system",
            timeout_seconds=20.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        from diapason.desktop.voice_commands import (
            execute_voice_action,
            parse_voice_command,
        )

        text = str(params.get("text") or "").strip()
        action = parse_voice_command(text)
        if action.kind == "none":
            return ToolResult(
                tool_name="run_voice_command",
                content="Not a recognized voice command.",
                success=False,
                metadata={"kind": "none"},
            )
        result = execute_voice_action(action)
        return ToolResult(
            tool_name="run_voice_command",
            content=str(result.get("detail") or result),
            success=bool(result.get("success")),
            metadata=result,
        )


__all__ = [
    "OpenAnythingTool",
    "OpenUriTool",
    "FocusAppTool",
    "OpenBrowserOnMonitorTool",
    "PasteToFrontmostTool",
    "PlayAudioFileTool",
    "RunVoiceCommandTool",
]
