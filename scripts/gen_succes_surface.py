"""Régénère l'instantané de l'ALIAS /v1/succes du domaine vie.

    .venv/bin/python scripts/gen_succes_surface.py

Le domaine s'appelle ``vie`` depuis le 25/09/2026 (voir
``scripts/gen_vie_surface.py``). Cet instantané fige l'alias que les clients
d'avant le renommage appellent encore : il reste le miroir de
``vie_api_surface.json`` au préfixe près, jusqu'au retrait volontaire de
l'alias (étape 14c du plan de la phase 1b). Le test de contrat échoue tant
qu'il n'est pas régénéré — c'est voulu : il force à constater qu'un client
déjà installé dépend de cette surface.
"""

import json
import pathlib

from diapason.vie.routes import PREFIXE_HERITE, surface_api

routes = surface_api(PREFIXE_HERITE)
racine = pathlib.Path(__file__).resolve().parents[1]
cible = racine / "tests/contract/succes_api_surface.json"
cible.write_text(
    json.dumps(routes, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(f"{len(routes)} routes écrites dans {cible.relative_to(racine)}")
