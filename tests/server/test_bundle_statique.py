"""Le bundle servi au téléphone : cache, revalidation, variantes précomprimées.

Chantier de la fluidité, lot 1 (26/09/2026). Au banc (4G simulée, 110 ms
d'aller-retour, 10 Mbit/s), le téléphone retéléchargeait 2 480 Ko à chaque
ouverture de l'app : tout partait en ``no-store``, sans ETag, sans
compression. Chaque test nomme ce qui arriverait sans la règle qu'il tient —
et celle qui ne se négocie pas : l'app du téléphone reste EXACTEMENT celle
du Mac.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from diapason.server.bundle_statique import (  # noqa: E402
    CACHE_IMMUABLE,
    COMPRESSIBLES,
    encodages_acceptes,
    monter_le_bundle,
    porte_une_empreinte,
)

brotli = pytest.importorskip("brotli")

RACINE = Path(__file__).resolve().parents[2]
JS_V1 = "console.log('bundle du premier build');" * 200
JS_V2 = "console.log('bundle du second build');" * 200


def _construire(static: Path, empreinte: str, contenu: str) -> None:
    """Un « build » : index.html qui nomme son fichier à empreinte, et les
    variantes .br/.gz posées comme precomprimer.mjs les pose."""
    assets = static / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    js = assets / f"index-{empreinte}.js"
    js.write_text(contenu)
    (static / "index.html").write_text(
        f'<!doctype html><html><head><script type="module" '
        f'src="/assets/index-{empreinte}.js"></script></head><body></body></html>'
    )
    brut = js.read_bytes()
    (assets / f"index-{empreinte}.js.br").write_bytes(brotli.compress(brut))
    (assets / f"index-{empreinte}.js.gz").write_bytes(gzip.compress(brut))


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

    def test_l_index_ne_se_garde_jamais(self, bundle):
        """26/09/2026, contre-épreuve : en ``no-cache``, un retour arrière
        reprenait l'index du cache sans le redemander (Chromium 152, cache de
        retour arrière coupé comme dans la WebView) et l'ancien bundle
        tournait après un nouveau build. Toute route de la SPA rend l'index :
        toutes doivent le dire ``no-store``."""
        client = _client(bundle)
        for chemin in ("/", "/taches", "/vie/tasks", "/index.html"):
            reponse = client.get(chemin)
            assert reponse.status_code == 200, chemin
            assert reponse.headers["cache-control"] == "no-store", chemin

    def test_un_fichier_revalide_rend_304_quand_rien_n_a_change(self, bundle):
        """sw.js et ses pareils ne coûtent qu'un 304 sans corps."""
        client = _client(bundle)
        premiere = client.get("/sw.js")
        etag = premiere.headers["etag"]
        seconde = client.get("/sw.js", headers={"If-None-Match": etag})
        assert seconde.status_code == 304, "même fichier, même ETag : 304 attendu"
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
        js = client.get("/assets/index-Zz9-yY_8.js", headers={"Accept-Encoding": "br"})
        assert js.text == JS_V2, (
            "le nouveau fichier est servi, décomprimé à l'identique"
        )

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
        for nom in (
            "index.html",
            "sw.js",
            "manifest.webmanifest",
            "app.js",
            "a-b.js",
            # Un mot de huit lettres n'est pas une empreinte (26/09/2026).
            "icon-maskable.png",
            "pwa-maskable.png",
            # Ni cinq, sept ou neuf caractères : Vite en pose huit.
            "app-Ab1c2.js",
            "app-Ab1cD2e.js",
            "app-Ab1cD2eF9.js",
        ):
            assert not porte_une_empreinte(nom), nom


class TestLesVariantesPrecomprimees:
    def test_brotli_est_servi_quand_le_client_l_accepte(self, bundle):
        """Sans variante, 1 422 181 octets partent au lieu de 353 108."""
        reponse = _client(bundle).get(
            "/assets/index-Ab1_cD-2.js",
            headers={"Accept-Encoding": "gzip, deflate, br"},
        )
        assert reponse.headers["content-encoding"] == "br"
        assert reponse.headers["content-type"].startswith("text/javascript"), (
            "le type est celui du fichier, pas celui de la variante"
        )
        assert "accept-encoding" in reponse.headers["vary"].lower()
        assert reponse.text == JS_V1

    def test_gzip_quand_brotli_n_est_pas_accepte(self, bundle):
        """Chromium n'annonce pas brotli en http : gzip, pas le brut."""
        reponse = _client(bundle).get(
            "/assets/index-Ab1_cD-2.js", headers={"Accept-Encoding": "gzip, deflate"}
        )
        assert reponse.headers["content-encoding"] == "gzip"
        assert reponse.text == JS_V1

    def test_le_brut_quand_rien_n_est_accepte_ou_que_br_est_refuse(self, bundle):
        client = _client(bundle)
        for entete in ("identity", "br;q=0, gzip;q=0", ""):
            reponse = client.get(
                "/assets/index-Ab1_cD-2.js", headers={"Accept-Encoding": entete}
            )
            assert "content-encoding" not in reponse.headers, entete
            assert reponse.text == JS_V1, entete
            assert "accept-encoding" in reponse.headers["vary"].lower(), (
                "même le brut varie : un cache ne doit pas le resservir à un autre"
            )

    def test_chaque_variante_a_son_etag_et_son_304(self, bundle):
        """Un ETag partagé ferait valider par 304 une copie gzip auprès d'un
        client qui attend du brotli."""
        client = _client(bundle)
        br = client.get("/assets/index-Ab1_cD-2.js", headers={"Accept-Encoding": "br"})
        gz = client.get(
            "/assets/index-Ab1_cD-2.js", headers={"Accept-Encoding": "gzip"}
        )
        assert br.headers["etag"] != gz.headers["etag"]
        revalide = client.get(
            "/assets/index-Ab1_cD-2.js",
            headers={"Accept-Encoding": "br", "If-None-Match": br.headers["etag"]},
        )
        assert revalide.status_code == 304
        assert revalide.headers["cache-control"] == CACHE_IMMUABLE

    def test_une_variante_plus_vieille_que_son_original_n_est_pas_servie(self, bundle):
        """Un `vite build` sans `npm run build` réécrit le fichier sans ses
        variantes : servir l'ancien .br, ce serait exécuter au téléphone un
        bundle que le Mac n'a plus."""
        js = bundle / "assets" / "index-Ab1_cD-2.js"
        js.write_text(JS_V2)
        passe = time.time() - 60
        for suffixe in (".br", ".gz"):
            os.utime(str(js) + suffixe, (passe, passe))
        reponse = _client(bundle).get(
            "/assets/index-Ab1_cD-2.js", headers={"Accept-Encoding": "br, gzip"}
        )
        assert "content-encoding" not in reponse.headers
        assert reponse.text == JS_V2, "l'original à jour, pas la variante périmée"

    def test_la_liste_des_extensions_est_la_meme_des_deux_cotes(self):
        """precomprimer.mjs pose des variantes que le serveur doit savoir
        servir : une extension d'un seul côté, et elle part brute."""
        script = (RACINE / "frontend" / "scripts" / "precomprimer.mjs").read_text()
        bloc = script.split("export const EXTENSIONS = new Set([", 1)[1].split("]);")[0]
        du_script = set(re.findall(r"'(\.[a-z0-9]+)'", bloc))
        assert du_script == set(COMPRESSIBLES), du_script ^ set(COMPRESSIBLES)

    def test_la_construction_du_serveur_precomprime(self):
        """`npm run build` écrit server/static ; sans l'étape, aucune variante."""
        paquet = json.loads((RACINE / "frontend" / "package.json").read_text())
        assert "precomprimer.mjs" in paquet["scripts"]["build"]
        assert "precomprimer.mjs" not in paquet["scripts"]["build:tauri"], (
            "l'app de bureau embarque dist/ : des .br/.gz l'alourdiraient"
        )
        installe = (RACINE / "scripts" / "install-desktop.sh").read_text()
        rsync = installe.index('rsync -a --delete "$RACINE/frontend/dist/"')
        assert installe.index("precomprimer.mjs", rsync) > rsync, (
            "la copie de dist/ efface les variantes : il faut les reposer après"
        )


class TestLesGardeFousDuBundle:
    """26/09/2026, contre-épreuve : chacune de ces règles survivait seule à
    son retrait, la suite restant verte."""

    def test_le_disque_n_est_jamais_lu_sur_la_boucle(self, bundle, monkeypatch):
        """§5 : une route ``async`` qui lit le disque en ligne gèle le flux du
        chat et la voix. Le choix de la variante (des ``stat``) et la
        recherche du fichier de l'attrape-tout passent par un fil."""
        import asyncio

        from diapason.server import bundle_statique as bs

        fils: list[str] = []
        origine = asyncio.to_thread

        async def espion(fonction, *args, **kwargs):
            fils.append(getattr(fonction, "__name__", "?"))
            return await origine(fonction, *args, **kwargs)

        monkeypatch.setattr(bs.asyncio, "to_thread", espion)
        client = _client(bundle)
        assert client.get("/assets/index-Ab1_cD-2.js").status_code == 200
        assert "_variante" in fils, "la variante d'un fichier d'/assets"
        fils.clear()
        assert client.get("/vie/tasks").status_code == 200
        assert "fichier_du_bundle" in fils, "la recherche de l'attrape-tout"
        assert "_variante" in fils, "la variante de l'index"

    def test_une_reponse_qui_n_est_pas_un_200_ne_devient_jamais_304(self, bundle):
        """Un 404 servi avec la page d'un fichier revalidé : un 304 dirait au
        navigateur de garder ce qu'il a, et masquerait l'erreur."""
        from diapason.server.bundle_statique import CACHE_REVALIDE, ReponseDuBundle

        app = FastAPI()
        fichier = bundle / "sw.js"

        @app.get("/absent")
        def absent():
            return ReponseDuBundle(fichier, CACHE_REVALIDE, status_code=404)

        client = TestClient(app)
        etag = client.get("/absent").headers["etag"]
        reponse = client.get("/absent", headers={"If-None-Match": etag})
        assert reponse.status_code == 404, "un 404 reste un 404, même ETag"

    def test_une_variante_qui_n_est_pas_un_fichier_est_ignoree(self, bundle):
        """Un dossier (ou un tube) nommé comme une variante ne se sert pas :
        FileResponse échouerait au milieu de l'envoi."""
        br = bundle / "assets" / "index-Ab1_cD-2.js.br"
        br.unlink()
        br.mkdir()
        reponse = _client(bundle).get(
            "/assets/index-Ab1_cD-2.js", headers={"Accept-Encoding": "br, gzip"}
        )
        assert reponse.status_code == 200
        assert reponse.headers["content-encoding"] == "gzip", "la suivante"
        assert reponse.text == JS_V1


class TestLAcceptEncoding:
    def test_les_q_nuls_excluent_et_le_joker_inclut(self):
        assert encodages_acceptes("gzip, deflate, br, zstd") >= {"br", "gzip"}
        assert "br" not in encodages_acceptes("gzip, br;q=0")
        assert encodages_acceptes("*") >= {"br", "gzip"}
        assert "gzip" not in encodages_acceptes("*, gzip;q=0")
        assert encodages_acceptes(None) == frozenset()
        assert encodages_acceptes("br;q=abc") == frozenset(), (
            "un q illisible ne vaut rien"
        )
