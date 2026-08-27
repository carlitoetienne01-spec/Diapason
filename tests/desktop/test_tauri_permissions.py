"""The Tauri bundle must be able to ask for every protected resource it uses."""

from __future__ import annotations

import plistlib
from pathlib import Path


def _info() -> dict:
    path = Path(__file__).parents[2] / "frontend" / "src-tauri" / "Info.plist"
    with path.open("rb") as stream:
        return plistlib.load(stream)


def test_la_decouverte_peut_demander_le_reseau_local_sur_macos():
    """Sans ces deux clés, macOS 15+ refuse sans même montrer la question."""
    info = _info()
    assert info["NSLocalNetworkUsageDescription"]
    assert "_diapason-mesh._tcp" in info["NSBonjourServices"]
