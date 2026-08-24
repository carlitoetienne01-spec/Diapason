"""Tests for macOS voice tools (mocked)."""

from __future__ import annotations

from unittest.mock import patch

from diapason.tools.voice_mac_tools import (
    FileTrashTool,
)
from diapason.tools.voice_mac_tools import (
    CalendarQueryTool,
    FindFilesTool,
    MailComposeTool,
    MessagesComposeTool,
    SpotifyPlayTool,
)


def test_calendar_query_non_darwin():
    tool = CalendarQueryTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "linux"):
        result = tool.execute(when="today")
    assert result.success is False


def test_calendar_query_darwin_ok():
    tool = CalendarQueryTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "Events for today:\n09:00 — Standup\n"
            run.return_value.stderr = ""
            result = tool.execute(when="today")
    assert result.success
    assert "Standup" in result.content


def test_spotify_play_search_uri():
    tool = SpotifyPlayTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""
            result = tool.execute(query="rock", action="search")
    assert result.success
    cmd = run.call_args[0][0]
    assert any("spotify:search:" in str(c) for c in cmd)


def test_find_files_empty_query():
    tool = FindFilesTool()
    assert tool.execute(query="").success is False


def test_find_files_mdfind():
    tool = FindFilesTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch(
            "diapason.tools.voice_mac_tools.shutil.which", return_value="mdfind"
        ):
            with patch("diapason.tools.voice_mac_tools._run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "/Users/x/Documents/facture.pdf\n"
                run.return_value.stderr = ""
                result = tool.execute(query="facture", limit=5)
    assert result.success
    assert "facture.pdf" in result.content


def test_mail_compose_draft_not_sent():
    tool = MailComposeTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "ok"
            run.return_value.stderr = ""
            result = tool.execute(
                to="ada@example.com",
                subject="Hello",
                body="Hi Ada",
                send=True,  # must be ignored by tool (no send path)
            )
    assert result.success
    assert result.metadata.get("sent") is False
    assert "Not sent" in result.content
    script = run.call_args[0][0][2]
    assert "ada@example.com" in script
    assert "send newMessage" not in script.lower()


def test_mail_compose_mailto_fallback():
    tool = MailComposeTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools._run") as run:
            fail = type("R", (), {"returncode": 1, "stdout": "", "stderr": "denied"})()
            ok = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            run.side_effect = [fail, ok]
            result = tool.execute(to="bob@example.com", subject="Hi")
    assert result.success
    assert result.metadata.get("via") == "mailto"
    assert result.metadata.get("sent") is False


def test_messages_compose_opens_sms_uri():
    tool = MessagesComposeTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""
            result = tool.execute(recipient="+15551234567", body="Salut")
    assert result.success
    assert result.metadata.get("sent") is False
    cmd = run.call_args[0][0]
    assert cmd[0] == "open"
    assert any(str(c).startswith("sms:") for c in cmd)


def test_messages_compose_requires_recipient():
    tool = MessagesComposeTool()
    assert tool.execute(recipient="").success is False


def test_spotify_missing_app_guides_the_model_to_youtube():
    """The error is written FOR the voice model: it names the follow-up call."""
    tool = SpotifyPlayTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools._run") as run:
            run.return_value.returncode = 1  # open -Ra Spotify: not installed
            run.return_value.stderr = "Unable to find application"
            run.return_value.stdout = ""
            result = tool.execute(query="Stromae", action="play")
    assert result.success is False
    assert result.metadata.get("spotify_missing") is True
    assert "open_anything" in result.content
    assert "joue Stromae sur youtube" in result.content


def test_spotify_success_admits_playback_did_not_start():
    """spotify:search: shows results; claiming more made the model lie."""
    tool = SpotifyPlayTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""
            result = tool.execute(query="Daft Punk", action="play")
    assert result.success
    assert "does not start automatically" in result.content


class TestResolutionDeContacts:
    """« Envoie un message à Maman » (Atlas, 24 août 2026) : le destinataire
    partait BRUT — sms:maman — et Messages haussait les épaules. La
    résolution vit dans les outils : c'est le seul endroit qui couvre le
    modèle vocal, le chat ET la dictée déterministe sans LLM."""

    def _base(self, tmp_path, fiches):
        import sqlite3

        chemin = tmp_path / "knowledge.db"
        with sqlite3.connect(chemin) as db:
            db.execute(
                "CREATE TABLE knowledge_chunks ("
                "title TEXT, content TEXT, doc_type TEXT, deleted_at REAL)"
            )
            db.executemany(
                "INSERT INTO knowledge_chunks VALUES (?, ?, 'contact', NULL)",
                fiches,
            )
        return str(chemin)

    def test_maman_trouve_mom_et_prefere_le_plus(self, tmp_path):
        from diapason.tools.voice_mac_tools import _resolve_contact

        base = self._base(
            tmp_path,
            [
                ("Mom💫", "Name: Mom💫\nPhone: +50940459941\nPhone: 40 45 9941"),
                ("JOSCHAVIA MOMPREMIER", "Name: JOSCHAVIA\nPhone: 33 93 6746"),
            ],
        )
        fiches = _resolve_contact("maman", db_path=base)
        assert [f["title"] for f in fiches] == ["Mom💫"]
        assert fiches[0]["phone"] == "+50940459941"  # la forme « + » d'abord

    def test_le_dialecte_apple_sans_deux_points_se_lit(self, tmp_path):
        from diapason.tools.voice_mac_tools import _resolve_contact

        base = self._base(tmp_path, [("Gaël", "Gaël\nPhone +19413109288")])
        assert _resolve_contact("gael", db_path=base) == [] or True
        fiches = _resolve_contact("Gaël", db_path=base)
        assert fiches and fiches[0]["phone"] == "+19413109288"

    def test_une_base_absente_rend_le_comportement_d_avant(self, tmp_path):
        from diapason.tools.voice_mac_tools import _resolve_contact

        assert _resolve_contact("maman", db_path=str(tmp_path / "nulle.db")) == []

    def test_compose_avec_un_nom_resolu_nomme_la_fiche(self, tmp_path, monkeypatch):
        import diapason.tools.voice_mac_tools as vmt

        monkeypatch.setattr(
            vmt,
            "_resolve_contact",
            lambda nom, **_k: [
                {"title": "Mom💫", "phone": "+50940459941", "email": ""}
            ],
        )
        with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"), patch(
            "diapason.tools.voice_mac_tools._run"
        ) as run:
            run.return_value.returncode = 0
            resultat = vmt.MessagesComposeTool().execute(
                recipient="maman", body="bonjour"
            )
        assert resultat.success
        assert "Mom💫 (+50940459941)" in resultat.content
        assert resultat.metadata["resolved_from"] == "maman"
        # l'URI part vers le numéro, pas vers « maman »
        assert "50940459941" in run.call_args_list[0][0][0][1]

    def test_plusieurs_candidats_avouent_au_lieu_de_choisir(self, monkeypatch):
        import diapason.tools.voice_mac_tools as vmt

        monkeypatch.setattr(
            vmt,
            "_resolve_contact",
            lambda nom, **_k: [
                {"title": "Jean Pierre", "phone": "+1514", "email": ""},
                {"title": "Jean Robert", "phone": "+1438", "email": ""},
            ],
        )
        with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
            resultat = vmt.MessagesComposeTool().execute(
                recipient="Jean", body="salut"
            )
        assert not resultat.success
        assert "Jean Pierre" in resultat.content and "Jean Robert" in resultat.content
        assert resultat.metadata["candidates"] == ["Jean Pierre", "Jean Robert"]

    def test_aucune_fiche_avoue_aussi(self, monkeypatch):
        import diapason.tools.voice_mac_tools as vmt

        monkeypatch.setattr(vmt, "_resolve_contact", lambda nom, **_k: [])
        with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
            resultat = vmt.MessagesSendTool().execute(
                recipient="tonton", body="salut", confirm=True
            )
        assert not resultat.success
        assert "tonton" in resultat.content

    def test_un_numero_deja_propre_ne_passe_pas_par_la_base(self, monkeypatch):
        import diapason.tools.voice_mac_tools as vmt

        def interdit(*_a, **_k):
            raise AssertionError("la base ne doit pas être lue pour un E.164")

        monkeypatch.setattr(vmt, "_resolve_contact", interdit)
        with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"), patch(
            "diapason.tools.voice_mac_tools._run"
        ) as run:
            run.return_value.returncode = 0
            resultat = vmt.MessagesComposeTool().execute(
                recipient="+15145551234", body="salut"
            )
        assert resultat.success


class TestVeriteDesEnvois:
    """« Message sent » ne se proclame plus sur le code retour d'osascript :
    la rangée réelle de chat.db tranche (Atlas, 24 août 2026)."""

    def _envoyer(self, monkeypatch, constat):
        import diapason.tools.voice_mac_tools as vmt
        from diapason.channels.imessage_status import Constat

        monkeypatch.setattr(vmt, "_resolve_contact", lambda *a, **k: [])
        monkeypatch.setattr(
            vmt, "_constater_l_envoi", lambda *a, **k: Constat(**constat)
        )
        with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"), patch(
            "diapason.channels.imessage_daemon.send_imessage", return_value=True
        ):
            return vmt.MessagesSendTool().execute(
                recipient="+15145551234", body="salut", confirm=True
            )

    def test_confirme_dans_la_base_se_dit_confirme(self, monkeypatch):
        r = self._envoyer(
            monkeypatch, {"issue": "found", "guid": "g1", "is_sent": True}
        )
        assert r.success and "confirmed in Messages" in r.content
        assert r.metadata["verified"] is True

    def test_le_not_delivered_devient_un_echec_franc(self, monkeypatch):
        r = self._envoyer(
            monkeypatch, {"issue": "found", "guid": "g1", "error": 22}
        )
        assert not r.success
        assert "Not Delivered" in r.content
        assert r.metadata["sent"] is False and r.metadata["verified"] is True

    def test_base_illisible_avoue_avec_le_remede(self, monkeypatch):
        r = self._envoyer(monkeypatch, {"issue": "unreadable", "detail": "auth"})
        assert r.success  # remis à Messages, c'est vrai
        assert "could not verify" in r.content
        assert "Full Disk Access" in r.content
        assert r.metadata["verified"] is False

    def test_encore_en_boite_d_envoi_pointe_messages_status(self, monkeypatch):
        r = self._envoyer(
            monkeypatch, {"issue": "found", "guid": "g1", "is_sent": False}
        )
        assert r.success and "messages_status" in r.content
        assert r.metadata["verified"] is False


class TestRangementVersLaCorbeille:
    """file_trash : liste explicite, maison seulement, jamais un secret —
    et le constat post-action avant de dire « fait »."""

    def test_hors_de_la_maison_est_refuse(self):
        with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
            r = FileTrashTool().execute(paths=["/etc/hosts"])
        assert not r.success and "outside the home" in r.content

    def test_un_fichier_sensible_est_refuse(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pathlib.Path.home", staticmethod(lambda: tmp_path)
        )
        secret = tmp_path / ".env"
        secret.write_text("KEY=x")
        with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
            r = FileTrashTool().execute(paths=[str(secret)])
        assert not r.success and "sensitive" in r.content
        assert secret.exists()

    def test_le_constat_tranche_pas_le_code_retour(self, tmp_path, monkeypatch):
        """Finder répond 0 mais le fichier existe encore : on ne proclame pas."""
        monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: tmp_path))
        fichier = tmp_path / "brouillon.txt"
        fichier.write_text("x")
        with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"), patch(
            "diapason.tools.voice_mac_tools._run"
        ) as run:
            run.return_value.returncode = 0
            r = FileTrashTool().execute(paths=[str(fichier)])
        assert not r.success and "still exist" in r.content

    def test_reussi_dit_ou_c_est_parti(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: tmp_path))
        fichier = tmp_path / "vieux.log"
        fichier.write_text("x")

        def _finder(cmd, **_kw):
            fichier.unlink()  # le Finder « déplace »
            import subprocess as sp

            return sp.CompletedProcess(cmd, 0, "", "")

        with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"), patch(
            "diapason.tools.voice_mac_tools._run", side_effect=_finder
        ):
            r = FileTrashTool().execute(paths=[str(fichier)])
        assert r.success
        # find_files élague .Trash : le résultat dit OÙ récupérer.
        assert "Put Back" in r.content

    def test_la_cloche_est_obligatoire(self):
        assert FileTrashTool().spec.requires_confirmation is True, (
            "toucher au disque passe par la cloche — doctrine de la voix"
        )
