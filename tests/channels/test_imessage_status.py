"""Le constat d'envoi lit chat.db — trois issues, jamais un vide ambigu.

Atlas, 24 août 2026 : « Message sent » se proclamait sur le code retour
d'osascript, alors que Messages échoue parfois en silence (« Not
Delivered »). La base, elle, dit vrai : is_sent, is_delivered, error.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from diapason.channels.imessage_status import (
    _dt_to_apple_ns,
    find_outgoing,
    status_by_guid,
)


def _fausse_chat_db(tmp_path, rangees):
    chemin = tmp_path / "chat.db"
    with sqlite3.connect(chemin) as db:
        db.execute(
            "CREATE TABLE message (ROWID INTEGER PRIMARY KEY, guid TEXT, "
            "text TEXT, date INTEGER, is_from_me INTEGER, is_sent INTEGER, "
            "is_delivered INTEGER, error INTEGER)"
        )
        db.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT)")
        db.execute(
            "CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)"
        )
        db.execute("INSERT INTO chat VALUES (1, '+15145551234')")
        for i, r in enumerate(rangees, start=1):
            db.execute(
                "INSERT INTO message VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (i, r.get("guid", f"g{i}"), r.get("text"), r["date"],
                 r.get("is_from_me", 1), r.get("is_sent", 0),
                 r.get("is_delivered", 0), r.get("error", 0)),
            )
            db.execute("INSERT INTO chat_message_join VALUES (1, ?)", (i,))
    return str(chemin)


def _ns(depuis_s: float) -> int:
    return _dt_to_apple_ns(datetime.now(timezone.utc) - timedelta(seconds=depuis_s))


class TestFindOutgoing:
    def test_le_parti_confirme_se_lit(self, tmp_path):
        base = _fausse_chat_db(
            tmp_path, [{"guid": "abc", "date": _ns(2), "is_sent": 1, "is_delivered": 1}]
        )
        c = find_outgoing("+15145551234", datetime.now(timezone.utc) - timedelta(seconds=30), db_path=base)
        assert c.issue == "found" and c.is_sent and c.is_delivered and not c.error

    def test_le_not_delivered_silencieux_devient_bruyant(self, tmp_path):
        base = _fausse_chat_db(
            tmp_path, [{"guid": "abc", "date": _ns(2), "is_sent": 1, "error": 22}]
        )
        c = find_outgoing("+15145551234", datetime.now(timezone.utc) - timedelta(seconds=30), db_path=base)
        assert c.issue == "found" and c.error == 22

    def test_un_texte_null_ne_cache_pas_la_rangee(self, tmp_path):
        """Sur macOS récent, text est parfois NULL (attributedBody) : le
        constat ne filtre pas dessus."""
        base = _fausse_chat_db(
            tmp_path, [{"guid": "abc", "text": None, "date": _ns(2), "is_sent": 1}]
        )
        c = find_outgoing("+15145551234", datetime.now(timezone.utc) - timedelta(seconds=30), db_path=base)
        assert c.issue == "found"

    def test_un_message_recu_ne_compte_pas(self, tmp_path):
        base = _fausse_chat_db(
            tmp_path, [{"guid": "abc", "date": _ns(2), "is_from_me": 0, "is_sent": 1}]
        )
        c = find_outgoing("+15145551234", datetime.now(timezone.utc) - timedelta(seconds=30), db_path=base)
        assert c.issue == "not_found"

    def test_une_base_illisible_le_dit_sans_confondre(self, tmp_path):
        c = find_outgoing(
            "+15145551234",
            datetime.now(timezone.utc),
            db_path=str(tmp_path / "absente" / "chat.db"),
        )
        assert c.issue == "unreadable" and c.detail


class TestStatusByGuid:
    def test_relire_plus_tard_voit_le_verdict_final(self, tmp_path):
        base = _fausse_chat_db(
            tmp_path, [{"guid": "abc", "date": _ns(60), "is_sent": 1, "is_delivered": 1}]
        )
        c = status_by_guid("abc", db_path=base)
        assert c.issue == "found" and c.is_delivered

    def test_un_guid_inconnu_avoue(self, tmp_path):
        base = _fausse_chat_db(tmp_path, [])
        assert status_by_guid("xyz", db_path=base).issue == "not_found"
