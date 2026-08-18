"""Régénère l'instantané de la surface API que le client Succès appelle.

    .venv/bin/python scripts/gen_succes_surface.py

À lancer dans le MÊME commit que tout ajout, retrait ou renommage de route
sous ``/v1/succes``. Le test de contrat échoue tant que ce n'est pas fait —
c'est voulu : il force à constater qu'une application mobile déjà installée
dépend de cette surface.
"""

import json
import pathlib

from diapason.succes.routes import router

routes = sorted(
    f"{sorted(r.methods - {'HEAD', 'OPTIONS'})[0]} {r.path}"
    for r in router.routes
    if getattr(r, "methods", None)
)
racine = pathlib.Path(__file__).resolve().parents[1]
cible = racine / "tests/contract/succes_api_surface.json"
cible.write_text(
    json.dumps(routes, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(f"{len(routes)} routes écrites dans {cible.relative_to(racine)}")
