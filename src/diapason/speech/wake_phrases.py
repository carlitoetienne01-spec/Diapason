"""Wake-word phrase matching (Diapason-style text gate for « Diapason »)."""

from __future__ import annotations

import re
from typing import Sequence

# Longer variants first for alternation.
DEFAULT_WAKE_VARIANTS: tuple[str, ...] = (
    "hey diapason",
    "dis diapason",
    "ok diapason",
    "okay diapason",
    "salut diapason",
    "bonjour diapason",
    "hi diapason",
    "hello diapason",
    "dia pason",
    "dia-pason",
    "diapasons",
    "diapazon",
    "diapason",
)

DEFAULT_WAKE_PREFIXES: tuple[str, ...] = (
    "hey",
    "hi",
    "hello",
    "ok",
    "okay",
    "salut",
    "bonjour",
    "dis",
    "yo",
)

_SEP = r"[\s,.\-!?]"


def _escape(s: str) -> str:
    return re.escape(s)


def build_wake_pattern(
    variants: Sequence[str] | None = None,
    prefixes: Sequence[str] | None = None,
) -> re.Pattern[str]:
    """Match wake phrase at the start of an utterance."""
    vars_ = tuple(variants) if variants else DEFAULT_WAKE_VARIANTS
    prefs = tuple(prefixes) if prefixes else DEFAULT_WAKE_PREFIXES
    # Sort longer first
    vars_sorted = sorted(
        {v.strip().lower() for v in vars_ if v.strip()}, key=len, reverse=True
    )
    prefs_sorted = sorted(
        {p.strip().lower() for p in prefs if p.strip()}, key=len, reverse=True
    )
    variant_group = "|".join(_escape(v) for v in vars_sorted)
    prefix_group = "|".join(_escape(p) for p in prefs_sorted)
    # Name alone OR prefix + name; require separator or end after name.
    # If variant already includes prefix (hey diapason), still OK.
    pattern = rf"^(?:(?:{prefix_group}){_SEP}*)?(?:{variant_group})(?:{_SEP}+|$)"
    return re.compile(pattern, re.IGNORECASE)


_DEFAULT_PATTERN = build_wake_pattern()


def has_wake_word(
    text: str,
    *,
    pattern: re.Pattern[str] | None = None,
) -> bool:
    """True if text opens with an address to Diapason."""
    t = (text or "").strip()
    if not t:
        return False
    return bool((pattern or _DEFAULT_PATTERN).search(t))


def strip_wake_word(
    text: str,
    *,
    pattern: re.Pattern[str] | None = None,
) -> str:
    """Remove leading wake address. « Diapason, ouvre YouTube » → « ouvre YouTube »."""
    t = (text or "").strip()
    if not t:
        return ""
    return (pattern or _DEFAULT_PATTERN).sub("", t, count=1).strip(" ,.-")


__all__ = [
    "DEFAULT_WAKE_PREFIXES",
    "DEFAULT_WAKE_VARIANTS",
    "build_wake_pattern",
    "has_wake_word",
    "strip_wake_word",
]
