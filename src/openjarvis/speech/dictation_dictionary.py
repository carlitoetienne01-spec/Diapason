"""User dictation dictionary — STT replacement words (Diapason-style).

Stored as JSON (default ``~/.openjarvis/dictation_dictionary.json``).
Not a filler lexicon — fillers live in ``dictate_polish.py``.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from openjarvis.core.config import get_config_dir

logger = logging.getLogger(__name__)

DEFAULT_DICTIONARY_NAME = "dictation_dictionary.json"


@dataclass
class DictionaryEntry:
    id: str = ""
    word: str = ""  # canonical spelling to emit
    original_word: str = ""  # primary STT mistake
    pronunciation: str = ""
    context: str = ""
    replacements: list[str] = field(default_factory=list)
    locale: str = ""
    usage_count: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid.uuid4())[:8]


def default_dictionary_path() -> Path:
    return get_config_dir() / DEFAULT_DICTIONARY_NAME


def resolve_dictionary_path(path: str | Path | None = None) -> Path:
    if path:
        return Path(path).expanduser()
    try:
        from openjarvis.core.config import load_config

        cfg_path = (load_config().dictation.dictionary_path or "").strip()
        if cfg_path:
            return Path(cfg_path).expanduser()
    except Exception:
        logger.debug("could not load dictation.dictionary_path", exc_info=True)
    return default_dictionary_path()


def load_dictionary(path: str | Path | None = None) -> list[DictionaryEntry]:
    p = resolve_dictionary_path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("failed to read dictation dictionary %s: %s", p, exc)
        return []
    entries_raw = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(entries_raw, list):
        return []
    out: list[DictionaryEntry] = []
    for item in entries_raw:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word") or "").strip()
        if not word:
            continue
        reps = item.get("replacements") or []
        if isinstance(reps, str):
            reps = [reps]
        out.append(
            DictionaryEntry(
                id=str(item.get("id") or ""),
                word=word,
                original_word=str(item.get("original_word") or "").strip(),
                pronunciation=str(item.get("pronunciation") or "").strip(),
                context=str(item.get("context") or "").strip(),
                replacements=[str(r).strip() for r in reps if str(r).strip()],
                locale=str(item.get("locale") or "").strip(),
                usage_count=int(item.get("usage_count") or 0),
            )
        )
    return out


def save_dictionary(
    entries: Iterable[DictionaryEntry],
    path: str | Path | None = None,
) -> Path:
    p = resolve_dictionary_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "entries": [asdict(e) for e in entries],
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def _replacement_keys(entry: DictionaryEntry) -> list[str]:
    keys: list[str] = []
    if entry.original_word:
        keys.append(entry.original_word)
    keys.extend(entry.replacements)
    # de-dupe preserving order, skip empty / identical to canonical
    seen: set[str] = set()
    out: list[str] = []
    canon = entry.word.lower()
    for k in keys:
        low = k.lower().strip()
        if not low or low == canon or low in seen:
            continue
        seen.add(low)
        out.append(k.strip())
    return out


def apply_dictionary(
    text: str,
    entries: Optional[list[DictionaryEntry]] = None,
    *,
    path: str | Path | None = None,
    bump_usage: bool = True,
) -> str:
    """Replace STT mistakes with canonical spellings (word-boundary, case-insensitive)."""
    raw = text or ""
    if not raw.strip():
        return raw
    items = entries if entries is not None else load_dictionary(path)
    if not items:
        return raw

    # Longer keys first so "open ai" wins over "ai"
    # Map key_lower → entry id for usage bumps
    key_to_id: dict[str, str] = {}
    pairs: list[tuple[str, str]] = []
    for entry in sorted(items, key=lambda e: (-e.usage_count, -len(e.word))):
        for key in _replacement_keys(entry):
            pairs.append((key, entry.word))
            key_to_id[key.lower()] = entry.id
    pairs.sort(key=lambda kv: len(kv[0]), reverse=True)

    result = raw
    bumped: set[str] = set()
    for key, word in pairs:
        # Allow multi-word keys with flexible whitespace
        parts = re.split(r"\s+", key.strip())
        if not parts:
            continue
        pattern = r"\b" + r"\s+".join(re.escape(p) for p in parts) + r"\b"
        new_result, n = re.subn(pattern, word, result, flags=re.IGNORECASE)
        if n and bump_usage:
            eid = key_to_id.get(key.lower())
            if eid:
                bumped.add(eid)
        result = new_result

    if bumped:
        by_id = {e.id: e for e in items}
        changed = False
        for eid in bumped:
            e = by_id.get(eid)
            if e is None:
                continue
            e.usage_count = int(e.usage_count or 0) + 1
            changed = True
        if changed:
            try:
                save_dictionary(items, path)
            except OSError:
                logger.debug("could not persist dictionary usage", exc_info=True)
    return result


_SKIP_LEARN_TOKENS = frozenset(
    {
        "um",
        "uh",
        "er",
        "ah",
        "eh",
        "like",
        "you",
        "know",
        "euh",
        "ben",
        "bah",
        "hein",
        "a",
        "an",
        "the",
        "le",
        "la",
        "les",
        "un",
        "une",
        "de",
        "du",
        "des",
        "et",
        "or",
        "and",
    }
)


def _learnable_phrase(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) < 2:
        return False
    tokens = re.findall(r"[\w''-]+", t, flags=re.UNICODE)
    if not tokens:
        return False
    if all(tok.lower() in _SKIP_LEARN_TOKENS for tok in tokens):
        return False
    if all(len(tok) < 2 for tok in tokens):
        return False
    return True


def learn_from_correction(
    original: str,
    corrected: str,
    *,
    path: str | Path | None = None,
    locale: str = "",
) -> list[DictionaryEntry]:
    """Infer dictionary entries from an STT→user-corrected pair.

    Uses difflib opcodes to find short replace spans (1–3 tokens).
    Skips filler-only and tiny tokens. Upserts into the dictionary file.
    """
    import difflib

    before = (original or "").strip()
    after = (corrected or "").strip()
    if not before or not after or before == after:
        return []

    a = before.split()
    b = after.split()
    if not a or not b:
        return []

    learned: list[DictionaryEntry] = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        if (i2 - i1) > 3 or (j2 - j1) > 3:
            continue
        from_phrase = " ".join(a[i1:i2]).strip()
        to_phrase = " ".join(b[j1:j2]).strip()
        if not from_phrase or not to_phrase:
            continue
        if from_phrase.lower() == to_phrase.lower():
            continue
        if not _learnable_phrase(from_phrase) or not _learnable_phrase(to_phrase):
            continue

        items = load_dictionary(path)
        existing = None
        for e in items:
            if e.word.lower() == to_phrase.lower():
                existing = e
                break
        if existing is None:
            entry = DictionaryEntry(
                word=to_phrase,
                original_word=from_phrase,
                replacements=[from_phrase],
                locale=locale,
                usage_count=1,
                context="auto-learn",
            )
        else:
            reps = list(existing.replacements or [])
            if from_phrase not in reps and from_phrase.lower() != existing.word.lower():
                reps.append(from_phrase)
            if not existing.original_word:
                existing.original_word = from_phrase
            existing.replacements = reps
            existing.usage_count = int(existing.usage_count or 0) + 1
            if not existing.context:
                existing.context = "auto-learn"
            entry = existing
        learned.append(upsert_entry(entry, path=path))
    return learned


def transcription_hints(
    entries: Optional[list[DictionaryEntry]] = None,
    *,
    path: str | Path | None = None,
    limit: int = 40,
) -> list[str]:
    """Canonical words for STT boosting prompts."""
    items = entries if entries is not None else load_dictionary(path)
    ranked = sorted(items, key=lambda e: -e.usage_count)
    words: list[str] = []
    seen: set[str] = set()
    for e in ranked:
        w = e.word.strip()
        if not w or w.lower() in seen:
            continue
        seen.add(w.lower())
        words.append(w)
        if len(words) >= limit:
            break
    return words


def upsert_entry(
    entry: DictionaryEntry,
    *,
    path: str | Path | None = None,
) -> DictionaryEntry:
    items = load_dictionary(path)
    for i, existing in enumerate(items):
        if existing.id == entry.id or (
            existing.word.lower() == entry.word.lower() and entry.word
        ):
            if not entry.id:
                entry.id = existing.id
            items[i] = entry
            save_dictionary(items, path)
            return entry
    if not entry.id:
        entry.id = str(uuid.uuid4())[:8]
    items.append(entry)
    save_dictionary(items, path)
    return entry


def dictionary_to_api(entries: Optional[list[DictionaryEntry]] = None) -> dict[str, Any]:
    items = entries if entries is not None else load_dictionary()
    return {"version": 1, "entries": [asdict(e) for e in items]}


__all__ = [
    "DictionaryEntry",
    "apply_dictionary",
    "default_dictionary_path",
    "dictionary_to_api",
    "learn_from_correction",
    "load_dictionary",
    "resolve_dictionary_path",
    "save_dictionary",
    "transcription_hints",
    "upsert_entry",
]
