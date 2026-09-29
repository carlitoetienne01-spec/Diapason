"""What is installed under the skills directory, read from disk.

28/09/2026: GET /v1/skills listed ``SkillRegistry.keys()`` — a registry no
code ever fills. It answered ``{"skills": []}`` whatever sat on the disk,
imported ECC skills included. This walks the disk instead, and says for
each skill whether it is active and which path reaches a model: an ECC
method reaches the chat only through the skill_guide tool; any other
installed skill only reaches the agents SystemBuilder builds for the CLI.

29/09/2026: ``reachedBy: "skill_guide"`` was computed from the config and
the disk, while the chat toolkit that decides it is built once and cached
(app.state._chat_tooling_cache). Configure, restart before the import,
then import: the route said "skill_guide" for the eight while neither the
chat nor the phone had the tool until the next restart (§100: the field
described the intent, not the receiver). It now reads the LIVE toolkit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from diapason.skills.loader import discover_skills
from diapason.skills.sources.ecc import (
    SOURCE_NAME,
    AllowListError,
    allowed_names,
    ecc_source_config,
    served_skills,
)


def _disabled_sources(cfg: Any) -> set[str]:
    sources = getattr(getattr(cfg, "skills", None), "sources", None) or []
    return {
        str(getattr(s, "source", ""))
        for s in sources
        if getattr(s, "enabled", True) is False
    }


GUIDE = "skill_guide"


def live_toolkit(app_state: Any) -> frozenset[str] | None:
    """The chat toolkit's tool names, or None while it is not built yet."""
    cached = getattr(app_state, "_chat_tooling_cache", "absent")
    if isinstance(cached, str) and cached == "absent":
        return None
    if not cached:
        return frozenset()
    tools = cached[0] if isinstance(cached, tuple) else []
    names = set()
    for tool in tools:
        try:
            names.add(tool.spec.name)
        except Exception:  # noqa: BLE001 - a broken tool is simply not named
            continue
    return frozenset(names)


def installed_skills(
    cfg: Any, toolkit: frozenset[str] | None = None
) -> list[dict[str, Any]]:
    """One entry per installed skill: wire fields in camelCase English.

    ``active``: skills on, source on, and — for ECC — allow-listed.
    ``reachedBy``: "skill_guide" only when the LIVE chat *toolkit* holds the
    guide; "cli-agents" for other sources; None otherwise.
    ``pendingRestart`` (ECC): active on disk and in the config, but the
    built toolkit has no guide — nothing reaches a model before a restart.
    With *toolkit* None (not built yet), neither is claimed.
    Reads files: call it off the event loop.
    """
    skills_cfg = getattr(cfg, "skills", None)
    skills_dir = getattr(skills_cfg, "skills_dir", None)
    if not isinstance(skills_dir, str) or not skills_dir:
        return []
    root = Path(skills_dir).expanduser()
    enabled = getattr(skills_cfg, "enabled", True) is True
    disabled = _disabled_sources(cfg)
    served = served_skills(cfg)
    try:
        allow = set(allowed_names(ecc_source_config(cfg)))
    except AllowListError:
        allow = set()

    out: list[dict[str, Any]] = []
    for manifest in discover_skills(root):
        meta = (manifest.metadata or {}).get("diapason") or {}
        source = str(meta.get("source") or "local")
        pending = None
        if source == SOURCE_NAME:
            active = manifest.name in served
            guide_live = toolkit is not None and GUIDE in toolkit
            reached_by = GUIDE if active and guide_live else None
            pending = active and toolkit is not None and not guide_live
            listed = manifest.name in allow
        else:
            active = enabled and source not in disabled
            reached_by = "cli-agents" if active else None
            listed = None
        entry: dict[str, Any] = {
            "name": manifest.name,
            "source": source,
            "commit": str(meta.get("commit") or ""),
            "origin": str(meta.get("origine") or ""),
            "active": active,
            "reachedBy": reached_by,
        }
        if listed is not None:
            entry["allowListed"] = listed
        if pending is not None:
            entry["pendingRestart"] = pending
        out.append(entry)
    out.sort(key=lambda e: (e["source"], e["name"]))
    return out


__all__ = ["GUIDE", "installed_skills", "live_toolkit"]
