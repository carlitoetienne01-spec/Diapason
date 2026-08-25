"""« Lis ma conversation avec Maman » — chat.db en lecture, trois issues.

Le faux chat.db reprend le schéma du connecteur ; jamais la vraie base
(l'Accès complet au disque manque de toute façon, et un test qui dépend de
l'état réel de la machine ne teste rien).
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

from diapason.tools.imessage_tools import IMessageConversationTool, lire_conversation

_EPOCH_NS = 796_000_000 * 1_000_000_000  # ~2026 en horloge Apple (2001)


def _faux_chat_db(tmp_path, rangees):
    chemin = tmp_path / "chat.db"
    with sqlite3.connect(chemin) as db:
        db.execute(
            "CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, "
            "date INTEGER, is_from_me INTEGER)"
        )
        db.execute(
            "CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT)"
        )
        db.execute(
            "CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)"
        )
        db.execute("INSERT INTO chat VALUES (1, '+50940459941')")
        for i, (texte, de_moi) in enumerate(rangees, start=1):
            db.execute(
                "INSERT INTO message VALUES (?, ?, ?, ?)",
                (i, texte, _EPOCH_NS + i * 60_000_000_000, de_moi),
            )
            db.execute("INSERT INTO chat_message_join VALUES (1, ?)", (i,))
    return str(chemin)


class TestLireConversation:
    def test_les_messages_reviennent_en_ordre_chronologique(self, tmp_path):
        base = _faux_chat_db(
            tmp_path, [("Salut !", 0), ("Salut maman", 1), ("Tu viens dimanche ?", 0)]
        )
        constat = lire_conversation("+50940459941", db_path=base)
        assert constat["issue"] == "found"
        assert [m["texte"] for m in constat["messages"]] == [
            "Salut !",
            "Salut maman",
            "Tu viens dimanche ?",
        ]
        assert constat["messages"][1]["de_moi"] is True

    def test_les_rangees_sans_texte_se_comptent_sans_s_inventer(self, tmp_path):
        base = _faux_chat_db(tmp_path, [("Regarde ça", 0), (None, 0)])
        constat = lire_conversation("+50940459941", db_path=base)
        assert len(constat["messages"]) == 1
        assert constat["sans_texte"] == 1

    def test_une_base_illisible_le_dit(self, tmp_path):
        constat = lire_conversation(
            "+509", db_path=str(tmp_path / "absente" / "chat.db")
        )
        assert constat["issue"] == "unreadable"


class TestOutil:
    def test_le_petit_nom_passe_par_le_resolveur_puis_la_base(
        self, tmp_path, monkeypatch
    ):
        import diapason.tools.voice_mac_tools as vmt

        base = _faux_chat_db(tmp_path, [("Tu viens dimanche ?", 0)])
        monkeypatch.setattr(
            vmt,
            "_resolve_contact",
            lambda nom, **_k: [
                {"title": "Mom💫", "phone": "+50940459941", "email": ""}
            ],
        )
        monkeypatch.setattr("diapason.tools.imessage_tools._DB_PAR_DEFAUT", base)
        with patch("diapason.tools.imessage_tools.lire_conversation") as lire:
            lire.return_value = {
                "issue": "found",
                "messages": [
                    {
                        "texte": "Tu viens dimanche ?",
                        "de_moi": False,
                        "quand": "2026-08-25T09:00",
                    }
                ],
                "sans_texte": 0,
            }
            r = IMessageConversationTool().execute(contact="maman")
        assert r.success
        lire.assert_called_once()
        assert lire.call_args[0][0] == "+50940459941"  # le numéro résolu
        assert "Mom💫" in r.content and "Tu viens dimanche ?" in r.content

    def test_sans_acces_disque_le_remede_est_nomme(self, monkeypatch):
        import diapason.tools.voice_mac_tools as vmt

        monkeypatch.setattr(
            vmt,
            "_resolve_contact",
            lambda nom, **_k: [{"title": "Mom💫", "phone": "+509", "email": ""}],
        )
        with patch(
            "diapason.tools.imessage_tools.lire_conversation",
            return_value={"issue": "unreadable", "detail": "auth", "messages": []},
        ):
            r = IMessageConversationTool().execute(contact="maman")
        assert not r.success and "Full Disk Access" in r.content

    def test_plusieurs_fiches_avouent_comme_messages_send(self, monkeypatch):
        import diapason.tools.voice_mac_tools as vmt

        monkeypatch.setattr(
            vmt,
            "_resolve_contact",
            lambda nom, **_k: [
                {"title": "Jean A", "phone": "+1", "email": ""},
                {"title": "Jean B", "phone": "+2", "email": ""},
            ],
        )
        r = IMessageConversationTool().execute(contact="Jean")
        assert not r.success and "Jean A" in r.content
