"""La branche autonome de knowledge_search — la pile hybride du chat.

L'outil existait, infirme : sans magasin injecté il répondait « No knowledge
store configured » — c'est pourquoi la trousse ne l'avait jamais pris. Nu,
il monte désormais la pile hybride lui-même et parle français.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from diapason.connectors.hybrid_search import SearchHit
from diapason.tools.knowledge_search import KnowledgeSearchTool


def _touche(titre, extrait, source="obsidian", score=0.8):
    return SearchHit(
        chunk_id="c1",
        document_id="d1",
        chunk_idx=0,
        title=titre,
        content_snippet=extrait,
        source=source,
        timestamp="2026-08-20T10:00:00",
        participants=[],
        score=score,
        bm25_score=score,
        vector_score=score,
    )


def test_nu_il_cherche_en_hybride_et_parle_francais():
    outil = KnowledgeSearchTool()
    hybride = MagicMock()
    hybride.search.return_value = [
        _touche("Plan d'apprentissage", "Étudier le CSS moderne chaque matin."),
        _touche(
            "Journal", "Le parcours OpenClassrooms avance bien.", source="apple_notes"
        ),
    ]
    outil._hybride = hybride

    resultat = outil.execute(query="parcours apprentissage")

    assert resultat.success
    assert "2 extrait(s)" in resultat.content
    assert "[obsidian] Plan d'apprentissage" in resultat.content
    assert resultat.metadata["num_results"] == 2
    assert resultat.metadata["resultats"][1]["source"] == "apple_notes"
    assert hybride.search.call_args.kwargs["limit"] == 10


def test_les_filtres_dates_et_source_passent_a_la_pile():
    outil = KnowledgeSearchTool()
    hybride = MagicMock()
    hybride.search.return_value = []
    outil._hybride = hybride

    resultat = outil.execute(
        query="notes", source="obsidian", since="2026-08-01", top_k=3
    )

    assert resultat.success
    assert "Rien trouvé" in resultat.content
    kwargs = hybride.search.call_args.kwargs
    assert kwargs["sources"] == ["obsidian"]
    assert kwargs["limit"] == 3
    assert kwargs["time_range"][0].year == 2026


def test_une_date_illisible_ne_fait_pas_tomber_la_recherche():
    outil = KnowledgeSearchTool()
    hybride = MagicMock()
    hybride.search.return_value = []
    outil._hybride = hybride

    resultat = outil.execute(query="notes", since="pas-une-date")
    assert resultat.success
    assert hybride.search.call_args.kwargs["time_range"] is None


def test_pile_impossible_repond_sans_lever(monkeypatch):
    outil = KnowledgeSearchTool()
    monkeypatch.setattr(outil, "_pile_hybride", lambda: None)
    resultat = outil.execute(query="notes")
    assert not resultat.success
    assert "inaccessible" in resultat.content


def test_le_magasin_injecte_garde_l_ancien_chemin():
    magasin = MagicMock()
    magasin.retrieve.return_value = []
    outil = KnowledgeSearchTool(store=magasin)
    resultat = outil.execute(query="quoi que ce soit")
    assert resultat.success
    magasin.retrieve.assert_called_once()
