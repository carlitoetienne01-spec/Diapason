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


# Les GÉNÉRIQUES DE SOUS-TITRES que Whisper hallucine sur le silence.
#
# Whisper a appris sur des sous-titres de vidéos ; face au souffle du micro en
# fin de phrase, il « entend » ce qu'il a le plus vu à cet endroit : le crédit
# des sous-titreurs. Rapporté le 23 août 2026 — « à chaque fin de phrase, ça
# me dit : Sous-titres par la communauté d'Amara.org ». La parade première est
# le filtre de silence (vad_filter) ; celle-ci raye ce qui passerait quand
# même. Les motifs exigent la FORMULE, jamais un mot seul : dicter une phrase
# qui parle réellement d'Amara reste possible.
_WHISPER_CREDITS_RE = re.compile(
    r"(?:"
    r"sous[- ]?titr\w*[^.!?\n]*?amara\.org[^.!?\n]*"
    r"|sous[- ]?titrage\s+(?:société\s+)?radio[- ]?canada[^.!?\n]*"
    r"|sous[- ]?titrage\s+st'?\s?501"
    r"|[^.!?\n]*soustitreur\.com[^.!?\n]*"
    r"|subtitles?\s+by\s+the\s+amara\.org\s+community"
    r"|merci\s+d['’ ]?\s*avoir\s+regardé\s+(?:cette\s+vidéo|la\s+vidéo)[^.!?\n]*"
    r"|thanks?\s+for\s+watching[^.!?\n]*"
    r"|n['’]oubliez\s+pas\s+de\s+(?:vous\s+)?abonner[^.!?\n]*"
    r")[.!?]?",
    re.IGNORECASE,
)


def strip_whisper_credits(text: str) -> str:
    """Raye les génériques hallucinés, puis nettoie la ponctuation orpheline."""
    nettoye = _WHISPER_CREDITS_RE.sub("", text or "")
    nettoye = re.sub(r"\s{2,}", " ", nettoye)
    return nettoye.strip(" \t\n,;")


def polish_dictation(raw: str, *, aggressive: bool = True) -> str:
    """Clean raw STT text: drop fillers, fix spacing, capitalize sentences."""
    text = strip_whisper_credits(raw)
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
