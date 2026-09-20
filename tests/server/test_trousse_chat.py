"""§5/§100 : alléger les schémas sans inventer les données ni élargir les droits."""

import asyncio
import copy
import json
from unittest.mock import MagicMock

import pytest

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
    return [
        e
        async for e in stream_with_tools(
            moteur, "local", dialogue, tools=liste, executor=executeur, **kwargs
        )
    ]


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
        trousse = TrousseChat(outils(), messages(demande))
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
        trousse = TrousseChat(outils(), messages(demande))
        assert trousse.verifier_lecture(messages(demande)) or noms(trousse.specs) == [
            o.nom for o in outils()
        ], "concevoir ne dispense pas de lire les données"

    def test_une_explication_n_envoie_que_le_catalogue(self):
        liste = outils()
        original = [o.to_openai_function() for o in liste]
        sauvegarde = copy.deepcopy(original)
        trousse = TrousseChat(liste, messages())
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
        trousse = TrousseChat(outils(), messages(question))
        assert attendus <= set(noms(trousse.specs))
        assert CHARGER_OUTILS in noms(trousse.specs)

    def test_suivi_court_et_historique_outille(self):
        historique = messages("Quelles sont mes tâches ?") + [
            Message(role=Role.USER, content="Et demain ?")
        ]
        assert "succes_tasks" in noms(TrousseChat(outils(), historique).specs)
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
        assert "outil_prive" in noms(TrousseChat(outils(), historique).specs)

    def test_les_schemas_charges_sont_exacts_et_independants_des_autres_fenetres(self):
        liste = outils()
        a, b = TrousseChat(liste, messages()), TrousseChat(liste, messages())
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
        t = TrousseChat(liste, messages())
        assert "error" in json.loads(t.charger(arguments))
        assert noms(t.specs) == [o.nom for o in liste], (
            "repli complet sans outil supplémentaire"
        )

    def test_deux_decouvertes_suffisent_et_la_petite_trousse_est_inchangee(self):
        liste = outils()
        t = TrousseChat(liste, messages())
        for _ in range(MAX_CHARGEMENTS):
            t.charger('{"toolNames":["outil_prive"]}')
        assert noms(t.specs) == [o.nom for o in liste]
        petit = [Outil("personnel", grand=False)]
        assert TrousseChat(petit, messages()).specs == [petit[0].to_openai_function()]

    def test_le_nom_reserve_ne_detourne_pas_un_outil_configure(self):
        liste = [*outils(), Outil(CHARGER_OUTILS)]
        t = TrousseChat(liste, messages())
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
        assert TrousseChat(liste, messages(question)).specs == [
            o.to_openai_function() for o in liste
        ], "l'optimisation ne doit pas faire croire que les données ont été lues"


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
        response = await _handle_stream(
            moteur, "test", requete, tooling=(outils(), executeur)
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
