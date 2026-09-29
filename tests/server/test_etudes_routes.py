"""§5/§100 : le transport ne dévoile pas le corrigé et ne simule pas une note."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.engine._stubs import StreamChunk
from diapason.etudes.magasin import MagasinEtudes
from diapason.server.conversations_routes import create_conversations_router
from diapason.server.conversations_store import ConversationsStore
from diapason.server.etudes_routes import router
from tests.server.test_etudes import demande, programme


def programme_genere():
    p = programme().model_dump(by_alias=True)
    questions = p.pop("questions")
    p["choiceQuestions"], p["openQuestions"] = [], []
    for q in questions:
        q.pop("id")
        if q.pop("kind") == "choice":
            q["answer"] = q["choices"].index(q["answer"])
            q.pop("criteria")
            p["choiceQuestions"].append(q)
        else:
            q.pop("choices")
            p["openQuestions"].append(q)
        q.pop("sourceIndex")
        q["quote"] = "S0P0"
    return p


def contenu_genere(options):
    champs = options["format"]["properties"]
    return {k: v for k, v in programme_genere().items() if k in champs}


class Moteur:
    engine_id = "ollama"
    is_cloud = False

    def __init__(self):
        self.appels = []
        self.invalide = False

    async def stream_full(self, messages, **kwargs):
        self.appels.append((messages, kwargs))
        contenu = (
            contenu_genere(kwargs)
            if "criteriaMet" not in kwargs["format"]["properties"]
            else {"criteriaMet": [True, False], "feedback": "Il manque l'unité."}
        )
        yield StreamChunk(content="{}" if self.invalide else json.dumps(contenu))
        yield StreamChunk(finish_reason="stop")


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.state.engine = Moteur()
    app.state.etudes_store = MagasinEtudes(tmp_path / "etudes.db")
    app.include_router(router)
    with TestClient(app) as c:
        yield c


def creer(client, mode="exam"):
    r = client.post(
        "/v1/study/sessions", json=demande(mode=mode).model_dump(by_alias=True)
    )
    assert r.status_code == 200, r.text
    return r.json()


def action(client, s, type, **donnees):
    return client.post(
        f"/v1/study/sessions/{s['id']}/actions",
        json={"version": s["version"], "action": type, **donnees},
    )


class TestLeParcoursComplet:
    def test_le_delai_de_creation_ne_pretend_pas_avoir_sauve_des_reponses(self, client):
        """§100 : avant l'épreuve, aucune réponse n'a encore été donnée."""

        class MoteurLent(Moteur):
            async def stream_full(self, messages, **kwargs):
                raise TimeoutError
                yield  # Le transport reste un générateur asynchrone.

        client.app.state.engine = MoteurLent()
        r = client.post("/v1/study/sessions", json=demande().model_dump(by_alias=True))
        assert r.status_code == 504, "la préparation inachevée reste un échec"
        assert "réponses" not in r.json()["detail"], (
            "une création ne doit pas annoncer des réponses sauvegardées"
        )
        assert client.app.state.etudes_store.lister("fil-test") == [], (
            "aucun cours partiel n'est publié"
        )

    def test_le_delai_de_correction_preserve_les_reponses(self, client):
        """§100 : un échec du modèle ne doit ni noter ni effacer l'étudiant."""
        s = action(client, creer(client), "start").json()
        s = action(client, s, "answer", questionId="q2", text="Une unité").json()

        class MoteurLent(Moteur):
            async def stream_full(self, messages, **kwargs):
                raise TimeoutError
                yield

        client.app.state.engine = MoteurLent()
        r = action(client, s, "finish")
        assert r.status_code == 504 and "correction" in r.json()["detail"], (
            "l'erreur doit nommer l'opération réellement interrompue"
        )
        relu = client.get(f"/v1/study/sessions/{s['id']}").json()
        assert relu["responses"]["q2"]["text"] == "Une unité" and not relu["grades"], (
            "la réponse exacte est conservée sans inventer une note"
        )

    def test_supprimer_la_discussion_retire_ses_documents_et_reponses(
        self, client, tmp_path
    ):
        conversations = ConversationsStore(tmp_path / "conversations.db")
        client.app.include_router(
            create_conversations_router(
                conversations,
                sur_suppression=client.app.state.etudes_store.supprimer_conversation,
            )
        )
        try:
            s = creer(client)
            assert client.delete("/v1/conversations/fil-test").status_code == 200
            assert client.get(f"/v1/study/sessions/{s['id']}").status_code == 404
        finally:
            conversations.close()

    def test_la_reference_restitue_le_vrai_passage_du_bon_document(self, client):
        class MoteurReferences(Moteur):
            async def stream_full(self, messages, **kwargs):
                if "lesson" in kwargs["format"]["properties"]:
                    yield StreamChunk(content=json.dumps(contenu_genere(kwargs)))
                    yield StreamChunk(finish_reason="stop")
                    return
                entrees = json.loads(messages[1].content)
                assert entrees["sources"][1]["passages"][0]["reference"] == "S1P0"
                assert kwargs["format"]["$defs"]["QcmPreparation"]["properties"][
                    "quote"
                ]["enum"] == ["S0P0", "S1P0"]
                brut = contenu_genere(kwargs)
                for q in [*brut["choiceQuestions"], *brut["openQuestions"]]:
                    q["quote"] = "S1P0"
                yield StreamChunk(content=json.dumps(brut))
                yield StreamChunk(finish_reason="stop")

        client.app.state.engine = MoteurReferences()
        d = demande(
            sources=[
                {"name": "premier.txt", "text": "Un autre document."},
                {
                    "name": "vrai.txt",
                    "text": "Deux moitiés — exactement — font une unité.",
                },
            ]
        )
        r = client.post("/v1/study/sessions", json=d.model_dump(by_alias=True))
        assert r.status_code == 200, r.text
        prive = client.app.state.etudes_store.lire(r.json()["id"])
        for q in prive["program"]["questions"]:
            assert q["sourceIndex"] == 1, "le repère détermine le document réel"
            assert q["quote"] == d.sources[1].texte, (
                "la ponctuation originale est conservée"
            )

    def test_deux_preparations_invalides_ne_publient_aucune_epreuve(self, client):
        client.app.state.engine.invalide = True
        r = client.post("/v1/study/sessions", json=demande().model_dump(by_alias=True))
        assert r.status_code == 422, "un JSON incomplet ne devient pas un cours"
        assert len(client.app.state.engine.appels) == 2, "pas de boucle infinie"
        assert (
            client.get(
                "/v1/study/sessions", params={"conversationId": "fil-test"}
            ).json()["sessions"]
            == []
        )

    def test_un_parcours_limite_aux_qcm_est_refuse(self, client):
        """§5 : le cours promet aussi d'expliquer, pas seulement de choisir."""

        class MoteurQcm(Moteur):
            async def stream_full(self, messages, **kwargs):
                brut = contenu_genere(kwargs)
                if "openQuestions" in brut:
                    brut["openQuestions"] = []
                yield StreamChunk(content=json.dumps(brut))
                yield StreamChunk(finish_reason="stop")

        client.app.state.engine = MoteurQcm()
        r = client.post("/v1/study/sessions", json=demande().model_dump(by_alias=True))
        assert r.status_code == 422, "la liste ouverte vide est invalide"
        assert client.app.state.etudes_store.lister("fil-test") == [], (
            "aucun parcours contraire au contrat n'est publié"
        )

    def test_un_flux_interrompu_ne_devient_pas_un_examen(self, client):
        class MoteurInterrompu(Moteur):
            async def stream_full(self, messages, **kwargs):
                yield StreamChunk(content=json.dumps(contenu_genere(kwargs)))
                yield StreamChunk(finish_reason="length")

        client.app.state.engine = MoteurInterrompu()
        r = client.post("/v1/study/sessions", json=demande().model_dump(by_alias=True))
        assert r.status_code == 422 and "incomplète" in r.json()["detail"]

    def test_un_corrige_incoherent_est_repare_avant_publication(self, client):
        class MoteurAReparer(Moteur):
            async def stream_full(self, messages, **kwargs):
                self.appels.append((messages, kwargs))
                brut = contenu_genere(kwargs)
                if len(self.appels) == 2:
                    brut["choiceQuestions"][0]["answer"] = 4
                yield StreamChunk(content=json.dumps(brut))
                yield StreamChunk(finish_reason="stop")

        client.app.state.engine = MoteurAReparer()
        s = creer(client)
        assert s["state"] == "ready", "seul le programme réparé est publié"
        assert len(client.app.state.engine.appels) == 3, (
            "le cours n'est pas réécrit pour réparer les questions"
        )

    def test_examen_repris_et_corrige_sans_fuite(self, client):
        s = creer(client)
        assert "answer" not in json.dumps(s) and "Choisir 1/2" not in json.dumps(s)
        s = action(client, s, "start").json()
        s = action(client, s, "answer", questionId="q1", text="1/2").json()
        s = action(
            client, s, "answer", questionId="q2", text="Deux parts égales"
        ).json()
        assert s["lesson"] == "" and s["grades"] == {}
        assert action(client, s, "check", questionId="q1").status_code == 422
        r = action(client, s, "finish")
        assert r.status_code == 200, r.text
        fini = r.json()
        assert fini["state"] == "finished"
        assert fini["grades"]["q1"]["score"] == 1
        assert fini["grades"]["q2"]["score"] == 1
        assert fini["questions"][0]["answer"] == "1/2"
        assert len(client.app.state.engine.appels) == 3, (
            "cours, questions et une correction ouverte seulement"
        )
        assert action(client, fini, "finish").json() == fini, "fin idempotente"
        relu = client.get(
            "/v1/study/sessions", params={"conversationId": "fil-test"}
        ).json()
        assert relu["sessions"][0] == fini
        client.delete(f"/v1/study/sessions/{fini['id']}")
        assert client.get(f"/v1/study/sessions/{fini['id']}").status_code == 404

    def test_correction_immediate_et_reponse_verrouillee(self, client):
        s = action(client, creer(client, "practice"), "start").json()
        s = action(client, s, "answer", questionId="q1", text="1/3").json()
        s = action(client, s, "check", questionId="q1").json()
        assert s["grades"]["q1"]["score"] == 0
        assert "answer" in s["questions"][0] and "answer" not in s["questions"][1]
        assert (
            action(client, s, "answer", questionId="q1", text="1/2").status_code == 422
        )

    def test_aucune_note_en_cas_de_reponse_invalide_du_modele(self, client):
        s = action(client, creer(client), "start").json()
        s = action(client, s, "answer", questionId="q2", text="Une unité").json()
        client.app.state.engine.invalide = True
        assert action(client, s, "finish").status_code == 422
        relu = client.get(f"/v1/study/sessions/{s['id']}").json()
        assert relu["state"] == "active" and relu["grades"] == {}
        assert relu["responses"]["q2"]["text"] == "Une unité"

    def test_pas_de_transmission_a_un_modele_cloud(self, client):
        client.app.state.engine.is_cloud = True
        r = client.post("/v1/study/sessions", json=demande().model_dump(by_alias=True))
        assert r.status_code == 422
        assert client.app.state.engine.appels == [], "les documents restent locaux"
