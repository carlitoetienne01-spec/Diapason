"""§5/§100 — une attente annoncée correspond à un véritable appel en cours."""

import asyncio
import threading
from unittest.mock import AsyncMock, Mock

import pytest

from diapason.speech.realtime.local_voice import LocalVoiceSession


def session(executer):
    return LocalVoiceSession(
        stt=lambda _: "",
        llm=lambda _: None,
        tts=lambda _: b"\x01\x02" * 240,
        tool_executor=executer,
    )


def appel(nom="web_search"):
    return {"function": {"name": nom, "arguments": {"query": "anglais"}}}


@pytest.mark.asyncio
async def test_le_resultat_immediat_ne_coute_aucun_son_de_plus():
    s = session(lambda *_: {"ok": True, "content": "résultat"})
    s._speak_sentence = AsyncMock()
    reponse = await s._run_tool(appel(), spoken=[])
    assert "résultat" in reponse["content"], "le résultat arrive directement"
    s._speak_sentence.assert_not_called()


@pytest.mark.asyncio
async def test_une_attente_reelle_est_variee_et_commence_apres_l_appel(monkeypatch):
    monkeypatch.setattr("diapason.speech.realtime.local_voice.SEUIL_ANNONCE_S", 0.01)
    parti, finir = threading.Event(), threading.Event()

    def executer(*_):
        parti.set()
        assert finir.wait(2), "la recherche doit pouvoir rendre la main"
        return {"ok": True, "content": "source"}

    s = session(executer)
    phrases = []

    async def dire(phrase, spoken):
        assert parti.is_set(), "pas d'annonce avant une opération réelle"
        phrases.append(phrase)
        spoken.append(phrase)
        finir.set()

    s._speak_sentence = dire
    try:
        for _ in range(3):
            parti.clear()
            finir.clear()
            await s._run_tool(appel(), spoken=[])
    finally:
        finir.set()
    assert len(set(phrases)) == 3, "les tours ne répètent pas toujours la même annonce"


@pytest.mark.asyncio
async def test_pas_d_annonce_si_refus_ou_si_une_phrase_explique_deja_l_attente():
    executer = Mock(return_value={"ok": True, "content": "source"})
    s = session(executer)
    s._speak_sentence = AsyncMock()
    await s._run_tool(appel(), spoken=["Je vais vérifier la source."])
    await s._run_tool(appel("open_anything"), spoken=[])
    # Le budget s'exprime par allow ; aucun dépendance à sa représentation.
    s._budget.allow = lambda: False
    avant = executer.call_count
    await s._run_tool(appel(), spoken=[])
    assert executer.call_count == avant, "budget épuisé : aucun appel"
    s._speak_sentence.assert_not_called()
    s._tool_executor = None
    s._budget.allow = lambda: True
    await s._run_tool(appel(), spoken=[])
    s._speak_sentence.assert_not_called()


@pytest.mark.asyncio
async def test_annuler_la_reponse_ne_laisse_pas_une_annonce_en_vol(monkeypatch):
    monkeypatch.setattr("diapason.speech.realtime.local_voice.SEUIL_ANNONCE_S", 0.001)
    liberation = threading.Event()

    def executer(*_):
        liberation.wait(2)
        return {"ok": True}

    s = session(executer)
    commence, annule = asyncio.Event(), asyncio.Event()

    async def dire(*_):
        commence.set()
        try:
            await asyncio.Event().wait()
        finally:
            annule.set()

    s._speak_sentence = dire
    tache = asyncio.create_task(s._run_tool(appel(), spoken=[]))
    try:
        await asyncio.wait_for(commence.wait(), 1)
        tache.cancel()
        await asyncio.gather(tache, return_exceptions=True)
        assert annule.is_set(), "aucune phrase fantôme après une interruption"
    finally:
        liberation.set()


@pytest.mark.asyncio
async def test_le_resultat_ne_disparait_pas_si_l_annonce_echoue(monkeypatch):
    monkeypatch.setattr("diapason.speech.realtime.local_voice.SEUIL_ANNONCE_S", 0)
    s = session(lambda *_: {"ok": True, "content": "source conservée"})
    s._speak_sentence = AsyncMock(side_effect=RuntimeError("audio indisponible"))
    reponse = await s._run_tool(appel(), spoken=[])
    assert "source conservée" in reponse["content"], "l'annonce est facultative"


def test_les_sons_ecrits_restent_fideles_au_texte():
    from diapason.speech.realtime.local_voice import speakable

    for phrase in (
        "Ah, je comprends.",
        "Oh, voilà une piste.",
        "On entend toc-toc.",
        "Et boum, la porte se ferme.",
    ):
        assert speakable(phrase) == phrase, (
            "la synthèse reçoit les mots sans les réécrire"
        )
