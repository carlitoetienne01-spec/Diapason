"""Menu-bar presence for background dictation.

A service with no terminal has no face: you cannot tell whether it is
listening, whether it heard you, or what it just wrote. The status item is the
smallest thing that fixes that — an icon that changes while recording, the
last transcript one click away, and a way to quit without hunting for
``launchctl``.

Design notes:

* The **menu model** (title, item labels, what each does) is pure and tested;
  only ``run()`` touches rumps/AppKit. A menu bar cannot be asserted on in CI,
  so everything that can be decided without a screen, is.
* Icons are text, not image assets: a bundled ``.icns`` would have to be
  regenerated and signed, and an emoji reads correctly in both light and dark
  menu bars at every size.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

IDLE_TITLE = "🎙"
RECORDING_TITLE = "🔴"
WORKING_TITLE = "⋯"


@dataclass(frozen=True)
class MenuItem:
    """One row of the status menu. ``action`` is None for a separator."""

    label: str
    action: Optional[str] = None
    enabled: bool = True


def title_for(state: str) -> str:
    """Map a dictation state to the menu-bar glyph.

    Anything unknown falls back to idle rather than raising: a status icon is
    never worth crashing a running service over.
    """
    return {
        "recording": RECORDING_TITLE,
        "transcribing": WORKING_TITLE,
        "pasting": WORKING_TITLE,
    }.get(state, IDLE_TITLE)


def build_menu(
    *, hotkey: str, last_text: str = "", running: bool = True
) -> List[MenuItem]:
    """The menu, as data.

    The last transcript is shown truncated and is copyable — that is the
    answer to "it pasted into the wrong window", which is the most common way
    a dictation goes missing.
    """
    items: List[MenuItem] = [
        MenuItem(
            f"Hold {hotkey.capitalize()} to dictate"
            if running
            else "Dictation is not running",
            action=None,
            enabled=False,
        ),
        MenuItem("", action=None),
    ]

    if last_text:
        preview = last_text if len(last_text) <= 60 else last_text[:57] + "…"
        items.append(MenuItem(f"Last: {preview}", action=None, enabled=False))
        items.append(MenuItem("Copy last transcript", action="copy_last"))
    else:
        items.append(MenuItem("No dictation yet", action=None, enabled=False))

    items.extend(
        [
            MenuItem("", action=None),
            MenuItem("Open history…", action="open_history"),
            MenuItem("", action=None),
            MenuItem("Quit dictation", action="quit"),
        ]
    )
    return items


def copy_to_clipboard(text: str) -> bool:
    """Put text on the pasteboard without pasting it anywhere."""
    if not text:
        return False
    try:
        from AppKit import NSPasteboard  # type: ignore

        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, "public.utf8-plain-text")
        return True
    except Exception:  # noqa: BLE001
        logger.debug("clipboard copy failed", exc_info=True)
        return False


class DictationMenuBar:
    """Live status item. Import-safe: rumps is only touched in ``run()``."""

    def __init__(
        self, *, hotkey: str = "control", on_quit: Callable[[], None] | None = None
    ):
        self.hotkey = hotkey
        self._on_quit = on_quit
        self._app = None
        self._last_text = ""

    def set_state(self, state: str) -> None:
        """Called from the dictation status callback; safe if no UI is up."""
        if self._app is None:
            return
        try:
            self._app.title = title_for(state)
        except Exception:  # noqa: BLE001 - a title update must never propagate
            logger.debug("menu title update failed", exc_info=True)

    def set_last_text(self, text: str) -> None:
        self._last_text = text or ""

    def run(self) -> None:  # pragma: no cover - needs a window server
        """Start the status item. Blocks on the AppKit run loop."""
        import rumps  # type: ignore

        menubar = self

        class _App(rumps.App):
            @rumps.clicked("Copy last transcript")
            def _copy(self, _sender):
                copy_to_clipboard(menubar._last_text)

            @rumps.clicked("Open history…")
            def _history(self, _sender):
                import subprocess

                from openjarvis.desktop.dictation_history import default_history_path

                subprocess.run(
                    ["open", "-t", str(default_history_path())],
                    capture_output=True,
                    check=False,
                )

            @rumps.clicked("Quit dictation")
            def _quit(self, _sender):
                if menubar._on_quit:
                    menubar._on_quit()
                rumps.quit_application()

        self._app = _App(IDLE_TITLE, quit_button=None)
        self._app.menu = [
            f"Hold {self.hotkey.capitalize()} to dictate",
            None,
            "Copy last transcript",
            "Open history…",
            None,
            "Quit dictation",
        ]
        self._app.run()
