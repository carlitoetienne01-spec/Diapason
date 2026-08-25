"""Les routes du maillage sont un contrat avec un dépôt qu'on ne compile pas.

Spatial Mesh, 25 août 2026. Le client Flutter (~/Desktop/Porfolio/Succes)
écrit quatre URL EN DUR dans ``mesh_api.dart`` et ne détient aucune clé
d'API : ces quatre routes sont sa seule porte. Or elles n'étaient figées
par aucun instantané — le cliquet existant surveille ``/v1/succes``, que le
Dart n'appelle justement jamais. Renommer ``/v1/mesh/commands/poll``
passait donc tous les tests des DEUX dépôts et rendait le téléphone muet,
avec un message d'erreur qui envoie chercher la panne du côté du réseau.

Deux cliquets de sévérité différente, parce que le risque l'est aussi :
une route quelconque qui bouge se régénère ; une des QUATRE routes du
téléphone qui bouge exige de livrer d'abord une version de l'app.
"""

from __future__ import annotations

import json
from pathlib import Path

SURFACE = Path(__file__).parent / "mesh_api_surface.json"

# Les quatre URL écrites en dur dans lib/services/mesh/mesh_api.dart, plus
# la présence signée. Le téléphone n'a aucune autre porte, et aucune clé
# d'API : ces routes sont aussi celles que le mur d'authentification
# exempte nommément (server/auth_middleware.py).
ROUTES_DU_TELEPHONE = frozenset(
    {
        "POST /v1/mesh/pairings/redeem",
        "POST /v1/mesh/commands/poll",
        "POST /v1/mesh/commands/deliver",
        "POST /v1/mesh/commands/ack",
        "POST /v1/mesh/presence",
    }
)


def _actuelles() -> set[str]:
    from diapason.mesh.routes import router

    return {
        f"{sorted(r.methods - {'HEAD', 'OPTIONS'})[0]} {r.path}"
        for r in router.routes
        if getattr(r, "methods", None)
    }


def _figees() -> set[str]:
    return set(json.loads(SURFACE.read_text(encoding="utf-8")))


class TestSurfaceDuMaillage:
    def test_aucune_route_disparue_ni_renommee(self):
        perdues = _figees() - _actuelles()
        assert not perdues, (
            f"{len(perdues)} route(s) de maillage ont disparu :\n  "
            + "\n  ".join(sorted(perdues))
            + "\n\nSi c'est voulu, régénère l'instantané DANS CE COMMIT :\n"
            "  .venv/bin/python scripts/gen_mesh_surface.py"
        )

    def test_les_routes_neuves_sont_declarees(self):
        """Ajouter est inoffensif pour le client — mais l'instantané doit
        rester le miroir exact, sinon il cesse d'être une référence."""
        neuves = _actuelles() - _figees()
        assert not neuves, (
            f"{len(neuves)} route(s) neuve(s) hors instantané :\n  "
            + "\n  ".join(sorted(neuves))
            + "\n\nRégénère :\n  .venv/bin/python scripts/gen_mesh_surface.py"
            + "\n\nET vérifie l'exemption d'authentification : une route "
            "mesh neuve part derrière le mur de la clé d'API et dans le "
            "mauvais seau de limitation tant qu'elle n'est pas ajoutée aux "
            "DEUX listes de server/auth_middleware.py."
        )


class TestLesQuatrePortesDuTelephone:
    """Celles-là ne bougent pas sans livrer d'abord une version mobile."""

    def test_elles_existent_toutes(self):
        manquantes = ROUTES_DU_TELEPHONE - _actuelles()
        assert not manquantes, (
            "Le client Flutter écrit ces URL en dur et n'a aucune autre "
            f"porte — il deviendrait muet :\n  " + "\n  ".join(sorted(manquantes))
        )

    def test_elles_sont_exemptees_du_mur_d_authentification(self):
        """Le téléphone ne détient aucune clé d'API. Une de ces routes qui
        repasserait derrière le mur lui rendrait un 401, que le client
        traduit en « vérifie que l'ordinateur est allumé » : un diagnostic
        qui envoie chercher au mauvais endroit."""
        from diapason.server.auth_middleware import AuthMiddleware

        mur = AuthMiddleware(app=None)
        for route in sorted(ROUTES_DU_TELEPHONE):
            chemin = route.split(" ", 1)[1]
            assert not mur._requires_auth(chemin), (
                f"{chemin} exige une clé d'API que le téléphone n'a pas"
            )
