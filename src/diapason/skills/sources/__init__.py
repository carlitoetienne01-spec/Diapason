"""Skill source resolvers — Hermes, OpenClaw, generic GitHub."""

from diapason.skills.sources.base import ResolvedSkill, SourceResolver
from diapason.skills.sources.github import GitHubResolver
from diapason.skills.sources.hermes import HERMES_REPO_URL, HermesResolver
from diapason.skills.sources.openclaw import OPENCLAW_REPO_URL, OpenClawResolver

__all__ = [
    "GitHubResolver",
    "HERMES_REPO_URL",
    "HermesResolver",
    "OPENCLAW_REPO_URL",
    "OpenClawResolver",
    "ResolvedSkill",
    "SourceResolver",
]
