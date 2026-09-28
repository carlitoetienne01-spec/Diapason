"""La compression du JSON de l'API — et jamais celle d'un flux.

Chantier de la fluidité, lot 1 (26/09/2026). La liste des tâches partait
brute au téléphone (365 834 octets au banc, plus du double sur un foyer
réel), relue par trois pages à 10 Mbit/s. Chaque test nomme ce qui
arriverait sans la règle qu'il tient — et la règle qui ne se négocie pas :
le chat et la voix restent mot à mot.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, WebSocket  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from diapason.server import compression_api as ca  # noqa: E402
from diapason.server.compression_api import CompressionDesReponses  # noqa: E402

brotli = pytest.importorskip("brotli")


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/v1/taches")
    def taches() -> JSONResponse:
        return JSONResponse(
            {"tasks": [{"id": i, "title": f"Tâche {i}"} for i in range(400)]}
        )

    @app.get("/v1/petit")
    def petit() -> JSONResponse:
        return JSONResponse({"ok": True})

    app.add_middleware(CompressionDesReponses)
    return TestClient(app)


class TestLeJsonDeLApi:
    def test_une_grande_reponse_json_est_comprimee(self):
        """La liste des tâches (365 834 octets au banc) relue par trois pages."""
        client = _client()
        brut = client.get("/v1/taches", headers={"Accept-Encoding": "identity"})
        for entete, attendu in (("gzip, deflate, br", "br"), ("gzip", "gzip")):
            reponse = client.get("/v1/taches", headers={"Accept-Encoding": entete})
            assert reponse.headers["content-encoding"] == attendu, entete
            assert int(reponse.headers["content-length"]) < len(brut.content) / 3
            assert reponse.json() == brut.json(), "décomprimée, la même réponse"
            assert "accept-encoding" in reponse.headers["vary"].lower()

    def test_la_vraie_app_comprime_son_json_sous_ses_middlewares(self):
        """Posée au-dessus des BaseHTTPMiddleware (sécurité, clé), la
        compression verrait chaque réponse redécoupée en flux et n'en
        comprimerait AUCUNE — sans rien dire. Elle doit rester la plus
        intérieure."""
        from diapason.core.config import DiapasonConfig
        from diapason.server.app import create_app

        moteur = MagicMock()
        moteur.list_models.return_value = ["test-model"]
        config = DiapasonConfig()
        config.analytics.enabled = False
        config.traces.enabled = False
        client = TestClient(create_app(moteur, "test-model", config=config))
        brut = client.get("/openapi.json", headers={"Accept-Encoding": "identity"})
        reponse = client.get("/openapi.json", headers={"Accept-Encoding": "br"})
        assert reponse.headers.get("content-encoding") == "br", reponse.headers
        assert reponse.headers.get("x-content-type-options") == "nosniff", (
            "les en-têtes de sécurité passent toujours"
        )
        assert reponse.json() == brut.json()

    def test_aucune_reponse_comprimee_ne_devient_cachable(self):
        """La confidentialité avant la vitesse : comprimée, une réponse /v1
        reste sans cache public, sans durée, sans ETag."""
        client = _client()
        for entete in ("br", "gzip", "identity"):
            reponse = client.get("/v1/taches", headers={"Accept-Encoding": entete})
            cache = reponse.headers.get("cache-control", "")
            assert "public" not in cache and "immutable" not in cache, (entete, cache)
            assert "max-age" not in cache, (entete, cache)
            assert "etag" not in reponse.headers, entete

    def test_une_petite_reponse_part_telle_quelle(self):
        """Sous un paquet du tailnet, comprimer ne gagne rien."""
        reponse = _client().get("/v1/petit", headers={"Accept-Encoding": "br"})
        assert "content-encoding" not in reponse.headers
        assert reponse.json() == {"ok": True}


# ── les flux : jamais retardés ─────────────────────────────────────────────


async def _appeler(app, scope: dict, corps: bytes = b"", *, sur_morceau=None):
    """Appelle ``app`` en ASGI brut et rend (début, morceaux).

    ``sur_morceau`` est appelé à CHAQUE morceau reçu, au moment où il est
    reçu : c'est ce qui prouve qu'un flux n'est pas retenu — la source
    attend que le test ait vu le mot précédent avant d'écrire le suivant.
    """
    debut: dict = {}
    morceaux: list[bytes] = []
    envoye = False

    async def recevoir() -> dict:
        nonlocal envoye
        if not envoye:
            envoye = True
            return {"type": "http.request", "body": corps, "more_body": False}
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    fini = False

    async def envoyer(message: dict) -> None:
        # Strict comme uvicorn (26/09/2026, contre-épreuve) : un harnais qui
        # acceptait un second `http.response.start` et des corps après le
        # dernier laissait vert un middleware qui coupait le flux au premier
        # mot — sous un vrai serveur, « data: Bonjour » seul, code 200.
        nonlocal fini
        assert not fini, f"message après la fin de la réponse : {message['type']}"
        if message["type"] == "http.response.start":
            assert not debut, "un second http.response.start"
            debut.update(message)
        elif message["type"] == "http.response.body":
            assert debut, "un corps avant l'en-tête"
            morceau = message.get("body", b"")
            morceaux.append(morceau)
            if morceau and sur_morceau is not None:
                sur_morceau(morceau)
            fini = not message.get("more_body", False)

    await asyncio.wait_for(app(scope, recevoir, envoyer), timeout=5)
    assert fini, "la réponse ne s'est jamais terminée"
    return debut, morceaux


def _scope(chemin: str, *, methode: str = "GET", entetes=()) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": methode,
        "scheme": "http",
        "path": chemin,
        "raw_path": chemin.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"accept-encoding", b"gzip, deflate, br"),
        ]
        + [(n.encode(), v.encode()) for n, v in entetes],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }


def _entetes(debut: dict) -> dict[str, str]:
    return {n.decode().lower(): v.decode() for n, v in debut.get("headers", [])}


class TestLesGardeFous:
    """Chaque garde de ``CompressionDesReponses``, tenue seule.

    26/09/2026, contre-épreuve : le seuil, l'ETag affaibli, le 206, le double
    codage, la compression qui grossit et le filtre de type survivaient
    chacun à leur retrait — la suite restait verte."""

    @staticmethod
    def _repondre(corps: bytes, type_: str, *, statut=200, entetes=None):
        from starlette.responses import Response

        async def app(scope, receive, send):
            await Response(
                corps, status_code=statut, media_type=type_, headers=entetes
            )(scope, receive, send)

        debut, morceaux = asyncio.run(
            _appeler(CompressionDesReponses(app), _scope("/v1/x"))
        )
        return _entetes(debut), b"".join(morceaux)

    def test_une_reponse_complete_qui_n_est_pas_du_json_part_brute(self):
        """Un flux SSE servi d'un bloc (une reprise, une erreur) ou une page
        HTML : sans le filtre de type, ils partiraient comprimés, et un
        client qui lit le SSE au fil de l'eau recevrait du brotli."""
        for type_ in ("text/event-stream", "text/html", "text/plain"):
            corps = ("data: mot\n\n" * 400).encode()
            entetes, recu = self._repondre(corps, type_)
            assert "content-encoding" not in entetes, type_
            assert recu == corps, type_

    def test_un_json_sous_le_seuil_part_brut_meme_compressible(self):
        """900 octets de JSON répétitif se compriment très bien : c'est le
        seuil, pas le hasard du taux, qui doit les laisser bruts."""
        corps = json.dumps({"x": "a" * 880}).encode()
        assert len(corps) < ca.SEUIL_DE_COMPRESSION
        assert len(brotli.compress(corps)) < len(corps) / 5, "compressible"
        entetes, recu = self._repondre(corps, "application/json")
        assert "content-encoding" not in entetes
        assert recu == corps

    def test_un_etag_fort_devient_faible_une_fois_comprime(self):
        """Un ETag fort nomme des octets : gardé tel quel sur un corps
        comprimé, il ferait valider par 304 un brut contre du brotli."""
        corps = json.dumps({"x": ["Tâche"] * 400}).encode()
        entetes, recu = self._repondre(
            corps, "application/json", entetes={"etag": '"abc"'}
        )
        assert entetes["content-encoding"] == "br"
        assert entetes["etag"] == 'W/"abc"'
        assert brotli.decompress(recu) == corps

    def test_une_reponse_partielle_n_est_pas_recomprimee(self):
        """Un 206 porte une TRANCHE : la comprimer rendrait son
        Content-Range faux."""
        corps = json.dumps({"x": ["Tâche"] * 400}).encode()
        entetes, recu = self._repondre(
            corps,
            "application/json",
            statut=206,
            entetes={"content-range": f"bytes 0-{len(corps) - 1}/99999"},
        )
        assert "content-encoding" not in entetes
        assert recu == corps

    def test_un_corps_deja_code_n_est_pas_code_deux_fois(self):
        corps = gzip.compress(json.dumps({"x": ["Tâche"] * 400}).encode())
        corps = corps + b" " * 2000
        entetes, recu = self._repondre(
            corps, "application/json", entetes={"content-encoding": "gzip"}
        )
        assert entetes["content-encoding"] == "gzip", "un seul codage"
        assert recu == corps

    def test_une_compression_qui_grossit_la_reponse_est_ecartee(self, monkeypatch):
        """Un JSON déjà dense (du base64) peut grossir : on garde le brut."""
        monkeypatch.setattr(ca, "_comprimer", lambda corps, enc: corps + b"\0" * 64)
        corps = json.dumps({"x": ["Tâche"] * 400}).encode()
        entetes, recu = self._repondre(corps, "application/json")
        assert "content-encoding" not in entetes
        assert recu == corps


class TestLesFluxRestentMotAMot:
    """Si la compression retenait un flux, la source attendrait un mot que
    le client n'a jamais reçu : le test finit en délai dépassé, pas vert."""

    @staticmethod
    def _source(mots: list[str], vus: list[str], format_) -> object:
        async def generer():
            for mot in mots:
                attendus = len(vus)
                yield format_(mot)
                for _ in range(200):
                    if len(vus) > attendus:
                        break
                    await asyncio.sleep(0.005)
                else:
                    raise AssertionError(
                        f"« {mot} » retenu : le client ne l'a pas reçu"
                    )

        return generer()

    @pytest.mark.parametrize(
        "type_",
        ["text/event-stream", "application/json", "application/x-ndjson", "audio/mpeg"],
    )
    def test_un_flux_passe_morceau_par_morceau(self, type_):
        mots = ["Bonjour", " Carlito", ",", " voici", " la", " réponse"]
        vus: list[str] = []
        app = FastAPI()

        @app.get("/flux")
        async def flux():
            return StreamingResponse(
                self._source(mots, vus, lambda m: f"data: {m}\n\n"), media_type=type_
            )

        pile = CompressionDesReponses(app)
        debut, morceaux = asyncio.run(
            _appeler(
                pile, _scope("/flux"), sur_morceau=lambda m: vus.append(m.decode())
            )
        )
        assert "content-encoding" not in _entetes(debut), type_
        assert [m for m in morceaux if m] == [f"data: {m}\n\n".encode() for m in mots]

    def test_le_chat_de_la_vraie_app_arrive_mot_a_mot_par_la_passerelle(
        self, tmp_path, monkeypatch
    ):
        """La preuve de bout en bout : la vraie app (sécurité, clé, CORS,
        compression), derrière la vraie passerelle du tailnet, avec une
        session d'appareil. Le moteur n'écrit le mot suivant que quand le
        téléphone a reçu le précédent."""
        from diapason.core.config import DiapasonConfig
        from diapason.mesh.routes import set_registry_for_tests
        from diapason.server.app import create_app
        from diapason.server.passerelle_tailnet import COOKIE_APPAREIL
        from tests.server.test_passerelle_tailnet import (
            ICI,
            KEY,
            _Monde,
        )

        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "foyer"))
        monde = _Monde(tmp_path)
        set_registry_for_tests(monde.registry)
        try:
            mots = ["Un", " mot", " après", " l'autre", "."]
            vus: list[str] = []

            async def flux_du_moteur(messages, *, model, **_):
                for mot in mots:
                    attendus = len(vus)
                    yield mot
                    for _ in range(400):
                        if len(vus) > attendus:
                            break
                        await asyncio.sleep(0.005)
                    else:
                        raise AssertionError(f"« {mot} » retenu en route")

            moteur = MagicMock()
            moteur.engine_id = "mock"
            moteur.list_models.return_value = ["test-model"]
            moteur.stream = flux_du_moteur
            config = DiapasonConfig()
            config.analytics.enabled = False
            config.traces.enabled = False
            app = create_app(moteur, "test-model", api_key=KEY, config=config)
            passerelle = monde.passerelle(app)
            ticket = monde.sessions.issue_ticket("dev_le_telephone")
            jeton = monde.sessions.redeem_ticket(ticket["ticket"])["sessionToken"]

            corps = json.dumps(
                {
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "Bonjour"}],
                    "stream": True,
                }
            ).encode()
            scope = _scope(
                "/v1/chat/completions",
                methode="POST",
                entetes=[
                    ("content-type", "application/json"),
                    ("content-length", str(len(corps))),
                    ("origin", ICI),
                    ("cookie", f"{COOKIE_APPAREIL}={jeton}"),
                ],
            )
            debut, morceaux = asyncio.run(
                _appeler(
                    passerelle,
                    scope,
                    corps,
                    sur_morceau=lambda m: vus.append(m.decode()),
                )
            )
        finally:
            set_registry_for_tests(None)

        entetes = _entetes(debut)
        assert debut.get("status") == 200, (debut, b"".join(morceaux)[:300])
        assert entetes["content-type"].startswith("text/event-stream")
        assert "content-encoding" not in entetes, (
            "un flux du chat n'est jamais comprimé"
        )
        texte = ""
        for ligne in b"".join(morceaux).decode().splitlines():
            if ligne.startswith("data: {"):
                choix = json.loads(ligne[6:]).get("choices") or [{}]
                texte += (choix[0].get("delta") or {}).get("content") or ""
        assert texte == "".join(mots), "chaque mot du moteur arrive, dans l'ordre"

    def test_un_websocket_traverse_sans_etre_touche(self):
        """La voix et le chat en direct : la compression ne lit que http."""
        app = FastAPI()

        @app.websocket("/ws")
        async def ws(websocket: WebSocket):
            await websocket.accept()
            for mot in ("un", "deux", "trois"):
                await websocket.send_text(mot * 600)
            await websocket.close()

        app.add_middleware(CompressionDesReponses)
        with TestClient(app).websocket_connect(
            "/ws", headers={"Accept-Encoding": "br"}
        ) as canal:
            recus = [canal.receive_text() for _ in range(3)]
        assert recus == [m * 600 for m in ("un", "deux", "trois")]

    def test_une_grande_compression_ne_prend_pas_la_boucle(self, monkeypatch):
        """§5 : au-delà de 64 Ko, la compression se fait dans un fil — une
        milliseconde volée à la boucle retarde chaque mot du chat."""
        fils: list[str] = []
        origine = asyncio.to_thread

        async def espion(fonction, *args, **kwargs):
            fils.append(getattr(fonction, "__name__", "?"))
            return await origine(fonction, *args, **kwargs)

        monkeypatch.setattr(ca.asyncio, "to_thread", espion)
        app = FastAPI()

        @app.get("/v1/gros")
        def gros() -> JSONResponse:
            return JSONResponse({"x": ["Tâche à faire"] * 20000})

        debut, morceaux = asyncio.run(
            _appeler(CompressionDesReponses(app), _scope("/v1/gros"))
        )
        assert _entetes(debut)["content-encoding"] == "br"
        assert "_comprimer" in fils, "la compression de 300 Ko doit sortir de la boucle"
        assert (
            json.loads(brotli.decompress(b"".join(morceaux)))["x"][0] == "Tâche à faire"
        )
