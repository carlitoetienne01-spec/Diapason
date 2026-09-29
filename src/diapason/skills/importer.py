"""SkillImporter — install ResolvedSkill instances into ~/.diapason/skills/.

Steps performed by ``import_skill``:

1. Parse the source SKILL.md through SkillParser (strict + tolerant).
2. Translate tool references in the markdown body via ToolTranslator —
   except for sources listed in ``VERBATIM_SOURCES``, copied byte for byte.
3. Decide on scripts (default-skip; opt-in via with_scripts=True, refused
   outright for sources listed in ``NO_SCRIPT_SOURCES``).
4. Write to disk at <target_root>/<source>/<name>/:
   - SKILL.md (translated, or verbatim)
   - references/, assets/, templates/ (always copied, symlinks left out;
     only small .md/.txt files, without exec bits, for NO_SCRIPT_SOURCES)
   - scripts/ (only if approved)
   - .source provenance file (escaped TOML)
5. Return ImportResult with status, warnings, translated/missing tools.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import yaml

from diapason.core.paths import get_config_dir
from diapason.skills.parser import SkillParser
from diapason.skills.provenance import (
    COPIED_SUBDIRS,
    copied_files,
    fingerprint,
    main_file,
    render_toml,
)
from diapason.skills.security import (
    TrustTier,
    classify_trust_tier,
    has_dangerous_capabilities,
)
from diapason.skills.sources.base import ResolvedSkill
from diapason.skills.tool_translator import ToolTranslator

# 28/09/2026: ECC skills are prose written for Claude Code. The translator
# rewrote it word by word — "Write a failing test" became "file_write a
# failing test", C#'s `Task<User?>` became `delegate_agent<User?>` — and
# promised the model five tools Diapason does not have. These sources are
# copied byte for byte; the tools they cite are recorded in .source and
# announced by the skill_guide tool instead.
VERBATIM_SOURCES = frozenset({"ecc"})

# A CEILING, not a default: with_scripts=True is refused for these sources,
# whoever asks (CLI flag, config, a future route). Carlito's decision of
# 28/09/2026: ECC is tied to Diapason without its scripts. "Restrict, never
# widen" — a restriction a caller can lift is decorative.
# 29/09/2026: the ceiling only named scripts/ — assets/setup.sh, exec bit
# and `curl … | sh` included, was copied whole while .source said
# scripts_imported = false. From these sources only small .md/.txt files
# are copied, without exec bits (provenance.copied_files, text_only).
NO_SCRIPT_SOURCES = frozenset({"ecc"})
# rw-r--r--: what a copied text file gets, whatever its upstream mode.
_TEXT_MODE = 0o644

# Keys the importer owns in .source; a resolver's provenance cannot set them.
_RESERVED_KEYS = frozenset(
    {
        "source",
        "commit",
        "category",
        "sha256_source",
        "sha256_importe",
        "installed_at",
        "traduit",
        "translated_tools",
        "missing_tools",
        "scripts_imported",
        "trust_tier",
        "dangerous_capabilities",
    }
)


def _ignore_symlinks(directory: str, names: list[str]) -> list[str]:
    """copytree filter: a link could point anywhere on the disk."""
    return [n for n in names if os.path.islink(os.path.join(directory, n))]


def _safe_segment(segment: str) -> bool:
    """One path component, never a way out of the skills root."""
    return (
        bool(segment)
        and segment not in (".", "..")
        and not any(sep in segment for sep in ("/", "\\", "\0"))
    )


@dataclass(slots=True)
class ImportResult:
    """Result of importing a single skill."""

    success: bool = True
    skipped: bool = False
    target_path: Path | None = None
    translated_tools: List[str] = field(default_factory=list)
    untranslated_tools: List[str] = field(default_factory=list)
    scripts_imported: bool = False
    warnings: List[str] = field(default_factory=list)
    trust_tier: TrustTier = TrustTier.UNREVIEWED
    dangerous_capabilities: List[str] = field(default_factory=list)
    requires_confirmation: bool = False


class SkillImporter:
    """Install resolved skills into the user skills directory."""

    def __init__(
        self,
        parser: SkillParser,
        tool_translator: ToolTranslator,
        target_root: Path | None = None,
    ) -> None:
        self._parser = parser
        self._translator = tool_translator
        if target_root is None:
            target_root = get_config_dir() / "skills"
        self._target_root = Path(target_root)

    def import_skill(
        self,
        resolved: ResolvedSkill,
        *,
        with_scripts: bool = False,
        force: bool = False,
        confirm_dangerous: bool = False,
    ) -> ImportResult:
        """Install *resolved* into ``<target_root>/<source>/<name>/``.

        Returns an :class:`ImportResult` with status, paths, translated
        tools, untranslated tools, and warnings.
        """
        result = ImportResult()
        # 28/09/2026: the name comes from a frontmatter someone else wrote.
        # `name: ../..` made target_dir the parent of the skills root — and
        # force=True runs shutil.rmtree on it.
        if not (_safe_segment(resolved.source) and _safe_segment(resolved.name)):
            result.success = False
            result.warnings.append(
                f"Refusing to install: unsafe source or name "
                f"({resolved.source!r}, {resolved.name!r})"
            )
            return result
        target_dir = self._target_root / resolved.source / resolved.name
        result.target_path = target_dir
        verbatim = resolved.source in VERBATIM_SOURCES
        # 29/09/2026: `name: ..` was closed, not its twin. With
        # ~/.diapason/skills/ecc a link to ~/Projets/ECC/skills (to avoid a
        # copy), force=True ran rmtree THROUGH the link — rmtree only refuses
        # a link as the LAST component — and emptied skills/<name> in the
        # clone, untracked files lost for good.
        if self._escapes_root(target_dir):
            result.success = False
            result.warnings.append(
                f"Refusing to install: {target_dir} is, or goes through, a "
                f"symbolic link out of {self._target_root}"
            )
            return result

        if with_scripts and resolved.source in NO_SCRIPT_SOURCES:
            result.success = False
            result.warnings.append(
                f"Refus : les scripts de la source « {resolved.source} » ne "
                "s'importent jamais (plafond décidé le 28/09/2026)."
            )
            return result

        # Skip if already installed and force is False
        if target_dir.exists() and not force:
            result.skipped = True
            result.warnings.append(
                f"Skill already installed at {target_dir} (use force=True to overwrite)"
            )
            return result

        # 1. Parse source SKILL.md (a regular file: never through a symlink)
        source_md = main_file(resolved.path)
        if source_md is None:
            result.success = False
            result.warnings.append(f"No SKILL.md found in {resolved.path}")
            return result

        try:
            frontmatter, body = self._read_skill_md(source_md)
            manifest = self._parser.parse_frontmatter(
                frontmatter, markdown_content=body
            )
        except Exception as exc:
            result.success = False
            result.warnings.append(f"Parse error: {exc}")
            return result

        # 1a. Classify trust and check for dangerous capabilities *before*
        # writing anything to disk. Everything the importer handles comes from
        # an external source (github/hermes/openclaw), so the BUNDLED and
        # WORKSPACE tiers never apply here, and no resolver verifies index
        # membership yet — a signature alone still classifies as UNREVIEWED.
        # Community skills get no special treatment just because they came
        # from a named source.
        result.trust_tier = classify_trust_tier(
            has_signature=bool(manifest.signature),
        )
        result.dangerous_capabilities = has_dangerous_capabilities(manifest)

        if result.dangerous_capabilities and result.trust_tier == TrustTier.UNREVIEWED:
            result.requires_confirmation = True
            if not confirm_dangerous:
                result.success = False
                result.warnings.append(
                    "Refusing to install: this unreviewed skill requests "
                    f"dangerous capabilities {result.dangerous_capabilities}. "
                    "Re-run with confirm_dangerous=True (or `--yes-dangerous` "
                    "on the CLI) only if you trust the source and have "
                    "reviewed what it does."
                )
                return result
            result.warnings.append(
                "Installed with dangerous capabilities "
                f"{result.dangerous_capabilities} — confirmed by caller. "
                "This skill can run shell commands, open network listeners, "
                "and/or write to the filesystem."
            )

        # 2. Translate tool references (never for verbatim sources)
        if verbatim:
            translated_body = body
        else:
            translated_body, untranslated = self._translator.translate_markdown(body)
            result.untranslated_tools = untranslated
            # Compute the list of translations actually applied
            applied: List[str] = []
            for ext, internal in self._translator._table.items():
                if ext in body and ext not in translated_body:
                    applied.append(f"{ext}->{internal}")
            result.translated_tools = applied

        # 3. Write the target directory
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True)

        # 3a. SKILL.md: verbatim bytes, or re-rendered after translation
        if verbatim:
            shutil.copyfile(source_md, target_dir / "SKILL.md")
        else:
            new_md = self._render_skill_md(frontmatter, translated_body)
            (target_dir / "SKILL.md").write_text(new_md, encoding="utf-8")

        # 3b. Always-copied subdirs — text files only for a no-script source
        if resolved.source in NO_SCRIPT_SOURCES:
            os.chmod(target_dir / "SKILL.md", _TEXT_MODE)
            for relative, path in copied_files(resolved.path, text_only=True):
                if relative == "SKILL.md":
                    continue
                destination = target_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
                os.chmod(destination, _TEXT_MODE)
        else:
            for subdir in COPIED_SUBDIRS:
                src_sub = resolved.path / subdir
                if src_sub.is_dir() and not src_sub.is_symlink():
                    shutil.copytree(
                        src_sub, target_dir / subdir, ignore=_ignore_symlinks
                    )

        # 3c. Scripts (gated by with_scripts)
        scripts_src = resolved.path / "scripts"
        if scripts_src.exists() and with_scripts and not scripts_src.is_symlink():
            shutil.copytree(
                scripts_src, target_dir / "scripts", ignore=_ignore_symlinks
            )
            result.scripts_imported = True
        elif scripts_src.exists() and resolved.source in NO_SCRIPT_SOURCES:
            result.warnings.append(
                f"scripts/ non importé : jamais pour la source « {resolved.source} »"
            )
        elif scripts_src.exists():
            result.warnings.append(
                "Skipped scripts/ directory (use with_scripts=True to import)"
            )

        # 4. Write .source metadata
        self._write_source_metadata(
            target_dir, resolved, result, translated=not verbatim
        )

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _escapes_root(self, target_dir: Path) -> bool:
        """A link as <source> or <name>: the only two components below the
        root (_safe_segment keeps them single). A link pointing INSIDE the
        root (skills/ecc → skills/hermes) is refused too: rmtree would empty
        another source's copy."""
        return target_dir.parent.is_symlink() or target_dir.is_symlink()

    def _read_skill_md(self, path: Path) -> tuple[dict, str]:
        """Parse a SKILL.md file into (frontmatter dict, markdown body)."""
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---"):
            return {}, raw
        rest = raw[3:].lstrip("\n")
        end = rest.find("\n---")
        if end == -1:
            return {}, raw
        fm_text = rest[:end]
        body = rest[end + 4 :].lstrip("\n")
        try:
            fm = yaml.safe_load(fm_text)
            if not isinstance(fm, dict):
                fm = {}
        except yaml.YAMLError:
            fm = {}
        return fm, body

    def _render_skill_md(self, frontmatter: dict, body: str) -> str:
        """Re-serialize a SKILL.md file from frontmatter dict + body."""
        fm_text = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False)
        return f"---\n{fm_text}---\n\n{body}"

    def _write_source_metadata(
        self,
        target_dir: Path,
        resolved: ResolvedSkill,
        result: ImportResult,
        *,
        translated: bool = True,
    ) -> None:
        """Write the .source TOML provenance file, every value escaped.

        28/09/2026: it was written with f-strings. A quote or a backslash in
        a path or a name made it unreadable; the loader only logged a
        WARNING and the provenance vanished in silence.
        """
        installed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fields: dict[str, object] = {
            "source": f"{resolved.source}:{resolved.name}",
            "commit": resolved.commit,
            "category": resolved.category,
        }
        provenance = (resolved.sidecar_data or {}).get("provenance") or {}
        if isinstance(provenance, dict):
            for key, value in provenance.items():
                if key not in _RESERVED_KEYS and isinstance(
                    value, (str, bool, int, list, tuple, type(None))
                ):
                    fields[str(key)] = value
        text_only = resolved.source in NO_SCRIPT_SOURCES
        fields.update(
            {
                "sha256_source": fingerprint(resolved.path, text_only=text_only),
                "sha256_importe": fingerprint(target_dir, text_only=text_only),
                "installed_at": installed_at,
                "traduit": translated,
                "translated_tools": list(result.translated_tools),
                "missing_tools": list(result.untranslated_tools),
                "scripts_imported": result.scripts_imported,
                "trust_tier": result.trust_tier.value,
                "dangerous_capabilities": list(result.dangerous_capabilities),
            }
        )
        (target_dir / ".source").write_text(render_toml(fields), encoding="utf-8")


__all__ = ["ImportResult", "SkillImporter"]
