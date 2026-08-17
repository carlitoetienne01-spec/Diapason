"""« Aucun résultat » doit vouloir dire qu'il n'y a rien.

FTS5 lit ``-``, ``:``, ``"``, ``*`` et les mots ``AND``/``OR``/``NOT`` comme
des *opérateurs*. Une requête humaine qui en contient un n'est pas une
recherche vide : c'est une erreur de syntaxe. Le code l'attrapait et rendait
``[]``. L'utilisateur lisait « aucun résultat » à propos d'un document qui
était là — la pire forme de fausse information, parce qu'elle est
indiscernable de la vérité.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import pytest

from diapason.connectors.store import KnowledgeStore, _quote_fts


@pytest.fixture
def store():
    s = KnowledgeStore(db_path=Path(tempfile.mkdtemp()) / "k.db")
    s.store(
        "Compte rendu de la réunion sur le budget marketing du quatrième trimestre.",
        source="reunion-q4",
    )
    s.store("Note sur l'échéance du contrat Legrand-Dupont.", source="contrat")
    return s


class TestLesRequetesOrdinairesTrouvent:
    """Chacune de ces formes rendait zéro résultat. Aucune n'est exotique."""

    @pytest.mark.parametrize(
        "query",
        [
            "budget marketing",  # témoin : marchait déjà
            "Legrand-Dupont",  # trait d'union
            "l'échéance",  # apostrophe
            "réunion: budget",  # deux-points
            "budget marketing.",  # ponctuation finale
        ],
    )
    def test_elle_trouve_le_document(self, store, query):
        assert store.retrieve(query, top_k=5), query


class TestUnVraiVideResteUnVide:
    """La correction ne doit pas rendre la recherche complaisante."""

    def test_un_terme_absent_ne_rend_rien(self, store):
        assert store.retrieve("carotte volante", top_k=5) == []

    def test_une_requete_vide_ne_rend_rien(self, store):
        assert store.retrieve("   ", top_k=5) == []

    @pytest.mark.parametrize("query", ["((", "*", '"', "NOT"])
    def test_les_operateurs_seuls_ne_font_plus_planter(self, store, query, caplog):
        with caplog.at_level(logging.WARNING):
            assert store.retrieve(query, top_k=5) == []
        # Zéro résultat, mais plus zéro *par erreur de syntaxe*.
        assert not [r for r in caplog.records if "FTS search failed" in r.message]


class TestLaCitationConserveLeSensDesTermes:
    def test_les_termes_sont_conjoints_par_defaut(self):
        """FTS5 conjoint par défaut ; citer ne doit pas élargir en douce."""
        assert _quote_fts("budget marketing") == '"budget" AND "marketing"'

    def test_la_recherche_hybride_garde_son_ou_explicite(self):
        """hybrid_search ratisse large et laisse le reclassement trancher."""
        assert _quote_fts("budget marketing", operator="OR") == (
            '"budget" OR "marketing"'
        )

    def test_un_guillemet_perdu_ne_casse_pas_la_citation(self):
        assert _quote_fts('guillemet " perdu') == '"guillemet" AND "perdu"'
