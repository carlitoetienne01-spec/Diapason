"""Regenerate the outbound manifest. Run when a legitimately new outbound
module is added: ``python -m tests.privacy._regen_manifest``.

Regenerating is a deliberate act — it records that a human looked at the new
outbound site and confirmed it is either behind a chokepoint or acceptable.
"""

from __future__ import annotations

from pathlib import Path

from tests.privacy._outbound_scan import scan_outbound_modules

_HEADER = (
    "# Modules capables d'un appel sortant, détectés par _outbound_scan.py.\n"
    "# Le cliquet test_outbound_ratchet.py échoue si un module NON listé\n"
    "# acquiert un appel sortant : il faut alors soit passer par une porte\n"
    "# (BaseTool/BaseConnector/BaseChannel/engine._discovery/cloud_router/\n"
    "# hybrid._base), soit ajouter ce fichier ici avec une raison en commentaire.\n"
    "# Régénérer : python -m tests.privacy._regen_manifest\n\n"
)


def main() -> None:
    here = Path(__file__).resolve().parent
    src = here.parent.parent / "src" / "openjarvis"
    mods = sorted(scan_outbound_modules(src))
    (here / "outbound_manifest.txt").write_text(
        _HEADER + "\n".join(mods) + "\n", encoding="utf-8"
    )
    print(f"{len(mods)} modules écrits dans outbound_manifest.txt")


if __name__ == "__main__":
    main()
