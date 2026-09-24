"""La forme du code du service : routes ``def``, indépendance, surface figée.

Conception : ``docs/development/compte-chiffre.md`` §3.1, §3.4 et étape 4
du §6 (« Forme du code »).
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import sys

from fastapi.routing import APIRoute

from diapason_comptes.app import ROUTEURS

RACINE = pathlib.Path(__file__).resolve().parents[2]
SURFACE = RACINE / "tests/contract/compte_api_surface.json"
AEAD = "cryptography.hazmat.primitives.ciphers.aead"

# Ce que charge un import NU d'``aead``, et ce que charge l'import de tout le
# service : les deux listes sortent de sous-processus neufs, pour qu'aucun
# module déjà importé par pytest (``diapason`` en tête, via le conftest
# racine) ne fausse la mesure.
_SONDE = r"""
import builtins, importlib, json, pkgutil, sys
sys.path.insert(0, {src!r})
directs = []
_import = builtins.__import__

def espion(nom, globals=None, locals=None, fromlist=(), level=0):
    appelant = (globals or {{}}).get("__name__", "")
    if appelant.startswith("diapason_comptes") and level == 0:
        directs.append(nom)
    return _import(nom, globals, locals, fromlist, level)

builtins.__import__ = espion
{corps}
builtins.__import__ = _import
print(json.dumps({{"modules": sorted(sys.modules), "directs": sorted(set(directs))}}))
"""

_CORPS_SERVICE = """
import diapason_comptes
for info in pkgutil.walk_packages(diapason_comptes.__path__, "diapason_comptes."):
    importlib.import_module(info.name)
"""


def _sonder(corps: str) -> dict:
    code = _SONDE.format(src=str(RACINE / "src"), corps=corps)
    sortie = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return json.loads(sortie.stdout)


class TestRoutesSynchrones:
    def test_toutes_les_routes_sont_des_def(self):
        """§3.1 et CLAUDE.md §5 — une route ``async`` qui appelle SQLite ou un
        HMAC le fait sur la boucle d'événements : un ``vault/commit`` lent
        figerait ``/health`` et toutes les autres requêtes."""
        routes = [r for routeur in ROUTEURS for r in routeur.routes]
        assert routes, "le service doit exposer des routes"
        for route in routes:
            assert isinstance(route, APIRoute), f"{route} n'est pas une APIRoute"
            assert not asyncio.iscoroutinefunction(route.endpoint), (
                f"{route.path} doit être une route def synchrone"
            )


class TestIndependance:
    def test_le_service_n_importe_rien_de_diapason(self):
        """§3.1 — le service tourne seul sur le VPS, sans l'app de bureau :
        un ``import diapason`` le ferait tomber au démarrage. Vérifié en
        sous-processus : un grep ne voit pas un import dynamique ni un import
        transitif par un module du service."""
        resultat = _sonder(_CORPS_SERVICE)
        fautifs = [
            m
            for m in resultat["modules"]
            if m == "diapason" or m.startswith("diapason.")
        ]
        assert fautifs == [], f"le service a chargé {fautifs}"

    def test_de_cryptography_seul_aead_est_importe(self):
        """D19 — ``cryptography`` est épinglé par empreinte sur le VPS pour
        AES-GCM seulement. Un import d'Argon2id, de HPKE ou d'une autre
        primitive élargirait ce que le VPS doit croire, et le §2.3 n'y met
        « aucun Argon2id côté serveur »."""
        resultat = _sonder(_CORPS_SERVICE)
        directs = [d for d in resultat["directs"] if d.split(".")[0] == "cryptography"]
        assert directs == [AEAD], f"imports directs de cryptography : {directs}"

        charges = {m for m in resultat["modules"] if m.startswith("cryptography")}
        attendus = {
            m
            for m in _sonder(f"import {AEAD}")["modules"]
            if m.startswith("cryptography")
        }
        en_trop = sorted(charges - attendus)
        assert not en_trop, f"modules cryptography chargés en plus d'aead : {en_trop}"


class TestSurface:
    def test_la_surface_est_figee(self):
        """§3.4 — ``compte_api_surface.json`` fige les routes : un renommage
        couperait du compte les applications déjà installées, sans erreur
        côté serveur. Régénérer avec ``scripts/gen_compte_surface.py`` dans
        le même commit."""
        sortie = subprocess.run(
            [
                sys.executable,
                "-c",
                "import runpy, json; "
                "m = runpy.run_path('scripts/gen_compte_surface.py', run_name='x'); "
                "print(json.dumps(m['surface']()))",
            ],
            capture_output=True,
            text=True,
            check=True,
            cwd=RACINE,
        )
        attendue = json.loads(SURFACE.read_text(encoding="utf-8"))
        assert json.loads(sortie.stdout) == attendue, (
            "surface changée : .venv/bin/python scripts/gen_compte_surface.py"
        )

    def test_aucune_route_ne_touche_au_maillage(self):
        """§3.4 — ni ``COMMAND_VERSION``, ni ``PULL_VERSION``, ni les champs
        signés du maillage : le compte et la flotte restent indépendants
        (§3.13, CLAUDE.md §4)."""
        routes = json.loads(SURFACE.read_text(encoding="utf-8"))
        assert all(r.split(" ", 1)[1].startswith("/api/v1/") for r in routes), (
            "toutes les routes vivent sous /api/v1"
        )
        assert not [r for r in routes if "mesh" in r or "device" in r], (
            "aucune route du maillage dans le service de comptes"
        )
