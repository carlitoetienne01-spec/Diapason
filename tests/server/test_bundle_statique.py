"""Le bundle servi au téléphone : ce qui se garde, ce qui se revalide.

Chantier de la fluidité, lot 1 (26/09/2026). Au banc (4G simulée, 110 ms
d'aller-retour, 10 Mbit/s), le téléphone retéléchargeait 2 480 Ko à chaque
ouverture de l'app : tout partait en ``no-store``, sans ETag, sans
compression. Chaque test nomme ce qui arriverait sans la règle qu'il tient —
et celle qui ne se négocie pas : l'app du téléphone reste EXACTEMENT celle
du Mac.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from diapason.server.bundle_statique import (  # noqa: E402
    CACHE_IMMUABLE,
    monter_le_bundle,
    porte_une_empreinte,
)

JS_V1 = "console.log('bundle du premier build');" * 200
JS_V2 = "console.log('bundle du second build');" * 200


def _construire(static: Path, empreinte: str, contenu: str) -> None:
    """Un « build » : index.html qui nomme son fichier à empreinte."""
    assets = static / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    js = assets / f"index-{empreinte}.js"
    js.write_text(contenu)
    (static / "index.html").write_text(
        f'<!doctype html><html><head><script type="module" '
        f'src="/assets/index-{empreinte}.js"></script></head><body></body></html>'
    )


def _client(static: Path) -> TestClient:
    app = FastAPI()

    @app.get("/v1/taches")
    def taches() -> JSONResponse:
        return JSONResponse(
            {"tasks": [{"id": i, "title": f"Tâche {i}"} for i in range(400)]}
        )

    monter_le_bundle(app, static)
    return TestClient(app)


@pytest.fixture
def bundle(tmp_path):
    static = tmp_path / "static"
    _construire(static, "Ab1_cD-2", JS_V1)
    (static / "assets" / "sans_empreinte.js").write_text("// " + "x" * 2000)
    (static / "sw.js").write_text("// service worker " + "y" * 2000)
    return static


class TestLeCache:
    def test_un_fichier_a_empreinte_est_immuable(self, bundle):
        """Sans cela, le téléphone redemande 1,4 Mo de JS à chaque ouverture
        (2 480 Ko retéléchargés au banc, rechargement complet)."""
        reponse = _client(bundle).get("/assets/index-Ab1_cD-2.js")
        assert reponse.status_code == 200
        assert reponse.headers["cache-control"] == CACHE_IMMUABLE, (
            "un nom à empreinte n'a qu'un contenu : il se garde un an"
        )
        assert reponse.headers.get("etag"), (
            "l'ETag doit rester, pour revalider au besoin"
        )

    def test_un_fichier_sans_empreinte_se_revalide(self, bundle):
        """Un nom sans empreinte peut changer de contenu sous le même nom :
        immuable, il resterait figé un an au téléphone."""
        client = _client(bundle)
        for chemin in ("/assets/sans_empreinte.js", "/sw.js"):
            reponse = client.get(chemin)
            assert reponse.headers["cache-control"] == "no-cache", chemin
            assert "no-store" not in reponse.headers["cache-control"], chemin
            assert reponse.headers.get("etag"), f"{chemin} sans ETag ne se revalide pas"

    def test_l_index_se_revalide_et_rend_304_quand_rien_n_a_change(self, bundle):
        """Une ouverture où rien n'a changé ne doit coûter qu'un aller-retour
        de quelques centaines d'octets, pas l'index entier."""
        client = _client(bundle)
        premiere = client.get("/")
        assert premiere.headers["cache-control"] == "no-cache"
        etag = premiere.headers["etag"]
        seconde = client.get("/taches", headers={"If-None-Match": etag})
        assert seconde.status_code == 304, "même index, même ETag : 304 attendu"
        assert seconde.content == b"", "un 304 n'a pas de corps"
        assert seconde.headers["cache-control"] == "no-cache", "le 304 garde sa règle"

    def test_apres_un_nouveau_build_le_telephone_execute_le_nouveau_bundle(
        self, bundle
    ):
        """La règle qui ne se négocie pas : l'app du téléphone est EXACTEMENT
        celle du Mac. L'ancien ETag de l'index ne doit plus rendre 304, et le
        nouvel index ne doit nommer que la nouvelle empreinte."""
        client = _client(bundle)
        ancien = client.get("/")
        assert "index-Ab1_cD-2.js" in ancien.text

        time.sleep(0.01)
        _construire(bundle, "Zz9-yY_8", JS_V2)
        (bundle / "assets" / "index-Ab1_cD-2.js").unlink()
        nouveau = client.get("/", headers={"If-None-Match": ancien.headers["etag"]})
        assert nouveau.status_code == 200, "l'ancien ETag ne doit plus valider l'index"
        assert nouveau.headers["etag"] != ancien.headers["etag"]
        assert "index-Zz9-yY_8.js" in nouveau.text
        assert "index-Ab1_cD-2.js" not in nouveau.text, (
            "l'ancien bundle n'est plus nommé"
        )
        js = client.get("/assets/index-Zz9-yY_8.js")
        assert js.text == JS_V2, "le nouveau fichier est servi"

    def test_aucune_reponse_de_l_api_ne_devient_cachable(self, bundle):
        """La confidentialité avant la vitesse : /v1 porte les données de
        Carlito. Les règles du bundle ne s'appliquent qu'au bundle — ni
        public, ni immuable, ni ETag qui en ferait une copie revalidable."""
        reponse = _client(bundle).get("/v1/taches")
        cache = reponse.headers.get("cache-control", "")
        assert "public" not in cache and "immutable" not in cache, cache
        assert "max-age" not in cache, cache
        assert "etag" not in reponse.headers

    def test_l_empreinte_de_vite_est_reconnue_et_seulement_elle(self):
        """Un faux positif rendrait immuable un fichier qui change."""
        for nom in (
            "index-DP3oxbgi.css",
            "KaTeX_Caligraphic-Regular-CTRA-rTL.woff",
            "GraphiqueDiscussion-D9Rjhn52.js",
        ):
            assert porte_une_empreinte(nom), nom
        for nom in ("index.html", "sw.js", "manifest.webmanifest", "app.js", "a-b.js"):
            assert not porte_une_empreinte(nom), nom
