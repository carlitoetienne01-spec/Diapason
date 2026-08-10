"""CLI: jarvis wake-listen — local mic wake word → open Talk."""

from __future__ import annotations

import logging
import time

import click

from openjarvis.channels.local_trigger import LocalTriggerChannel, default_trigger_path
from openjarvis.speech.clap_listener import choose_input_device
from openjarvis.speech.wakeword import (
    WakeWordListener,
    openwakeword_available,
    resolve_backend,
    wake_config_from_toml,
)

logger = logging.getLogger(__name__)


@click.command("wake-listen")
@click.option("--once/--repeat", default=False, show_default=True)
@click.option(
    "--cooldown",
    type=float,
    default=None,
    help="Override [speech.wakeword].cooldown_s",
)
@click.option(
    "--min-rms",
    type=float,
    default=None,
    help="Override energy gate (phrase_gate only).",
)
@click.option(
    "--device",
    default=None,
    help="Mic index or name substring (default: auto / config).",
)
@click.option("--debug", is_flag=True, help="Log mic peaks / scores / STT text.")
@click.option(
    "--fire",
    "fire_now",
    is_flag=True,
    help="Emit talk_open immediately without waiting for wake word.",
)
@click.option(
    "--phrases",
    default="",
    help="Comma-separated wake phrases (default from config).",
)
@click.option(
    "--backend",
    type=click.Choice(
        ["", "auto", "phrase_gate", "openwakeword"], case_sensitive=False
    ),
    default="",
    help="Wake backend (default: [speech.wakeword].backend).",
)
@click.option(
    "--text",
    "fake_text",
    default="",
    help="Simulate a transcript (no mic) — useful for testing the text gate.",
)
def wake_listen(
    once: bool,
    cooldown: float | None,
    min_rms: float | None,
    device: str | None,
    debug: bool,
    fire_now: bool,
    phrases: str,
    backend: str,
    fake_text: str,
) -> None:
    """Listen for « Hey Jarvis » and open Talk (talk_open trigger).

    Backends: phrase_gate (Whisper+regex) or openwakeword (ML hey_jarvis).
    """
    path = default_trigger_path()
    channel = LocalTriggerChannel(path=path)

    def fire(transcript: str = "") -> None:
        channel.emit(
            transcript or "wake",
            event="talk_open",
            source="wake-listen",
        )
        click.echo(f"Emitted talk_open → {path}")

    if fire_now:
        fire("manual")
        return

    cfg = wake_config_from_toml(
        cooldown=cooldown,
        min_rms=min_rms,
        phrases=phrases or None,
        backend=backend or None,
    )

    if fake_text.strip():
        listener = WakeWordListener(fire, cfg=cfg, once=True, debug=debug)
        ok = listener.check_text(fake_text.strip())
        if not ok:
            click.echo(f"No wake word in: {fake_text!r}")
            raise SystemExit(1)
        return

    try:
        resolved = resolve_backend(cfg.backend)
    except ImportError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc

    # Resolve mic like clap-listen
    blocksize = max(1, int(cfg.sample_rate * cfg.block_ms / 1000))
    device_override = device
    if not device_override:
        try:
            from openjarvis.core.config import load_config

            device_override = (load_config().speech.wakeword.device or "").strip() or None
        except Exception:
            device_override = None
    try:
        from openjarvis.speech.clap_listener import ClapConfig

        mic = choose_input_device(
            ClapConfig(sample_rate=cfg.sample_rate, channels=cfg.channels),
            blocksize if resolved == "phrase_gate" else 1280,
            override=device_override,
        )
    except Exception as exc:
        click.echo(f"Mic setup failed: {exc}", err=True)
        raise SystemExit(1) from exc

    click.echo(
        f"Listening ({resolved}"
        + (
            f", thr={cfg.sensitivity:.2f}"
            if resolved == "openwakeword"
            else f", phrases={', '.join(cfg.phrases[:4])}…"
        )
        + "). Ctrl+C to stop."
    )
    if resolved == "openwakeword":
        click.echo("ML wake: openWakeWord hey_jarvis (local).")
    else:
        click.echo("phrase_gate: sounddevice + faster-whisper tiny.")
        if openwakeword_available():
            click.echo("Tip: --backend openwakeword for lower-latency ML wake.")
        else:
            click.echo("Tip: uv sync --extra speech-wake  # enable openWakeWord")

    listener = WakeWordListener(
        fire,
        cfg=cfg,
        once=once,
        device=mic,
        debug=debug,
    )
    listener.start()
    try:
        while True:
            time.sleep(0.5)
            if once and listener._fired:  # noqa: SLF001
                break
    except KeyboardInterrupt:
        click.echo("\nStopped.")
    finally:
        listener.stop()
