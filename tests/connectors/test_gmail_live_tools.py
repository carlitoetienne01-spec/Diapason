"""Les mains Gmail (Atlas, 25 août 2026) : les specs fantômes s'incarnent.

Sous tests/connectors/ à dessein : la fixture autouse _isoler_les_jetons
repointe les identifiants vers tmp_path — un test qui lirait les VRAIS
jetons de ~/.diapason/connectors deviendrait faux dès la connexion.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from diapason.tools.gmail_live import GmailSearchTool, MailArchiveTool, MailTrashTool


def _faux_connecteur():
    connecteur = MagicMock()

    def _refresh(fn, *args, **kwargs):
        return fn("jeton", *args, **kwargs)

    connecteur._call_with_refresh.side_effect = _refresh
    return connecteur


class TestGmailSearch:
    def test_la_recherche_liste_puis_lit_les_entetes(self):
        connecteur = _faux_connecteur()
        with patch(
            "diapason.tools.gmail_live._connecteur", return_value=connecteur
        ), patch(
            "diapason.connectors.gmail._gmail_api_list_messages",
            return_value={"messages": [{"id": "m1"}, {"id": "m2"}]},
        ), patch(
            "diapason.connectors.gmail._gmail_api_get_message",
            side_effect=[
                {
                    "id": "m1",
                    "threadId": "t1",
                    "snippet": "On d&#233;jeune ?",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "Alice <a@x.com>"},
                            {"name": "Subject", "value": "Déjeuner"},
                            {"name": "Date", "value": "Mon, 25 Aug 2026"},
                        ]
                    },
                },
                {
                    "id": "m2",
                    "threadId": "t2",
                    "snippet": "Relance",
                    "payload": {"headers": []},
                },
            ],
        ):
            r = GmailSearchTool().execute(query="from:alice", max_results=5)
        assert r.success
        assert "Déjeuner — Alice <a@x.com>" in r.content
        assert "[gmail id=m1]" in r.content  # l'id que mail_archive attend
        assert "On déjeune ?" in r.content  # entités HTML décodées
        assert r.metadata["resultats"][0]["url"].endswith("#all/m1")

    def test_sans_connexion_l_outil_avoue(self):
        with patch("diapason.tools.gmail_live._connecteur", return_value=None):
            r = GmailSearchTool().execute(query="x")
        assert not r.success and "not connected" in r.content

    def test_zero_resultat_se_dit_sans_inventer(self):
        connecteur = _faux_connecteur()
        with patch(
            "diapason.tools.gmail_live._connecteur", return_value=connecteur
        ), patch(
            "diapason.connectors.gmail._gmail_api_list_messages",
            return_value={},
        ):
            r = GmailSearchTool().execute(query="from:personne")
        assert r.success and "Aucun mail" in r.content

    def test_la_requete_part_donc_l_outil_est_distant(self):
        assert GmailSearchTool.is_local is False, (
            "le trajet de la DONNÉE : la requête part chez Google"
        )


class TestActionsGmail:
    def test_archiver_appelle_le_connecteur_et_le_dit_reversible(self):
        connecteur = _faux_connecteur()
        with patch(
            "diapason.tools.gmail_live._connecteur", return_value=connecteur
        ):
            r = MailArchiveTool().execute(message_id="m1")
        assert r.success
        connecteur.archive_message.assert_called_once_with("m1")
        assert "All Mail" in r.content

    def test_la_corbeille_dit_les_trente_jours(self):
        connecteur = _faux_connecteur()
        with patch(
            "diapason.tools.gmail_live._connecteur", return_value=connecteur
        ):
            r = MailTrashTool().execute(message_id="m2")
        assert r.success
        connecteur.delete_message.assert_called_once_with("m2")
        assert "30 days" in r.content

    def test_les_actions_exigent_la_cloche_et_sont_distantes(self):
        """PRIVACY.md : « archiver ou mettre à la corbeille uniquement sur
        sa demande explicite » — la cloche EST cette demande constatée."""
        for outil in (MailArchiveTool, MailTrashTool):
            assert outil().spec.requires_confirmation is True
            assert outil.is_local is False

    def test_un_refus_google_remonte_sans_lever(self):
        connecteur = _faux_connecteur()
        connecteur.archive_message.side_effect = RuntimeError("HTTP 403")
        with patch(
            "diapason.tools.gmail_live._connecteur", return_value=connecteur
        ):
            r = MailArchiveTool().execute(message_id="m1")
        assert not r.success and "403" in r.content
