"""The outbound ratchet — no new network path slips in unnoticed.

The census found 297 outbound sites. The seven structural gates cover the
families that route through a base class or a shared entry point, but nothing
stops a module added next month from calling ``httpx.post`` on its own and
bypassing every gate. This test is the backstop: it statically finds every
outbound-capable module and fails if one appears that the manifest does not
already know about.

Modelled on the journal ratchet from the user's Diapason project, which scans
src/ and fails on any log call that receives user content. Same idea, other
axis: scan src/ and fail on any *new* module that can reach the network.

When it fails on a genuinely new outbound module, the fix is one of:
  * route it through a gate (BaseTool/BaseConnector/BaseChannel, the engine
    discovery, cloud_router, or hybrid._base) so it has no raw transport call
    of its own; or
  * add the file to outbound_manifest.txt (``python -m tests.privacy
    ._regen_manifest``) — a deliberate act recording that a human checked it.
"""

from __future__ import annotations

from pathlib import Path

from tests.privacy._outbound_scan import scan_outbound_modules

_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "diapason"
_MANIFEST = Path(__file__).resolve().parent / "outbound_manifest.txt"


def _manifest_entries() -> set[str]:
    lines = _MANIFEST.read_text(encoding="utf-8").splitlines()
    return {
        ln.strip()
        for ln in lines
        if ln.strip() and not ln.lstrip().startswith("#")
    }


def test_no_unlisted_outbound_module():
    """A module that can reach the network must be in the manifest."""
    found = scan_outbound_modules(_SRC)
    known = _manifest_entries()

    unlisted = sorted(found - known)
    assert not unlisted, (
        f"{len(unlisted)} module(s) atteignent le réseau sans figurer au "
        "manifeste. Passez par une porte, ou régénérez le manifeste après "
        "vérification (python -m tests.privacy._regen_manifest) :\n"
        + "\n".join(f"  · {m}" for m in unlisted)
    )


def test_manifest_has_no_stale_entries():
    """A manifest entry that is no longer outbound should be removed.

    Kept honest in both directions: a stale entry hides the fact that the file
    stopped needing an exemption, and lets the next stale addition pass.
    """
    found = scan_outbound_modules(_SRC)
    known = _manifest_entries()

    stale = sorted(known - found)
    assert not stale, (
        f"{len(stale)} entrée(s) du manifeste ne sont plus sortantes — "
        "régénérez (python -m tests.privacy._regen_manifest) :\n"
        + "\n".join(f"  · {m}" for m in stale)
    )


def test_scanner_actually_finds_outbound_calls():
    """A ratchet that matches nothing is a lie.

    If the scanner broke (import moved, AST shape changed), the test above
    would pass vacuously. This floor stops that.
    """
    found = scan_outbound_modules(_SRC)
    assert len(found) > 50, f"scanner suspiciously quiet: only {len(found)} modules"
