"""§5/§100 : l'indexation attend la voix sans perdre ses vecteurs."""

import threading
import time
from types import SimpleNamespace

import requests

from diapason.connectors.embeddings import OllamaEmbedder
from diapason.engine import scheduling


def attendre(predicat):
    fin = time.monotonic() + 2
    while not predicat():
        assert time.monotonic() < fin, "la file n'a pas atteint l'état attendu"
        time.sleep(0.001)


class TestPrioriteVecteurs:
    """§100 : différer n'est ni abandonner ni choisir le modèle de dialogue."""

    def test_l_indexation_attend_la_fin_du_tour_et_garde_son_modele(self, monkeypatch):
        file = scheduling.InferenceScheduler(quiet_seconds=0)
        file.remember_model("modele-de-dialogue")
        monkeypatch.setattr(scheduling, "scheduler_for", lambda _: file)
        appels, vecteurs = [], []

        def post(url, *, json, timeout):
            appels.append(json)
            return SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: {"embedding": [0.2, 0.5]}
            )

        monkeypatch.setattr("diapason.connectors.embeddings.requests.post", post)

        def indexer():
            with scheduling.background_work(use_active_model=True):
                vecteurs.append(OllamaEmbedder().embed("fragment à conserver"))

        fil = threading.Thread(target=indexer, daemon=True)
        try:
            with scheduling.interactive_turn():
                fil.start()
                attendre(lambda: file._pending or appels)
                assert not appels, "aucun POST d'indexation pendant la conversation"
                # Une recherche utile à la réponse peut, elle, calculer son vecteur.
                assert OllamaEmbedder().embed("recherche de l'utilisateur") is not None
                assert len(appels) == 1, "le fond reste en attente"
        finally:
            fil.join(2)
        assert not fil.is_alive(), "l'indexation doit reprendre à la fermeture"
        assert vecteurs and vecteurs[0] is not None, "le vecteur différé est conservé"
        assert [a["model"] for a in appels] == ["nomic-embed-text"] * 2, (
            "le modèle de conversation ne doit jamais servir d'encodeur"
        )

    def test_un_echec_http_libere_la_place(self, monkeypatch):
        file = scheduling.InferenceScheduler(quiet_seconds=0)
        monkeypatch.setattr(scheduling, "scheduler_for", lambda _: file)

        def echouer(*_a, **_kw):
            raise requests.Timeout("test sans réseau")

        monkeypatch.setattr("diapason.connectors.embeddings.requests.post", echouer)
        with scheduling.background_work():
            assert OllamaEmbedder().embed("fragment") is None
        assert not file._background_active and not file._pending, (
            "l'échec d'indexation ne bloque pas la prochaine question"
        )

    def test_la_route_de_sync_classe_aussi_la_sonde_en_travail_de_fond(
        self, monkeypatch
    ):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from diapason.connectors import pipeline, store, sync_engine
        from diapason.core.registry import ConnectorRegistry
        from diapason.server import connectors_router as route

        entre, termine = threading.Event(), threading.Event()
        priorites = []
        monkeypatch.setattr(route, "_ensure_connectors_registered", lambda: None)
        monkeypatch.setattr(ConnectorRegistry, "contains", lambda _: True)
        monkeypatch.setitem(
            route._instances, "test", SimpleNamespace(is_connected=lambda: True)
        )
        monkeypatch.setattr(store, "KnowledgeStore", lambda: object())

        def sonde(self, texte):
            priorites.append(scheduling._background.get())
            entre.set()
            return b"vecteur"

        class Moteur:
            def __init__(self, **_kw):
                pass

            def get_checkpoint(self, _):
                return None

            def sync(self, _):
                priorites.append(scheduling._background.get())
                termine.set()

        monkeypatch.setattr(OllamaEmbedder, "embed", sonde)
        monkeypatch.setattr(pipeline, "IngestionPipeline", lambda **_kw: object())
        monkeypatch.setattr(sync_engine, "SyncEngine", Moteur)
        app = FastAPI()
        app.include_router(route.create_connectors_router())
        with TestClient(app) as client:
            assert client.post("/v1/connectors/test/sync").status_code == 200
            assert entre.wait(2) and termine.wait(2), "le fil de synchronisation finit"
        assert len(priorites) == 2 and all(p is not None for p in priorites), (
            "la sonde et le pipeline doivent attendre la conversation"
        )
