"""Tests for KnowledgeSQLTool."""

from __future__ import annotations

from pathlib import Path

import pytest

from diapason.connectors.store import KnowledgeStore
from diapason.core.registry import ToolRegistry


@pytest.fixture()
def store(tmp_path: Path) -> KnowledgeStore:
    ks = KnowledgeStore(str(tmp_path / "test.db"))
    ks.store("Hello from Alice", source="imessage", author="Alice", doc_type="message")
    ks.store(
        "Hello from Alice again", source="imessage", author="Alice", doc_type="message"
    )
    ks.store("Meeting notes Q1", source="granola", author="Bob", doc_type="document")
    ks.store("Email about Spain trip", source="gmail", author="Carol", doc_type="email")
    return ks


def test_select_count(store: KnowledgeStore) -> None:
    from diapason.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(query="SELECT COUNT(*) as total FROM knowledge_chunks")
    assert result.success
    assert "4" in result.content


def test_group_by_author(store: KnowledgeStore) -> None:
    from diapason.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(
        query=(
            "SELECT author, COUNT(*) as n "
            "FROM knowledge_chunks "
            "GROUP BY author ORDER BY n DESC"
        )
    )
    assert result.success
    assert "Alice" in result.content
    assert "2" in result.content


def test_rejects_non_select(store: KnowledgeStore) -> None:
    from diapason.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(query="DELETE FROM knowledge_chunks")
    assert not result.success
    assert "read-only" in result.content.lower() or "SELECT" in result.content


def test_rejects_drop(store: KnowledgeStore) -> None:
    from diapason.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(query="DROP TABLE knowledge_chunks")
    assert not result.success


def test_allows_select_with_keyword_substring(store: KnowledgeStore) -> None:
    """A read-only SELECT must not be rejected because a column/alias merely
    contains a write keyword as a substring (e.g. 'created' -> CREATE)."""
    from diapason.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(query="SELECT author AS created_author FROM knowledge_chunks")
    assert result.success, result.content
    assert "Alice" in result.content


def test_allows_keyword_inside_string_literal(store: KnowledgeStore) -> None:
    """A write keyword appearing only inside a string literal must not be
    treated as a forbidden statement."""
    from diapason.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(
        query="SELECT content FROM knowledge_chunks WHERE content LIKE '%delete%'"
    )
    assert result.success, result.content


def test_rejects_multi_statement(store: KnowledgeStore) -> None:
    """Multi-statement strings fail with a ToolResult, not an exception."""
    from diapason.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(query="SELECT 1; VACUUM")
    assert not result.success
    assert "error" in result.content.lower()


def test_handles_bad_sql(store: KnowledgeStore) -> None:
    from diapason.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(query="SELECT * FROM nonexistent_table")
    assert not result.success


def test_filter_by_source(store: KnowledgeStore) -> None:
    from diapason.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(
        query="SELECT title, author FROM knowledge_chunks WHERE source = 'gmail'"
    )
    assert result.success
    assert "Carol" in result.content


def test_registered() -> None:
    """Le MODULE inscrit son outil au registre, et sous sa vraie classe.

    Deux corrections successives d'un même test creux. Le 13 septembre 2026
    pour `knowledge_sql`, le 22 au soir pour `scan_chunks` : l'appel nu à
    `register_value` a été mis sous garde (`if not contains(...)`), ce qui a
    bien rendu le test déterministe — et l'a rendu INCAPABLE d'échouer. La
    fixture autouse `_clean_registries` (`tests/conftest.py:78`) vide le
    registre avant CHAQUE test, et un module déjà chargé ne réexécute pas son
    décorateur : la clé est donc toujours absente à l'entrée, la garde la pose
    elle-même, et les assertions relisent ce que le test vient d'écrire.

    Éprouvé le 22/09 au soir par un greffon qui neutralise
    `@ToolRegistry.register` pour ces deux clés : les deux tests restaient
    VERTS. §100 — la preuve vient du récepteur, pas de l'appelant.

    Le registre est vidé JUSTE AVANT le rechargement — explicitement, sans se
    fier à l'ordre des fixtures — pour que le décorateur du module soit la
    seule chose au monde qui puisse poser cette clé. Sans ce vidage, le
    rechargement d'un module encore absent de `sys.modules` se heurtait à
    l'inscription que son propre import venait de faire.
    """
    import importlib

    charge = importlib.import_module("diapason.tools.knowledge_sql")
    ToolRegistry.clear()
    module = importlib.reload(charge)

    assert ToolRegistry.contains("knowledge_sql"), (
        "l'import du module doit SUFFIRE à enregistrer l'outil"
    )
    assert ToolRegistry.get("knowledge_sql") is module.KnowledgeSQLTool, (
        "la clé doit pointer sur LA classe du module, pas sur autre chose"
    )
