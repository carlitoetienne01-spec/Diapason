"""Le schéma OpenAPI se génère — et personne ne s'en assurait.

Constaté le 26 août 2026 : `GET /openapi.json` rendait **500** sur tout le
dépôt. Six routes `delete_*` des Finances suffisaient à emporter le schéma
entier, et donc `/docs` et `/redoc` avec lui.

La cause tenait en une ligne : `finances_routes.py` déclare ses routes DANS
une fonction, `DeleteBody` lui arrivait en paramètre, et le fichier porte
`from __future__ import annotations`. L'annotation devient alors la chaîne
`"DeleteBody"`, que FastAPI résout contre les GLOBALES du module — jamais
contre les variables locales de la fonction. Le nom n'y était pas.

Ce test existe parce que rien ne demandait ce schéma : la panne pouvait durer
des mois sans qu'un seul test rougisse.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from diapason.server.app import create_app  # noqa: E402


@pytest.fixture(scope="module")
def schema() -> dict:
    app = create_app(MagicMock(), "test-model")
    reponse = TestClient(app, raise_server_exceptions=False).get("/openapi.json")
    assert reponse.status_code == 200, (
        f"le schéma OpenAPI ne se génère pas : {reponse.text[:400]}"
    )
    return reponse.json()


def test_le_schema_decrit_les_routes_du_depot(schema: dict):
    """Un schéma qui se génère mais ne décrit rien serait un faux vert."""
    assert len(schema.get("paths", {})) > 100, (
        f"seulement {len(schema.get('paths', {}))} routes décrites"
    )


def test_les_finances_sont_dans_le_schema(schema: dict):
    """C'est leur absence qui emportait tout : qu'elles soient là le prouve."""
    chemins = schema.get("paths", {})
    finances = [c for c in chemins if "/finances/" in c]
    assert finances, "aucune route Finances décrite"


def test_un_seul_schema_pour_un_seul_corps_de_suppression(schema: dict):
    """Une classe dupliquée dans deux modules aurait produit deux schémas.

    FastAPI les aurait nommés `DeleteBody` et `DeleteBody-Input` — une seule
    forme, deux entrées, et un client généré qui hésite. C'est la raison pour
    laquelle `DeleteBody` vit dans `succes/corps.py` plutôt que d'être
    recopié.
    """
    schemas = schema.get("components", {}).get("schemas", {})
    delete = [nom for nom in schemas if nom.startswith("DeleteBody")]
    assert delete == ["DeleteBody"], f"schémas trouvés : {delete}"


def test_la_documentation_se_sert(schema: dict):
    """`/docs` et `/redoc` ne valent que par le schéma qu'ils vont chercher."""
    app = create_app(MagicMock(), "test-model")
    client = TestClient(app, raise_server_exceptions=False)
    for page in ("/docs", "/redoc"):
        assert client.get(page).status_code == 200, f"{page} ne répond pas"
