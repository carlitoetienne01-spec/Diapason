"""Régénère l'instantané de la surface API du domaine vie (/v1/vie).

    .venv/bin/python scripts/gen_vie_surface.py

À lancer dans le MÊME commit que tout ajout, retrait ou renommage de route
du domaine — avec ``scripts/gen_succes_surface.py``, qui fige l'alias. Le
test de contrat échoue tant que ce n'est pas fait : c'est voulu, il force à
constater que le téléphone et la fenêtre dépendent de cette surface.
"""

import json
import pathlib

from diapason.vie.routes import PREFIXE, surface_api

routes = surface_api(PREFIXE)
racine = pathlib.Path(__file__).resolve().parents[1]
cible = racine / "tests/contract/vie_api_surface.json"
cible.write_text(
    json.dumps(routes, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(f"{len(routes)} routes écrites dans {cible.relative_to(racine)}")
