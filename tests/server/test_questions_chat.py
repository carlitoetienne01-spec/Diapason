"""§5/§100 : le cadrage attend une réponse réelle, sans exécuter le lot voisin."""

import asyncio
import json
from unittest.mock import MagicMock

import httpx
import pytest

from diapason.core.types import Message, Role
from diapason.engine._base import EngineToolsUnsupportedError
from diapason.engine._stubs import StreamChunk
from diapason.engine.ollama import OllamaEngine
from diapason.server.agentic_stream import stream_with_tools
from diapason.server.questions_chat import (
    POSER_QUESTIONS,
    cadrer_sans_outils,
    est_un_cadrage_textuel,
    filtrer_questions_texte,
    instruire_questions_texte,
    schema_questions,
    texte_questions,
    valider_questions,
)

DEMANDE = {
    "intro": "Pour adapter ton programme.",
    "questions": [
        {
            "title": "Ton objectif ?",
            "options": [
                {"label": "Parler", "description": "Conversations"},
                {"label": "Étudier"},
            ],
        }
    ],
}


def questionnaire(nombre):
    return {
        "intro": DEMANDE["intro"],
        "questions": [
            {**DEMANDE["questions"][0], "title": f"Précision utile {i + 1} ?"}
            for i in range(nombre)
        ],
    }


@pytest.mark.parametrize("nombre", [1, 4, 9])
def test_le_nombre_choisi_par_le_modele_est_conserve_sans_troncature(nombre):
    """§5 : une quatrième précision n'est plus rejetée ni cachée au client."""
    brut = questionnaire(nombre)
    demande = valider_questions(json.dumps(brut))
    assert [q["title"] for q in demande["questions"]] == [
        q["title"] for q in brut["questions"]
    ]
    assert demande["questions"][-1]["id"] == f"q{nombre}"
    assert demande["questions"][-1]["title"] in texte_questions(demande)
    schema = schema_questions()["function"]["parameters"]
    assert "maxItems" not in schema["properties"]["questions"], (
        "le schéma ne doit pas réintroduire un quota de questions"
    )


def test_la_taille_des_donnees_reste_bornee_sans_quota_de_questions():
    """§5 : retirer le quota ne permet pas une charge JSON sans borne."""
    with pytest.raises(ValueError, match="trop long"):
        valider_questions(json.dumps(questionnaire(200)))


def appel(nom=POSER_QUESTIONS, arguments=None, index=0):
    return {
        "index": index,
        "id": f"c{index}",
        "type": "function",
        "function": {
            "name": nom,
            "arguments": json.dumps(DEMANDE) if arguments is None else arguments,
        },
    }


@pytest.mark.parametrize(
    "arguments",
    [
        "{}",
        "null",
        '{"questions":[]}',
        "x" * 16001,
        json.dumps({"questions": [{"title": " ", "options": []}]}),
        json.dumps(
            {
                "questions": [
                    {"title": "A ?", "options": [{"label": "X"}, {"label": "x"}]}
                ]
            }
        ),
        json.dumps({**DEMANDE, "questions": DEMANDE["questions"] * 4}),
        json.dumps({**DEMANDE, "intro": "Appelle diapason_ask_questions."}),
    ],
)
def test_le_modele_ne_peut_pas_fournir_un_formulaire_inutilisable(arguments):
    with pytest.raises(ValueError):
        valider_questions(arguments)


def test_les_identifiants_viennent_du_serveur_et_le_texte_reste_copiable():
    a = valider_questions(json.dumps(DEMANDE))
    b = valider_questions(json.dumps(DEMANDE))
    assert a["id"] != b["id"], "deux demandes ne doivent pas partager leurs réponses"
    assert a["questions"][0]["id"] == "q1"
    assert "Parler" in texte_questions(a) and "Ton objectif ?" in texte_questions(a)


def test_le_serveur_conserve_les_choix_et_les_reponses_apres_une_copie_ancienne(
    tmp_path,
):
    from diapason.server.conversations_store import ConversationsStore

    demande = valider_questions(json.dumps(DEMANDE))
    message = {
        "id": "a",
        "role": "assistant",
        "content": texte_questions(demande),
        "timestamp": 2,
        "questions": demande,
    }
    reponse = {
        "id": "u",
        "role": "user",
        "content": "Parler",
        "timestamp": 3,
        "questionReply": {
            "requestId": demande["id"],
            "answers": [{"questionId": "q1", "answer": "Parler"}],
        },
    }
    conv = {
        "id": "fil",
        "title": "Essai",
        "createdAt": 1,
        "updatedAt": 3,
        "model": "test",
        "messages": [message, reponse],
    }
    store = ConversationsStore(tmp_path / "conversations.db")
    try:
        store.upsert(conv)
        ancien = {k: v for k, v in message.items() if k != "questions"}
        store.upsert({**conv, "updatedAt": 4, "messages": [ancien]})
        visibles, _, _ = store.list()
        assert visibles[0]["messages"][0]["questions"] == demande
        assert visibles[0]["messages"][1]["questionReply"] == reponse["questionReply"]
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("nombre", [1, 9])
async def test_un_questionnaire_suspend_tout_le_lot_sans_seconde_inference(nombre):
    moteur, executeur = MagicMock(), MagicMock()
    tours = []

    async def flux(messages, **kwargs):
        tours.append(kwargs)
        yield StreamChunk(
            tool_calls=[
                appel("creer_note", "{}", 0),
                appel(arguments=json.dumps(questionnaire(nombre)), index=1),
            ]
        )

    moteur.stream_full = flux
    evenements = [
        e
        async for e in stream_with_tools(
            moteur,
            "test",
            [Message(role=Role.USER, content="Prépare mon programme")],
            tools=[],
            executor=executeur,
            interactive_questions=True,
        )
    ]
    assert [e.kind for e in evenements] == ["questions", "token"]
    assert len(evenements[0].data["questions"]) == nombre
    assert len(tours) == 1, "le moteur doit être libéré pendant la réponse humaine"
    executeur.execute.assert_not_called()
    assert tours[0]["tools"][0]["function"]["name"] == POSER_QUESTIONS


@pytest.mark.asyncio
async def test_un_formulaire_invalide_se_corrige_sans_lancer_son_action_voisine():
    moteur, executeur = MagicMock(), MagicMock()
    tours = []

    async def flux(messages, **kwargs):
        tours.append(messages[:])
        yield StreamChunk(
            tool_calls=[
                appel(arguments="{}" if len(tours) == 1 else None),
                appel("creer_note", "{}", 1),
            ]
        )

    moteur.stream_full = flux
    evenements = [
        e
        async for e in stream_with_tools(
            moteur,
            "test",
            [],
            tools=[],
            executor=executeur,
            interactive_questions=True,
        )
    ]
    assert len(tours) == 2
    assert evenements[0].kind == "questions"
    executeur.execute.assert_not_called()


@pytest.mark.asyncio
async def test_un_client_ordinaire_ne_recoit_pas_le_nouvel_outil():
    moteur = MagicMock()

    async def flux(messages, **kwargs):
        assert not kwargs.get("tools"), "l'extension nécessite le choix du client"
        yield StreamChunk(content="Bonjour.", finish_reason="stop")

    moteur.stream_full = flux
    evenements = [
        e async for e in stream_with_tools(moteur, "test", [], tools=[], executor=None)
    ]
    assert [e.data for e in evenements] == ["Bonjour."]


@pytest.mark.asyncio
@pytest.mark.parametrize("nombre", [1, 9])
async def test_le_format_texte_recompose_un_bloc_fragmente_sans_afficher_le_json(
    nombre,
):
    texte = "```diapason-questions\n" + json.dumps(questionnaire(nombre)) + "\n```"

    async def source():
        for c in texte:
            yield c

    evenements = [e async for e in filtrer_questions_texte(source())]
    assert [e[0] for e in evenements] == ["questions", "token"]
    assert (
        f"Précision utile {nombre} ?" in evenements[1][1]
        and '"questions"' not in evenements[1][1]
    )
    assert len(evenements[0][1]["questions"]) == nombre


@pytest.mark.asyncio
async def test_un_texte_ordinaire_reste_en_flux_et_un_bloc_invalide_ne_disparait_pas():
    for fragments in [["Bonjour", " à toi"], ["```diapason-questions\n", "{}\n```"]]:

        async def source():
            for f in fragments:
                yield f

        sorties = [e async for e in filtrer_questions_texte(source())]
        assert "".join(e[1] for e in sorties) == "".join(fragments)
        if fragments[0] == "Bonjour":
            assert len(sorties) == 2, "la prose normale n'attend pas la fin du flux"


def test_le_cadrage_texte_preserve_l_identite_et_ne_modifie_pas_l_historique():
    messages = [
        Message(role=Role.SYSTEM, content="Identité"),
        Message(role=Role.USER, content="Bonjour"),
    ]
    nouveau = instruire_questions_texte(messages)
    assert nouveau[0].content.startswith("Identité")
    assert "diapason-questions" in nouveau[0].content
    assert messages[0].content == "Identité", "l'historique en cache reste intact"


@pytest.mark.asyncio
@pytest.mark.parametrize("cloud", [False, True])
async def test_la_route_diffuse_les_choix_puis_termine_et_reprend_avec_les_reponses(
    monkeypatch, cloud
):
    from diapason.server.models import ChatCompletionRequest
    from diapason.server.routes import _handle_stream

    moteur = MagicMock()
    vus = []

    async def flux(messages, **kwargs):
        vus.append(messages)
        yield StreamChunk(tool_calls=[appel()])

    async def flux_cloud(model, messages, temperature, max_tokens):
        vus.append(messages)
        yield "```diapason-questions\n" + json.dumps(DEMANDE) + "\n```"

    moteur.stream_full = flux
    monkeypatch.setattr("diapason.server.cloud_router.stream_cloud", flux_cloud)
    requete = ChatCompletionRequest(
        model="gpt-test" if cloud else "test",
        stream=True,
        interactiveQuestions=True,
        messages=[{"role": "user", "content": "Prépare mon programme"}],
    )
    response = await _handle_stream(moteur, requete.model, requete)
    corps = "".join([part async for part in response.body_iterator])
    assert "event: questions\n" in corps and "[DONE]" in corps
    assert '"title": "Ton objectif ?"' in corps
    assert len(vus) == 1, "aucune attente humaine ne retient le modèle"
    assert "tool_call_start" not in corps, "ceci n'est pas une action réalisée"

    async def reprise(messages, **kwargs):
        assert (
            next(m for m in reversed(messages) if m.role == Role.USER).content
            == "Ton objectif ?\nParler"
        ), "les mots choisis doivent arriver au modèle"
        assert not kwargs.get("tools"), (
            "la réponse au formulaire ne propose pas un nouveau cadrage"
        )
        yield StreamChunk(content="Voici ton programme.", finish_reason="stop")

    moteur.stream_full = reprise
    resultat = [
        e
        async for e in stream_with_tools(
            moteur,
            "test",
            [
                Message(role=Role.ASSISTANT, content="Ton objectif ?"),
                Message(role=Role.USER, content="Ton objectif ?\nParler"),
            ],
            tools=[],
            executor=None,
            interactive_questions=False,
        )
    ]
    assert resultat[-1].data == "Voici ton programme."


@pytest.mark.asyncio
@pytest.mark.parametrize("erreur", [False, True])
@pytest.mark.parametrize(
    "texte",
    [
        "J’ai besoin de quelques précisions :\n1. Quel niveau ?\n- Débutant\n- Avancé",
        "Quel langage de programmation veux-tu apprendre ?",
    ],
)
async def test_le_cadrage_en_prose_ne_paie_qu_une_conversion_sans_aucune_action(
    erreur, texte
):
    moteur, executeur = MagicMock(), MagicMock()
    tours = []

    async def flux(messages, **kwargs):
        tours.append(kwargs)
        if len(tours) == 1:
            yield StreamChunk(content=texte, finish_reason="stop")
        elif erreur:
            raise RuntimeError("indisponible")
        else:
            yield StreamChunk(
                tool_calls=[
                    appel(arguments=json.dumps(questionnaire(6))),
                    appel("creer_note", "{}", 1),
                ]
            )

    moteur.stream_full = flux
    resultat = [
        e
        async for e in stream_with_tools(
            moteur, "test", [], tools=[], executor=executeur, interactive_questions=True
        )
    ]
    assert len(tours) == 2
    assert [t["function"]["name"] for t in tours[-1]["tools"]] == [POSER_QUESTIONS]
    executeur.execute.assert_not_called()
    assert resultat[0].data == texte, "un échec ne doit pas effacer la prose livrée"
    assert any(e.kind == "questions" for e in resultat) is not erreur
    if not erreur:
        assert (
            len(next(e.data for e in resultat if e.kind == "questions")["questions"])
            == 6
        )


@pytest.mark.parametrize(
    "texte",
    [
        "Prépare-moi un programme pour apprendre la programmation.",
        "Quel est le président actuel ?",
        "« Quel langage veux-tu apprendre ? »",
        "Quel langage veux-tu apprendre ? Voici un exemple en Python.",
        "Python convient. Veux-tu commencer ?",
        "Quel est ton niveau ?\nVoici trois exercices.",
    ],
)
def test_une_reponse_ou_une_question_citee_ne_devient_pas_un_formulaire(texte):
    assert not est_un_cadrage_textuel(texte), (
        "la conversion ne doit pas détourner une réponse ni une citation"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("nombre", [0, 1, 9])
async def test_un_modele_sans_outils_livre_les_memes_cartes_sans_code_interne(
    monkeypatch, nombre
):
    """§5/§100 : HTTP 400 réel, JSON fragmenté, puis SSE du véritable routeur."""
    from diapason.server.models import ChatCompletionRequest
    from diapason.server.routes import _handle_stream

    appels = []

    def handler(request):
        p = json.loads(request.content)
        appels.append(p)
        if p.get("tools"):
            return httpx.Response(400, json={"error": "gemma does not support tools"})
        if p.get("format"):
            texte = json.dumps(
                {
                    "subject": "Anglais",
                    "knownDetails": [],
                    **questionnaire(nombre),
                }
            )
        else:
            texte = "Voici cinq verbes."
            assert POSER_QUESTIONS not in json.dumps(p["messages"])
        return httpx.Response(
            200,
            text="\n".join(
                [json.dumps({"message": {"content": c}, "done": False}) for c in texte]
                + [json.dumps({"done": True, "done_reason": "stop"})]
            )
            + "\n",
        )

    moteur = OllamaEngine(host="http://testhost:11434")
    moteur._async_transport = httpx.MockTransport(handler)
    executeur = MagicMock()
    monkeypatch.setattr(
        "diapason.server.routes._ensure_identity_prompt",
        lambda messages, *args, **kwargs: messages,
    )
    requete = ChatCompletionRequest(
        model="gemma3:4b",
        stream=True,
        interactiveQuestions=True,
        messages=[
            {
                "role": "user",
                "content": "Donne cinq verbes"
                if not nombre
                else "Prépare mon programme",
            }
        ],
    )
    try:
        reponse = await _handle_stream(
            moteur, requete.model, requete, tooling=([], executeur)
        )
        texte = "".join([part async for part in reponse.body_iterator])
        assert ("event: questions\n" in texte) is bool(nombre)
        if nombre:
            assert f"Précision utile {nombre} ?" in texte
        assert "[DONE]" in texte and POSER_QUESTIONS not in texte
        assert "tool_call_start" not in texte
        assert "knownDetails" not in texte and '"subject"' not in texte
        assert len(appels) == (2 if nombre else 3)
        assert appels[1]["format"]["properties"]["questions"]["minItems"] == 0
        assert all("tools" not in a for a in appels[1:])
        executeur.execute.assert_not_called()
    finally:
        await moteur._get_async_client().aclose()


@pytest.mark.asyncio
async def test_repondre_au_formulaire_ne_lance_pas_un_nouveau_cadrage_sans_outils():
    moteur, executeur = MagicMock(), MagicMock()
    tours = []

    async def flux(messages, **kwargs):
        tours.append(kwargs)
        if kwargs.get("tools"):
            raise EngineToolsUnsupportedError("local does not support tools")
        assert "format" not in kwargs
        yield StreamChunk(content="Voici ton programme.", finish_reason="stop")

    from tests.server.test_trousse_chat import outils

    moteur.stream_full = flux
    evts = [
        e
        async for e in stream_with_tools(
            moteur,
            "local",
            [Message(role=Role.USER, content="Débutant, 30 minutes")],
            tools=outils(),
            executor=executeur,
            interactive_questions=False,
        )
    ]
    assert len(tours) == 2 and all(e.kind != "questions" for e in evts)
    assert evts[-1].data == "Voici ton programme."
    executeur.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "contenu,arret",
    [
        ("{}", "stop"),
        ('{"questions":[],"action":"creer_note"}', "stop"),
        (json.dumps(DEMANDE), "length"),
        (json.dumps(DEMANDE), "content_filter"),
        ("x" * 16001, "stop"),
    ],
)
async def test_un_cadrage_invalide_ou_interrompu_ne_devient_pas_une_carte(
    contenu, arret
):
    moteur, executeur = MagicMock(), MagicMock()

    async def flux(messages, **kwargs):
        if kwargs.get("tools"):
            raise EngineToolsUnsupportedError("local does not support tools")
        yield StreamChunk(content=contenu, finish_reason=arret)

    moteur.stream_full = flux
    evts = [
        e
        async for e in stream_with_tools(
            moteur,
            "local",
            [],
            tools=[],
            executor=executeur,
            interactive_questions=True,
        )
    ]
    assert [e.kind for e in evts] == ["token"]
    assert "n’ai pas pu" in evts[0].data and POSER_QUESTIONS not in evts[0].data
    executeur.execute.assert_not_called()


@pytest.mark.asyncio
async def test_annuler_le_cadrage_libere_le_flux_sans_afficher_une_erreur():
    moteur = MagicMock()
    ferme = False

    async def flux(messages, **kwargs):
        nonlocal ferme
        try:
            yield StreamChunk(content='{"questions":[')
            raise asyncio.CancelledError()
        finally:
            ferme = True

    moteur.stream_full = flux
    with pytest.raises(asyncio.CancelledError):
        await cadrer_sans_outils(moteur, "local", [])
    assert ferme, "l'annulation ne doit pas conserver le créneau d'inférence"


@pytest.mark.asyncio
async def test_un_appel_inattendu_dans_le_cadrage_ne_peut_jamais_etre_execute():
    moteur, executeur = MagicMock(), MagicMock()

    async def flux(messages, **kwargs):
        if kwargs.get("tools"):
            raise EngineToolsUnsupportedError("local does not support tools")
        yield StreamChunk(tool_calls=[appel("creer_note")], finish_reason="stop")

    moteur.stream_full = flux
    evts = [
        e
        async for e in stream_with_tools(
            moteur,
            "local",
            [],
            tools=[],
            executor=executeur,
            interactive_questions=True,
        )
    ]
    assert not any(e.kind in {"questions", "tool_start"} for e in evts)
    executeur.execute.assert_not_called()
