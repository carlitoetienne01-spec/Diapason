"""§5/§100 : la trousse adaptative du 19 septembre, toujours disponible sur demande.

Les classes ci-dessous instancient TrousseChat(adaptative=True) ; la trousse
stable par défaut (20 septembre 2026) est testée dans TestLaTrousseStable.
"""

import asyncio
import copy
import json
from unittest.mock import MagicMock

import pytest

from diapason.core.config import DiapasonConfig
from diapason.core.types import Message, Role, ToolCall, ToolResult
from diapason.engine._stubs import StreamChunk
from diapason.server.agentic_stream import stream_with_tools
from diapason.server.trousse_chat import CHARGER_OUTILS, MAX_CHARGEMENTS, TrousseChat
from diapason.tools._stubs import BaseTool, ToolExecutor, ToolSpec


class Outil(BaseTool):
    def __init__(self, nom, *, protege=False, grand=True):
        self.nom = nom
        self.protege = protege
        self.grand = grand
        self.executions = []

    @property
    def spec(self):
        return ToolSpec(
            name=self.nom,
            description="Un outil personnel. Ne pas inventer son résultat.",
            parameters={
                "type": "object",
                "properties": {
                    **{
                        f"parametre_{i}": {
                            "type": "string",
                            "description": "Description détaillée du paramètre.",
                        }
                        for i in range(40 if self.grand else 0)
                    },
                    "value": {"type": "string", "enum": ["a", "b"]},
                },
                "additionalProperties": False,
            },
            requires_confirmation=self.protege,
        )

    def execute(self, **params):
        self.executions.append(params)
        return ToolResult(tool_name=self.nom, content="lu réellement", success=True)


def outils():
    return [
        Outil(n)
        for n in (
            "succes_tasks",
            "succes_workspace",
            "current_time",
            "digest_collect",
            "outil_prive",
        )
    ]


def messages(question="Explique la croissance des arbres."):
    return [Message(role=Role.USER, content=question)]


def noms(specs):
    return [s["function"]["name"] for s in specs]


class Moteur:
    def __init__(self, tours):
        self.tours = tours
        self.appels = []
        self.ferme = False

    async def stream_full(self, msgs, **kwargs):
        self.appels.append((list(msgs), kwargs))
        try:
            for chunk in self.tours[min(len(self.appels) - 1, len(self.tours) - 1)]:
                yield chunk
        finally:
            self.ferme = True


def appel(nom, arguments=None, ident="appel", index=0):
    return {
        "index": index,
        "id": ident,
        "type": "function",
        "function": {
            "name": nom,
            "arguments": json.dumps(arguments or {}),
        },
    }


async def collecter(moteur, liste, **kwargs):
    dialogue = kwargs.pop("messages", None) or messages()
    executeur = kwargs.pop("executor", None) or ToolExecutor(
        liste, autoload_capability_policy=False
    )
    kwargs.setdefault("trousse_adaptative", True)
    return [
        e
        async for e in stream_with_tools(
            moteur, "local", dialogue, tools=liste, executor=executeur, **kwargs
        )
    ]


class TestLaTrousseStable:
    """20/09/2026 : la trousse qui change invalide le préfixe calculé par Ollama."""

    @pytest.mark.parametrize(
        "question",
        [
            "Quelles sont mes tâches aujourd’hui ?",
            "Quelle est la capitale du Pérou ?",
            'Que veut dire "Self Aware" en français ?',
            "Prepare moi un programme pour la programmation",
        ],
    )
    def test_par_defaut_les_memes_schemas_quelle_que_soit_la_demande(self, question):
        liste = outils_du_bureau()
        trousse = TrousseChat(liste, messages(question))
        assert noms(trousse.specs) == [o.nom for o in liste], (
            "reconnue, inconnue ou autonome : la même trousse, dans le même ordre"
        )
        assert not trousse.verifier_lecture(messages(question)), (
            "avec tous les schémas, rien à relire"
        )
        assert not trousse.est_chargement(CHARGER_OUTILS)

    @pytest.mark.asyncio
    async def test_les_tours_d_une_conversation_envoient_la_meme_trousse(self):
        # Banc réel du 20/09 : tâches → Pérou → notes → Chili → retard, quatre
        # préremplissages à froid sur cinq (9,1 / 24,4 / 8,4 / 9,0 s).
        liste = outils_du_bureau()
        moteur = Moteur([[StreamChunk(content="Oui.", finish_reason="stop")]])
        fil: list[Message] = []
        for question in (
            "Quelles sont mes tâches aujourd’hui ?",
            "Quelle est la capitale du Pérou ?",
            "Et mes notes ?",
            "Quelle est la capitale du Chili ?",
        ):
            fil.append(Message(role=Role.USER, content=question))
            await collecter(moteur, liste, messages=list(fil), trousse_adaptative=False)
            fil.append(Message(role=Role.ASSISTANT, content="Oui."))
        trousses = [json.dumps(k.get("tools")) for _, k in moteur.appels]
        assert len(trousses) == 4, "un seul passage par tour, aucune relecture"
        assert len(set(trousses)) == 1, (
            "la même trousse, octet pour octet, à chaque tour"
        )

    def test_l_ancienne_trousse_reste_disponible_sur_demande(self):
        trousse = TrousseChat(outils(), messages(), adaptative=True)
        assert noms(trousse.specs) == [CHARGER_OUTILS]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("app_config", [None, DiapasonConfig()])
    async def test_la_route_du_bureau_envoie_toute_la_trousse_par_defaut(
        self, monkeypatch, app_config
    ):
        """Revue du 20/09 : seul le mode adaptatif était prouvé de bout en bout."""
        from diapason.server.models import ChatCompletionRequest
        from diapason.server.routes import _handle_stream

        moteur = Moteur([[StreamChunk(content="Oui.", finish_reason="stop")]])
        monkeypatch.setattr(
            "diapason.server.routes._ensure_identity_prompt",
            lambda messages, *args, **kwargs: messages,
        )
        liste = outils()
        requete = ChatCompletionRequest(
            model="test",
            stream=True,
            messages=[
                {
                    "role": "user",
                    "content": "Prepare moi un programme pour la programmation",
                }
            ],
        )
        response = await _handle_stream(
            moteur, "test", requete, tooling=(liste, MagicMock()), app_config=app_config
        )
        "".join([part async for part in response.body_iterator])
        assert noms(moteur.appels[0][1]["tools"]) == [o.nom for o in liste], (
            "sans réglage, la route envoie tous les schémas, sans catalogue"
        )
        assert len(moteur.appels) == 1


class TestCatalogue:
    @pytest.mark.parametrize(
        "demande",
        [
            "Prepare moi un programme pour la programmation",
            "Prépare-moi un programme pour apprendre l’anglais.",
            "Peux-tu créer un plan pour apprendre Python ?",
        ],
    )
    def test_concevoir_un_programme_ne_charge_pas_tous_les_parametres(self, demande):
        trousse = TrousseChat(outils(), messages(demande), adaptative=True)
        assert noms(trousse.specs) == [CHARGER_OUTILS], (
            "le cadrage garde l'accès aux outils sans noyer le modèle dans 44 schémas"
        )
        assert not trousse.verifier_lecture(messages(demande))

    @pytest.mark.parametrize(
        "demande",
        [
            "Prépare le programme de ce projet.",
            "Prépare un plan à partir des tâches.",
            "Prépare un programme à partir de mon dossier.",
        ],
    )
    def test_un_programme_fonde_sur_des_donnees_conserve_le_filet_de_lecture(
        self, demande
    ):
        trousse = TrousseChat(outils(), messages(demande), adaptative=True)
        assert trousse.verifier_lecture(messages(demande)) or noms(trousse.specs) == [
            o.nom for o in outils()
        ], "concevoir ne dispense pas de lire les données"

    def test_une_explication_n_envoie_que_le_catalogue(self):
        liste = outils()
        original = [o.to_openai_function() for o in liste]
        sauvegarde = copy.deepcopy(original)
        trousse = TrousseChat(liste, messages(), adaptative=True)
        assert noms(trousse.specs) == [CHARGER_OUTILS], (
            "aucune exclusion de capacité : les noms restent au catalogue"
        )
        description = trousse.specs[0]["function"]["description"]
        assert all(n in description for n in noms(original))
        assert len(json.dumps(trousse.specs)) < len(json.dumps(original)) / 2
        assert original == sauvegarde, "aucun changement des schémas de validation"

    @pytest.mark.parametrize(
        "question,attendus",
        [
            ("Quelles sont mes tâches aujourd’hui ?", {"succes_tasks", "current_time"}),
            ("Mes notes de projets", {"succes_workspace"}),
            ("What are my tasks?", {"succes_tasks"}),
        ],
    )
    def test_precharge_sans_supprimer_le_catalogue(self, question, attendus):
        trousse = TrousseChat(outils(), messages(question), adaptative=True)
        assert attendus <= set(noms(trousse.specs))
        assert CHARGER_OUTILS in noms(trousse.specs)

    def test_suivi_court_et_historique_outille(self):
        historique = messages("Quelles sont mes tâches ?") + [
            Message(role=Role.USER, content="Et demain ?")
        ]
        assert "succes_tasks" in noms(
            TrousseChat(outils(), historique, adaptative=True).specs
        )
        historique = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="precedent", name="outil_prive", arguments="{}")
                ],
            ),
            *messages("Continue"),
        ]
        assert "outil_prive" in noms(
            TrousseChat(outils(), historique, adaptative=True).specs
        )

    def test_les_schemas_charges_sont_exacts_et_independants_des_autres_fenetres(self):
        liste = outils()
        a, b = (
            TrousseChat(liste, messages(), adaptative=True),
            TrousseChat(liste, messages(), adaptative=True),
        )
        reponse = json.loads(
            a.charger(json.dumps({"toolNames": ["outil_prive", "shell_exec"]}))
        )
        assert reponse["unavailable"] == ["shell_exec"]
        assert "outil_prive" in noms(a.specs) and "outil_prive" not in noms(b.specs)
        original = next(o.to_openai_function() for o in liste if o.nom == "outil_prive")
        assert (
            next(s for s in a.specs if s["function"]["name"] == "outil_prive")
            == original
        )
        assert "shell_exec" not in noms(a.specs), (
            "charger ne peut pas élargir la trousse"
        )
        assert all(not o.executions for o in liste), (
            "la découverte ne lit ni ne modifie les données"
        )

    @pytest.mark.parametrize(
        "arguments", ["{", "[]", "{}", '{"toolNames":[]}', '{"toolNames":[1]}']
    )
    def test_une_decouverte_mal_formee_revient_aux_schemas_complets(self, arguments):
        liste = outils()
        t = TrousseChat(liste, messages(), adaptative=True)
        assert "error" in json.loads(t.charger(arguments))
        assert noms(t.specs) == [o.nom for o in liste], (
            "repli complet sans outil supplémentaire"
        )

    def test_deux_decouvertes_suffisent_et_la_petite_trousse_est_inchangee(self):
        liste = outils()
        t = TrousseChat(liste, messages(), adaptative=True)
        for _ in range(MAX_CHARGEMENTS):
            t.charger('{"toolNames":["outil_prive"]}')
        assert noms(t.specs) == [o.nom for o in liste]
        petit = [Outil("personnel", grand=False)]
        assert TrousseChat(petit, messages(), adaptative=True).specs == [
            petit[0].to_openai_function()
        ]

    def test_le_nom_reserve_ne_detourne_pas_un_outil_configure(self):
        liste = [*outils(), Outil(CHARGER_OUTILS)]
        t = TrousseChat(liste, messages(), adaptative=True)
        assert not t.est_chargement(CHARGER_OUTILS)
        assert noms(t.specs) == [o.nom for o in liste]

    @pytest.mark.parametrize(
        "question",
        [
            "J’ai reçu quoi ?",
            "Et ça ?",
            "Tu peux faire le nécessaire ?",
            "Explique ce qui a changé dans mon dossier.",
            "Explique cette URL https://example.test",
        ],
    )
    def test_une_demande_inconnue_ou_dependante_garde_la_trousse(self, question):
        liste = outils()
        assert TrousseChat(liste, messages(question), adaptative=True).specs == [
            o.to_openai_function() for o in liste
        ], "l'optimisation ne doit pas faire croire que les données ont été lues"


def apres_youtube(question):
    """Le vrai fil du 20 septembre 2026, avec un web_search plus haut."""
    return [
        Message(role=Role.USER, content="Qui est le président actuel d’Haïti ?"),
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[ToolCall(id="recherche", name="web_search", arguments="{}")],
        ),
        Message(role=Role.TOOL, content="…", tool_call_id="recherche"),
        Message(role=Role.ASSISTANT, content="Un conseil de transition."),
        Message(
            role=Role.USER, content="Ouvre moi Youtube et joue la musique Self Away"
        ),
        Message(role=Role.ASSISTANT, content="Ouvert."),
        Message(role=Role.USER, content=question),
    ]


def outils_du_bureau():
    return [
        Outil(n)
        for n in (
            "succes_tasks",
            "current_time",
            "web_search",
            "open_anything",
            "browser_tabs",
            "spotify_play",
            "media_control",
            "volume_control",
        )
    ]


class TestLaRelectureNeViseQueLesDonnees:
    """§5 : retenir une réponse n'a de sens que si elle affirme des données non lues.

    20/09/2026 : une traduction a coûté deux passages du 27b (53 s + 36 s) et
    88 s sans un mot à l'écran, parce que le tour précédent parlait de musique.
    """

    def test_une_traduction_apres_youtube_n_est_pas_relue(self):
        fil = apres_youtube('Que veut dire "Self Aware" en français ?')
        trousse = TrousseChat(outils_du_bureau(), fil, adaptative=True)
        assert noms(trousse.specs) == [CHARGER_OUTILS], (
            "une traduction est une réponse autonome : le catalogue seul"
        )
        assert not trousse.verifier_lecture(fil), (
            "aucune donnée personnelle en jeu : la réponse s'affiche tout de suite"
        )

    def test_une_question_de_culture_generale_garde_tous_les_schemas(self):
        # « Qui est le président actuel d'Haïti ? » n'est ni reconnue ni
        # autonome (« actuel ») : tous les schémas, et un seul passage.
        fil = apres_youtube("Qui est le premier ministre actuel d'Haïti ?")
        trousse = TrousseChat(outils_du_bureau(), fil, adaptative=True)
        assert noms(trousse.specs) == [o.nom for o in outils_du_bureau()]
        assert not trousse.verifier_lecture(fil)

    @pytest.mark.parametrize(
        "question",
        [
            "Montre mes tâches de demain",
            "Cherche sur le web le président d’Haïti",
            "Quels onglets sont ouverts ?",
        ],
    )
    def test_une_demande_de_donnees_garde_le_filet(self, question):
        fil = apres_youtube(question)
        trousse = TrousseChat(outils_du_bureau(), fil, adaptative=True)
        assert trousse.verifier_lecture(fil) or noms(trousse.specs) == [
            o.nom for o in outils_du_bureau()
        ], "une lecture attendue est relue, ou reçoit d'emblée tous les schémas"

    def test_un_suivi_court_herite_du_sujet_lu(self):
        lecture = [
            Message(role=Role.USER, content="Quelles sont mes tâches ?"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="t", name="succes_tasks", arguments="{}")],
            ),
            Message(role=Role.TOOL, content="…", tool_call_id="t"),
            Message(role=Role.ASSISTANT, content="Deux tâches."),
        ]
        suite = [*lecture, Message(role=Role.USER, content="Et demain ?")]
        assert TrousseChat(outils_du_bureau(), suite, adaptative=True).verifier_lecture(
            suite
        )
        merci = [*lecture, Message(role=Role.USER, content="Merci !")]
        assert not TrousseChat(
            outils_du_bureau(), merci, adaptative=True
        ).verifier_lecture(merci), "un remerciement n'affirme rien sur les données"

    @pytest.mark.parametrize(
        "question",
        [
            "Envoie-moi une blague",
            "Peux-tu m'ouvrir les yeux sur la philosophie ?",
            "Lance-moi un défi",
        ],
    )
    def test_une_action_amorcee_ne_fait_pas_une_demande_de_donnees(self, question):
        # Revue du 20/09/2026 : « envoie » amorçait mesh_devices, « ouvre »
        # browser_tabs, tous deux « lecteurs » — une blague était relue.
        fil = apres_youtube(question)
        trousse = TrousseChat(outils_du_bureau(), fil, adaptative=True)
        assert not trousse.verifier_lecture(fil)

    @pytest.mark.parametrize(
        "question",
        ["Qu'est-ce que j'ai reçu aujourd'hui ?", "Rien de neuf aujourd'hui ?"],
    )
    def test_un_mot_de_temps_seul_garde_les_schemas_complets(self, question):
        # Revue du 20/09/2026 : « aujourd'hui » réduisait la trousse à l'horloge
        # et « Tu n'as rien reçu, j'ai tout vérifié » partait sans lecture.
        liste = [*outils_du_bureau(), Outil("digest_collect")]
        trousse = TrousseChat(liste, messages(question), adaptative=True)
        assert noms(trousse.specs) == [o.nom for o in liste], (
            "une demande inconnue garde tous les schémas, l'horloge n'est pas un sujet"
        )

    @pytest.mark.parametrize(
        "suivi", ["Merci, c'est toi qui gères !", "Bof, plus ou moins", "Parfait."]
    )
    def test_un_commentaire_apres_une_lecture_n_est_pas_relu(self, suivi):
        lecture = [
            Message(role=Role.USER, content="Quelles sont mes tâches ?"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="t", name="succes_tasks", arguments="{}")],
            ),
            Message(role=Role.TOOL, content="…", tool_call_id="t"),
            Message(role=Role.ASSISTANT, content="Deux tâches."),
            Message(role=Role.USER, content=suivi),
        ]
        assert not TrousseChat(
            outils_du_bureau(), lecture, adaptative=True
        ).verifier_lecture(lecture)

    @pytest.mark.parametrize(
        "question",
        [
            "Est-ce que Carlito m'a répondu ?",
            "Qu'est-ce que j'ai de prévu ce soir ?",
        ],
    )
    def test_une_demande_inconnue_apres_une_action_garde_tous_les_schemas(
        self, question
    ):
        # Revue du 20/09/2026 : la demande précédente (Spotify), fusionnée
        # parce que la courante est courte, réduisait la trousse à Spotify et
        # « non, personne ne t'a répondu » partait sans lecture.
        liste = [*outils_du_bureau(), Outil("imessage_conversation")]
        fil = [
            Message(role=Role.USER, content="Mets la musique Self Aware sur Spotify"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="s", name="spotify_play", arguments="{}")],
            ),
            Message(role=Role.TOOL, content="lecture lancée", tool_call_id="s"),
            Message(role=Role.ASSISTANT, content="C'est parti."),
            Message(role=Role.USER, content=question),
        ]
        assert noms(TrousseChat(liste, fil, adaptative=True).specs) == [
            o.nom for o in liste
        ]

    def test_un_suivi_court_apres_une_action_n_est_pas_relu(self):
        fil = [
            Message(role=Role.USER, content="Joue Self Away sur Spotify"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="s", name="spotify_play", arguments="{}")],
            ),
            Message(role=Role.TOOL, content="lecture lancée", tool_call_id="s"),
            Message(role=Role.ASSISTANT, content="C'est parti."),
            Message(role=Role.USER, content="Et le titre suivant ?"),
        ]
        assert not TrousseChat(
            outils_du_bureau(), fil, adaptative=True
        ).verifier_lecture(fil)

    @pytest.mark.asyncio
    async def test_la_traduction_s_affiche_au_premier_passage(self):
        moteur = Moteur(
            [[StreamChunk(content="« Conscient de soi ».", finish_reason="stop")]]
        )
        fil = apres_youtube('Que veut dire "Self Aware" en français ?')
        evts = await collecter(moteur, outils_du_bureau(), messages=fil)
        assert len(moteur.appels) == 1, "un seul passage, pas de relecture"
        texte = "".join(e.data for e in evts if e.kind == "token")
        assert texte == "« Conscient de soi »."


class TestDialogueAvecDecouverte:
    @pytest.mark.asyncio
    async def test_le_programme_vague_recoit_une_carte_par_le_flux_du_chat(
        self, monkeypatch
    ):
        from diapason.server.models import ChatCompletionRequest
        from diapason.server.questions_chat import POSER_QUESTIONS
        from diapason.server.routes import _handle_stream

        demande = {
            "questions": [
                {
                    "title": "Quel langage veux-tu apprendre ?",
                    "options": [{"label": "Python"}, {"label": "JavaScript"}],
                }
            ]
        }
        moteur = Moteur(
            [
                [
                    StreamChunk(
                        content="Quel langage de programmation veux-tu apprendre ?",
                        finish_reason="stop",
                    )
                ],
                [StreamChunk(tool_calls=[appel(POSER_QUESTIONS, demande)])],
            ]
        )
        monkeypatch.setattr(
            "diapason.server.routes._ensure_identity_prompt",
            lambda messages, *args, **kwargs: messages,
        )
        executeur = MagicMock()
        requete = ChatCompletionRequest(
            model="test",
            stream=True,
            interactiveQuestions=True,
            messages=[
                {"role": "user", "content": "Qui est le président actuel ?"},
                {"role": "assistant", "content": "Je dois vérifier."},
                {
                    "role": "user",
                    "content": "Prepare moi un programme pour la programmation",
                },
            ],
        )
        config = DiapasonConfig()
        config.agent.trousse_adaptative = True
        response = await _handle_stream(
            moteur, "test", requete, tooling=(outils(), executeur), app_config=config
        )
        corps = "".join([part async for part in response.body_iterator])
        assert noms(moteur.appels[0][1]["tools"]) == [
            CHARGER_OUTILS,
            POSER_QUESTIONS,
        ], "les paramètres des actions ne doivent pas noyer le cadrage"
        assert noms(moteur.appels[1][1]["tools"]) == [POSER_QUESTIONS]
        assert corps.count("event: questions\n") == 1 and "[DONE]" in corps
        assert len(moteur.appels) == 2, "une seule conversion, jamais une boucle"
        executeur.execute.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raison", ["content_filter", "length", None])
    async def test_un_arret_de_securite_ou_une_coupure_ne_relance_pas(self, raison):
        moteur = Moteur([[StreamChunk(content="Arrêt.", finish_reason=raison)]])
        evts = await collecter(
            moteur, outils(), messages=messages("Quelles sont mes tâches ?")
        )
        assert len(moteur.appels) == 1, "aucune reprise pour contourner un arrêt"
        assert "".join(e.data for e in evts if e.kind == "token") == "Arrêt."

    @pytest.mark.asyncio
    async def test_une_absence_de_donnees_inventee_est_reprise_avant_affichage(self):
        liste = outils()
        moteur = Moteur(
            [
                [
                    StreamChunk(
                        content="Aucune tâche, j'ai tout vérifié.", finish_reason="stop"
                    )
                ],
                [StreamChunk(tool_calls=[appel("succes_tasks", {"value": "a"})])],
                [StreamChunk(content="Voici le résultat réellement lu.")],
            ]
        )
        evts = await collecter(
            moteur, liste, messages=messages("Quelles sont mes tâches ?")
        )
        assert "Aucune tâche" not in "".join(e.data for e in evts if e.kind == "token")
        assert noms(moteur.appels[1][1]["tools"]) == [o.nom for o in liste]
        assert all(
            "j'ai tout vérifié" not in (m.content or "") for m in moteur.appels[1][0]
        )
        assert liste[0].executions == [{"value": "a"}], "le repli conserve l'accès réel"

    @pytest.mark.asyncio
    async def test_le_repli_de_lecture_ne_recommence_pas_a_l_infini(self):
        moteur = Moteur(
            [[StreamChunk(content="Précise la période.", finish_reason="stop")]]
        )
        evts = await collecter(
            moteur, outils(), messages=messages("Quelles sont mes tâches ?")
        )
        assert len(moteur.appels) == 2, "un unique repli aux schémas complets"
        assert (
            "".join(e.data for e in evts if e.kind == "token") == "Précise la période."
        )

    @pytest.mark.asyncio
    async def test_une_decouverte_ne_prend_pas_le_budget_de_l_action(self):
        liste = outils()
        moteur = Moteur(
            [
                [
                    StreamChunk(
                        tool_calls=[
                            appel(
                                CHARGER_OUTILS, {"toolNames": ["outil_prive"]}, "charge"
                            )
                        ]
                    )
                ],
                [StreamChunk(tool_calls=[appel("outil_prive", {"value": "a"}, "lit")])],
                [StreamChunk(content="Résultat après lecture.")],
            ]
        )
        evenements = await collecter(moteur, liste, max_tool_turns=1)
        assert [e.kind for e in evenements] == ["tool_start", "tool_end", "token"], (
            "le chargement n'est pas une fausse action visible"
        )
        assert next(o for o in liste if o.nom == "outil_prive").executions == [
            {"value": "a"}
        ]
        assert "outil_prive" in noms(moteur.appels[1][1]["tools"])
        assert not moteur.appels[2][1].get("tools"), (
            "la dernière passe reste sans outil"
        )
        charges = [m for m in moteur.appels[1][0] if m.role == Role.TOOL]
        assert charges[0].tool_call_id == "charge"
        assert "Aucune donnée lue" in charges[0].content

    @pytest.mark.asyncio
    async def test_l_approbation_refusee_reste_un_echec_apres_chargement(self):
        liste = [*outils(), Outil("outil_protege", protege=True, grand=False)]
        demandes = []

        def refuser(prompt):
            demandes.append(prompt)
            return False

        executor = ToolExecutor(
            liste,
            interactive=True,
            confirm_callback=refuser,
            autoload_capability_policy=False,
        )
        moteur = Moteur(
            [
                [
                    StreamChunk(
                        tool_calls=[
                            appel(CHARGER_OUTILS, {"toolNames": ["outil_protege"]})
                        ]
                    )
                ],
                [StreamChunk(tool_calls=[appel("outil_protege")])],
                [StreamChunk(content="L'action a été refusée.")],
            ]
        )
        evenements = await collecter(moteur, liste, executor=executor)
        assert len(demandes) == 1, "l'exécuteur conserve sa confirmation"
        assert not liste[-1].executions, "aucun effet en cas de refus"
        assert (
            next(e for e in evenements if e.kind == "tool_end").data["success"] is False
        )

    @pytest.mark.asyncio
    async def test_un_nom_non_autorise_n_atteint_pas_l_executeur(self):
        class Interdit:
            def execute(self, tool_call):
                pytest.fail("l'outil hors trousse a atteint l'exécuteur")

        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel("shell_exec")])],
                [StreamChunk(content="Refusé.")],
            ]
        )
        evenements = await collecter(moteur, outils(), executor=Interdit())
        assert (
            next(e for e in evenements if e.kind == "tool_end").data["success"] is False
        )

    @pytest.mark.asyncio
    async def test_un_modele_bloque_sur_la_decouverte_finit_sans_outils(self):
        moteur = Moteur(
            [
                [
                    StreamChunk(
                        tool_calls=[
                            appel(CHARGER_OUTILS, {"toolNames": ["outil_prive"]})
                        ]
                    )
                ]
            ]
        )
        evts = await collecter(moteur, outils(), max_tool_turns=2)
        assert len(moteur.appels) == 2 + MAX_CHARGEMENTS + 1, "pas de boucle infinie"
        assert not moteur.appels[-1][1].get("tools"), (
            "la dernière passe rédige sans outil"
        )
        assert "pas pu préparer" in "".join(
            e.data for e in evts if e.kind == "token"
        ), "la limite ne doit pas produire une réponse vide ou un faux succès"

    @pytest.mark.asyncio
    async def test_fermer_pendant_la_decouverte_ne_lance_pas_l_action(self):
        attente = asyncio.Event()
        ferme = asyncio.Event()

        class Lent(Moteur):
            async def stream_full(self, msgs, **kwargs):
                try:
                    attente.set()
                    await asyncio.Event().wait()
                    yield StreamChunk(tool_calls=[appel(CHARGER_OUTILS)])
                finally:
                    ferme.set()

        liste = outils()
        tache = asyncio.create_task(collecter(Lent([]), liste))
        await attente.wait()
        tache.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tache
        assert ferme.is_set() and all(not o.executions for o in liste)
