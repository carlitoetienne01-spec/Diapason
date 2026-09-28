"""§100 : un timbre choisi doit être disponible, fidèle au choix et interruptible."""

from __future__ import annotations

import asyncio
import base64
import sys

import pytest

from diapason.speech.realtime.local_voice import LocalVoiceSession
from diapason.speech.realtime.voix_expressive import VoixExpressive, voix_configuree


async def ouvrier_factice(voix, code):
    processus = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        code,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    voix._processus = processus
    return processus


@pytest.mark.asyncio
async def test_le_premier_morceau_arrive_avant_la_fin_et_une_coupure_tue_le_calcul(
    monkeypatch,
):
    """§100 : garder les morceaux en mémoire jusqu'à DONE détruisait le flux."""
    voix = VoixExpressive("qwen3-b")
    processus = await ouvrier_factice(
        voix,
        """
import json,sys,time
sys.stdin.readline()
print(json.dumps({"type":"audio","sampleRate":24000,"data":"AAAAAA=="}),flush=True)
time.sleep(30)
""",
    )

    async def pret():
        pass

    monkeypatch.setattr(voix, "_demarrer", pret)
    flux = voix.morceaux("Bonjour.")
    try:
        pcm = await asyncio.wait_for(anext(flux), 3)
        assert pcm == b"\0" * 4, "le lecteur doit recevoir le son sans attendre DONE"
        assert processus.returncode is None, "le calcul n'est pas encore terminé"
        await flux.aclose()
        assert processus.returncode is not None, (
            "interrompre doit arrêter le vrai calcul"
        )
    finally:
        await voix.fermer()


@pytest.mark.asyncio
async def test_annuler_une_attente_ne_laisse_aucun_son_pour_le_tour_suivant(
    monkeypatch,
):
    voix = VoixExpressive("qwen3-b")
    processus = await ouvrier_factice(
        voix, "import sys,time; sys.stdin.readline(); time.sleep(30)"
    )

    async def pret():
        pass

    monkeypatch.setattr(voix, "_demarrer", pret)
    flux = voix.morceaux("Bonjour.")
    attente = asyncio.create_task(anext(flux))
    await asyncio.sleep(0.05)
    attente.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attente
    assert processus.returncode is not None, "le travail natif annulé ne continue pas"
    assert voix._processus is None, "la prochaine réponse devra avoir son propre flux"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trame",
    [
        '{"type":"audio","sampleRate":16000,"data":"AAAA"}',
        '{"type":"audio","sampleRate":24000,"data":"AA=="}',
        '{"type":"error"}',
    ],
)
async def test_un_son_invalide_ne_passe_pas_pour_une_voix_reussie(monkeypatch, trame):
    voix = VoixExpressive("qwen3-b")
    processus = await ouvrier_factice(
        voix, f"import sys; sys.stdin.readline(); print({trame!r},flush=True)"
    )

    async def pret():
        pass

    monkeypatch.setattr(voix, "_demarrer", pret)
    with pytest.raises(RuntimeError):
        _ = [pcm async for pcm in voix.morceaux("Bonjour.")]
    assert processus.returncode is not None, "le protocole cassé est arrêté"


@pytest.mark.asyncio
async def test_la_session_transmet_les_morceaux_et_ne_joue_pas_un_accuse_kokoro(
    monkeypatch,
):
    class Flux:
        async def morceaux(self, _texte):
            yield b"\0" * 4800
            yield b"\1" * 4800

    session = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None)
    session._tts_flux = Flux()
    dit = []
    monkeypatch.setattr(
        "diapason.speech.realtime.local_voice._SHARED",
        {"acks": {"Ça marche.": b"\0" * 4800}},
    )
    monkeypatch.setattr("diapason.speech.realtime.tools.FAST_ACK_TOOL_IDS", {"test"})
    await session._emit_optimistic_ack([{"function": {"name": "test"}}], dit)
    assert session._queue.empty(), (
        "la voix B ne doit pas répondre avec un ancien son Kokoro"
    )
    await session._speak_sentence("Bonjour.", dit)
    texte = await session._queue.get()
    assert texte.kind == "transcript" and not texte.final, (
        "texte préparé, pas succès audio"
    )
    premier, second = await session._queue.get(), await session._queue.get()
    assert base64.b64decode(premier.audio_b64) == b"\0" * 4800, "premier morceau intact"
    assert base64.b64decode(second.audio_b64) == b"\1" * 4800, "second morceau intact"
    assert dit == ["Bonjour."], "l'historique n'ajoute pas une phrase par morceau"


def test_une_ancienne_configuration_ne_retablit_pas_une_voix_retiree(
    tmp_path, monkeypatch
):
    fichier = tmp_path / "config.toml"
    monkeypatch.setattr("diapason.server.config_routes._config_path", lambda: fichier)
    for choix in ("qwen3-b", "qwen3-a", "ff_siwis", ""):
        fichier.write_text(f'[speech.realtime]\nvoice="{choix}"\n')
        assert voix_configuree(choix) == "qwen3-b", (
            "le bureau et le mini-panneau gardent uniquement la voix masculine"
        )


def test_seule_la_voix_masculine_est_disponible_sans_repli_classique(monkeypatch):
    from diapason.speech.realtime import voix_expressive as voix

    monkeypatch.setattr(voix, "moteur_installe", lambda: True)
    assert voix.voix_disponibles() == ["qwen3-b"], "aucune option A ou classique"
    for ancienne in ("", "qwen3-a", "ff_siwis"):
        assert LocalVoiceSession(voice=ancienne)._voice == "qwen3-b"
    with pytest.raises(ValueError):
        VoixExpressive("qwen3-a")
    monkeypatch.setattr(voix, "moteur_installe", lambda: False)
    assert voix.voix_disponibles() == [], "pas de voix de secours non demandée"


@pytest.mark.asyncio
async def test_une_phrase_lente_est_preparee_avant_la_lecture_sans_perdre_de_pcm():
    """§100 : le calcul plus lent que le son coupait les mots toutes les 480 ms."""
    premier = asyncio.Event()
    suite = asyncio.Event()

    class Flux:
        async def morceaux(self, _texte):
            yield b"\1\0" * 11520
            premier.set()
            await suite.wait()
            yield b"\2\0" * 11520

    session = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None)
    session._tts_flux = Flux()
    dit = []
    travail = asyncio.create_task(session._speak_sentence("Bonjour à toi.", dit))
    try:
        await asyncio.wait_for(premier.wait(), 1)
        texte = await session._queue.get()
        assert texte.kind == "transcript" and not texte.final
        assert session._queue.empty(), "ne pas démarrer un mot dont la suite manque"
        suite.set()
        await asyncio.wait_for(travail, 1)
        morceaux = [await session._queue.get(), await session._queue.get()]
        assert [base64.b64decode(m.audio_b64) for m in morceaux] == [
            b"\1\0" * 11520,
            b"\2\0" * 11520,
        ], "les morceaux préparés gardent exactement leurs échantillons et leur ordre"
        assert dit == ["Bonjour à toi."], "une phrase, pas un message par paquet"
    finally:
        travail.cancel()
        await asyncio.gather(travail, return_exceptions=True)


@pytest.mark.asyncio
async def test_interrompre_la_preparation_ne_laisse_pas_sortir_le_debut_ancien():
    """§100 : le tampon d'une réponse interrompue ne doit jamais se faire entendre."""
    premier, ferme = asyncio.Event(), asyncio.Event()

    class Flux:
        async def morceaux(self, _texte):
            try:
                yield b"\0" * 4800
                premier.set()
                await asyncio.Event().wait()
            finally:
                ferme.set()

    session = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None)
    session._tts_flux = Flux()
    dit = []
    travail = asyncio.create_task(session._speak_sentence("Ancienne réponse.", dit))
    await asyncio.wait_for(premier.wait(), 1)
    travail.cancel()
    with pytest.raises(asyncio.CancelledError):
        await travail
    assert ferme.is_set(), "le générateur doit libérer le vrai processus de calcul"
    texte = await session._queue.get()
    assert texte.kind == "transcript" and not texte.final, (
        "seul le brouillon préparé est visible"
    )
    assert session._queue.empty() and not dit, "aucun vieux son ni faux succès"


@pytest.mark.asyncio
async def test_les_voix_expressives_ne_decoupent_pas_une_phrase_a_la_virgule(
    monkeypatch,
):
    """§100 : découper une amorce obligeait à recalculer la suite en pleine parole."""
    session = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None)
    session._tts_flux = object()
    phrases = []

    async def parler(texte, dit):
        phrases.append(texte)
        dit.append(texte)

    monkeypatch.setattr(session, "_speak_sentence", parler)
    debut = "Pour apprendre l'anglais, "
    dit = []
    reste = await session._speak_complete_sentences(debut, dit)
    assert reste == debut and not phrases, "la virgule seule ne démarre pas la voix"
    reste = await session._speak_complete_sentences(
        reste + "répète une phrase. Ensuite", dit
    )
    assert phrases == ["Pour apprendre l'anglais, répète une phrase."], (
        "une proposition complète garde sa continuité"
    )
    assert reste == "Ensuite", "ne perdre aucun texte en attente"


@pytest.mark.asyncio
@pytest.mark.parametrize("vide", [True, False])
async def test_une_synthese_vide_ou_interrompue_par_erreur_ne_publie_aucun_audio(vide):
    """§100 : un échec de calcul ne devient ni un demi-mot ni une phrase dite."""

    class Flux:
        async def morceaux(self, _texte):
            if vide:
                return
            yield b"\0" * 4800
            raise RuntimeError("échec de synthèse")

    session = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None)
    session._tts_flux = Flux()
    dit = []
    with pytest.raises(RuntimeError):
        await session._speak_sentence("Cette phrase échoue.", dit)
    texte = await session._queue.get()
    assert texte.kind == "transcript" and not texte.final
    assert session._queue.empty() and not dit, "ne pas lire le morceau orphelin"


@pytest.mark.asyncio
async def test_un_prefixe_fidele_arrive_avant_la_fin_sans_doubler_la_lecture():
    """§100 : retenir le préfixe validé jusqu'à DONE annulait son gain de latence."""
    suite = asyncio.Event()

    class Flux:
        lecture_anticipee = True

        async def morceaux(self, _texte):
            yield b"\1\0" * 11520
            await suite.wait()
            yield b"\2\0" * 11520

    session = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None)
    session._tts_flux = Flux()
    dit = []
    travail = asyncio.create_task(session._speak_sentence("Bonjour à toi.", dit))
    try:
        texte = await asyncio.wait_for(session._queue.get(), 1)
        assert texte.kind == "transcript" and not texte.final
        premier = await asyncio.wait_for(session._queue.get(), 1)
        assert base64.b64decode(premier.audio_b64) == b"\1\0" * 11520
        assert not travail.done() and not dit, "la phrase n'est pas encore terminée"
        suite.set()
        await asyncio.wait_for(travail, 1)
        dernier = session._queue.get_nowait()
        assert base64.b64decode(dernier.audio_b64) == b"\2\0" * 11520
        assert session._queue.empty(), "le tampon ne se rejoue pas après le flux"
        assert dit == ["Bonjour à toi."], "une seule phrase complète est journalisée"
    finally:
        travail.cancel()
        await asyncio.gather(travail, return_exceptions=True)


@pytest.mark.asyncio
async def test_interrompre_un_flux_anticipe_ferme_la_suite_et_ne_valide_pas_la_phrase():
    """§100 : après interruption, aucun ancien son ni succès complet ne doit sortir."""
    ferme = asyncio.Event()

    class Flux:
        lecture_anticipee = True

        async def morceaux(self, _texte):
            try:
                yield b"\1\0" * 11520
                await asyncio.Event().wait()
            finally:
                ferme.set()

    session = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None)
    session._tts_flux = Flux()
    dit = []
    travail = asyncio.create_task(session._speak_sentence("Ancienne réponse.", dit))
    texte = await asyncio.wait_for(session._queue.get(), 1)
    assert texte.kind == "transcript" and not texte.final
    audio = await asyncio.wait_for(session._queue.get(), 1)
    assert audio.kind == "audio"
    travail.cancel()
    with pytest.raises(asyncio.CancelledError):
        await travail
    assert ferme.is_set(), "le générateur libère le calcul de la suite"
    assert session._queue.empty() and not dit, "aucune fin ancienne ni faux succès"
