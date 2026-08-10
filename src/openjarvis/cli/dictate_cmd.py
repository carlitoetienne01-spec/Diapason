"""CLI: jarvis dictate — hold the hotkey, speak, release, text appears.

Wires the push-to-talk stack to the configured speech backend and the
clipboard-preserving paste. Runs headless (no window needed); needs
Accessibility permission for the key tap and Microphone permission for capture.
"""

from __future__ import annotations

import logging
import sys

import click

logger = logging.getLogger(__name__)


@click.command("dictate")
@click.option(
    "--hotkey",
    default="",
    help="Push-to-talk key: control (default), option, or fn.",
)
@click.option(
    "--check",
    is_flag=True,
    help="Diagnose the hotkey: echo key down/up for 15s, no mic, no model.",
)
def dictate(hotkey: str, check: bool) -> None:
    """Start global push-to-talk dictation."""
    from openjarvis.core.config import load_config
    from openjarvis.desktop.dictation_service import DictationService
    from openjarvis.desktop.hotkey import AccessibilityError
    from openjarvis.desktop.keycodes import SUPPORTED_HOTKEYS, normalize_hotkey
    from openjarvis.speech._discovery import get_speech_backend

    config = load_config()

    if check:
        _run_check(hotkey or getattr(config.dictation, "hotkey", "") or "control")
        return
    raw = hotkey or getattr(config.dictation, "hotkey", "") or "control"
    # The push-to-talk tap listens for a BARE modifier, not a chord. The
    # existing config may carry a Tauri accelerator like "Cmd+Alt+Space",
    # which normalize_hotkey coerces to the default. Tell the user which key
    # is actually live instead of echoing a value that does nothing.
    key = normalize_hotkey(raw)
    if key != raw.strip().lower():
        click.echo(
            f"Note: {raw!r} is not a bare modifier; using {key!r}. "
            f"Set dictation.hotkey to one of {', '.join(SUPPORTED_HOTKEYS)}.",
            err=True,
        )

    backend = get_speech_backend(config)
    if backend is None:
        click.echo(
            "No speech backend available. In local-only mode, run "
            "`jarvis model pull base` first, or set [privacy] local_only = false.",
            err=True,
        )
        sys.exit(1)

    def _transcribe(wav_bytes: bytes) -> str:
        result = backend.transcribe(wav_bytes, format="wav")
        return getattr(result, "text", "") or ""

    def _paste(text: str) -> None:
        from openjarvis.desktop.clipboard import paste_text

        paste_text(text)

    service = DictationService(transcribe=_transcribe, paste=_paste, hotkey=key)

    try:
        service.start()
    except AccessibilityError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    click.echo(
        f"Dictation ready. Hold the {key.capitalize()} key and speak, then "
        "release. Double-tap for hands-free. Ctrl-C to quit."
    )

    # Block the main thread until interrupted; the tap runs on its own run
    # loop thread. threading.Event().wait() is interruptible by Ctrl-C.
    import threading

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
        click.echo("Dictation stopped.")


def _run_check(raw_hotkey: str) -> None:
    """Echo hotkey transitions for 15s — isolates the tap from mic/model."""
    import time

    from openjarvis.desktop.hotkey import AccessibilityError, HotkeyListener
    from openjarvis.desktop.keycodes import normalize_hotkey

    key = normalize_hotkey(raw_hotkey)
    counts = {"down": 0, "up": 0}

    def _down() -> None:
        counts["down"] += 1
        click.echo(f"  {key.capitalize()} DOWN  (#{counts['down']})")

    def _up() -> None:
        counts["up"] += 1
        click.echo(f"  {key.capitalize()} UP    (#{counts['up']})")

    listener = HotkeyListener(hotkey=key, on_down=_down, on_up=_up)
    try:
        listener.start()
    except AccessibilityError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    click.echo(f"Press and release the {key.capitalize()} key a few times (15s)...")
    try:
        time.sleep(15)
    finally:
        listener.stop()
    total = counts["down"] + counts["up"]
    if total == 0:
        click.echo(
            "\nReceived 0 events. The tap is starved — grant Accessibility to "
            "your terminal app (System Settings › Privacy & Security › "
            "Accessibility), fully quit and reopen the terminal, then retry.",
            err=True,
        )
        sys.exit(1)
    click.echo(f"\nOK — {counts['down']} down, {counts['up']} up. The hotkey works.")
