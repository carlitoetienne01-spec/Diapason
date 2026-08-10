"""HEARTBEAT.md queue — Diapason-style pending task drain."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_TASK_RE = re.compile(r"^(\s*)-\s+\[([ xX])\]\s+(.*)$")


@dataclass
class HeartbeatTask:
    text: str
    done: bool
    line_index: int  # 0-based in full file lines
    indent: str = ""


DEFAULT_HEARTBEAT = """# HEARTBEAT
> Ambient task queue. Heartbeat drains the first unchecked item under ## Now.
> Add tasks with: jarvis heartbeat add "…"

## Now
- [ ] Check calendar for meetings in the next 2 hours

## Watching
> Long-lived watchers (not auto-drained)
"""


def default_workspace_dir() -> Path:
    from openjarvis.core.config import get_config_dir

    return get_config_dir() / "workspace"


def heartbeat_path(workspace: Path | str | None = None) -> Path:
    root = Path(workspace).expanduser() if workspace else default_workspace_dir()
    return root / "HEARTBEAT.md"


def changelog_path(workspace: Path | str | None = None) -> Path:
    root = Path(workspace).expanduser() if workspace else default_workspace_dir()
    return root / "CHANGELOG.md"


def ensure_heartbeat_file(workspace: Path | str | None = None) -> Path:
    path = heartbeat_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_HEARTBEAT, encoding="utf-8")
    return path


def _section_bounds(lines: list[str], heading: str) -> tuple[int, int]:
    """Return [start, end) line indices for a ## section body."""
    start = -1
    needle = heading.strip().lower()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## ") and needle in line.strip().lower():
            start = i + 1
            break
    if start < 0:
        return (-1, -1)
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].strip().startswith("## "):
            end = j
            break
    return start, end


def parse_heartbeat(text: str) -> tuple[list[HeartbeatTask], list[HeartbeatTask]]:
    """Parse ## Now and ## Watching task lists."""
    lines = text.splitlines()
    now: list[HeartbeatTask] = []
    watching: list[HeartbeatTask] = []

    for section, bucket in (("## Now", now), ("## Watching", watching)):
        start, end = _section_bounds(lines, section)
        if start < 0:
            continue
        for i in range(start, end):
            m = _TASK_RE.match(lines[i])
            if not m:
                continue
            indent, mark, body = m.group(1), m.group(2), m.group(3).strip()
            if not body:
                continue
            bucket.append(
                HeartbeatTask(
                    text=body,
                    done=mark.lower() == "x",
                    line_index=i,
                    indent=indent,
                )
            )
    return now, watching


def read_heartbeat(workspace: Path | str | None = None) -> tuple[list[HeartbeatTask], list[HeartbeatTask]]:
    path = ensure_heartbeat_file(workspace)
    return parse_heartbeat(path.read_text(encoding="utf-8"))


def pending_now(workspace: Path | str | None = None) -> list[HeartbeatTask]:
    now, _ = read_heartbeat(workspace)
    return [t for t in now if not t.done]


def mark_done(task: HeartbeatTask, workspace: Path | str | None = None) -> None:
    path = ensure_heartbeat_file(workspace)
    lines = path.read_text(encoding="utf-8").splitlines()
    if task.line_index < 0 or task.line_index >= len(lines):
        return
    m = _TASK_RE.match(lines[task.line_index])
    if not m:
        return
    lines[task.line_index] = f"{m.group(1)}- [x] {m.group(3).strip()}"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_task(text: str, workspace: Path | str | None = None) -> HeartbeatTask:
    path = ensure_heartbeat_file(workspace)
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    start, end = _section_bounds(lines, "## Now")
    entry = f"- [ ] {text.strip()}"
    if start < 0:
        # Create Now section
        lines.extend(["", "## Now", entry])
        idx = len(lines) - 1
    else:
        # Insert before end of section (after last task or at start)
        insert_at = end
        for i in range(end - 1, start - 1, -1):
            if _TASK_RE.match(lines[i]):
                insert_at = i + 1
                break
        else:
            insert_at = start
        lines.insert(insert_at, entry)
        idx = insert_at
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return HeartbeatTask(text=text.strip(), done=False, line_index=idx)


def clear_done(workspace: Path | str | None = None) -> int:
    """Remove checked items under ## Now. Returns count removed."""
    path = ensure_heartbeat_file(workspace)
    lines = path.read_text(encoding="utf-8").splitlines()
    start, end = _section_bounds(lines, "## Now")
    if start < 0:
        return 0
    kept: list[str] = []
    removed = 0
    for i, line in enumerate(lines):
        if start <= i < end:
            m = _TASK_RE.match(line)
            if m and m.group(2).lower() == "x":
                removed += 1
                continue
        kept.append(line)
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return removed


def append_changelog(entry: str, workspace: Path | str | None = None) -> None:
    from datetime import datetime, timezone

    path = changelog_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    block = f"- {stamp}: {entry.strip()}\n"
    if path.exists():
        path.write_text(path.read_text(encoding="utf-8") + block, encoding="utf-8")
    else:
        path.write_text(f"# CHANGELOG\n\n{block}", encoding="utf-8")


__all__ = [
    "HeartbeatTask",
    "DEFAULT_HEARTBEAT",
    "append_changelog",
    "append_task",
    "clear_done",
    "default_workspace_dir",
    "ensure_heartbeat_file",
    "heartbeat_path",
    "mark_done",
    "parse_heartbeat",
    "pending_now",
    "read_heartbeat",
]
