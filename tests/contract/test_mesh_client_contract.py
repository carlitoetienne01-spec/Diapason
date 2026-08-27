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
    from diapason.mesh.files_routes import router as files_router
    from diapason.mesh.routes import router

    return {
        f"{sorted(r.methods - {'HEAD', 'OPTIONS'})[0]} {r.path}"
        for routeur in (router, files_router)
        for r in routeur.routes
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


class TestLesCinqPortesDuTelephone:
    """Celles-là ne bougent pas sans livrer d'abord une version mobile."""

    def test_elles_existent_toutes(self):
        manquantes = ROUTES_DU_TELEPHONE - _actuelles()
        assert not manquantes, (
            "Le client Flutter écrit ces URL en dur et n'a aucune autre "
            "porte — il deviendrait muet :\n  " + "\n  ".join(sorted(manquantes))
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


class TestLInvariantReciproque:
    """Toute route hors du mur doit être dans un seau de limitation.

    Le test existant ne verrouille qu'un sens : une route exemptée du mur
    mais absente des listes de seaux ne déclenche aucune alarme — c'est le
    bug historique que le commentaire d'auth_middleware raconte. Ceci est
    l'autre sens.
    """

    def test_aucune_route_mesh_n_est_hors_mur_et_hors_seau(self):
        from diapason.server.auth_middleware import (
            _OPEN_MESH_ROUTES,
            AuthMiddleware,
            est_route_de_transfert,
        )

        orphelines = []
        for route in sorted(_actuelles()):
            chemin = route.split(" ", 1)[1]
            if AuthMiddleware._requires_auth(chemin):
                continue  # derrière le mur : le seau authentifié s'applique
            if chemin in _OPEN_MESH_ROUTES or est_route_de_transfert(chemin):
                continue  # hors du mur, mais dans un seau connu
            orphelines.append(chemin)
        assert not orphelines, (
            "Ces routes sont hors du mur d'authentification ET hors de tout "
            "seau de limitation — un inconnu du réseau peut les marteler :\n  "
            + "\n  ".join(orphelines)
        )

    def test_les_routes_de_transfert_sont_reconnues_comme_telles(self):
        from diapason.server.auth_middleware import est_route_de_transfert

        transferts = [
            r.split(" ", 1)[1]
            for r in _actuelles()
            if "/files/" in r or r.endswith("/files/offer")
        ]
        assert transferts, "le routeur de transfert doit être dans l'instantané"
        for chemin in transferts:
            # Les chemins déclarés portent {session_id} : on le remplace par
            # un identifiant plausible, comme le ferait une vraie requête.
            concret = chemin.replace("{session_id}", "abc123").replace(
                "{request_id}", "request123"
            )
            assert est_route_de_transfert(concret), (
                f"{concret} n'est pas reconnue : elle partirait derrière le "
                "mur, et l'appareil émetteur n'a pas la clé d'API"
            )
