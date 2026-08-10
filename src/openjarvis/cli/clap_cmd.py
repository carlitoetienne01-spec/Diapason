"""CLI: jarvis clap-listen — double-clap → welcome sequence (+ optional trigger file)."""

from __future__ import annotations

import logging
import time

import click

from openjarvis.channels.local_trigger import LocalTriggerChannel, default_trigger_path
from openjarvis.desktop.welcome_runner import run_welcome_sequence
from openjarvis.speech.clap_listener import ClapConfig, ClapListener, choose_input_device

logger = logging.getLogger(__name__)


@click.command("clap-listen")
@click.option("--once/--repeat", default=True, show_default=True, help="Fire once then exit.")
@click.option("--spike-ratio", type=float, default=2.5, show_default=True)
@click.option("--min-rms", type=float, default=0.003, show_default=True)
@click.option(
    "--device",
    default=None,
    help="Mic index or name substring (default: auto-pick loudest working input).",
)
@click.option("--debug", is_flag=True, help="Log mic RMS peaks each second.")
@click.option(
    "--fire",
    "fire_now",
    is_flag=True,
    help="Run welcome sequence immediately without waiting for a clap.",
)
@click.option(
    "--emit-only",
    is_flag=True,
    help="Only write local_trigger event (do not run welcome tools).",
)
@click.option("--no-tts", is_flag=True, help="Skip ElevenLabs TTS step.")
@click.option("--no-chrome", is_flag=True, help="Skip Chrome windows.")
@click.option("--no-cursor", is_flag=True, help="Skip focusing Cursor.")
def clap_listen(
    once: bool,
    spike_ratio: float,
    min_rms: float,
    device: str | None,
    debug: bool,
    fire_now: bool,
    emit_only: bool,
    no_tts: bool,
    no_chrome: bool,
    no_cursor: bool,
) -> None:
    """Listen for a double clap and run the desktop welcome sequence."""
    path = default_trigger_path()
    channel = LocalTriggerChannel(path=path)

    def fire() -> None:
        channel.emit(
            "welcome_home",
            event="welcome_home",
            source="clap-listen",
        )
        click.echo(f"Emitted welcome_home → {path}")
        if emit_only:
            return
        click.echo("Running welcome sequence…")
        results = run_welcome_sequence(
            skip_tts=no_tts,
            skip_chrome=no_chrome,
            skip_cursor=no_cursor,
        )
        for name, result in results.items():
            ok = getattr(result, "success", False)
            content = getattr(result, "content", result)
            click.echo(f"  [{('ok' if ok else 'fail')}] {name}: {content}")

    if fire_now:
        fire()
        return

    cfg = ClapConfig(spike_ratio=spike_ratio, min_rms=min_rms)
    blocksize = max(1, int(cfg.sample_rate * cfg.block_ms / 1000))
    device_idx = choose_input_device(
        cfg,
        blocksize,
        override=device,
        silent_rms=0.0005,
        probe_s=0.5,
    )
    listener = ClapListener(
        fire,
        cfg=cfg,
        once=once,
        device=device_idx,
        debug=debug,
    )
    click.echo(
        f"Listening for double clap (device={device_idx}, spike_ratio={spike_ratio}, "
        f"min_rms={min_rms}, once={once}, debug={debug}). Ctrl+C to stop."
    )
    listener.start()
    try:
        while True:
            time.sleep(0.5)
            if once and listener._fired:  # noqa: SLF001
                time.sleep(0.2)
                break
    except KeyboardInterrupt:
        click.echo("Stopped.")
    finally:
        listener.stop()
