#!/usr/bin/env python3
"""Fail CI when product identity, filenames, or release versions drift."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
LEGACY_RE = re.compile(r"open[ -]?jarvis|openjarvis|OPENJARVIS|\bJARVIS_", re.I)
OLD_URL_RE = re.compile(r"open-jarvis\.github\.io|github\.com/open-jarvis", re.I)
ALLOWED_LEGACY_PATHS = {
    ".gitleaksignore",  # exact fingerprints for reviewed pre-migration fixtures
    "NOTICE",
    "scripts/check_project_identity.py",
    "src/diapason/core/env.py",
    "src/diapason/core/paths.py",
    "src/diapason/migration.py",
    "frontend/src-tauri/src/lib.rs",
    "deploy/windows/install.ps1",
    "deploy/windows/diapason-service.ps1",
    "scripts/install/install.sh",
    "scripts/install/bg-orchestrator.sh",
    "scripts/install/build-extension.sh",
    "scripts/install/pull-model.sh",
    "scripts/quickstart.sh",
    "scripts/install/diapason-wrapper.sh",
    "scripts/install/diapason-uninstall.sh",
    "docs/getting-started/migration-to-diapason.md",
    "src/diapason/cli/migrate_cmd.py",
}
ALLOWED_LEGACY_PREFIXES = ("tests/",)
EXPECTED_VERSION = "1.0.2"


def project_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def check_branding() -> list[str]:
    errors: list[str] = []
    for path in project_files():
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if LEGACY_RE.search(relative) and relative not in ALLOWED_LEGACY_PATHS:
            errors.append(f"legacy product name in path: {relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if OLD_URL_RE.search(text):
            errors.append(f"obsolete canonical URL: {relative}")
        allowed = relative in ALLOWED_LEGACY_PATHS or relative.startswith(
            ALLOWED_LEGACY_PREFIXES
        )
        if not allowed and LEGACY_RE.search(text):
            errors.append("legacy product name outside compatibility code: " + relative)
    return errors


def check_versions() -> list[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    values = {
        "pyproject.toml": pyproject["project"]["version"],
        "frontend/package.json": json.loads(
            (ROOT / "frontend/package.json").read_text()
        )["version"],
        "frontend/src-tauri/tauri.conf.json": json.loads(
            (ROOT / "frontend/src-tauri/tauri.conf.json").read_text()
        )["version"],
        "frontend/src-tauri/Cargo.toml": tomllib.loads(
            (ROOT / "frontend/src-tauri/Cargo.toml").read_text()
        )["package"]["version"],
    }
    return [
        f"version mismatch: {path}={version}, expected {EXPECTED_VERSION}"
        for path, version in values.items()
        if version != EXPECTED_VERSION
    ]


def main() -> int:
    errors = check_branding() + check_versions()
    if errors:
        print("Project identity check failed:", file=sys.stderr)
        for error in sorted(set(errors)):
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Project identity check passed (Diapason {EXPECTED_VERSION}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
