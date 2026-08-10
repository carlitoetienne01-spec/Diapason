"""Run the desktop welcome sequence (song, Chrome, TTS, Cursor)."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "song_uri": (
        "https://open.spotify.com/track/39shmbIHICJ2Wxnk1fPSdz?si=2900c75c2e2d4b82"
    ),
    "claude_url": "https://claude.ai/new",
    "claude_monitor": 1,
    "binance_url": "https://www.binance.com/en/trade/BTC_USDT",
    "binance_monitor": 1,
    "welcome_phrase": "Welcome home sir. Systems online.",
    "elevenlabs_voice_id": "",
    "focus_app": "Cursor",
    "fullscreen": True,
    "after_song_delay_s": 1.0,
    "open_binance": True,
    "open_claude": True,
}


@dataclass
class WelcomeClapSettings:
    song_uri: str = _DEFAULTS["song_uri"]  # type: ignore[assignment]
    claude_url: str = _DEFAULTS["claude_url"]  # type: ignore[assignment]
    claude_monitor: int = 1
    binance_url: str = _DEFAULTS["binance_url"]  # type: ignore[assignment]
    binance_monitor: int = 1
    welcome_phrase: str = _DEFAULTS["welcome_phrase"]  # type: ignore[assignment]
    elevenlabs_voice_id: str = ""
    focus_app_name: str = "Cursor"
    fullscreen: bool = True
    after_song_delay_s: float = 1.0
    open_claude: bool = True
    open_binance: bool = True


def _read_toml_section() -> dict[str, Any]:
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_PATH
    except Exception:
        DEFAULT_CONFIG_PATH = Path.home() / ".openjarvis" / "config.toml"

    path = Path(DEFAULT_CONFIG_PATH)
    if not path.is_file():
        return {}
    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        section = data.get("welcome_clap") or {}
        return dict(section) if isinstance(section, dict) else {}
    except Exception as exc:
        logger.warning("Could not read welcome_clap config: %s", exc)
        return {}


def load_welcome_settings() -> WelcomeClapSettings:
    raw = {**_DEFAULTS, **_read_toml_section()}
    voice = str(raw.get("elevenlabs_voice_id") or "").strip() or os.environ.get(
        "ELEVENLABS_VOICE_ID", ""
    )
    return WelcomeClapSettings(
        song_uri=str(raw.get("song_uri") or _DEFAULTS["song_uri"]),
        claude_url=str(raw.get("claude_url") or _DEFAULTS["claude_url"]),
        claude_monitor=int(raw.get("claude_monitor") or 1),
        binance_url=str(raw.get("binance_url") or _DEFAULTS["binance_url"]),
        binance_monitor=int(raw.get("binance_monitor") or 1),
        welcome_phrase=str(raw.get("welcome_phrase") or _DEFAULTS["welcome_phrase"]),
        elevenlabs_voice_id=voice,
        focus_app_name=str(raw.get("focus_app") or "Cursor"),
        fullscreen=bool(raw.get("fullscreen", True)),
        after_song_delay_s=float(raw.get("after_song_delay_s") or 1.0),
        open_claude=bool(raw.get("open_claude", True)),
        open_binance=bool(raw.get("open_binance", True)),
    )


def run_welcome_sequence(
    settings: WelcomeClapSettings | None = None,
    *,
    skip_tts: bool = False,
    skip_chrome: bool = False,
    skip_cursor: bool = False,
) -> Mapping[str, Any]:
    """Execute welcome actions via registered tools. Returns step results."""
    import openjarvis.speech  # noqa: F401 — register TTS
    import openjarvis.tools  # noqa: F401 — register tools

    from openjarvis.tools.desktop_tools import (
        FocusAppTool,
        OpenBrowserOnMonitorTool,
        OpenUriTool,
        PlayAudioFileTool,
    )
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    cfg = settings or load_welcome_settings()
    results: dict[str, Any] = {}

    logger.info("Welcome sequence: opening song")
    results["song"] = OpenUriTool().execute(uri=cfg.song_uri)

    if not skip_chrome:
        if cfg.open_claude:
            results["claude"] = OpenBrowserOnMonitorTool().execute(
                url=cfg.claude_url,
                monitor=cfg.claude_monitor,
                fullscreen=cfg.fullscreen,
                label="Claude",
            )
        if cfg.open_binance:
            results["binance"] = OpenBrowserOnMonitorTool().execute(
                url=cfg.binance_url,
                monitor=cfg.binance_monitor,
                fullscreen=cfg.fullscreen,
                label="Binance",
            )

    delay = max(0.0, cfg.after_song_delay_s)
    if delay:
        time.sleep(delay)

    if not skip_tts and cfg.welcome_phrase.strip():
        tts = TextToSpeechTool().execute(
            text=cfg.welcome_phrase.strip(),
            backend="elevenlabs",
            voice_id=cfg.elevenlabs_voice_id,
        )
        results["tts"] = tts
        if tts.success and tts.content:
            results["play"] = PlayAudioFileTool().execute(path=tts.content)

    if not skip_cursor:
        results["cursor"] = FocusAppTool().execute(
            app_name=cfg.focus_app_name,
            fullscreen=cfg.fullscreen,
        )

    ok = all(getattr(r, "success", False) for r in results.values() if r is not None)
    logger.info("Welcome sequence finished (all_ok=%s)", ok)
    return results
