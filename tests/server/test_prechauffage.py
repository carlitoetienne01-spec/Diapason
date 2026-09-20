"""§5 : le préfixe du chat reste chaud entre deux questions, sans passer devant."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from diapason.core.config import DiapasonConfig
from diapason.core.types import Message, Role
from diapason.engine.scheduling import InferenceQueueTimeout
from diapason.server import prechauffage
from diapason.server.questions_chat import POSER_QUESTIONS
from diapason.server.trousse_chat import CHARGER_OUTILS
from diapason.tools._stubs import BaseTool, ToolSpec


class Outil(BaseTool):
    def __init__(self, nom):
        self.nom = nom

    @property
    def spec(self):
        return ToolSpec(
            name=self.nom,
            description="Un outil personnel.",
            parameters={"type": "object", "properties": {}},
        )

    def execute(self, **params):
        raise AssertionError("le préchauffage n'exécute jamais un outil")


class MoteurLocal:
    engine_id = "ollama"
    _host = "http://127.0.0.1:11434"

    def __init__(self, erreur=None):
        self.appels = []
        self.erreur = erreur

    def generate(self, messages, *, model, **kwargs):
        if self.erreur is not None:
            raise self.erreur
        self.appels.append((model, list(messages), kwargs))
        return {"content": ""}


def config(leger="", defaut="qwen3.5:9b"):
    cfg = DiapasonConfig()
    cfg.intelligence.default_model = defaut
    cfg.intelligence.light_model = leger
    return cfg


def etat(moteur, cfg, outils):
    return SimpleNamespace(
        engine=moteur,
        model=cfg.intelligence.default_model,
        config=cfg,
        _chat_tooling_cache=(outils, None),
    )


@pytest.fixture(autouse=True)
def identite_stable(monkeypatch):
    monkeypatch.setattr(
        "diapason.prompt.builder.SystemPromptBuilder.build", lambda _: "Identité"
    )
    monkeypatch.setattr("diapason.server.routes._now_anchor", lambda: "Horloge")


class TestLesModelesAChauffer:
    def test_le_defaut_et_le_leger_une_fois_chacun(self):
        assert prechauffage.modeles_a_chauffer(config("qwen3.5:4b"), "qwen3.5:9b") == [
            "qwen3.5:9b",
            "qwen3.5:4b",
        ]
        assert prechauffage.modeles_a_chauffer(config("qwen3.5:9b"), "qwen3.5:9b") == [
            "qwen3.5:9b"
        ], "le même modèle n'est pas chauffé deux fois"

    def test_ni_default_ni_vide_ni_distant(self, monkeypatch):
        monkeypatch.setattr(
            "diapason.server.cloud_router.is_cloud_model",
            lambda m: m.startswith("gemini"),
        )
        assert prechauffage.modeles_a_chauffer(config("gemini-2.5"), "default") == []
        assert prechauffage.modeles_a_chauffer(None, "") == []


class TestLePromptDuPrefixe:
    def test_meme_identite_meme_trousse_que_le_bureau(self):
        cfg = config()
        outils = [Outil("succes_tasks"), Outil("web_search")]
        messages, specs = prechauffage.prompt_du_prefixe(
            etat(MoteurLocal(), cfg, outils), cfg
        )
        assert messages[0].role == Role.SYSTEM and messages[0].content == "Identité", (
            "l'identité ouvre le prompt, comme pour un vrai tour"
        )
        assert messages[-1] == Message(role=Role.USER, content="Bonjour")
        noms = [s["function"]["name"] for s in specs]
        assert noms == ["succes_tasks", "web_search", POSER_QUESTIONS], (
            "tous les schémas, puis celui des questions interactives : la trousse "
            "du bureau, dans son ordre, sans catalogue"
        )
        assert CHARGER_OUTILS not in noms

    def test_sans_trousse_le_prompt_tient_quand_meme(self):
        cfg = config()
        etat_sans = SimpleNamespace(engine=MoteurLocal(), model="m", config=cfg)
        etat_sans._chat_tooling_cache = None
        messages, specs = prechauffage.prompt_du_prefixe(etat_sans, cfg)
        assert messages[-1].content == "Bonjour"
        assert [s["function"]["name"] for s in specs] == [POSER_QUESTIONS]


class TestPrechauffer:
    def test_rejoue_le_prefixe_avec_un_seul_jeton(self):
        cfg = config("qwen3.5:4b")
        moteur = MoteurLocal()
        chauffes = prechauffage.prechauffer(
            etat(moteur, cfg, [Outil("succes_tasks")]), cfg
        )
        assert [m for m, _ in chauffes] == ["qwen3.5:9b", "qwen3.5:4b"]
        assert all(duree >= 0 for _, duree in chauffes)
        for modele, messages, kwargs in moteur.appels:
            assert kwargs["max_tokens"] == 1, "chauffer, pas répondre"
            assert kwargs["temperature"] == 0.0
            assert [s["function"]["name"] for s in kwargs["tools"]] == [
                "succes_tasks",
                POSER_QUESTIONS,
            ]
            assert messages[-1].content == "Bonjour"

    def test_un_moteur_occupe_est_laisse_tranquille(self):
        cfg = config()
        moteur = MoteurLocal(erreur=InferenceQueueTimeout("occupé"))
        assert prechauffage.prechauffer(etat(moteur, cfg, []), cfg) == []

    def test_un_moteur_distant_ou_etranger_n_est_pas_chauffe(self):
        cfg = config()
        distant = MoteurLocal()
        distant._host = "http://serveur-gpu.lan:11434"
        assert prechauffage.prechauffer(etat(distant, cfg, []), cfg) == []
        etranger = MoteurLocal()
        etranger.engine_id = "vllm"
        assert prechauffage.prechauffer(etat(etranger, cfg, []), cfg) == []

    def test_passe_par_l_admission_de_fond(self, monkeypatch):
        """Le préchauffage attend qu'un tour interactif finisse, jamais l'inverse."""
        vus = []
        from diapason.engine import scheduling

        class Moteur(MoteurLocal):
            def generate(self, messages, *, model, **kwargs):
                travail = scheduling._background.get()
                vus.append(travail is not None and not travail.use_active_model)
                return super().generate(messages, model=model, **kwargs)

        cfg = config()
        prechauffage.prechauffer(etat(Moteur(), cfg, []), cfg)
        assert vus == [True], "un ticket de fond, sur le modèle demandé"

    def test_le_moteur_enveloppe_est_deballe(self):
        cfg = config()
        interne = MoteurLocal()
        enveloppe = SimpleNamespace(engine_id="instrumented", _inner=interne)
        e = etat(enveloppe, cfg, [])
        assert [m for m, _ in prechauffage.prechauffer(e, cfg)] == ["qwen3.5:9b"]
        assert len(interne.appels) == 1

    def test_le_multi_moteur_ne_cache_plus_ollama(self):
        """20/09/2026 : sur ce Mac un moteur cloud fait naître un MultiEngine ;
        l'ancien déballage s'arrêtait sur « multi » et aucun /api/generate n'a
        jamais atteint Ollama au démarrage."""
        interne = MoteurLocal()
        # GuardrailsEngine relaie engine_id : il dit « ollama » sans hôte.
        garde = SimpleNamespace(engine_id="ollama", _engine=interne)
        instrumente = SimpleNamespace(engine_id="instrumented", _inner=garde)
        cloud = SimpleNamespace(engine_id="cloud", _host="https://api.example")
        multi = SimpleNamespace(
            engine_id="multi", _engines=[("cloud", cloud), ("ollama", instrumente)]
        )
        assert prechauffage.moteur_local(SimpleNamespace(engine=multi)) is interne
        assert prechauffage.moteur_local(SimpleNamespace(engine=cloud)) is None
        boucle = SimpleNamespace(engine_id="x")
        boucle._inner = boucle
        assert prechauffage.moteur_local(SimpleNamespace(engine=boucle)) is None, (
            "une enveloppe qui se contient ne fait pas boucler le déballage"
        )


class TestLaTacheDeFond:
    @pytest.mark.asyncio
    async def test_rejoue_a_intervalle_et_s_arrete_proprement(self, monkeypatch):
        monkeypatch.setattr(prechauffage, "PREMIER_DELAI_S", 0.0)
        tours = []
        pret = threading.Event()

        def faux_prechauffer(app_state, cfg):
            tours.append(1)
            if len(tours) >= 2:
                pret.set()
            return [("m", 0.3)]

        monkeypatch.setattr(prechauffage, "prechauffer", faux_prechauffer)
        app = SimpleNamespace(state=SimpleNamespace(config=None))
        tache = asyncio.create_task(
            prechauffage.entretenir_le_prefixe(app, intervalle_s=0.01)
        )
        await asyncio.to_thread(pret.wait, 5.0)
        tache.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tache
        assert len(tours) >= 2, "au démarrage puis à chaque intervalle"

    @pytest.mark.asyncio
    async def test_un_rate_ne_tue_pas_la_boucle(self, monkeypatch):
        monkeypatch.setattr(prechauffage, "PREMIER_DELAI_S", 0.0)
        tours = []
        pret = threading.Event()

        def faux_prechauffer(app_state, cfg):
            tours.append(1)
            if len(tours) == 1:
                raise RuntimeError("Ollama absent")
            pret.set()
            return []

        monkeypatch.setattr(prechauffage, "prechauffer", faux_prechauffer)
        app = SimpleNamespace(state=SimpleNamespace(config=None))
        tache = asyncio.create_task(
            prechauffage.entretenir_le_prefixe(app, intervalle_s=0.01)
        )
        await asyncio.to_thread(pret.wait, 5.0)
        tache.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tache
        assert len(tours) >= 2
