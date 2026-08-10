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
def dictate(hotkey: str) -> None:
    """Start global push-to-talk dictation."""
    from openjarvis.core.config import load_config
    from openjarvis.desktop.dictation_service import DictationService
    from openjarvis.desktop.hotkey import AccessibilityError
    from openjarvis.speech._discovery import get_speech_backend

    config = load_config()
    key = hotkey or getattr(config.dictation, "hotkey", "") or "control"

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

    click.echo(f"Dictation ready. Hold {key!r} and speak. Ctrl-C to quit.")

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
