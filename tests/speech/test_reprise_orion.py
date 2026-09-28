"""§100 — céder le GPU à Orion ne perd ni contexte, ni outil, ni annulation."""

import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from diapason.speech.realtime import local_voice as v


@pytest.fixture
def transport(monkeypatch):
    import httpx

    etat = SimpleNamespace(requetes=[], actifs=0, creneaux=0, fragments=None)

    class Ordonnanceur:
        @asynccontextmanager
        async def async_slot(self, *_, **__):
            etat.creneaux += 1
            try:
                yield SimpleNamespace(wait_ms=0)
            finally:
                etat.creneaux -= 1

        def remember_model(self, _):
            pass

    class Flux:
        status_code = 200

        def __init__(self, numero):
            self.numero = numero

        async def __aenter__(self):
            etat.actifs += 1
            return self

        async def __aexit__(self, *_):
            etat.actifs -= 1

        async def aiter_lines(self):
            fragments = etat.fragments
            if callable(fragments):
                fragments = fragments(self.numero)
            if fragments is None:
                fragments = (
                    [
                        {"content": "Un conseil"},
                        {"content": " utile. Ensuite"},
                        {"content": " ceci ne doit pas être consommé."},
                    ]
                    if self.numero == 0
                    else [{"content": ", pratique."}]
                )
            for message in fragments:
                yield json.dumps({"message": message})
            yield json.dumps({"done": True})

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def stream(self, *_, json):
            numero = len(etat.requetes)
            etat.requetes.append(deepcopy(json))
            return Flux(numero)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(
        "diapason.engine.scheduling.scheduler_for", lambda _: Ordonnanceur()
    )
    return etat


@pytest.mark.asyncio
@pytest.mark.parametrize("speculation", [False, True])
async def test_la_phrase_libere_le_gpu_et_la_suite_reprend_son_vrai_prefixe(
    transport, speculation
):
    """§100 — même trajet en adoption spéculative, sans reprise avant la voix."""
    llm = v._default_llm("qwen3.5:9b", "Contexte complet", pause_phrases=True)
    s = v.LocalVoiceSession(
        stt=lambda _: "", llm=llm, tts=lambda _: b"", conversation_seule=True
    )
    phrases = []

    class Voix:
        lecture_anticipee = True

        async def morceaux(self, phrase):
            assert transport.actifs == 0 and transport.creneaux == 0, (
                "pas de calcul retenu pendant Orion"
            )
            if not phrases:
                assert len(transport.requetes) == 1, (
                    "la suite attend la première phrase audio"
                )
            phrases.append(phrase)
            yield b"\0\0" * 2400

    s._tts = None
    s._tts_flux = Voix()
    spec = None
    if speculation:
        spec = v._SpecTurn("Explique.")
        spec.source = llm(s._turn_messages("Explique."))
        spec.drainer = asyncio.create_task(s._drain_speculative(spec, spec.source))
    await asyncio.wait_for(s._respond_to_text("Explique.", spec_llm=spec), 2)
    assert phrases == ["Un conseil utile.", "Ensuite, pratique."], (
        "ni mot perdu, ni répétition"
    )
    debut, reprise = transport.requetes
    assert reprise["messages"] == debut["messages"] + [
        {"role": "assistant", "content": "Un conseil utile. Ensuite"}
    ], "le mot déjà reçu après la ponctuation appartient au préfixe"
    assert s._history[-1]["content"] == "Un conseil utile. Ensuite, pratique."


@pytest.mark.asyncio
async def test_une_annulation_en_pause_ne_relance_jamais_le_modele(transport):
    """§100 — l'ancien tour ne doit pas repartir après une interruption."""
    q = v._default_llm("qwen3.5:9b", "Contexte", pause_phrases=True)([])
    assert await asyncio.wait_for(q.get(), 1) == "Un conseil"
    assert await asyncio.wait_for(q.get(), 1) == " utile. Ensuite"
    assert transport.actifs == transport.creneaux == 0
    q.abort()
    assert await asyncio.wait_for(q.get(), 1) is None
    q.reprendre()
    await asyncio.sleep(0)
    assert len(transport.requetes) == 1, "aucune reprise après barge-in"


@pytest.mark.asyncio
async def test_une_reponse_portant_un_outil_est_livree_sans_coupure(transport):
    """§100 — ne jamais interrompre les arguments structurés d'un outil."""
    outil = {"function": {"name": "current_time", "arguments": {}}}
    transport.fragments = [{"content": "Je vérifie. ", "tool_calls": [outil]}]
    q = v._default_llm("qwen3.5:9b", "Contexte", [{}], pause_phrases=True)([])
    assert await asyncio.wait_for(q.get(), 1) == "Je vérifie. "
    assert await asyncio.wait_for(q.get(), 1) == ("tools", [outil])
    assert await asyncio.wait_for(q.get(), 1) is None
    assert len(transport.requetes) == 1, "un appel d'outil n'est ni fragmenté ni rejoué"


@pytest.mark.asyncio
async def test_une_introduction_garde_son_exemple_avant_de_parler(transport):
    """§100 — les deux-points ne fabriquent pas un départ suivi de silence."""
    transport.fragments = [
        {"content": "Dites à voix haute : "},
        {"content": "I would like a coffee; "},
        {"content": "puis répétez."},
    ]
    llm = v._default_llm("qwen3.5:9b", "Contexte", pause_phrases=True)
    s = v.LocalVoiceSession(stt=lambda _: "", llm=llm, tts=lambda _: b"")
    phrases = []

    class Voix:
        lecture_anticipee = True

        async def morceaux(self, phrase):
            assert transport.actifs == 0, "la réponse est complète avant cette lecture"
            phrases.append(phrase)
            yield b"\0\0" * 2400

    s._tts = None
    s._tts_flux = Voix()
    await asyncio.wait_for(s._respond_to_text("Un exemple ?"), 2)
    assert phrases == ["Dites à voix haute : I would like a coffee; puis répétez."], (
        "une phrase complète, sans départ isolé sur une introduction"
    )
    assert len(transport.requetes) == 1, "pas de reprise artificielle à deux-points"


@pytest.mark.asyncio
async def test_les_reprises_successives_gardent_tout_le_prefixe(transport):
    """§100 — ne pas remplacer le début de réponse par la seule dernière phrase."""
    transport.fragments = lambda numero: [
        {"content": ["Un. Deux", ". Trois", "."][numero]}
    ]
    mesures = {}
    q = v._default_llm("qwen3.5:9b", "Contexte", pause_phrases=True, mesures=mesures)(
        [{"role": "user", "content": "Compte jusqu'à trois."}]
    )
    morceaux = []
    while (fragment := await asyncio.wait_for(q.get(), 1)) is not None:
        assert transport.actifs == 0, "pas de concurrence pendant cette phrase"
        morceaux.append(fragment)
        q.reprendre()
    assert "".join(morceaux) == "Un. Deux. Trois.", "ni répétition ni perte"
    assert transport.requetes[1]["messages"][-1]["content"] == "Un. Deux"
    assert transport.requetes[2]["messages"][-1]["content"] == "Un. Deux. Trois"
    assert [r["options"]["num_predict"] for r in transport.requetes] == [320, 319, 318]
    assert mesures["rounds"] == 3 and mesures["llm_pauses"] == 2, (
        "le diagnostic ne doit pas omettre les flux sans chunk terminal"
    )


@pytest.mark.asyncio
async def test_les_pauses_ne_creent_pas_une_boucle_sans_fin(transport):
    """§100 — une génération répétitive ne multiplie pas les requêtes indéfiniment."""
    transport.fragments = [{"content": "Encore. "}]
    q = v._default_llm("qwen3.5:9b", "Contexte", pause_phrases=True)([])
    morceaux = []
    while (fragment := await asyncio.wait_for(q.get(), 1)) is not None:
        morceaux.append(fragment)
        q.reprendre()
    assert len(transport.requetes) == 9, "huit pauses, puis une passe complète"
    assert "".join(morceaux) == "Encore. " * 9, "la dernière passe reste livrée"


@pytest.mark.asyncio
async def test_les_guillemets_ne_font_pas_attendre_la_traduction(transport):
    """§100 — l'exemple anglais était retenu jusqu'à la fin de sa traduction."""
    transport.fragments = lambda numero: [
        {
            "content": [
                'Répète cette phrase : "I like coffee." Cela',
                ' signifie : "J’aime le café".',
            ][numero]
        }
    ]
    s = v.LocalVoiceSession(
        stt=lambda _: "",
        llm=v._default_llm("qwen3.5:9b", "Contexte", pause_phrases=True),
        tts=lambda _: b"",
    )
    phrases = []

    class Voix:
        lecture_anticipee = True

        async def morceaux(self, phrase):
            assert transport.actifs == 0, "la frontière libère le modèle avant Orion"
            if not phrases:
                assert len(transport.requetes) == 1, (
                    "l'exemple n'attend pas sa traduction"
                )
            phrases.append(phrase)
            yield b"\0\0" * 2400

    s._tts = None
    s._tts_flux = Voix()
    await asyncio.wait_for(s._respond_to_text("Un exemple ?"), 2)
    assert phrases == [
        'Répète cette phrase : "I like coffee."',
        'Cela signifie : "J’aime le café".',
    ], "garder les deux langues et toutes leurs ponctuations"
