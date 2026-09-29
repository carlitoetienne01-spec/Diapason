"""EccResolver — a local, read-only view of an ECC clone (affaan-m/ECC).

28/09/2026: Carlito ties a *selection* of ECC skills to Diapason, without
their scripts. The generic GitHubResolver could not serve here:

- its ``sync()`` runs ``git pull --ff-only`` in the clone — the network, and
  a mutation of a clone whose ``.codex-plugin/plugin.json`` and ``.mcp.json``
  the Codex install had already modified;
- its ``rglob`` sees 898 SKILL.md in that clone: 286 canonical ones under
  ``skills/``, 519 translations under ``docs/<lang>/skills``, 43 in
  ``.kiro``, 39 in ``.agents``, 11 in ``.cursor`` — and the copies differ.
  It would pick ``.agents/skills/article-writing`` or a ``docs/ja-JP``
  translation before the canonical file.

This resolver never touches the network and never writes to the clone.
Pulling the clone stays Carlito's act. It reads ``skills/*/SKILL.md`` one
level deep, and nothing else; it records HEAD, whether the skill's own
directory is modified locally, VERSION, the declared origin, a fingerprint,
the resources that are NOT imported (scripts, hooks, agents…) and the tools
and ECC skills the text cites — so the model can be told what is absent.

The selection lives in ``config.toml`` as an ALLOW-list of exact names
(``[skills.sources.filter] names = [...]``). There is no wildcard: a name
nobody wrote down is never imported, and never served.
"""

from __future__ import annotations

import logging
import os
import re
import stat
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from diapason.skills.provenance import COPIED_SUBDIRS, fingerprint, main_file
from diapason.skills.sources.base import ResolvedSkill, SourceResolver

LOGGER = logging.getLogger(__name__)

SOURCE_NAME = "ecc"
DEFAULT_REPO_PATH = "~/Projets/ECC"

# Claude Code's own tool names. They mean something to Claude Code only;
# ToolTranslator used to map five of them onto Diapason tools that do not
# exist (file_edit, file_glob, file_grep, delegate_agent, notebook_edit).
CLAUDE_CODE_TOOLS = frozenset(
    {
        "Agent",
        "Bash",
        "Edit",
        "Glob",
        "Grep",
        "MultiEdit",
        "NotebookEdit",
        "Read",
        "Skill",
        "Task",
        "TodoWrite",
        "WebFetch",
        "WebSearch",
        "Write",
    }
)

# A name is exactly what `name:` says in the frontmatter: lowercase kebab
# case, the rule SkillParser enforces. Anything else in the allow-list is
# refused rather than interpreted — "*", "research-*", "../x" included.
_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?!-)){0,62}[a-z0-9]$|^[a-z0-9]$")
_WILDCARD = re.compile(r"[*?\[\]]")

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*#*\s*$")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_SNAKE_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
_TOOL_WORD = re.compile(r"\b(" + "|".join(sorted(CLAUDE_CODE_TOOLS)) + r")\s+tool\b")
_MCP = re.compile(r"\bMCPs?\b")
_NPX = re.compile(r"\bnpx\b")
_CLAUDE_HOME = re.compile(r"~/\.claude|\bCLAUDE\.md\b")
_CURL_SH = re.compile(r"curl[^\n|]*\|\s*(?:ba|z)?sh\b")

# What the provenance line may say, and nothing else: these values come from
# files and frontmatter somebody else wrote (29/09/2026, see _first_line).
_VERSION = re.compile(r"^\d{1,4}(?:\.\d{1,4}){0,3}(?:-[0-9A-Za-z.]{1,20})?$")
_SPDX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]{0,39}$")
_KNOWN_LICENSES = (
    (re.compile(r"^MIT\b", re.IGNORECASE), "MIT"),
    (re.compile(r"^Apache License", re.IGNORECASE), "Apache-2.0"),
    (re.compile(r"^GNU LESSER GENERAL PUBLIC", re.IGNORECASE), "LGPL"),
    (re.compile(r"^GNU AFFERO GENERAL PUBLIC", re.IGNORECASE), "AGPL"),
    (re.compile(r"^GNU GENERAL PUBLIC", re.IGNORECASE), "GPL"),
    (re.compile(r"^Mozilla Public License", re.IGNORECASE), "MPL-2.0"),
    (re.compile(r"^BSD\b", re.IGNORECASE), "BSD"),
    (re.compile(r"^ISC\b", re.IGNORECASE), "ISC"),
    (re.compile(r"^This is free and unencumbered", re.IGNORECASE), "Unlicense"),
)
# An origin is an attribution (« community », « Ronald Skelton - Founder,
# RapportScore.ai »): letters, digits and light punctuation, one short line.
_ORIGIN_CHARS = re.compile(r"[^\w .,'&()/-]")


class AllowListError(ValueError):
    """``filter.names`` is not a list of exact skill names."""


@dataclass(slots=True)
class RepoState:
    """What the clone says about itself, read without writing anything."""

    head: str = ""
    version: str = ""
    license: str = ""
    # Paths (relative to the repo) that `git status` reports; None when git
    # could not be asked.
    dirty: frozenset[str] | None = None
    git_error: str = ""

    def skill_dirty(self, dir_name: str) -> bool | None:
        if self.dirty is None:
            return None
        prefix = f"skills/{dir_name}/"
        return any(p.startswith(prefix) for p in self.dirty)

    def dirty_outside_skills(self) -> int:
        if self.dirty is None:
            return 0
        return sum(1 for p in self.dirty if not p.startswith("skills/"))


@dataclass(slots=True)
class _Entry:
    dir_name: str
    path: Path
    frontmatter: dict[str, Any]
    body: str
    raw: str
    names: set[str] = field(default_factory=set)


class EccResolver(SourceResolver):
    """Local, read-only resolver for an ECC clone."""

    name = SOURCE_NAME

    def __init__(
        self,
        repo_path: str | Path = DEFAULT_REPO_PATH,
        *,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self._repo = Path(repo_path).expanduser()
        self._runner = runner
        self._state: RepoState | None = None

    # ------------------------------------------------------------------
    # SourceResolver
    # ------------------------------------------------------------------

    def cache_dir(self) -> Path:
        return self._repo

    def sync(self) -> None:
        """Read the clone's state. No clone, no pull, no fetch — no network.

        Raises FileNotFoundError when ``<repo>/skills`` is missing, so the
        CLI says so instead of importing nothing in silence.
        """
        if not (self._repo / "skills").is_dir():
            raise FileNotFoundError(
                f"Pas de dossier skills/ dans {self._repo} : le clone ECC est "
                "absent ou ailleurs (clé path de [[skills.sources]])."
            )
        self._state = self._read_state()

    @property
    def state(self) -> RepoState:
        if self._state is None:
            self._state = self._read_state()
        return self._state

    def list_skills(self) -> list[ResolvedSkill]:
        entries = self._read_entries()
        if not entries:
            return []
        state = self.state
        known = set()
        for entry in entries:
            known |= entry.names
        results: list[ResolvedSkill] = []
        for entry in entries:
            fm = entry.frontmatter
            name = str(fm.get("name") or entry.dir_name)
            origin = declared_origin(fm)
            provenance = {
                "depot": str(self._repo),
                "chemin": f"skills/{entry.dir_name}/SKILL.md",
                "depot_modifie": state.skill_dirty(entry.dir_name),
                "version_ecc": state.version,
                "origine": origin,
                "licence": declared_license(fm, state.license),
                "outils_cites": cited_tools(entry.body, fm),
                "competences_citees": cited_skills(entry.body, known - entry.names),
                "ressources_absentes": absent_resources(entry.path),
            }
            results.append(
                ResolvedSkill(
                    name=name,
                    source=self.name,
                    path=entry.path,
                    category=origin_category(origin),
                    description=str(fm.get("description") or ""),
                    commit=state.head,
                    sidecar_data={
                        "provenance": provenance,
                        "dir": entry.dir_name,
                        "tokens": estimated_tokens(entry.raw),
                        "sections": count_sections(entry.body),
                        "flags": dependency_flags(entry.body),
                        "fingerprint": fingerprint(entry.path),
                    },
                )
            )
        return results

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def _read_entries(self) -> list[_Entry]:
        root = self._repo / "skills"
        if not root.is_dir() or root.is_symlink():
            return []
        entries: list[_Entry] = []
        # One level only: skills/<dir>/SKILL.md. docs/<lang>, .agents,
        # .kiro and .cursor hold older or translated copies.
        for child in sorted(root.iterdir()):
            if child.is_symlink() or not child.is_dir():
                continue
            md = main_file(child)
            if md is None or md.name != "SKILL.md":
                continue
            try:
                raw = md.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                LOGGER.warning("ECC skill %s unreadable: %s", md, exc)
                continue
            fm, body = split_frontmatter(raw)
            names = {child.name}
            if isinstance(fm.get("name"), str) and fm["name"]:
                names.add(fm["name"])
            entries.append(_Entry(child.name, child, fm, body, raw, names))
        return entries

    def _git(self, *args: str) -> str:
        env = dict(os.environ)
        # `git status` refreshes the index and REWRITES .git/index when a
        # file's stat changed (measured 28/09/2026: a touched SKILL.md is
        # enough). GIT_OPTIONAL_LOCKS=0 makes it read-only.
        env["GIT_OPTIONAL_LOCKS"] = "0"
        env["GIT_TERMINAL_PROMPT"] = "0"
        completed = self._runner(
            ["git", "-C", str(self._repo), "-c", "core.fsmonitor=false", *args],
            capture_output=True,
            check=True,
            env=env,
            timeout=15,
        )
        out = completed.stdout
        return out.decode("utf-8", "replace") if isinstance(out, bytes) else out

    def _read_state(self) -> RepoState:
        state = RepoState(
            version=_version_of(self._repo),
            license=_license_of(self._repo),
        )
        try:
            state.head = self._git("rev-parse", "HEAD").strip()
            porcelain = self._git(
                "status", "--porcelain=v1", "-z", "--untracked-files=all"
            )
            state.dirty = frozenset(_parse_porcelain_z(porcelain))
        except (OSError, subprocess.SubprocessError) as exc:
            state.git_error = type(exc).__name__
            LOGGER.warning("ECC clone %s: git unavailable (%s)", self._repo, exc)
        return state


# ----------------------------------------------------------------------
# Text analysis (pure functions, shared with the CLI and the tool)
# ----------------------------------------------------------------------


def split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """(frontmatter dict, body). A missing or broken block gives ({}, raw)."""
    if not raw.startswith("---"):
        return {}, raw
    rest = raw[3:].lstrip("\n")
    end = rest.find("\n---")
    if end == -1:
        return {}, raw
    try:
        fm = yaml.safe_load(rest[:end])
    except yaml.YAMLError:
        return {}, raw
    body = rest[end + 4 :]
    body = body[body.find("\n") + 1 :] if "\n" in body else ""
    return (fm if isinstance(fm, dict) else {}), body


def headings(body: str) -> list[tuple[int, str, int]]:
    """(level, title, line index) of ## and ### headings outside code fences.

    deep-research carries a whole report template (« ## Executive Summary »)
    inside a fence: counted as sections, it doubled the table of contents.
    """
    out: list[tuple[int, str, int]] = []
    fence: str | None = None
    for index, line in enumerate(body.splitlines()):
        match = _FENCE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is not None:
            continue
        heading = _HEADING.match(line)
        if heading:
            out.append((len(heading.group(1)), heading.group(2).strip(), index))
    return out


def count_sections(body: str) -> int:
    return sum(1 for level, _, _ in headings(body) if level == 2)


def estimated_tokens(text: str) -> int:
    """Four characters per token: the estimate the chat budget uses."""
    return (len(text) + 3) // 4


def declared_origin(frontmatter: dict[str, Any]) -> str:
    """What the frontmatter DECLARES as origin — an attribution, not a proof.

    Light punctuation only, one short line: the value is shown in the
    provenance line of every reading.
    """
    meta = frontmatter.get("metadata")
    origin = meta.get("origin") if isinstance(meta, dict) else None
    origin = origin or frontmatter.get("origin") or ""
    return _one_line(_ORIGIN_CHARS.sub(" ", _one_line(str(origin), 200)), 60)


def origin_category(origin: str) -> str:
    lowered = origin.lower()
    if lowered == "ecc":
        return "ecc"
    if lowered == "community":
        return "community"
    return "autre"


def declared_license(frontmatter: dict[str, Any], repo_license: str) -> str:
    """The skill's own license, else the repository's — said as such.

    42 ECC skills come from "community" authors and carry no license of
    their own: they are published inside the MIT repository, which is not
    the same as being written under it. The wording keeps the difference.
    """
    own = frontmatter.get("license")
    if isinstance(own, str) and own.strip():
        own = own.strip()
        # An SPDX-like identifier (MIT, Apache-2.0), never a sentence.
        return own if _SPDX.match(own) else "déclarée, non reconnue"
    repo = repo_license or "inconnue"
    if origin_category(declared_origin(frontmatter)) == "community":
        return f"aucune licence propre (dépôt ECC : {repo})"
    return f"{repo} (licence du dépôt ECC)"


def cited_tools(body: str, frontmatter: dict[str, Any]) -> list[str]:
    """Tools the text really cites, not every CamelCase word.

    ToolTranslator's heuristic took ValueError, GitHub, TypeScript or
    UserService for missing tools. Counted here: the frontmatter ``tools:``
    / ``allowed-tools:`` fields; a Claude Code tool named as such (« the
    Task tool ») or alone in backticks; a snake_case identifier in
    backticks on a line that speaks of tools or MCP, or under an MCP
    heading (``firecrawl_search`` in deep-research).
    """
    found: list[str] = []

    def add(name: str) -> None:
        if name and name not in found:
            found.append(name)

    for key in ("tools", "allowed-tools"):
        value = frontmatter.get(key)
        tokens: Iterable[str]
        if isinstance(value, str):
            tokens = re.split(r"[,\s]+", value)
        elif isinstance(value, list):
            tokens = [str(v) for v in value]
        else:
            tokens = []
        for token in tokens:
            add(token.split("(", 1)[0].strip())

    fence: str | None = None
    under_mcp_heading = False
    for line in body.splitlines():
        match = _FENCE.match(line)
        if match:
            marker = match.group(1)
            fence = marker if fence is None else (None if marker == fence else fence)
            continue
        if fence is not None:
            continue
        heading = _HEADING.match(line)
        if heading:
            under_mcp_heading = bool(_MCP.search(heading.group(2)))
            continue
        for tool in _TOOL_WORD.findall(line):
            add(tool)
        speaks_of_tools = under_mcp_heading or bool(
            re.search(r"\btools?\b|\bMCPs?\b", line, re.IGNORECASE)
        )
        for code in _INLINE_CODE.findall(line):
            code = code.strip()
            if code in CLAUDE_CODE_TOOLS:
                add(code)
            elif speaks_of_tools and _SNAKE_ID.match(code):
                add(code)
    return found


def cited_skills(body: str, other_names: Iterable[str]) -> list[str]:
    """Other ECC skills the text names in backticks (`deep-research`…)."""
    others = set(other_names)
    found: list[str] = []
    for code in _INLINE_CODE.findall(body):
        code = code.strip()
        if code in others and code not in found:
            found.append(code)
    return found


def dependency_flags(body: str) -> list[str]:
    flags = []
    if _MCP.search(body):
        flags.append("MCP")
    if _NPX.search(body):
        flags.append("npx")
    if _CLAUDE_HOME.search(body):
        flags.append("~/.claude")
    if _CURL_SH.search(body):
        flags.append("curl|sh")
    return flags


def absent_resources(skill_dir: Path) -> list[str]:
    """What the skill directory holds and the import will NOT copy."""
    out = []
    for child in sorted(skill_dir.iterdir()):
        if child.name == ".DS_Store":
            continue
        if child.name in ("SKILL.md", "skill.md") or child.name in COPIED_SUBDIRS:
            if not child.is_symlink():
                continue
        out.append(child.name + ("/" if child.is_dir() else ""))
    return out


# ----------------------------------------------------------------------
# Configuration: which ECC skills are allowed, where they live
# ----------------------------------------------------------------------


def ecc_source_config(cfg: Any) -> Any | None:
    """The first ``[[skills.sources]]`` entry with ``source = "ecc"``."""
    sources = getattr(getattr(cfg, "skills", None), "sources", None)
    if not isinstance(sources, (list, tuple)):
        return None
    for src in sources:
        if getattr(src, "source", None) == SOURCE_NAME:
            return src
    return None


def repo_path(src_cfg: Any) -> Path:
    path = getattr(src_cfg, "path", "") if src_cfg is not None else ""
    return Path(
        path if isinstance(path, str) and path else DEFAULT_REPO_PATH
    ).expanduser()


def allowed_names(src_cfg: Any) -> list[str]:
    """``filter.names``, validated: a list of exact skill names, no wildcard.

    Raises AllowListError instead of guessing: a string "*" or a pattern
    "research-*" would otherwise widen the selection nobody wrote down.
    """
    filt = getattr(src_cfg, "filter", None) if src_cfg is not None else None
    raw = filt.get("names", []) if isinstance(filt, dict) else []
    if isinstance(raw, str):
        raise AllowListError(
            "filter.names doit être une LISTE de noms exacts, pas une chaîne "
            f"({raw!r})."
        )
    if not isinstance(raw, (list, tuple)):
        raise AllowListError("filter.names doit être une liste de noms exacts.")
    names: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise AllowListError(f"filter.names : {item!r} n'est pas un nom.")
        if _WILDCARD.search(item):
            raise AllowListError(
                f"filter.names : joker refusé ({item!r}). Chaque compétence se "
                "nomme exactement."
            )
        if not _NAME.match(item):
            raise AllowListError(
                f"filter.names : {item!r} n'est pas un nom de compétence "
                "(minuscules, chiffres et tirets)."
            )
        if item not in names:
            names.append(item)
    return names


def installed_root(cfg: Any) -> Path | None:
    skills_dir = getattr(getattr(cfg, "skills", None), "skills_dir", None)
    if not isinstance(skills_dir, str) or not skills_dir:
        return None
    return Path(skills_dir).expanduser() / SOURCE_NAME


def source_active(cfg: Any) -> bool:
    """Skills on, and the ecc source present and switched on."""
    skills = getattr(cfg, "skills", None)
    if getattr(skills, "enabled", None) is not True:
        return False
    src = ecc_source_config(cfg)
    return src is not None and getattr(src, "enabled", None) is True


def served_skills(cfg: Any) -> dict[str, Path]:
    """Installed ECC skills the model may read, by name.

    Empty unless skills and the ecc source are on; limited to the
    allow-list, even when other copies sit on disk. Never raises: a broken
    configuration closes the guide, it does not break the chat toolkit.
    """
    try:
        if not source_active(cfg):
            return {}
        names = allowed_names(ecc_source_config(cfg))
        root = installed_root(cfg)
        if root is None or not root.is_dir() or root.is_symlink():
            return {}
        served: dict[str, Path] = {}
        for name in names:
            skill_dir = root / name
            if skill_dir.is_symlink() or not skill_dir.is_dir():
                continue
            md = main_file(skill_dir)
            if md is not None and md.name == "SKILL.md":
                served[name] = skill_dir
        return served
    except AllowListError as exc:
        LOGGER.warning("ECC source closed: %s", exc)
        return {}
    except Exception:  # noqa: BLE001 - the chat must keep its other tools
        LOGGER.warning("ECC source closed: unreadable configuration", exc_info=True)
        return {}


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------


def _one_line(text: str, limit: int) -> str:
    cleaned = " ".join("".join(c if c.isprintable() else " " for c in text).split())
    return cleaned[:limit]


def _first_line(path: Path) -> str:
    """The first line of a REGULAR file of the clone, never through a link.

    29/09/2026: VERSION and LICENSE were opened with ``path.open()``, which
    follows a symlink. A commit replacing LICENSE by a link to
    ``../../.netrc`` sent that file's first line — a token — into .source,
    then into the head of every skill_guide reading, phone included.
    lstat, then O_NOFOLLOW: a FIFO would also have blocked the read forever.
    """
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return ""
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return ""
    try:
        with os.fdopen(fd, encoding="utf-8") as fh:
            return _one_line(fh.readline(), 80)
    except (OSError, UnicodeDecodeError):
        return ""


def _version_of(repo: Path) -> str:
    """VERSION if it reads like a version number, else nothing."""
    first = _first_line(repo / "VERSION")
    return first if _VERSION.match(first) else ""


def _license_of(repo: Path) -> str:
    """A known license's short name, "non reconnue", or "" when absent.

    Never the file's own words: whatever LICENSE says is upstream text, and
    it lands in the provenance line the model reads as Diapason's.
    """
    first = _first_line(repo / "LICENSE")
    if not first:
        return ""
    for pattern, label in _KNOWN_LICENSES:
        if pattern.search(first):
            return label
    return "non reconnue"


def _parse_porcelain_z(out: str) -> list[str]:
    records = out.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 4:
            continue
        status, path = record[:2], record[3:]
        paths.append(path)
        # A rename or copy is followed by its original path.
        if "R" in status or "C" in status:
            if index < len(records) and records[index]:
                paths.append(records[index])
            index += 1
    return paths


__all__ = [
    "AllowListError",
    "CLAUDE_CODE_TOOLS",
    "DEFAULT_REPO_PATH",
    "EccResolver",
    "RepoState",
    "SOURCE_NAME",
    "absent_resources",
    "allowed_names",
    "cited_skills",
    "cited_tools",
    "count_sections",
    "declared_license",
    "declared_origin",
    "dependency_flags",
    "ecc_source_config",
    "estimated_tokens",
    "headings",
    "installed_root",
    "origin_category",
    "repo_path",
    "served_skills",
    "source_active",
    "split_frontmatter",
]
