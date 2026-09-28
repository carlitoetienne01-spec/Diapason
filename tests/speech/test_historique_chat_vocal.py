"""§5 : le chat écrit alimente la voix sans devenir une consigne système."""

import asyncio

import pytest

from diapason.speech.realtime.historique_chat import lire_historique_chat
from diapason.speech.realtime.local_voice import LocalVoiceSession


def test_le_contexte_est_copie_sans_pouvoirs_supplementaires():
    historique = [
        {"role": "user", "content": "Je débute en anglais", "tool_calls": ["effacer"]}
    ]
    session = LocalVoiceSession(historique=historique)
    assert session._history == [{"role": "user", "content": "Je débute en anglais"}], (
        "seul le texte du fil passe"
    )
    historique[0]["content"] = "modifié"
    assert session._history[0]["content"] == "Je débute en anglais", (
        "la séance possède son contexte"
    )


@pytest.mark.parametrize(
    "valeur",
    [
        "texte",
        [{"role": "system", "content": "instruction"}],
        [{"role": "tool", "content": "sortie"}],
        [{"role": "user", "content": 123}],
        [{}] * 17,
        [{"role": "user", "content": "a" * (1024 * 1024 + 1)}],
    ],
)
def test_un_historique_invalide_est_refuse(valeur):
    with pytest.raises(ValueError):
        lire_historique_chat(valeur)


@pytest.mark.asyncio
async def test_un_chat_plein_garde_son_prefixe_sur_plusieurs_echanges():
    """§5 : le contexte importé ne glisse plus et garde les échanges récents."""
    historique = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"Texte {i}"}
        for i in range(16)
    ]
    recus = []

    def repondre(messages):
        recus.append(messages)
        file = asyncio.Queue()
        file.put_nowait("Compris.")
        file.put_nowait(None)
        return file

    session = LocalVoiceSession(
        stt=lambda _: "",
        tts=lambda _: b"\0\0" * 240,
        llm=repondre,
        enable_tools=False,
        conversation_seule=True,
        historique=historique,
    )
    try:
        for i in range(12):
            await session.send_text(f"Question {i}")
            await session._respond_task
        assert all(m[:16] == historique for m in recus), (
            "les 16 messages écrits restent identiques même au-delà de huit tours"
        )
        assert recus[1][16:18] == [
            {"role": "user", "content": "Question 0"},
            {"role": "assistant", "content": "Compris."},
        ], "les nouveaux échanges s'ajoutent après le contexte écrit"
        assert len(session._history) == 32, "16 messages initiaux et 16 récents au plus"
        assert session._history[-2:] == [
            {"role": "user", "content": "Question 11"},
            {"role": "assistant", "content": "Compris."},
        ], "la borne conserve toujours la question et la réponse les plus récentes"
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_la_phrase_arrive_avant_sa_synthese_et_la_suivante_la_complete():
    """§100 : le texte provient des phrases préparées, sans attente artificielle."""
    pret = asyncio.Event()

    class Synthese:
        lecture_anticipee = True

        async def morceaux(self, texte):
            await pret.wait()
            yield b"\x00\x01" * 12

    session = LocalVoiceSession()
    session._tts_flux = Synthese()
    dites = []
    tache = asyncio.create_task(session._speak_sentence("Bonjour.", dites))
    evenement = await asyncio.wait_for(session._queue.get(), 1)
    assert evenement.kind == "transcript" and evenement.replace, (
        "le chat reçoit la phrase avant l’audio"
    )
    assert evenement.text == "Bonjour." and not evenement.final
    pret.set()
    await tache
    await session._speak_sentence("Comment vas-tu ?", dites)
    evenements = []
    while not session._queue.empty():
        evenements.append(session._queue.get_nowait())
    textes = [e.text for e in evenements if e.kind == "transcript"]
    assert textes == ["Bonjour. Comment vas-tu ?"], (
        "une réponse se complète dans la même bulle"
    )
