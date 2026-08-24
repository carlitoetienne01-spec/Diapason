"""La consolidation nocturne : collecte, extraction, dépôt, résumé.

Aucun Ollama, aucun ~/.diapason : traces.db en tmp_path, générateur factice
injecté, magasin de faits local en tmp_path — la convention du dossier.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from diapason.core.types import Trace
from diapason.heartbeat.consolidation import (
    Echange,
    collecter_le_jour,
    composer_messages,
    consolider_le_jour,
    interpreter,
)
from diapason.memory.store import LocalFactStore
from diapason.traces.store import TraceStore

JOUR = date(2026, 8, 23)


def _tracer(chemin, *, heure, question, reponse, trace_id):
    quand = datetime(JOUR.year, JOUR.month, JOUR.day, heure).timestamp()
    TraceStore(chemin).save(
        Trace(
            trace_id=trace_id,
            query=question,
            result=reponse,
            agent="server",
            started_at=quand,
            ended_at=quand + 2.0,
        )
    )


class TestCollecter:
    def test_la_journee_se_lit_dans_l_ordre_du_vecu(self, tmp_path):
        chemin = tmp_path / "traces.db"
        _tracer(chemin, heure=15, question="Après-midi ?", reponse="Oui.", trace_id="t2")
        _tracer(chemin, heure=9, question="Matin ?", reponse="Bonjour.", trace_id="t1")
        echanges = collecter_le_jour(chemin, JOUR)
        assert [e.question for e in echanges] == ["Matin ?", "Après-midi ?"]

    def test_les_autres_jours_et_les_vides_restent_dehors(self, tmp_path):
        chemin = tmp_path / "traces.db"
        _tracer(chemin, heure=9, question="Aujourd'hui", reponse="Oui.", trace_id="t1")
        _tracer(chemin, heure=9, question="Sans réponse", reponse="  ", trace_id="t2")
        veille = datetime(2026, 8, 22, 9).timestamp()
        TraceStore(chemin).save(
            Trace(trace_id="t3", query="Hier", result="Vieux.", started_at=veille)
        )
        echanges = collecter_le_jour(chemin, JOUR)
        assert [e.question for e in echanges] == ["Aujourd'hui"]


class TestInterpreter:
    def test_le_json_nu_passe(self):
        faits, resume = interpreter('{"faits": ["Il aime le café."], "resume": "Bonne journée."}')
        assert faits == ["Il aime le café."]
        assert resume == "Bonne journée."

    def test_le_bavardage_autour_du_json_est_pardonne(self):
        brut = 'Voici :\n```json\n{"faits": ["A"], "resume": "R"}\n``` merci'
        assert interpreter(brut) == (["A"], "R")

    def test_l_illisible_rend_le_vide_sans_lever(self):
        assert interpreter("désolé, aucune idée") == ([], "")
        assert interpreter("") == ([], "")

    def test_les_faits_non_textuels_sont_rayes(self):
        faits, _ = interpreter(json.dumps({"faits": ["Bon", 42, "  "], "resume": ""}))
        assert faits == ["Bon"]


class TestConsolider:
    def _journee(self, tmp_path):
        chemin = tmp_path / "traces.db"
        _tracer(
            chemin,
            heure=10,
            question="Je commence le parcours OpenClassrooms en septembre.",
            reponse="Noté, bon courage !",
            trace_id="t1",
        )
        return chemin

    def test_les_faits_se_deposent_et_le_resume_s_ecrit(self, tmp_path):
        traces = self._journee(tmp_path)
        magasin = LocalFactStore(tmp_path / "faits.jsonl")
        journal = tmp_path / "journal.md"

        vus = {}

        def generer(messages):
            vus["messages"] = messages
            return json.dumps(
                {
                    "faits": ["Carlito commence le parcours OpenClassrooms en septembre 2026."],
                    "resume": "Une journée de préparation du parcours.",
                }
            )

        resultat = consolider_le_jour(
            JOUR,
            chemin_traces=traces,
            generer=generer,
            magasin_faits=magasin,
            chemin_journal=journal,
        )

        assert resultat.faits_ajoutes == 1
        assert resultat.echanges_lus == 1
        assert magasin.count() == 1
        assert "## 2026-08-23" in journal.read_text()
        assert "préparation du parcours" in journal.read_text()
        # la journée transcrite est bien passée au modèle
        transcription = vus["messages"][1].content
        assert "OpenClassrooms" in transcription and "10:00" in transcription

    def test_deux_nuits_ne_deposent_pas_deux_fois_le_meme_fait(self, tmp_path):
        traces = self._journee(tmp_path)
        magasin = LocalFactStore(tmp_path / "faits.jsonl")
        journal = tmp_path / "journal.md"
        generer = lambda _m: json.dumps({"faits": ["Fait unique."], "resume": "R."})  # noqa: E731

        premier = consolider_le_jour(
            JOUR, chemin_traces=traces, generer=generer,
            magasin_faits=magasin, chemin_journal=journal,
        )
        second = consolider_le_jour(
            JOUR, chemin_traces=traces, generer=generer,
            magasin_faits=magasin, chemin_journal=journal,
        )
        assert premier.faits_ajoutes == 1
        assert second.faits_ajoutes == 0
        assert magasin.count() == 1

    def test_une_journee_muette_ne_touche_a_rien(self, tmp_path):
        traces = tmp_path / "traces.db"
        TraceStore(traces)  # base vide
        journal = tmp_path / "journal.md"

        def generer(_m):
            raise AssertionError("le modèle ne doit pas être appelé")

        resultat = consolider_le_jour(
            JOUR, chemin_traces=traces, generer=generer,
            magasin_faits=None, chemin_journal=journal,
        )
        assert resultat.vide
        assert not journal.exists()

    def test_un_modele_incoherent_ne_salit_rien(self, tmp_path):
        traces = self._journee(tmp_path)
        magasin = LocalFactStore(tmp_path / "faits.jsonl")
        journal = tmp_path / "journal.md"
        resultat = consolider_le_jour(
            JOUR, chemin_traces=traces, generer=lambda _m: "grognement illisible",
            magasin_faits=magasin, chemin_journal=journal,
        )
        assert resultat.faits_ajoutes == 0
        assert magasin.count() == 0
        assert not journal.exists()
        assert resultat.echanges_lus == 1


def test_composer_borne_la_transcription():
    echanges = [
        Echange(question="Q" * 900, reponse="R" * 1200, quand=datetime(2026, 8, 23, 9))
    ]
    messages = composer_messages(echanges, JOUR)
    assert len(messages) == 2
    assert "2026-08-23" in messages[0].content
    assert "faits" in messages[0].content and "resume" in messages[0].content


class TestPurgeDuBanc:
    """293 « who are you? » → « Hello world » au modèle test-model noyaient
    les vraies conversations (23 août 2026) : la mémoire n'apprend que du
    vécu, jamais du banc d'essai."""

    def test_le_banc_se_reconnait_au_modele(self):
        from diapason.heartbeat.consolidation import est_trace_de_banc

        assert est_trace_de_banc("test-model")
        assert est_trace_de_banc("TEST")
        assert not est_trace_de_banc("qwen3.5:9b")
        assert not est_trace_de_banc("")

    def test_la_collecte_ignore_le_banc(self, tmp_path):
        chemin = tmp_path / "traces.db"
        quand = datetime(JOUR.year, JOUR.month, JOUR.day, 9).timestamp()
        magasin = TraceStore(chemin)
        magasin.save(Trace(trace_id="vrai", query="Bonjour", result="Salut.",
                           model="qwen3.5:9b", started_at=quand))
        magasin.save(Trace(trace_id="banc", query="who are you?", result="Hello world",
                           model="test-model", started_at=quand + 60))
        echanges = collecter_le_jour(chemin, JOUR)
        assert [e.question for e in echanges] == ["Bonjour"]
