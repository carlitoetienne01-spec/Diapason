"""Tests for ScanChunksTool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from diapason.connectors.store import KnowledgeStore
from diapason.core.registry import ToolRegistry


@pytest.fixture()
def store(tmp_path: Path) -> KnowledgeStore:
    ks = KnowledgeStore(str(tmp_path / "test.db"))
    ks.store("Met with Sequoia about Series A", source="granola", doc_type="document")
    ks.store("Fundraising discussion with a16z", source="granola", doc_type="document")
    ks.store("Weekly standup notes", source="granola", doc_type="document")
    ks.store("Trip to Spain with family", source="imessage", doc_type="message")
    return ks


def _fake_engine() -> MagicMock:
    engine = MagicMock()
    engine.generate.return_value = {
        "content": "Found: Sequoia Series A discussion, a16z fundraising",
        "usage": {},
    }
    return engine


def test_scan_finds_semantic_matches(store: KnowledgeStore) -> None:
    from diapason.tools.scan_chunks import ScanChunksTool

    engine = _fake_engine()
    tool = ScanChunksTool(store=store, engine=engine, model="test")
    result = tool.execute(question="Which VCs have I spoken with?")
    assert result.success
    assert "Sequoia" in result.content or "Found" in result.content
    assert engine.generate.called


def test_scan_respects_source_filter(store: KnowledgeStore) -> None:
    from diapason.tools.scan_chunks import ScanChunksTool

    engine = _fake_engine()
    tool = ScanChunksTool(store=store, engine=engine, model="test")
    result = tool.execute(question="What trips?", source="imessage")
    assert result.success
    call_args = engine.generate.call_args
    messages = call_args[0][0] if call_args[0] else call_args[1].get("messages", [])
    all_content = str(messages)
    assert "Spain" in all_content


def test_scan_empty_store(tmp_path: Path) -> None:
    from diapason.tools.scan_chunks import ScanChunksTool

    ks = KnowledgeStore(str(tmp_path / "empty.db"))
    engine = _fake_engine()
    tool = ScanChunksTool(store=ks, engine=engine, model="test")
    result = tool.execute(question="Anything?")
    assert result.success
    assert "no chunks" in result.content.lower() or result.content == ""


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

    charge = importlib.import_module("diapason.tools.scan_chunks")
    ToolRegistry.clear()
    module = importlib.reload(charge)

    assert ToolRegistry.contains("scan_chunks"), (
        "l'import du module doit SUFFIRE à enregistrer l'outil"
    )
    assert ToolRegistry.get("scan_chunks") is module.ScanChunksTool, (
        "la clé doit pointer sur LA classe du module, pas sur autre chose"
    )
