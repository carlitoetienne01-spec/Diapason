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


def _quiet_library_noise() -> None:
    """Silence library chatter that prints mid-dictation and reads as broken.

    faster-whisper's mel filterbank emits numpy RuntimeWarnings (divide by
    zero / overflow in matmul) on ordinary speech frames — harmless, upstream,
    and printed straight into the session. Scoped to that one module so real
    warnings elsewhere still surface.
    """
    import warnings

    warnings.filterwarnings(
        "ignore",
        category=RuntimeWarning,
        module=r"faster_whisper\.feature_extractor",
    )


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
@click.option(
    "--mic-test",
    is_flag=True,
    help="Diagnose the microphone: record 3s, print level and transcript.",
)
@click.option(
    "--menu-bar/--no-menu-bar",
    default=False,
    show_default=True,
    help="Show a status icon in the menu bar (needs a GUI session).",
)
def dictate(hotkey: str, check: bool, mic_test: bool, menu_bar: bool) -> None:
    """Start global push-to-talk dictation."""
    from openjarvis.core.config import load_config
    from openjarvis.desktop.dictation_service import DictationService
    from openjarvis.desktop.hotkey import AccessibilityError
    from openjarvis.desktop.keycodes import SUPPORTED_HOTKEYS, normalize_hotkey
    from openjarvis.speech._discovery import get_speech_backend

    _quiet_library_noise()
    config = load_config()

    if check:
        _run_check(hotkey or getattr(config.dictation, "hotkey", "") or "control")
        return
    if mic_test:
        _run_mic_test(config)
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

    if not _ensure_permissions():
        # Exit 0, not 1: missing permission is a "come back after granting"
        # state, not a crash. Under the LaunchAgent (KeepAlive on failure
        # only) a clean exit avoids a restart loop that would re-prompt every
        # few seconds. The user grants, then runs `dictate-service restart`.
        sys.exit(0)

    # Optional menu-bar presence: a background service otherwise has no face.
    bar = None
    if menu_bar:
        from openjarvis.desktop.menu_bar import DictationMenuBar

        bar = DictationMenuBar(hotkey=key)

    def _status(msg: str) -> None:
        click.echo(f"  [{msg}]")
        if bar is not None:
            # Map the human status line onto the icon's coarse states.
            state = (
                "recording"
                if msg.startswith("recording")
                else "transcribing"
                if msg.startswith("transcribing")
                else "pasting"
                if msg.startswith("pasting")
                else "idle"
            )
            bar.set_state(state)

    service = DictationService(
        transcribe=_transcribe,
        paste=_paste,
        hotkey=key,
        # Every stage reports to the terminal. Without this, a muted mic, a
        # silent buffer and a failed paste all look the same: "nothing".
        on_status=_status,
        model_name=str(getattr(config.speech, "model", "") or ""),
        on_transcript=(bar.set_last_text if bar is not None else None),
    )

    try:
        service.start()
    except AccessibilityError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    click.echo(
        f"Dictation ready. Hold the {key.capitalize()} key and speak, then "
        "release. Double-tap for hands-free. Ctrl-C to quit."
    )

    if bar is not None:
        # rumps owns the main thread once started, so the blocking wait below
        # is replaced by its run loop. Quitting the menu stops the service.
        bar._on_quit = service.stop
        try:
            bar.run()
        except Exception as exc:  # noqa: BLE001 - fall back to headless
            click.echo(f"Menu bar unavailable ({exc}); running headless.", err=True)
        else:
            click.echo("Dictation stopped.")
            return

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


def _ensure_permissions() -> bool:
    """Check the three TCC permissions dictation needs; prompt for any missing.

    Input Monitoring gates the key tap, Microphone gates capture, Accessibility
    gates the paste. All are requested so the user grants them in one pass.
    Returns True only when nothing is missing.
    """
    from openjarvis.desktop import permissions

    missing = permissions.missing_for_dictation()
    if not missing:
        return True

    click.echo(
        "Dictation needs these macOS permissions, still missing: "
        + ", ".join(missing),
        err=True,
    )
    click.echo(
        "Opening the system prompts. Enable your terminal app under EACH of "
        "them in System Settings › Privacy & Security, then FULLY quit (Cmd-Q) "
        "and reopen the terminal, and rerun.",
        err=True,
    )
    if "Input Monitoring" in missing:
        permissions.request_input_monitoring()
    if "Microphone" in missing:
        permissions.request_microphone()
    if "Accessibility" in missing:
        permissions.request_accessibility()
    for name in missing:
        permissions.open_pane(name)
    return False


def _run_mic_test(config) -> None:
    """Record 3 s, print the level, transcribe, print the text.

    Isolates microphone + STT from the hotkey and the paste: if this works
    but dictation pastes nothing, the problem is on the other side (tap or
    Cmd+V); if the level stays at ~0, it is the Microphone permission.
    """
    import time

    from openjarvis.desktop.dictation_service import float_mono_to_wav
    from openjarvis.desktop.mic_capture import MicCapture, rms_level
    from openjarvis.speech._discovery import get_speech_backend

    _quiet_library_noise()
    backend = get_speech_backend(config)
    if backend is None:
        click.echo("No speech backend available.", err=True)
        sys.exit(1)

    click.echo("Recording 3 seconds — SPEAK NOW…")
    cap = MicCapture()
    try:
        cap.start()
    except Exception as exc:  # noqa: BLE001 - surface device errors verbatim
        click.echo(f"Could not open the microphone: {exc}", err=True)
        click.echo(
            "Grant Microphone to your terminal app (System Settings › "
            "Privacy & Security › Microphone), then retry.",
            err=True,
        )
        sys.exit(1)
    time.sleep(3)
    audio = cap.stop()

    level = rms_level(audio) if len(audio) else 0.0
    click.echo(f"Captured {len(audio) / 16_000.0:.1f}s, level {level:.2f} (0–100).")

    if len(audio) == 0 or level < 0.05:
        click.echo(
            "\nThe microphone delivered silence. macOS gives an app muted "
            "audio when Microphone permission is missing — enable your "
            "terminal app under System Settings › Privacy & Security › "
            "Microphone, fully quit and reopen the terminal, then retry.",
            err=True,
        )
        sys.exit(1)

    click.echo("Transcribing…")
    result = backend.transcribe(float_mono_to_wav(audio), format="wav")
    text = (getattr(result, "text", "") or "").strip()
    click.echo(f"Transcript: {text!r}" if text else "Transcript came back empty.")
    click.echo("\nMic + transcription OK." if text else "", err=False)


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

    if not _ensure_permissions():
        sys.exit(1)

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
