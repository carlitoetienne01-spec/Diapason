"""Régénère l'instantané de la surface API du service de comptes du VPS.

    .venv/bin/python scripts/gen_compte_surface.py

À lancer dans le MÊME commit que tout ajout, retrait ou renommage de route
de ``src/diapason_comptes/`` (conception ``docs/development/compte-chiffre.md``
§3.4). Le test de ``tests/diapason_comptes/test_forme.py`` échoue tant que ce
n'est pas fait — c'est voulu : les applications de bureau déjà installées
appellent cette surface, et un renommage silencieux les couperait du compte.
"""

import json
import pathlib
import sys

racine = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(racine / "src"))

from diapason_comptes.app import ROUTEURS  # noqa: E402


def surface() -> list[str]:
    return sorted(
        f"{methode} {route.path}"
        for routeur in ROUTEURS
        for route in routeur.routes
        for methode in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"})
    )


if __name__ == "__main__":
    routes = surface()
    cible = racine / "tests/contract/compte_api_surface.json"
    cible.write_text(
        json.dumps(routes, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"{len(routes)} routes écrites dans {cible.relative_to(racine)}")
