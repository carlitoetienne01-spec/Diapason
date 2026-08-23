"""L'historique des échanges vocaux — traces.db, agent='voice'.

La voix ne laissait aucune persistance serveur : la consolidation nocturne
ne relisait que le chat. Chaque échange abouti rejoint désormais le même
magasin, étiqueté, pour que la nuit relise AUSSI ce qui s'est dit.
Le conftest du dossier coupe la résolution par la config : ces tests
injectent leur magasin en tmp_path, jamais le vrai.
"""

from __future__ import annotations

import pytest

from diapason.traces.store import TraceStore

from .test_local_voice import END_OF_TURN_S, Harness, pcm


def _armer(session, tmp_path):
    magasin = TraceStore(tmp_path / "traces.db")
    session._magasin_traces_obj = magasin
    session._magasin_traces_resolu = True
    return magasin


@pytest.mark.asyncio
async def test_un_tour_complet_ecrit_son_echange(tmp_path):
    harness = Harness(answer="Bonjour Carlito. Oui, je vais bien.")
    magasin = _armer(harness.session, tmp_path)

    await harness.session.send_audio(pcm(0.6))
    await harness.session.send_audio(pcm(END_OF_TURN_S + 0.1, amplitude=0.0))
    assert harness.session._respond_task is not None
    await harness.session._respond_task

    traces = magasin.list_traces()
    assert len(traces) == 1
    assert traces[0].agent == "voice"
    assert "diapason" in traces[0].query.lower()
    assert "je vais bien" in traces[0].result.lower()
    assert traces[0].started_at <= traces[0].ended_at


def test_sans_magasin_le_journal_se_tait(tmp_path):
    harness = Harness()
    # le conftest a coupé la résolution : aucun magasin, aucun plantage
    harness.session._journaliser_echange("bonjour", "salut", duree_s=1.0)


def test_le_vide_ne_s_ecrit_pas(tmp_path):
    harness = Harness()
    magasin = _armer(harness.session, tmp_path)
    harness.session._journaliser_echange("bonjour", "   ")
    harness.session._journaliser_echange("  ", "salut")
    assert magasin.list_traces() == []


def test_la_consolidation_relit_la_voix(tmp_path):
    """Le point de tout ça : la passe nocturne voit l'échange vocal."""
    import json
    from datetime import date

    from diapason.heartbeat.consolidation import consolider_le_jour
    from diapason.memory.store import LocalFactStore

    harness = Harness()
    magasin = _armer(harness.session, tmp_path)
    harness.session._journaliser_echange(
        "Diapason, rappelle-toi que je pars à Montréal vendredi.",
        "C'est noté, départ vendredi pour Montréal.",
    )
    assert magasin.list_traces()[0].agent == "voice"

    faits = LocalFactStore(tmp_path / "faits.jsonl")
    resultat = consolider_le_jour(
        date.today(),
        chemin_traces=tmp_path / "traces.db",
        generer=lambda _m: json.dumps(
            {"faits": ["Carlito part à Montréal vendredi."], "resume": "Départ préparé."}
        ),
        magasin_faits=faits,
        chemin_journal=tmp_path / "journal.md",
    )
    assert resultat.echanges_lus == 1
    assert resultat.faits_ajoutes == 1
