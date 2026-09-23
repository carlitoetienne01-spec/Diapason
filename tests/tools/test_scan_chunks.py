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
    """L'outil est dans le registre — que l'import l'y ait mis ou non.

    La seconde moitié du défaut corrigé pour `knowledge_sql` le 13 septembre
    2026, restée sur place : `scan_chunks.py:22` porte
    `@ToolRegistry.register("scan_chunks")`, donc l'import enregistre — et ce
    test réenregistrait ensuite sans regarder, alors que `register_value`
    refuse un doublon (`core/registry.py:66`).

    Ce qui décide, c'est la fixture autouse `_clean_registries`
    (`tests/conftest.py:78`) : elle vide le registre avant CHAQUE test, et
    l'import de la ligne suivante est un no-op quand un test antérieur du même
    fil a déjà chargé le module. Fil vierge → l'import réenregistre → le test
    levait « already has an entry » ; fil déjà chargé → le registre est vide →
    il passait. Mesuré le 22 septembre 2026 : SEUL, il échouait 3 fois sur 3 ;
    avec le fichier entier, 4 passed — son voisin charge le module à sa place.

    Retirer l'appel ne suffirait pas : après le `clear()`, un import déjà fait
    n'enregistre plus rien, et le test affirmerait « enregistré » sans que
    rien ne le soit (§100 — la preuve vient du récepteur, pas de l'appelant).
    """
    from diapason.tools.scan_chunks import ScanChunksTool

    if not ToolRegistry.contains("scan_chunks"):
        ToolRegistry.register_value("scan_chunks", ScanChunksTool)
    assert ToolRegistry.contains("scan_chunks"), "l'outil doit être enregistré"
    assert ToolRegistry.get("scan_chunks") is ScanChunksTool, (
        "la clé doit pointer sur LA classe, pas seulement exister"
    )
