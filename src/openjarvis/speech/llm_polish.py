"""Optional one-shot LLM polish for dictation (Diapason-style, opt-in)."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DICTATION_SYSTEM = """\
You clean speech-to-text. Output ONLY the cleaned text.
Preserve meaning and the user's words. Do not add facts, names, or signatures.
Allowed: remove fillers; fix obvious STT/grammar/punctuation/capitalization;
apply self-corrections ("4pm sorry 5pm" → "5pm");
"readme dot md" → "readme.md"; spoken emoji phrases → emoji.
Never invent closings. Never explain."""

_EMAIL_EXTRA = """\
If this is clearly an email, add line breaks after the greeting and before any closing.
Keep spoken closings exactly ("Best" stays "Best"). Never add a signature the user did not say."""


def _strip_model_noise(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = re.sub(
        r"^(?:here(?:'s| is)(?: the)?(?: cleaned| polished)?(?: text)?[:\s]*)",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    if t.startswith("```") and t.endswith("```"):
        t = re.sub(r"^```\w*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    return t.strip()


def llm_polish_text(
    text: str,
    *,
    email_mode: bool = False,
    timeout_ms: int = 2000,
    model: str = "",
    engine: Any = None,
) -> Optional[str]:
    """Polish dictation via the configured engine. Returns None on skip/failure."""
    raw = (text or "").strip()
    if not raw:
        return None
    if len(raw.split()) < 3:
        return None

    system = _DICTATION_SYSTEM
    if email_mode:
        system = system + "\n" + _EMAIL_EXTRA

    try:
        from openjarvis.core.config import load_config
        from openjarvis.core.types import Message, Role

        cfg = load_config()
        resolved_model = (model or cfg.intelligence.default_model or "").strip()
        if not resolved_model:
            logger.debug("llm polish skipped: no default model")
            return None

        eng = engine
        if eng is None:
            from openjarvis.engine._discovery import get_engine

            key = (cfg.engine.default or "").strip() or None
            eng = get_engine(cfg, key)
        if eng is None:
            return None

        messages = [
            Message(role=Role.SYSTEM, content=system),
            Message(
                role=Role.USER,
                content=f"===SPEECH===\n{raw}\n===END===",
            ),
        ]
        timeout_s = max(0.3, float(timeout_ms) / 1000.0)

        def _call() -> str:
            result = eng.generate(
                messages,
                model=resolved_model,
                temperature=0.1,
                max_tokens=min(512, max(64, len(raw.split()) * 4)),
            )
            content = ""
            if isinstance(result, dict):
                content = str(result.get("content") or "")
            return _strip_model_noise(content)

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_call)
            try:
                out = fut.result(timeout=timeout_s)
            except FuturesTimeout:
                logger.info("llm polish timed out after %sms", timeout_ms)
                return None

        if not out or len(out) > max(40, len(raw) * 3):
            return None
        return out
    except Exception:
        logger.debug("llm polish failed", exc_info=True)
        return None


__all__ = ["llm_polish_text"]
