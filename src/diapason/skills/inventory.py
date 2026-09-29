"""What is installed under the skills directory, read from disk.

28/09/2026: GET /v1/skills listed ``SkillRegistry.keys()`` — a registry no
code ever fills. It answered ``{"skills": []}`` whatever sat on the disk,
imported ECC skills included. This walks the disk instead, and says for
each skill whether it is active and which path reaches a model: an ECC
method reaches the chat only through the skill_guide tool; any other
installed skill only reaches the agents SystemBuilder builds for the CLI.
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


def installed_skills(cfg: Any) -> list[dict[str, Any]]:
    """One entry per installed skill: wire fields in camelCase English.

    ``active``: skills on, source on, and — for ECC — allow-listed.
    ``reachedBy``: "skill_guide", "cli-agents", or None when inactive.
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
        if source == SOURCE_NAME:
            active = manifest.name in served
            reached_by = "skill_guide" if active else None
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
        out.append(entry)
    out.sort(key=lambda e: (e["source"], e["name"]))
    return out


__all__ = ["installed_skills"]
