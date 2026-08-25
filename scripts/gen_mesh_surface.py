#!/usr/bin/env python
"""Engendre l'instantané des routes du maillage.

Spatial Mesh, 25 août 2026. Les quatre routes que le client Flutter appelle
n'étaient figées par AUCUN instantané : le cliquet existant ne surveille que
/v1/succes, que le Dart n'appelle justement pas. Renommer
/v1/mesh/commands/poll passait tous les tests des deux dépôts et cassait le
téléphone en silence.

Usage : .venv/bin/python scripts/gen_mesh_surface.py
"""

from __future__ import annotations

import json
from pathlib import Path

SORTIE = Path(__file__).resolve().parents[1] / "tests" / "contract" / "mesh_api_surface.json"


def surface() -> list[str]:
    # Les DEUX routeurs du maillage : les commandes et le transfert de
    # fichiers. Oublier le second laisserait ses routes libres de bouger —
    # exactement le trou que cet instantané existe pour fermer.
    from diapason.mesh.files_routes import router as files_router
    from diapason.mesh.routes import router

    return sorted(
        f"{sorted(r.methods - {'HEAD', 'OPTIONS'})[0]} {r.path}"
        for routeur in (router, files_router)
        for r in routeur.routes
        if getattr(r, "methods", None)
    )


def main() -> None:
    routes = surface()
    SORTIE.write_text(json.dumps(routes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(routes)} routes figées dans {SORTIE.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
