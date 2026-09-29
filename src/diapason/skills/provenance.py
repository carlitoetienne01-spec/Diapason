"""Provenance helpers shared by the importer and the local ECC source.

28/09/2026. Two things were missing before an imported skill could be
trusted to say where it came from:

- a fingerprint. Without one, a copy under ``~/.diapason/skills`` aged in
  silence: nothing told "changed upstream" from "edited by hand" from "up to
  date";
- a TOML writer that escapes. The ``.source`` sidecar was written with
  f-strings: one quote or backslash in a path or a name made it unreadable,
  and the loader only logged a WARNING — the provenance vanished without a
  word.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path

# Subdirectories of a skill that the importer always copies (never gated by
# --with-scripts). The fingerprint covers exactly what is copied.
COPIED_SUBDIRS = ("references", "assets", "templates")

# 29/09/2026: for a source imported "without its scripts" (ECC), the ceiling
# only named scripts/. references/, assets/ and templates/ were copied
# whole, exec bits included — ECC 5064474 already ships
# skills/manim-video/assets/network_graph_scene.py. From such a source only
# these text files are copied (and served as annexes); the rest is listed
# as absent. 64 KiB: past that, an annex is a corpus, not a reference sheet.
TEXT_ANNEX_SUFFIXES = (".md", ".txt")
TEXT_ANNEX_MAX_BYTES = 65536


def main_file(skill_dir: Path) -> Path | None:
    """The skill's markdown file, if it is a regular file (never a symlink)."""
    for name in ("SKILL.md", "skill.md"):
        candidate = skill_dir / name
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def is_text_annex(path: Path) -> bool:
    """A small .md or .txt file: what a text-only source may copy."""
    try:
        return (
            path.suffix.lower() in TEXT_ANNEX_SUFFIXES
            and path.stat().st_size <= TEXT_ANNEX_MAX_BYTES
        )
    except OSError:
        return False


def copied_files(skill_dir: Path, *, text_only: bool = False) -> list[tuple[str, Path]]:
    """(relative posix path, file) for SKILL.md and the always-copied subdirs.

    Symlinks are left out, file or directory: a link in ``references/``
    pointing at ``~/.ssh`` would otherwise be copied as its target's
    content, then served to the model as an annex. With *text_only*, only
    :func:`is_text_annex` files of the subdirectories count.
    """
    out: list[tuple[str, Path]] = []
    main = main_file(skill_dir)
    if main is not None:
        out.append(("SKILL.md", main))
    for subdir in COPIED_SUBDIRS:
        root = skill_dir / subdir
        if not root.is_dir() or root.is_symlink():
            continue
        # os.walk without followlinks never descends into a linked directory.
        for current, _dirs, files in os.walk(root, followlinks=False):
            for name in files:
                path = Path(current) / name
                if path.is_symlink() or not path.is_file():
                    continue
                if text_only and not is_text_annex(path):
                    continue
                out.append((path.relative_to(skill_dir).as_posix(), path))
    out.sort(key=lambda item: item[0])
    return out


def fingerprint(skill_dir: Path, *, text_only: bool = False) -> str:
    """sha256 over SKILL.md and the copied subdirectories, path by path.

    The same function reads the upstream directory and the imported copy:
    equal fingerprints mean equal content, whatever the file dates say.
    Both sides must pass the same *text_only*.
    """
    digest = hashlib.sha256()
    for relative, path in copied_files(skill_dir, text_only=text_only):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def toml_string(value: str) -> str:
    """A TOML basic string, quotes included, valid whatever *value* holds.

    TOML forbids every control character but tab in a basic string, DEL
    included; overlay._escape only covers \\n, \\r and \\t. Lone surrogates
    (a non-UTF-8 file name decoded with surrogateescape) become U+FFFD.
    """
    out = ['"']
    for char in str(value):
        code = ord(char)
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        elif char == "\r":
            out.append("\\r")
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04X}")
        elif 0xD800 <= code <= 0xDFFF:
            out.append("\\uFFFD")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_string(str(v)) for v in value) + "]"
    return toml_string(str(value))


def render_toml(fields: Mapping[str, object]) -> str:
    """Flat ``key = value`` lines. ``None`` values are left out."""
    lines = []
    for key, value in fields.items():
        if value is None:
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


__all__ = [
    "COPIED_SUBDIRS",
    "TEXT_ANNEX_MAX_BYTES",
    "TEXT_ANNEX_SUFFIXES",
    "copied_files",
    "fingerprint",
    "is_text_annex",
    "main_file",
    "render_toml",
    "toml_string",
]
