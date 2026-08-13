from __future__ import annotations

from diapason.desktop.app_index import MacAppIndex


def test_index_caches_scan(monkeypatch):
    index = MacAppIndex(ttl_s=300)
    calls = []

    def scan():
        calls.append(True)
        return ("Google Chrome", "Notes")

    monkeypatch.setattr(index, "_scan", scan)
    assert index.resolve("notes") == "Notes"
    assert index.resolve("chrome") == "Google Chrome"
    assert len(calls) == 1


def test_app_suffix_is_removed_safely(monkeypatch):
    index = MacAppIndex()
    monkeypatch.setattr(index, "applications", lambda: ("WhatsApp",))
    assert index.resolve("WhatsApp.app") == "WhatsApp"
