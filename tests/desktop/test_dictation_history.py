"""The local dictation history — bounded, corruption-tolerant, local-only."""

from __future__ import annotations

import json

from diapason.desktop.dictation_history import (
    DictationEntry,
    append_entry,
    clear_history,
    load_history,
    stats,
)


def _entry(text="bonjour", ts=1000.0, **kw):
    return DictationEntry(text=text, timestamp=ts, **kw)


def test_roundtrip_newest_first(tmp_path):
    p = tmp_path / "h.jsonl"
    append_entry(_entry("premier", 1.0), path=p)
    append_entry(_entry("deuxieme", 2.0), path=p)

    entries = load_history(p)
    assert [e.text for e in entries] == ["deuxieme", "premier"]


def test_chars_is_derived_when_absent():
    assert _entry("douze chars").chars == len("douze chars")


def test_history_is_bounded(tmp_path):
    """An all-day dictation tool must not accumulate every sentence forever."""
    p = tmp_path / "h.jsonl"
    for i in range(20):
        append_entry(_entry(f"phrase {i}", float(i)), path=p, max_entries=5)

    entries = load_history(p)
    assert len(entries) == 5
    # The newest survived, the oldest were dropped.
    assert entries[0].text == "phrase 19"
    assert all("phrase 1" != e.text for e in entries)


def test_a_corrupt_line_does_not_destroy_the_history(tmp_path):
    p = tmp_path / "h.jsonl"
    append_entry(_entry("bon", 1.0), path=p)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("{ceci n'est pas du json\n")
    append_entry(_entry("aussi bon", 3.0), path=p)

    texts = [e.text for e in load_history(p)]
    assert texts == ["aussi bon", "bon"]


def test_missing_file_is_empty_not_an_error(tmp_path):
    assert load_history(tmp_path / "absent.jsonl") == []


def test_append_never_raises_on_unwritable_path(tmp_path):
    """Losing a history line must not break a dictation that worked."""
    bad = tmp_path / "no-such-dir" / "sub" / "h.jsonl"
    bad.parent.parent.mkdir()
    bad.parent.touch()  # a FILE where a directory is needed
    append_entry(_entry("x"), path=bad)  # must not raise


def test_limit_returns_only_the_newest(tmp_path):
    p = tmp_path / "h.jsonl"
    for i in range(5):
        append_entry(_entry(f"p{i}", float(i)), path=p)
    assert [e.text for e in load_history(p, limit=2)] == ["p4", "p3"]


def test_clear_removes_the_file(tmp_path):
    p = tmp_path / "h.jsonl"
    append_entry(_entry("x"), path=p)
    assert clear_history(p) is True
    assert load_history(p) == []
    assert clear_history(p) is False  # already gone


def test_entries_are_plain_json_lines(tmp_path):
    """Readable and greppable by the user — it is their data."""
    p = tmp_path / "h.jsonl"
    append_entry(_entry("accentué é", 1.0, app="Notes"), path=p)
    raw = p.read_text(encoding="utf-8").strip()
    data = json.loads(raw)
    assert data["text"] == "accentué é"  # not \u-escaped
    assert data["app"] == "Notes"


def test_stats_reports_only_what_the_data_supports():
    entries = [
        _entry("douze chars.", 1.0, duration_s=2.0),
        _entry("abc", 2.0, duration_s=1.0),
    ]
    s = stats(entries)
    assert s["count"] == 2
    assert s["total_chars"] == len("douze chars.") + 3
    assert s["total_seconds"] == 3.0
    # No invented words-per-minute: the data has no speaking-time denominator.
    assert "wpm" not in s


def test_stats_of_nothing_is_zeroes():
    assert stats([])["count"] == 0
    assert stats([])["avg_chars"] == 0.0
