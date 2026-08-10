"""A local, bounded history of dictations.

Two things make this worth having: you can recover a sentence the paste lost
(wrong window focused, app ate it), and you can see what the recogniser
actually heard — which is how you find out that "small" fixes the proper nouns
"base" was mangling.

Design constraints that follow from the privacy contract:

* **Local only.** A JSONL file under the OpenJarvis config dir. Nothing here
  is ever sent anywhere; the outbound ratchet has no reason to see this module.
* **Opt-out and bounded.** Off by default is wrong (an invisible history is
  the point of a history), but unbounded growth is a liability: a dictation
  tool used all day would accumulate every sentence you ever spoke. It keeps
  the last N entries, N being small enough to stay a convenience rather than
  an archive.
* **Content lives here, so nowhere else.** Entries hold the transcript in
  clear — that IS the feature — which is precisely why the log must not.
  ``redact`` stays the rule for logging; this file is the one sanctioned
  place the text is written down.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_ENTRIES = 200


@dataclass(slots=True)
class DictationEntry:
    """One completed dictation."""

    text: str
    timestamp: float
    duration_s: float = 0.0
    app: str = ""          # frontmost app at paste time, when known
    model: str = ""        # which recogniser produced it
    chars: int = field(default=0)

    def __post_init__(self) -> None:
        if not self.chars:
            self.chars = len(self.text)


def default_history_path() -> Path:
    from diapason.core.paths import get_config_dir

    return get_config_dir() / "dictation_history.jsonl"


def _resolve(path: str | Path | None) -> Path:
    return Path(path) if path else default_history_path()


def load_history(
    path: str | Path | None = None, *, limit: Optional[int] = None
) -> List[DictationEntry]:
    """Return entries, newest first. A corrupt line is skipped, not fatal."""
    p = _resolve(path)
    if not p.is_file():
        return []
    entries: List[DictationEntry] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                entries.append(DictationEntry(**data))
            except (json.JSONDecodeError, TypeError):
                # One bad line must not destroy the whole history.
                continue
    except OSError:
        logger.debug("could not read dictation history", exc_info=True)
        return []
    entries.reverse()  # newest first
    return entries[:limit] if limit else entries


def append_entry(
    entry: DictationEntry,
    *,
    path: str | Path | None = None,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> None:
    """Append one entry, trimming the file to ``max_entries``.

    Never raises: losing a history line must not break a dictation that
    otherwise succeeded.
    """
    p = _resolve(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        _trim(p, max_entries)
    except OSError:
        logger.debug("could not append to dictation history", exc_info=True)


def _trim(path: Path, max_entries: int) -> None:
    """Keep only the newest ``max_entries`` lines, rewritten atomically."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= max_entries:
        return
    keep = lines[-max_entries:]
    _atomic_write(path, "\n".join(keep) + "\n")


def _atomic_write(path: Path, content: str) -> None:
    """Write via a temp file + replace so a crash cannot truncate history."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".hist-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except OSError:
        logger.debug("atomic history write failed", exc_info=True)
        try:
            os.unlink(tmp)
        except OSError:
            pass


def clear_history(path: str | Path | None = None) -> bool:
    """Delete the history file. Returns True if one existed."""
    p = _resolve(path)
    if p.exists():
        try:
            p.unlink()
            return True
        except OSError:
            return False
    return False


def stats(entries: Iterable[DictationEntry]) -> dict:
    """Aggregate a few honest numbers for a dashboard.

    Words-per-minute is deliberately absent: it would need a speaking-time
    denominator this data cannot support, and a made-up productivity figure is
    worse than none.
    """
    items = list(entries)
    total_chars = sum(e.chars for e in items)
    total_seconds = sum(e.duration_s for e in items)
    return {
        "count": len(items),
        "total_chars": total_chars,
        "total_seconds": round(total_seconds, 1),
        "avg_chars": round(total_chars / len(items), 1) if items else 0.0,
    }
