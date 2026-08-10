"""ElevenLabs TTS backend — cloud voice synthesis with on-disk WAV/MP3 cache."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import List

import httpx

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

logger = logging.getLogger(__name__)

_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


def _default_cache_dir() -> Path:
    override = (os.environ.get("JARVIS_WELCOME_CACHE_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    home = Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))
    return home / "cache" / "elevenlabs_tts"


def _cache_path(
    cache_dir: Path,
    text: str,
    voice_id: str,
    model_id: str,
    output_format: str,
) -> Path:
    key = f"{text}|{voice_id}|{model_id}|{output_format}".encode()
    digest = hashlib.sha256(key).hexdigest()[:24]
    ext = "mp3" if "mp3" in output_format else "wav"
    if output_format.startswith("pcm_"):
        ext = "pcm"
    return cache_dir / f"{digest}.{ext}"


def _elevenlabs_tts_request(
    api_key: str,
    text: str,
    voice_id: str,
    model_id: str,
    output_format: str,
) -> bytes:
    url = _TTS_URL.format(voice_id=voice_id)
    resp = httpx.post(
        url,
        headers={
            "xi-api-key": api_key,
            "Accept": "application/octet-stream",
            "Content-Type": "application/json",
        },
        params={"output_format": output_format},
        json={
            "text": text,
            "model_id": model_id,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.content


@TTSRegistry.register("elevenlabs")
class ElevenLabsTTSBackend(TTSBackend):
    """ElevenLabs TTS with optional disk cache (phrase|voice|model|format)."""

    backend_id = "elevenlabs"

    def __init__(
        self,
        *,
        api_key: str = "",
        model_id: str = "",
        cache_enabled: bool = True,
        cache_dir: Path | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self._model = model_id or os.environ.get(
            "ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"
        )
        self._default_voice = os.environ.get("ELEVENLABS_VOICE_ID", "")
        self._cache_enabled = cache_enabled
        self._cache_dir = cache_dir or _default_cache_dir()

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3_44100_128",
    ) -> TTSResult:
        del speed  # ElevenLabs convert API does not use this param here
        if not self._api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")
        vid = (voice_id or self._default_voice).strip()
        if not vid:
            raise RuntimeError("ELEVENLABS_VOICE_ID not set (pass voice_id=)")

        # Map simple aliases used by the text_to_speech tool
        fmt = output_format
        if fmt in ("mp3", ""):
            fmt = "mp3_44100_128"
        if fmt == "pcm":
            fmt = "pcm_24000"

        cache_file = _cache_path(self._cache_dir, text, vid, self._model, fmt)
        if self._cache_enabled and cache_file.is_file():
            audio = cache_file.read_bytes()
            logger.debug("ElevenLabs TTS cache hit: %s", cache_file)
            return TTSResult(
                audio=audio,
                format="mp3" if "mp3" in fmt else ("pcm" if fmt.startswith("pcm") else "wav"),
                voice_id=vid,
                sample_rate=24000 if fmt.startswith("pcm") else 44100,
                metadata={
                    "backend": "elevenlabs",
                    "model": self._model,
                    "cache": "hit",
                    "cache_path": str(cache_file),
                },
            )

        audio = _elevenlabs_tts_request(
            self._api_key, text, vid, self._model, fmt
        )
        if self._cache_enabled and audio:
            try:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
                tmp.write_bytes(audio)
                tmp.replace(cache_file)
            except OSError as exc:
                logger.warning("Could not write ElevenLabs TTS cache: %s", exc)

        return TTSResult(
            audio=audio,
            format="mp3" if "mp3" in fmt else ("pcm" if fmt.startswith("pcm") else "wav"),
            voice_id=vid,
            sample_rate=24000 if fmt.startswith("pcm") else 44100,
            metadata={
                "backend": "elevenlabs",
                "model": self._model,
                "cache": "miss",
                "cache_path": str(cache_file),
            },
        )

    def available_voices(self) -> List[str]:
        if self._default_voice:
            return [self._default_voice]
        return []

    def health(self) -> bool:
        return bool(self._api_key)
