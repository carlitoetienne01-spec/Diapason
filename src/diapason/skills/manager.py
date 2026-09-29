"""SkillManager — coordinates skill discovery, catalog, tool wrapping, and execution."""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from diapason.core.events import EventBus
from diapason.core.paths import get_config_dir
from diapason.skills.dependency import validate_dependencies
from diapason.skills.executor import SkillExecutor, SkillResult
from diapason.skills.loader import discover_skills
from diapason.skills.tool_adapter import SkillTool
from diapason.skills.types import SkillManifest
from diapason.tools._stubs import BaseTool, ToolExecutor

LOGGER = logging.getLogger(__name__)

# 28/09/2026: ECC skills reach a model through ONE tool, skill_guide, which
# heads every reading with its provenance and says the text is a method,
# never an order. A SkillTool per skill would hand the same text over with
# neither — and add a schema per skill to the prefix of every agent built
# by SystemBuilder.
GUIDE_ONLY_SOURCES = frozenset({"ecc"})


def _source_of(manifest: SkillManifest) -> str:
    meta = manifest.metadata.get("diapason", {}) if manifest.metadata else {}
    source = meta.get("source", "") if isinstance(meta, dict) else ""
    return source if isinstance(source, str) else ""


def _disabled_sources_from_config() -> set[str]:
    try:
        from diapason.core.config import load_config

        sources = load_config().skills.sources
    except Exception:  # noqa: BLE001 - discovery must not die on a config
        return set()
    return {
        str(getattr(s, "source", ""))
        for s in sources or []
        if getattr(s, "enabled", True) is False
    }


class SkillManager:
    """Coordinate skill discovery, resolution, catalog generation, and execution.

    Parameters
    ----------
    bus:
        Event bus for publishing lifecycle events.
    capability_policy:
        Optional capability policy passed through to tool executors.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        capability_policy: Optional[Any] = None,
        overlay_dir: Optional[Path] = None,
    ) -> None:
        self._bus = bus
        self._capability_policy = capability_policy
        self._skills: Dict[str, SkillManifest] = {}
        self._tool_executor: Optional[ToolExecutor] = None
        # (name, kept source, ignored source) for every name seen twice.
        self.collisions: List[tuple[str, str, str]] = []
        if overlay_dir is None:
            # Try to read from config first; fall back to the default
            # ~/.diapason/learning/skills/ if config can't be loaded.
            try:
                from diapason.core.config import load_config

                cfg = load_config()
                cfg_dir = getattr(
                    getattr(cfg.learning, "skills", None),
                    "overlay_dir",
                    None,
                )
                if cfg_dir:
                    overlay_dir = Path(cfg_dir).expanduser()
            except Exception:
                pass
            if overlay_dir is None:
                overlay_dir = get_config_dir() / "learning" / "skills"
        self._overlay_dir = Path(overlay_dir).expanduser()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(
        self,
        paths: Optional[List[Path]] = None,
        *,
        disabled_sources: Optional[set[str]] = None,
    ) -> None:
        """Scan directories in order and register skills.

        First-seen name wins (workspace path listed first = highest precedence).
        After loading, the full dependency graph is validated and any
        sidecar overlays in ``overlay_dir`` are applied to discovered skills.

        Parameters
        ----------
        paths:
            Directories to scan.  If *None* or empty, no skills are loaded
            from disk — but ``_load_overlays()`` still runs (in case the
            caller had previously seeded ``self._skills`` directly).
        disabled_sources:
            Sources whose installed skills are skipped (``enabled = false``
            in ``[[skills.sources]]``). Read from the config when *None*.
        """
        if paths:
            if disabled_sources is None:
                disabled_sources = _disabled_sources_from_config()
            for directory in paths:
                manifests = discover_skills(directory)
                for manifest in manifests:
                    source = _source_of(manifest)
                    if source and source in disabled_sources:
                        continue
                    # First-seen wins: do not overwrite an already-registered
                    # skill. 28/09/2026: it won in silence — an ECC skill
                    # could hide a Hermes one (or be hidden) without a word.
                    kept = self._skills.get(manifest.name)
                    if kept is None:
                        self._skills[manifest.name] = manifest
                        continue
                    collision = (
                        manifest.name,
                        _source_of(kept) or "local",
                        source or "local",
                    )
                    self.collisions.append(collision)
                    LOGGER.warning(
                        "Skill name %r seen twice: the %s copy wins, "
                        "the %s copy is ignored",
                        *collision,
                    )

            # Validate the dependency graph after loading skills
            if self._skills:
                validate_dependencies(self._skills)

        # Load optimization overlays (Plan 2A) — always runs, even when no
        # paths are provided, so callers can apply overlays to skills loaded
        # via other means.
        self._load_overlays()

    def _load_overlays(self) -> None:
        """Apply optimization overlays to discovered skills.

        For each skill, look for ``<overlay_dir>/<skill-name>/optimized.toml``.
        If present, override the manifest description and stash few-shot
        examples under ``manifest.metadata.diapason.few_shot``.

        Bad overlays are silently ignored — they should not break discovery.
        """
        from diapason.skills.overlay import SkillOverlayLoader

        loader = SkillOverlayLoader(self._overlay_dir)
        for name, manifest in self._skills.items():
            overlay = loader.load(name)
            if overlay is None:
                continue
            if overlay.description:
                manifest.description = overlay.description
            if overlay.few_shot:
                new_metadata = dict(manifest.metadata) if manifest.metadata else {}
                oj = dict(new_metadata.get("diapason", {}) or {})
                oj["few_shot"] = list(overlay.few_shot)
                new_metadata["diapason"] = oj
                manifest.metadata = new_metadata

    # ------------------------------------------------------------------
    # Resolve / introspect
    # ------------------------------------------------------------------

    def resolve(self, name: str) -> SkillManifest:
        """Return the manifest for a skill by name.

        Raises
        ------
        KeyError
            If *name* is not registered.
        """
        if name not in self._skills:
            raise KeyError(f"Skill '{name}' not found")
        return self._skills[name]

    def skill_names(self) -> List[str]:
        """Return the names of all registered skills."""
        return list(self._skills.keys())

    # ------------------------------------------------------------------
    # Tool wrapping
    # ------------------------------------------------------------------

    def get_skill_tools(
        self, *, tool_executor: Optional[ToolExecutor] = None
    ) -> List[BaseTool]:
        """Wrap each registered skill as a :class:`SkillTool` (a :class:`BaseTool`).

        Parameters
        ----------
        tool_executor:
            Tool executor to use when running skill pipelines.  Falls back to
            the one set via :meth:`set_tool_executor` if not provided here.

        Returns
        -------
        list[BaseTool]
            One :class:`SkillTool` per registered skill.
        """
        executor = tool_executor or self._tool_executor
        tools: List[BaseTool] = []

        for manifest in self._skills.values():
            if _source_of(manifest) in GUIDE_ONLY_SOURCES:
                continue
            real_executor = executor or _NullToolExecutor()
            skill_exec = SkillExecutor(real_executor, bus=self._bus)

            # Wire sub-skill resolver so nested skill_name steps can delegate back
            skill_exec.set_skill_resolver(self._make_resolver())

            skill_tool = SkillTool(manifest, skill_exec, skill_manager=self)
            tools.append(skill_tool)

        return tools

    def _make_resolver(self):
        """Return a resolver callback that delegates sub-skill execution."""

        def _resolver(name: str, context: Dict[str, Any]) -> SkillResult:
            manifest = self.resolve(name)
            skill_exec = SkillExecutor(
                self._tool_executor or _NullToolExecutor(),
                bus=self._bus,
            )
            skill_exec.set_skill_resolver(_resolver)
            return skill_exec.run(manifest, initial_context=context)

        return _resolver

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def get_catalog_xml(self) -> str:
        """Generate an ``<available_skills>`` XML catalog.

        Skills with ``disable_model_invocation=True`` are excluded so that
        internal or automation-only skills are not surfaced to the model.
        """
        lines: List[str] = ["<available_skills>"]

        for manifest in self._skills.values():
            if manifest.disable_model_invocation:
                continue
            escaped_name = html.escape(manifest.name)
            escaped_desc = html.escape(manifest.description or manifest.name)
            lines.append(
                f"  <skill name={escaped_name!r} description={escaped_desc!r} />"
            )

        lines.append("</available_skills>")
        return "\n".join(lines)

    def get_few_shot_examples(self) -> List[str]:
        """Return formatted few-shot example strings ready for system prompt.

        Pulls from ``manifest.metadata.diapason.few_shot`` for every
        registered skill.  Returns one formatted string per example.
        """
        examples: List[str] = []
        for name, manifest in self._skills.items():
            oj = manifest.metadata.get("diapason", {}) if manifest.metadata else {}
            few_shot = oj.get("few_shot", []) or []
            for ex in few_shot:
                if not isinstance(ex, dict):
                    continue
                inp = str(ex.get("input", ""))
                out = str(ex.get("output", ""))
                if inp or out:
                    examples.append(f"### {name}\nInput: {inp}\nOutput: {out}")
        return examples

    # ------------------------------------------------------------------
    # Trace-driven skill discovery (Plan 2A)
    # ------------------------------------------------------------------

    def discover_from_traces(
        self,
        trace_store: Any,
        *,
        min_frequency: int = 3,
        min_outcome: float = 0.5,
        output_dir: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Mine the trace store for recurring tool sequences.

        For each recurring sequence found by :class:`SkillDiscovery`, write
        a TOML skill manifest into *output_dir* (default
        ``~/.diapason/skills/discovered/``).  Returns a list of dicts with
        ``name`` and ``path`` for each manifest written.

        Names are normalized to spec-compliant kebab-case (lowercase with
        hyphens, no underscores) so the resulting manifests load cleanly
        through the discovery walker.
        """
        from diapason.learning.agents.skill_discovery import SkillDiscovery

        traces = trace_store.list_traces(limit=10000)
        discovery = SkillDiscovery(
            min_frequency=min_frequency,
            min_outcome=min_outcome,
        )
        discovered = discovery.analyze_traces(traces)

        if output_dir is None:
            output_dir = get_config_dir() / "skills" / "discovered"
        output_dir = Path(output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        written: List[Dict[str, Any]] = []
        for skill in discovered:
            name = self._normalize_skill_name(skill.name)
            skill_subdir = output_dir / name
            skill_subdir.mkdir(parents=True, exist_ok=True)
            toml_path = skill_subdir / "skill.toml"
            toml_path.write_text(
                self._serialize_discovered_skill(name, skill),
                encoding="utf-8",
            )
            written.append({"name": name, "path": str(toml_path)})

        return written

    @staticmethod
    def _normalize_skill_name(raw_name: str) -> str:
        """Convert an arbitrary discovered name to a spec-compliant kebab name.

        - Lowercase
        - Replace underscores and whitespace with hyphens
        - Collapse runs of hyphens
        - Strip leading/trailing hyphens
        """
        import re

        normalized = raw_name.lower()
        normalized = re.sub(r"[_\s]+", "-", normalized)
        normalized = re.sub(r"-+", "-", normalized)
        normalized = normalized.strip("-")
        if not normalized:
            normalized = "discovered-skill"
        return normalized

    @staticmethod
    def _serialize_discovered_skill(name: str, skill: Any) -> str:
        """Serialize a DiscoveredSkill into a spec-compliant skill.toml."""
        lines: List[str] = ["[skill]"]
        lines.append(f'name = "{name}"')
        lines.append('version = "0.1.0"')
        # Truncate description to spec max 1024 chars
        description = (skill.description or f"Discovered skill: {name}")[:1024]
        # Escape backslashes and double quotes for basic TOML strings
        description = description.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'description = "{description}"')
        lines.append('author = "diapason (auto-discovered)"')
        lines.append('tags = ["auto-discovered"]')
        lines.append("")

        for tool_name in skill.tool_sequence:
            lines.append("[[skill.steps]]")
            lines.append(f'tool_name = "{tool_name}"')
            lines.append('arguments_template = "{}"')
            lines.append('output_key = ""')
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        """Resolve and execute a skill by name.

        Parameters
        ----------
        name:
            Skill name to execute.
        context:
            Initial context dict passed to the executor.

        Returns
        -------
        SkillResult
        """
        manifest = self.resolve(name)
        executor = SkillExecutor(
            self._tool_executor or _NullToolExecutor(),
            bus=self._bus,
        )
        executor.set_skill_resolver(self._make_resolver())
        return executor.run(manifest, initial_context=context)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_tool_executor(self, tool_executor: ToolExecutor) -> None:
        """Attach a :class:`ToolExecutor` for running tool steps in skill pipelines."""
        self._tool_executor = tool_executor

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def find_installed_paths(
        self, name: str, *, roots: Optional[List[Path]] = None
    ) -> List[Path]:
        """Return on-disk skill directories matching ``name``.

        A directory matches when it contains ``skill.toml`` or ``SKILL.md``
        and either the directory name equals ``name`` or its parsed
        manifest's ``name`` field equals ``name``.
        """
        if roots is None:
            roots = [get_config_dir() / "skills", Path("./skills")]

        matches: List[Path] = []
        for root in roots:
            if not root.exists():
                continue
            for candidate in root.rglob("*"):
                if not candidate.is_dir():
                    continue
                toml = candidate / "skill.toml"
                md = candidate / "SKILL.md"
                if not (toml.exists() or md.exists()):
                    continue
                if candidate.name == name:
                    matches.append(candidate)
                    continue
                # Fall back to parsed manifest name
                try:
                    from diapason.skills.loader import load_skill_directory

                    manifest = load_skill_directory(candidate)
                    if manifest is not None and manifest.name == name:
                        matches.append(candidate)
                except Exception:
                    continue
        return matches

    def remove(self, name: str, *, roots: Optional[List[Path]] = None) -> List[Path]:
        """Remove an installed skill by name.

        Returns the list of directories that were removed.  Raises
        :class:`FileNotFoundError` when no matching skill exists on disk.
        """
        import shutil

        paths = self.find_installed_paths(name, roots=roots)
        if not paths:
            raise FileNotFoundError(f"No installed skill named {name!r}")
        for p in paths:
            shutil.rmtree(p)
        # Drop from in-memory catalog
        self._skills.pop(name, None)
        return paths


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _NullToolExecutor(ToolExecutor):
    """A no-op ToolExecutor used when no real executor is available.

    Allows SkillTool/SkillExecutor construction to succeed even before a
    real tool executor is wired in; any actual tool call will produce an
    error ToolResult rather than raising.
    """

    def __init__(self) -> None:
        super().__init__(tools=[], bus=None)


__all__ = ["SkillManager"]
