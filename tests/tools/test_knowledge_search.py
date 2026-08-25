"""Tests for the knowledge_search tool."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from diapason.connectors.store import KnowledgeStore
from diapason.core.registry import ToolRegistry
from diapason.tools.knowledge_search import KnowledgeSearchTool

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    """Return a KnowledgeStore pre-loaded with 3 diverse items."""
    s = KnowledgeStore(db_path=tmp_path / "test_knowledge.db")

    # Item 1 — gmail email from alice
    s.store(
        "Meeting about Kubernetes migration scheduled for next Tuesday.",
        source="gmail",
        doc_type="email",
        title="Re: K8s migration",
        author="alice@example.com",
        url="https://mail.google.com/mail/u/0/#inbox/abc123",
        timestamp="2026-01-15T10:00:00Z",
    )

    # Item 2 — slack message from bob
    s.store(
        "Discussion about K8s costs — we should consider spot instances.",
        source="slack",
        doc_type="message",
        title="#infrastructure",
        author="bob@example.com",
        url="slack://thread/def456",
        timestamp="2026-01-20T14:30:00Z",
    )

    # Item 3 — obsidian document from sarah
    s.store(
        "Research notes on large language model fine-tuning strategies.",
        source="obsidian",
        doc_type="document",
        title="LLM Fine-tuning Notes",
        author="sarah@example.com",
        url="obsidian://vault/llm-notes",
        timestamp="2026-02-01T09:00:00Z",
    )

    yield s
    s.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestKnowledgeSearchTool:
    def test_basic_search(self, store):
        """Search finds the matching document from the 3-item store."""
        tool = KnowledgeSearchTool(store=store)
        result = tool.execute(query="Kubernetes migration")
        assert result.success is True
        assert "Kubernetes" in result.content
        assert result.metadata["num_results"] >= 1

    def test_filter_by_source(self, store):
        """source filter restricts results to gmail only."""
        tool = KnowledgeSearchTool(store=store)
        result = tool.execute(query="Kubernetes", source="gmail")
        assert result.success is True
        assert "gmail" in result.content
        # Every returned result must come from gmail
        assert "slack" not in result.content

    def test_filter_by_author(self, store):
        """author filter restricts results to sarah only."""
        tool = KnowledgeSearchTool(store=store)
        # Use "language model" — FTS5 does not tokenise hyphenated terms like
        # "fine-tuning" as a single token, so we search for a phrase that works.
        result = tool.execute(query="language model", author="sarah@example.com")
        assert result.success is True
        assert "sarah@example.com" in result.content
        assert result.metadata["num_results"] >= 1

    def test_no_results(self, store):
        """Query matching nothing returns success=True with 'No relevant results'."""
        tool = KnowledgeSearchTool(store=store)
        result = tool.execute(query="zzz_nonexistent_xyzzy_12345")
        assert result.success is True
        assert "No relevant results" in result.content
        assert result.metadata["num_results"] == 0

    def test_empty_query(self, store):
        """Empty query string returns success=False."""
        tool = KnowledgeSearchTool(store=store)
        result = tool.execute(query="")
        assert result.success is False
        assert "No query provided" in result.content

    def test_no_store(self, monkeypatch):
        """Nu, l'outil monte sa pile hybride ; pile impossible = échec doux.

        L'ancien contrat — « sans magasin injecté, échec » — était
        l'infirmité qui tenait l'outil hors de la trousse du chat. Le
        monkeypatch simule une pile qui ne se monte pas, SANS toucher au
        vrai ~/.diapason/knowledge.db.
        """
        tool = KnowledgeSearchTool()
        monkeypatch.setattr(tool, "_pile_hybride", lambda: None)
        result = tool.execute(query="kubernetes")
        assert result.success is False
        assert "inaccessible" in result.content

    def test_spec_has_filter_params(self):
        """ToolSpec.parameters includes all required and optional filter fields."""
        tool = KnowledgeSearchTool()
        props = tool.spec.parameters.get("properties", {})
        for field in ("query", "source", "doc_type", "author", "since", "top_k"):
            assert field in props, f"Missing parameter: {field}"
        assert "query" in tool.spec.parameters.get("required", [])
        assert tool.spec.category == "knowledge"

    def test_registry(self):
        """ToolRegistry contains 'knowledge_search' after module import.

        The autouse ``_clean_registries`` fixture clears all registries before
        each test.  Since the module is already cached in ``sys.modules`` a
        plain import won't re-execute the ``@ToolRegistry.register`` decorator,
        so we explicitly reload the module.
        """
        mod_name = "diapason.tools.knowledge_search"
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
        else:
            importlib.import_module(mod_name)

        assert ToolRegistry.contains("knowledge_search")


def test_tool_uses_two_stage_retriever(tmp_path: Path) -> None:
    """KnowledgeSearchTool delegates to TwoStageRetriever when supplied."""
    from diapason.connectors.retriever import TwoStageRetriever

    store = KnowledgeStore(db_path=str(tmp_path / "ts_test.db"))
    store.store(
        content="Deep learning research paper", source="gdrive", doc_type="document"
    )
    retriever = TwoStageRetriever(store=store)
    tool = KnowledgeSearchTool(store=store, retriever=retriever)
    result = tool.execute(query="deep learning")
    assert result.success
    assert result.metadata["num_results"] > 0


class TestLeDocumentEntier:
    """knowledge_get_document : l'extrait de 300 caractères remonte au
    document complet — le dernier kilomètre (Atlas, 25 août 2026)."""

    def test_le_document_revient_entier_avec_son_entete(self, monkeypatch):
        from diapason.tools.knowledge_search import KnowledgeGetDocumentTool

        magasin = MagicMock()
        magasin.get_document.return_value = {
            "doc_id": "gmail:abc",
            "title": "Relevé de mars",
            "author": "banque@x.com",
            "source": "gmail",
            "timestamp": "2026-03-04T10:00:00",
            "url": "https://mail.google.com/mail/u/0/#all/abc",
            "thread_id": "gmail:abc",
            "content": "Le corps complet du relevé.",
            "chunks": 2,
        }
        with patch(
            "diapason.tools.knowledge_search.KnowledgeStore",
            return_value=magasin,
        ):
            r = KnowledgeGetDocumentTool().execute(doc_id="gmail:abc")
        assert r.success
        assert "[gmail] Relevé de mars — banque@x.com (2026-03-04)" in r.content
        assert "Le corps complet du relevé." in r.content
        assert r.metadata["url"].endswith("#all/abc")

    def test_un_long_document_se_tronque_et_le_dit(self, monkeypatch):
        from diapason.tools.knowledge_search import KnowledgeGetDocumentTool

        magasin = MagicMock()
        magasin.get_document.return_value = {
            "doc_id": "d", "title": "t", "author": "", "source": "gmail",
            "timestamp": "", "url": "", "thread_id": "",
            "content": "x" * 50_000, "chunks": 25,
        }
        with patch(
            "diapason.tools.knowledge_search.KnowledgeStore",
            return_value=magasin,
        ):
            r = KnowledgeGetDocumentTool().execute(doc_id="d", max_chars=1000)
        assert r.success and r.metadata["truncated"]
        assert "50000 caractères" in r.content
        assert "max_chars" in r.content  # le remède est dans le message

    def test_un_doc_inconnu_renvoie_vers_la_recherche(self):
        from diapason.tools.knowledge_search import KnowledgeGetDocumentTool

        magasin = MagicMock()
        magasin.get_document.return_value = None
        with patch(
            "diapason.tools.knowledge_search.KnowledgeStore",
            return_value=magasin,
        ):
            r = KnowledgeGetDocumentTool().execute(doc_id="gmail:zzz")
        assert not r.success and "knowledge_search" in r.content

    def test_les_extraits_de_recherche_portent_le_doc_id(self):
        """Sans doc_id/url dans les metadata de knowledge_search, cet outil
        est inatteignable — c'était exactement le trou : hybrid_search les
        portait, le façonnage les jetait."""
        from diapason.connectors.hybrid_search import SearchHit
        from diapason.tools.knowledge_search import KnowledgeSearchTool

        touche = SearchHit(
            chunk_id="c1", document_id="gmail:abc", chunk_idx=0,
            title="Relevé", content_snippet="extrait du relevé",
            source="gmail", timestamp="2026-03-04", participants=[],
            score=0.9, bm25_score=0.5, vector_score=0.4,
            thread_id="gmail:t",
            url="https://mail.google.com/mail/u/0/#all/abc",
        )
        faux_hybride = MagicMock()
        faux_hybride.search.return_value = [touche]
        r = KnowledgeSearchTool()._chercher_en_hybride(
            faux_hybride,
            "relevé",
            top_k=5,
            source=None,
            author=None,
            since=None,
            until=None,
        )
        assert r.success
        extrait = r.metadata["resultats"][0]
        assert extrait["doc_id"] == "gmail:abc"
        assert extrait["url"].endswith("#all/abc")
        assert extrait["thread_id"] == "gmail:t"
