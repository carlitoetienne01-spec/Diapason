"""Lightweight dictation polish (Diapason-inspired fillers / punctuation)."""

from __future__ import annotations

import re
from typing import List, Optional

_FILLERS = (
    r"\b(?:um|uh|erm|hmm|like|you know|sort of|kind of|basically|actually|"
    r"euh|ben|bah|du coup|genre|en fait|voilà)\b"
)

_FILLER_RE = re.compile(_FILLERS, re.IGNORECASE)
_MULTI_SPACE = re.compile(r"\s{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.!?;:])")
_SPOKEN_DOT_EXT = re.compile(
    r"\b([A-Za-z0-9_-]+)\s+dot\s+(md|txt|pdf|py|js|ts|tsx|jsx|json|toml|csv|html|css|docx|xlsx)\b",
    re.IGNORECASE,
)


def polish_dictation(raw: str, *, aggressive: bool = True) -> str:
    """Clean raw STT text: drop fillers, fix spacing, capitalize sentences."""
    text = (raw or "").strip()
    if not text:
        return ""

    if aggressive:
        text = _FILLER_RE.sub(" ", text)

    # "readme dot md" → "readme.md"
    text = _SPOKEN_DOT_EXT.sub(lambda m: f"{m.group(1)}.{m.group(2).lower()}", text)

    text = _MULTI_SPACE.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = text.strip(" ,;")

    # Sentence capitalization
    parts: List[str] = re.split(r"([.!?]\s+)", text)
    out: List[str] = []
    capitalize_next = True
    for part in parts:
        if not part:
            continue
        if re.fullmatch(r"[.!?]\s+", part):
            out.append(part)
            capitalize_next = True
            continue
        if capitalize_next and part:
            out.append(part[:1].upper() + part[1:])
            capitalize_next = False
        else:
            out.append(part)

    text = "".join(out).strip()
    if text and text[-1] not in ".!?":
        # Don't force period on short commands
        if len(text.split()) >= 4:
            text += "."
    return text


def polish_pipeline(
    raw: str,
    *,
    polish: bool = True,
    use_dictionary: bool = True,
    llm_polish: bool = False,
    email_mode: bool = False,
    llm_timeout_ms: int = 2000,
    dictionary_path: Optional[str] = None,
) -> str:
    """Local polish → dictionary → optional LLM. Safe for paste path only."""
    if not polish:
        return (raw or "").strip()

    from diapason.speech.dictation_dictionary import apply_dictionary

    text = polish_dictation(raw)
    if use_dictionary:
        text = apply_dictionary(text, path=dictionary_path or None)
    if llm_polish:
        from diapason.speech.llm_polish import llm_polish_text

        improved = llm_polish_text(
            text, email_mode=email_mode, timeout_ms=llm_timeout_ms
        )
        if improved:
            text = improved
    return text
