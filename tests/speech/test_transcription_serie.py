"""§100 — une annulation ne fait pas disparaître une inférence native."""

import asyncio
import logging
import threading

import pytest

from diapason.speech.realtime.transcription_serie import TranscriptionSerie


@pytest.mark.asyncio
async def test_annuler_un_partiel_ne_libere_pas_le_cpu_avant_sa_fin(caplog):
    caplog.set_level(
        logging.INFO, logger="diapason.speech.realtime.transcription_serie"
    )
    entre = threading.Event()
    sortir = threading.Event()
    appels = []

    def calcul(audio):
        appels.append(audio)
        if audio == b"partiel":
            entre.set()
            assert sortir.wait(2), "le banc doit libérer son calcul bloquant"
        return audio.decode()

    serie = TranscriptionSerie(calcul)
    partiel = asyncio.create_task(serie(b"partiel"))
    final = None
    try:
        assert await asyncio.to_thread(entre.wait, 2), "le calcul a démarré"
        partiel.cancel()
        with pytest.raises(asyncio.CancelledError):
            await partiel
        assert not caplog.records, "annuler l'attente ne termine pas le vrai calcul"
        final = asyncio.create_task(serie(b"final"))
        await asyncio.sleep(0)
        assert appels == [b"partiel"], "aucune inférence simultanée"
        sortir.set()
        assert await asyncio.wait_for(final, 2) == "final"
        assert appels == [b"partiel", b"final"]
        mesures = [r.message for r in caplog.records if "stt_compute" in r.message]
        assert len(mesures) == 2, "le partiel abandonné garde sa mesure native"
        assert all("queue_ms=" in m and "compute_ms=" in m for m in mesures)
        assert all("partiel" not in m for m in mesures), "aucune parole au journal"
    finally:
        sortir.set()
        await asyncio.gather(
            partiel, *([final] if final else []), return_exceptions=True
        )


@pytest.mark.asyncio
async def test_un_calcul_en_attente_annule_ne_transcrit_jamais():
    entre = threading.Event()
    sortir = threading.Event()
    appels = []

    def calcul(audio):
        appels.append(audio)
        if len(appels) == 1:
            entre.set()
            assert sortir.wait(2)
        return "ok"

    serie = TranscriptionSerie(calcul)
    premier = asyncio.create_task(serie(b"actif"))
    try:
        assert await asyncio.to_thread(entre.wait, 2)
        obsolete = asyncio.create_task(serie(b"obsolete"))
        await asyncio.sleep(0)
        obsolete.cancel()
        await asyncio.gather(obsolete, return_exceptions=True)
        sortir.set()
        await premier
        assert await serie(b"recent") == "ok"
        assert appels == [b"actif", b"recent"], "pas de file de paroles périmées"
    finally:
        sortir.set()
        await asyncio.gather(premier, return_exceptions=True)


@pytest.mark.asyncio
async def test_un_echec_libere_la_reconnaissance():
    def calcul(audio):
        if not audio:
            raise ValueError("échec du modèle")
        return "reprise"

    serie = TranscriptionSerie(calcul)
    with pytest.raises(ValueError, match="modèle"):
        await serie(b"")
    assert await asyncio.wait_for(serie(b"nouvelle phrase"), 2) == "reprise"


@pytest.mark.asyncio
async def test_le_final_depasse_les_partiels_en_attente_sans_doubler_le_calcul():
    """§100 : une finale prioritaire n'est pas une préemption native fictive."""
    entre, sortir = threading.Event(), threading.Event()
    appels = []

    def calcul(audio):
        appels.append(audio)
        if audio == b"actif":
            entre.set()
            assert sortir.wait(2)
        return audio.decode()

    serie = TranscriptionSerie(calcul)
    actif = asyncio.create_task(serie(b"actif", etape="partial"))
    attente = []
    try:
        assert await asyncio.to_thread(entre.wait, 2)
        for nom, etape in [
            (b"partiel", "partial"),
            (b"spec", "speculative"),
            (b"final", "final"),
        ]:
            attente.append(asyncio.create_task(serie(nom, etape=etape)))
            await asyncio.sleep(0)
        assert appels == [b"actif"], "le calcul natif actif reste seul"
        sortir.set()
        await asyncio.wait_for(asyncio.gather(actif, *attente), 2)
        assert appels == [b"actif", b"final", b"spec", b"partiel"], (
            "la parole complète dépasse les sous-titres encore en file"
        )
    finally:
        sortir.set()
        await asyncio.gather(actif, *attente, return_exceptions=True)


@pytest.mark.asyncio
async def test_seul_le_brouillon_utilise_le_calcul_provisoire():
    """§100 : la finale et sa spéculation gardent le même décodage complet."""
    serie = TranscriptionSerie(lambda _: "complet", partiel=lambda _: "brouillon")
    assert await serie(b"son", etape="partial") == "brouillon"
    assert await serie(b"son", etape="speculative") == "complet"
    assert await serie(b"son") == "complet"
