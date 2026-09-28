"""§100 — les sources survivent à la parole et à une question de suivi."""

import asyncio
import json

import pytest

from diapason.speech.realtime.local_voice import LocalVoiceSession, _tool_note


@pytest.mark.asyncio
async def test_le_lien_reste_dans_le_chat_sans_etre_epelle():
    lus = []
    session = LocalVoiceSession(
        stt=lambda _: "", llm=lambda _: None, tts=lambda t: lus.append(t) or b"\0\0"
    )
    paroles = []
    await session._speak_sentence("Voici le site : https://code.org/a_b.", paroles)
    assert "https://code.org/a_b." in paroles[0], (
        "adresse exacte dans le texte conservé"
    )
    assert lus == ["Voici le site :"], "adresse exclue du vocodeur seulement"


def test_la_source_et_son_identifiant_survivent_a_la_trace():
    contenu = "Description " * 30 + "\nSource: https://example.org/une_vraie_page"
    note = _tool_note(
        {"function": {"name": "web_search", "arguments": {"query": "test"}}},
        {"content": json.dumps({"ok": True, "content": contenu})},
    )
    assert "https://example.org/une_vraie_page" in note, (
        "le suivi ne doit pas deviner le lien"
    )


@pytest.mark.asyncio
async def test_le_mauvais_destinataire_ne_recoit_aucune_ecriture():
    appels = []
    session = LocalVoiceSession(
        stt=lambda _: "",
        llm=lambda _: None,
        tts=lambda _: b"",
        tool_executor=lambda *a: appels.append(a),
    )
    session._history = [
        {"role": "user", "content": "Crée une note Diapason de diagnostic"}
    ]
    resultat = await session._run_tool(
        {
            "function": {
                "name": "notes_write",
                "arguments": {"action": "create", "title": "test", "text": "test"},
            }
        }
    )
    assert not appels, "Apple Notes ne doit rien recevoir"
    assert not json.loads(resultat["content"])["ok"]


@pytest.mark.asyncio
async def test_la_question_suivante_reste_engagee_apres_une_longue_reponse(monkeypatch):
    from diapason.speech.realtime import local_voice as v

    monkeypatch.setattr(v.time, "monotonic", lambda: 1000.0)
    session = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None, tts=lambda _: b"")
    session._engagee_jusqua = 990
    session._speaking_until = 1090
    await session._emettre_pcm(b"\0\0" * 24000)
    assert session._engagee_jusqua == 1091 + v.ADDRESS_WINDOW_S, (
        "compter le silence après le son"
    )


@pytest.mark.asyncio
async def test_un_lien_ne_declenche_pas_une_simple_ouverture_de_navigateur(monkeypatch):
    from diapason.desktop import voice_commands

    def ouvrir(*_):
        raise AssertionError(
            "une recherche de lien demande un résultat, pas une fenêtre"
        )

    monkeypatch.setattr(voice_commands, "execute_voice_action", ouvrir)
    session = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None, tts=lambda _: b"")
    assert not await session._try_fast_voice_action(
        "Recherche le site officiel de Code.org et donne-moi son lien exact",
        turn_started=0,
    )


@pytest.mark.asyncio
async def test_une_source_recue_reste_connue_meme_apres_la_toilette_actualite():
    from diapason.speech.realtime.actualite_vocale import TourVocal

    def outil(*_):
        return {
            "ok": True,
            "content": "Page reçue.",
            "metadata": {
                "sources": [{"url": "https://example.org/a_b", "title": "Page"}]
            },
        }

    session = LocalVoiceSession(
        stt=lambda _: "", llm=lambda _: None, tts=lambda _: b"", tool_executor=outil
    )
    await session._run_tool(
        {"function": {"name": "web_search", "arguments": {"query": "page"}}},
        tour=TourVocal(question="site officiel"),
    )
    assert "https://example.org/a_b" in session._liens_recus, (
        "la toilette du modèle ne supprime pas la preuve"
    )


@pytest.mark.asyncio
async def test_une_fausse_adresse_vocale_est_reprise_avant_le_son():
    lus = []
    tour = 0

    def llm(messages):
        nonlocal tour
        tour += 1
        q = asyncio.Queue()
        if tour == 1:
            q.put_nowait("Voici https://example.org/inventee.")
        elif tour == 2:
            q.put_nowait(
                (
                    "tools",
                    [
                        {
                            "function": {
                                "name": "web_search",
                                "arguments": {"query": "page"},
                            }
                        }
                    ],
                )
            )
        else:
            q.put_nowait("Voici https://example.org/vraie.")
        q.put_nowait(None)
        return q

    def outil(*_):
        return {
            "ok": True,
            "content": "Source: https://example.org/vraie",
            "metadata": {"sources": [{"url": "https://example.org/vraie"}]},
        }

    session = LocalVoiceSession(
        stt=lambda _: "",
        llm=llm,
        tts=lambda t: lus.append(t) or b"\0\0",
        tool_executor=outil,
    )
    await session._respond_to_text("Donne le lien de cette page")
    finals = [
        e.text
        for e in list(session._queue._queue)
        if e.kind == "transcript" and e.final and e.role == "assistant"
    ]
    assert finals == ["Voici https://example.org/vraie."], (
        "ni fausse adresse ni préambule incorrect diffusé"
    )
    assert lus == ["Voici"], "les caractères du lien ne se lisent pas"


def test_la_voix_dispose_du_calculateur_local():
    from diapason.speech.realtime.tools import (
        DEFAULT_VOICE_TOOL_IDS,
        openai_tools_schema,
    )

    assert "calculator" in DEFAULT_VOICE_TOOL_IDS
    assert any(
        t["function"]["name"] == "calculator"
        for t in openai_tools_schema(["calculator"])
    ), "le schéma doit être exécutable"
