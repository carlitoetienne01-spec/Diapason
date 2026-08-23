"""CLI: diapason dictate — hold the hotkey, speak, release, text appears.

Wires the push-to-talk stack to the configured speech backend and the
clipboard-preserving paste. Runs headless (no window needed); needs
Accessibility permission for the key tap and Microphone permission for capture.
"""

from __future__ import annotations

import logging
import os
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


_CORRECTION_MARGE_ABSOLUE = 12


def _correction_fidele(brut: str, corrige: str, *, marge: float = 0.35) -> bool:
    """Si la correction reste proche de ce qui a été dit.

    Le garde-fou que le polissage par modèle exige. Le prompt lui interdit
    d'inventer, mais un prompt est un vœu : sur une phrase mal transcrite, un
    petit modèle résume, complète ou répond à la question au lieu de la
    corriger. L'écart de longueur est le signal le plus simple et le plus
    robuste — une correction d'orthographe ne change pas un texte d'un tiers.

    Une dictée corrigée à tort est difficile à rattraper : on écarte au
    moindre doute, quitte à laisser passer une faute.
    """
    b, c = (brut or "").strip(), (corrige or "").strip()
    if not c:
        return False
    if not b:
        return True
    delta = abs(len(c) - len(b))
    # Un plancher absolu à côté de la marge relative : sur une phrase courte,
    # « ca va » → « Ça va ? » fait +40 % tout en étant exactement la
    # correction demandée. Accents, ponctuation et majuscules ajoutent un
    # nombre BORNÉ de caractères ; c'est la proportion qui trompe, pas eux.
    if delta <= _CORRECTION_MARGE_ABSOLUE:
        return True
    return delta / max(len(b), 1) <= marge


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
    "--setup",
    is_flag=True,
    help="Check everything dictation needs and say what is missing.",
)
@click.option(
    "--menu-bar/--no-menu-bar",
    default=False,
    show_default=True,
    help="Show a status icon in the menu bar (needs a GUI session).",
)
@click.option(
    "--sound/--no-sound",
    default=True,
    show_default=True,
    help="Play a short blip when recording starts and stops.",
)
@click.option(
    "--overlay/--no-overlay",
    default=True,
    show_default=True,
    help="Show the floating level indicator while dictating.",
)
def dictate(
    hotkey: str,
    check: bool,
    mic_test: bool,
    setup: bool,
    menu_bar: bool,
    sound: bool,
    overlay: bool,
) -> None:
    """Start global push-to-talk dictation."""
    # Le MICRO d'abord — le contrôle le moins cher, avant de résoudre modèle
    # ou touches. Trois fois déjà, ce venv a perdu des paquets (une
    # synchronisation d'uv sans les extras les élague) ; le service démarrait
    # « prêt », puis chaque pression de Contrôle échouait en silence dans le
    # journal — pour l'utilisateur, « la dictée ne fonctionne plus » sans un
    # mot. Constaté le 23 août 2026, sounddevice absent. Sortie 0 exprès :
    # avec KeepAlive, un code d'échec relancerait la même impasse en boucle.
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        click.echo(
            "La dictée ne peut pas démarrer : le paquet du micro (sounddevice) "
            "manque à l'environnement.\n"
            "Remède :  uv pip install --python .venv/bin/python 'sounddevice>=0.4'\n"
            "puis :    launchctl kickstart -k gui/$UID/com.diapason.dictate",
            err=True,
        )
        sys.exit(0)

    from diapason.core.config import load_config
    from diapason.desktop.dictation_service import DictationService
    from diapason.desktop.hotkey import AccessibilityError
    from diapason.desktop.keycodes import SUPPORTED_HOTKEYS, normalize_hotkey
    from diapason.speech._discovery import get_speech_backend

    _quiet_library_noise()
    config = load_config()

    if check:
        _run_check(hotkey or getattr(config.dictation, "hotkey", "") or "control")
        return
    if mic_test:
        _run_mic_test(config)
        return
    if setup:
        _run_setup(config)
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
            "`diapason model pull base` first, or set [privacy] local_only = false.",
            err=True,
        )
        sys.exit(1)

    use_dictionary = bool(getattr(config.dictation, "dictionary", True))
    # Le polissage par modèle existait dans la configuration et dans le code,
    # mais la dictée de bureau — celle qu'on utilise vraiment — ne l'appelait
    # pas : elle collait la sortie brute de Whisper. Le prompt était écrit,
    # testé, et jamais atteint.
    polish_llm = bool(getattr(config.dictation, "llm_polish", False))
    polish_timeout_ms = int(getattr(config.dictation, "llm_timeout_ms", 2000))

    def _correct(text: str) -> str:
        """Apply the personal dictionary to raw model output.

        The dictionary exists precisely to fix words the recogniser gets
        wrong every time — "Karlito" for "Carlito". It was wired into the
        HTTP dictation route only, so the desktop push-to-talk path, which is
        the one people actually use, pasted raw Whisper output and the
        corrections never applied.

        Only the correction step is borrowed, NOT ``finalize_dictation``:
        that also parses voice commands and calls ``execute_voice_action``,
        so routing dictation through it would let a spoken sentence launch an
        application instead of being typed.
        """
        if not text.strip():
            return text
        try:
            from diapason.speech.dictate_polish import polish_pipeline

            corrige = polish_pipeline(
                text,
                use_dictionary=use_dictionary,
                llm_polish=polish_llm,
                llm_timeout_ms=polish_timeout_ms,
            )
        except Exception:  # noqa: BLE001 - a correction must never lose the text
            logger.debug("dictation polish failed", exc_info=True)
            return text

        # Une correction n'a pas le droit de RÉÉCRIRE la phrase. Le modèle
        # doit réparer l'écriture — accents, ponctuation, majuscules — pas le
        # propos. Un écart de longueur trop grand signale qu'il a résumé,
        # complété ou inventé : on garde alors les mots dits.
        if not _correction_fidele(text, corrige):
            logger.info("correction écartée : trop éloignée du dicté")
            return text
        return corrige

    def _transcribe(wav_bytes: bytes) -> str:
        result = backend.transcribe(wav_bytes, format="wav")
        return _correct(getattr(result, "text", "") or "")

    def _paste(text: str) -> None:
        from diapason.desktop.clipboard import paste_text

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
        from diapason.desktop.menu_bar import DictationMenuBar

        bar = DictationMenuBar(hotkey=key)

    # Immediate feedback: a blip the moment the key is seen, and a floating
    # level meter while the mic is open. Both are best-effort — a machine with
    # no sound card or no window server still dictates.
    from diapason.desktop.audio_cues import CuePlayer
    from diapason.desktop.overlay import DictationOverlay
    from diapason.desktop.ptt import Action

    cues = CuePlayer(enabled=sound)
    cues.prime()
    indicator = DictationOverlay() if overlay else None

    _CUE = {
        Action.START: "start",
        Action.START_HANDS_FREE: "start",
        Action.STOP_AND_TRANSCRIBE: "stop",
        Action.STOP_HANDS_FREE_AND_TRANSCRIBE: "stop",
        Action.CANCEL: "cancel",
    }

    def _on_action(action: Action) -> None:
        name = _CUE.get(action)
        if name is not None:
            cues.play(name)
        if indicator is not None:
            if action in (Action.START, Action.START_HANDS_FREE):
                indicator.set_state("recording")
            elif action is Action.CANCEL:
                indicator.set_state("idle")

    def _capture_factory():
        from diapason.desktop.mic_capture import MicCapture

        if indicator is None:
            return MicCapture()
        # The meter is fed straight from the audio callback, so the display
        # moves with the real signal: a flat indicator means a silent
        # microphone, which is the diagnosis the user actually needs. The
        # bands carry the spectral shape on top of the loudness.
        return MicCapture(
            level_cb=indicator.set_level,
            bands_cb=indicator.set_bands,
        )

    def _status(msg: str) -> None:
        click.echo(f"  [{msg}]")
        if indicator is not None:
            indicator.on_status(msg)
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
        on_action=_on_action,
        capture_factory=_capture_factory,
        model_name=str(getattr(config.speech, "model", "") or ""),
        on_transcript=(bar.set_last_text if bar is not None else None),
    )

    try:
        service.start()
    except AccessibilityError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    # Build the model before announcing readiness. The service starts at
    # login and then sits idle, so otherwise the first dictation of the day
    # pays model construction while the user is already talking — and
    # "ready" would be a lie.
    preload = getattr(backend, "preload", None)
    if callable(preload):
        click.echo("Loading the speech model…")
        preload()

    # Le PID dans la bannière : deux services de dictée écoutent tous deux la
    # même touche, transcrivent le même audio et collent chacun leur version.
    # Constaté le 20 août 2026, et indétectable — les deux écrivent dans le même
    # journal, d'où deux bannières identiques que rien ne distinguait.
    click.echo(
        f"Dictation ready (PID {os.getpid()}). Hold the {key.capitalize()} key "
        "and speak, then release. Double-tap for hands-free. Ctrl-C to quit."
    )

    # Dire au démarrage ce que ce service peut réellement faire, plutôt que
    # de le découvrir au premier mot dicté. Le test est un APPEL, pas un
    # drapeau : AXIsProcessTrusted répondait True pendant que chaque
    # insertion rendait -25204, et la dictée retombait silencieusement sur
    # le collage — plus lent, et incapable de dictée progressive.
    from diapason.desktop.accessibility import (
        accessibility_remediation,
        accessibility_works,
        paste_works,
    )

    # Deux capacités, deux autorisations, deux messages. Les confondre
    # faisait annoncer « accessibilité REFUSÉE » à un service qui collait
    # parfaitement : mesuré sur cette machine, System Events répondait
    # pendant que l'API AX brute rendait -25204. Un message alarmant à
    # propos de rien envoie chercher un défaut là où il n'y en a pas.
    colle = paste_works()
    ecrit = accessibility_works()

    if colle:
        click.echo("  Collage : disponible — la dictée écrit dans vos apps.")
    else:
        click.echo("  Collage : INDISPONIBLE — la dictée ne pourra rien écrire.")

    if ecrit:
        click.echo("  Écriture directe : disponible (dictée progressive).")
    elif colle:
        # Une absence, pas une panne : le chemin principal fonctionne.
        click.echo(
            "  Écriture directe : indisponible — pas de dictée progressive, "
            "le reste fonctionne."
        )

    if not colle:
        click.echo(accessibility_remediation())

    # The overlay draws from the main thread's run loop, so it has to be built
    # before whichever loop below takes that thread over. If there is no
    # window server (ssh, CI) start() returns False and dictation carries on
    # blind but working.
    showing_overlay = indicator is not None and indicator.start()
    if indicator is not None and not showing_overlay:
        # Worth saying out loud: under the LaunchAgent this line is the only
        # way to tell "the indicator is off" from "the indicator is broken".
        click.echo(
            "No window server available; running without the visual "
            "indicator (dictation itself is unaffected).",
            err=True,
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

    if showing_overlay and _run_appkit_loop():
        service.stop()
        if indicator is not None:
            indicator.stop()
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


def _run_appkit_loop() -> bool:
    """Service the main-thread event loop so the overlay can draw.

    Returns False when AppKit is unavailable, leaving the caller to fall back
    to a plain blocking wait.

    Ctrl-C takes two tricks, both learned the hard way — without them the
    documented "Ctrl-C to quit" simply does nothing:

    1. SIGINT arrives while the main thread is inside Objective-C, and Python
       defers the handler until it next executes bytecode. So a polling timer
       runs on this loop; its callback is the bytecode that lets the deferred
       handler fire.
    2. ``NSApplication.stop_`` is only honoured while an *NSEvent* is being
       dispatched, and a timer is not an event — calling it alone leaves the
       loop spinning until the user happens to move the mouse. Posting a
       no-op event makes it unwind immediately.
    """
    import signal

    try:
        from AppKit import (  # type: ignore
            NSApplication,
            NSApplicationActivationPolicyAccessory,
            NSEvent,
        )
        from Foundation import NSTimer  # type: ignore
    except Exception:  # noqa: BLE001 - headless: caller waits instead
        return False

    try:
        from AppKit import NSEventTypeApplicationDefined as _APP_EVENT  # type: ignore
    except ImportError:  # pragma: no cover - pre-10.12 spelling
        _APP_EVENT = 15

    app = NSApplication.sharedApplication()
    # Accessory, not Regular: this is a background service, so it may own
    # windows but must not take a Dock tile or a menu bar of its own.
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    interrupted = {"now": False}

    def _poll(_timer) -> None:
        if not interrupted["now"]:
            return
        app.stop_(None)
        # The PyObjC selector name is too long to spell inline within the
        # line budget; getattr keeps it one readable identifier.
        make_event = getattr(
            NSEvent,
            "otherEventWithType_location_modifierFlags_timestamp_"
            "windowNumber_context_subtype_data1_data2_",
        )
        app.postEvent_atStart_(
            make_event(_APP_EVENT, (0.0, 0.0), 0, 0, 0, None, 0, 0, 0), True
        )

    def _interrupt(_sig, _frame) -> None:
        interrupted["now"] = True

    timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(0.2, True, _poll)
    previous = signal.signal(signal.SIGINT, _interrupt)
    try:
        app.run()
    finally:
        timer.invalidate()
        signal.signal(signal.SIGINT, previous)
    return True


def _ensure_permissions() -> bool:
    """Check the three TCC permissions dictation needs; prompt for any missing.

    Input Monitoring gates the key tap, Microphone gates capture, Accessibility
    gates the paste. All are requested so the user grants them in one pass.
    Returns True only when nothing is missing.
    """
    from diapason.desktop import permissions

    missing = permissions.missing_for_dictation()
    if not missing:
        return True

    click.echo(
        "Dictation needs these macOS permissions, still missing: " + ", ".join(missing),
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

    from diapason.desktop.dictation_service import float_mono_to_wav
    from diapason.desktop.mic_capture import MicCapture, rms_level
    from diapason.speech._discovery import get_speech_backend

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

    from diapason.desktop.hotkey import AccessibilityError, HotkeyListener
    from diapason.desktop.keycodes import normalize_hotkey

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


def _run_setup(config) -> None:
    """Print every requirement, its state, and the one next action."""
    from diapason.desktop.setup_check import blocking_failures, is_ready, run_all

    checks = run_all(config)
    click.echo("Dictation setup\n")
    for c in checks:
        colour = "green" if c.ok else ("red" if c.blocking else "yellow")
        click.echo(f"  {click.style(c.symbol, fg=colour)} {c.name:<20} {c.detail}")
        if c.fix:
            click.echo(f"      → {c.fix}")

    click.echo("")
    if is_ready(checks):
        click.echo(
            click.style("Ready.", fg="green")
            + " Hold the key and speak — run `diapason dictate`, or "
            "`diapason dictate-service install` to run it at login."
        )
    else:
        n = len(blocking_failures(checks))
        click.echo(
            click.style(f"{n} thing(s) still to fix", fg="red")
            + " — see the arrows above, then rerun this check."
        )
        sys.exit(1)
