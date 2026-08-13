"""Compatibility audit and one-way local migration to Diapason names."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from diapason.core.paths import get_config_dir

LEGACY_ENV_PREFIXES = ("OPENJARVIS_", "JARVIS_")
LEGACY_HOME_NAMES = (".openjarvis", ".jarvis")


@dataclass(slots=True)
class MigrationFinding:
    kind: str
    source: str
    target: str
    applied: bool = False


def inspect_legacy_state() -> list[MigrationFinding]:
    """Return legacy state that should be migrated or renamed."""
    findings: list[MigrationFinding] = []
    for name in sorted(os.environ):
        for prefix in LEGACY_ENV_PREFIXES:
            if name.startswith(prefix):
                suffix = name.removeprefix(prefix)
                findings.append(
                    MigrationFinding("environment", name, f"DIAPASON_{suffix}")
                )
                break

    target_home = get_config_dir()
    for legacy_name in LEGACY_HOME_NAMES:
        legacy = Path.home() / legacy_name
        if legacy.exists() and legacy.resolve() != target_home.resolve():
            findings.append(
                MigrationFinding("directory", str(legacy), str(target_home))
            )

    launch_agents = Path.home() / "Library" / "LaunchAgents"
    if launch_agents.is_dir():
        for source in sorted(launch_agents.glob("com.openjarvis*.plist")):
            target = source.with_name(
                source.name.replace("com.openjarvis", "com.diapason")
            )
            findings.append(MigrationFinding("launchd", str(source), str(target)))
    return findings


def apply_migration(findings: Iterable[MigrationFinding]) -> list[MigrationFinding]:
    """Apply safe filesystem migrations; shell environment changes are reported."""
    results: list[MigrationFinding] = []
    for finding in findings:
        if finding.kind == "environment":
            results.append(finding)
            continue

        source = Path(finding.source)
        target = Path(finding.target)
        if finding.kind == "directory":
            if target.exists():
                # Merge without overwriting current Diapason state.
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                for child in source.iterdir():
                    destination = target / child.name
                    if not destination.exists():
                        shutil.move(str(child), str(destination))
                if not any(source.iterdir()):
                    source.rmdir()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
            finding.applied = True
        elif finding.kind == "launchd" and not target.exists():
            text = source.read_text(encoding="utf-8")
            target.write_text(
                text.replace("com.openjarvis", "com.diapason"),
                encoding="utf-8",
            )
            target.chmod(0o600)
            source.unlink()
            finding.applied = True
        results.append(finding)
    return results
