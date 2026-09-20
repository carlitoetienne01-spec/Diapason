"""Un refresh_token révoqué doit déconnecter, pas être réessayé chaque heure.

Du 6 au 20 septembre 2026, le jeton Google des cinq connecteurs (un seul
jeton, copié dans cinq fichiers) était mort — sept jours après le consentement
du 30 août, la limite du statut « Testing » d'un projet Google Cloud. Rien ne
l'inscrivait : ``is_connected()`` ne regarde que la présence d'un
``access_token``, la synchro horaire relançait les cinq, chacun rappelait
Google, et serve.err.log a reçu 1 715 « invalid_grant ». Pendant ce temps,
``diapason connect gmail`` répondait « already connected ».
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from diapason.connectors import google_auth


class _Reponse:
    def __init__(self, status_code: int, corps=None, text: str = ""):
        self.status_code = status_code
        self._corps = corps
        self.text = text or (json.dumps(corps) if corps is not None else "")

    def json(self):
        if self._corps is None:
            raise ValueError("pas du JSON")
        return self._corps


def _identifiants(tmp_path: Path, **extra) -> str:
    chemin = tmp_path / "gmail.json"
    chemin.write_text(
        json.dumps(
            {
                "access_token": "acces-perime",
                "token": "acces-perime",
                "refresh_token": "refresh-mort",
                "client_id": "client-id",
                "client_secret": "client-secret",
                **extra,
            }
        ),
        encoding="utf-8",
    )
    return str(chemin)


def _lire(chemin: str) -> dict:
    return json.loads(Path(chemin).read_text(encoding="utf-8"))


class TestUnInvalidGrantDeconnecte:
    def test_le_fichier_est_marque_et_l_acces_vide(self, tmp_path):
        chemin = _identifiants(tmp_path)
        reponse = _Reponse(
            400,
            {
                "error": "invalid_grant",
                "error_description": "Token has been expired or revoked.",
            },
        )
        with mock.patch.object(google_auth.httpx, "post", return_value=reponse):
            with pytest.raises(google_auth.GoogleAuthError, match="invalid_grant"):
                google_auth.refresh_access_token(chemin)

        tokens = _lire(chemin)
        assert tokens["access_token"] == "" and tokens["token"] == "", (
            "vider les deux clés est ce qui retourne is_connected() partout"
        )
        assert tokens["revoked_reason"] == "Token has been expired or revoked."
        assert tokens["revoked_at"].endswith("+00:00"), "horodatage UTC explicite"
        assert tokens["refresh_token"] == "refresh-mort", (
            "le jeton mort reste pour le diagnostic"
        )
        assert tokens["client_id"] == "client-id" and tokens["client_secret"], (
            "le couple client sert au nouveau consentement"
        )

    def test_les_cinq_connecteurs_google_se_voient_deconnectes(self, tmp_path):
        """Sans toucher à leur code : ils lisent tous ``access_token``."""
        from diapason.connectors.gmail import GmailConnector

        chemin = _identifiants(tmp_path)
        assert GmailConnector(credentials_path=chemin).is_connected() is True
        reponse = _Reponse(400, {"error": "invalid_grant"})
        with mock.patch.object(google_auth.httpx, "post", return_value=reponse):
            with pytest.raises(google_auth.GoogleAuthError):
                google_auth.refresh_access_token(chemin)
        assert GmailConnector(credentials_path=chemin).is_connected() is False, (
            "la synchro horaire ne relance que les connecteurs connectés"
        )

    def test_une_erreur_passagere_ne_deconnecte_pas(self, tmp_path):
        """Un 503 ou un 400 d'une autre nature n'est pas un verdict."""
        chemin = _identifiants(tmp_path)
        for reponse in (
            _Reponse(503, None, text="Service Unavailable"),
            _Reponse(400, {"error": "invalid_request"}),
        ):
            with mock.patch.object(google_auth.httpx, "post", return_value=reponse):
                with pytest.raises(google_auth.GoogleAuthError, match="refresh failed"):
                    google_auth.refresh_access_token(chemin)
            tokens = _lire(chemin)
            assert tokens["access_token"] == "acces-perime", "rien n'a été touché"
            assert "revoked_at" not in tokens

    def test_un_fichier_revoque_ne_rappelle_plus_google(self, tmp_path):
        """L'outil Gmail insisterait à chaque usage ; le verdict est déjà rendu."""
        chemin = _identifiants(
            tmp_path, revoked_at="2026-09-06T03:00:00+00:00", revoked_reason="x"
        )
        with mock.patch.object(
            google_auth.httpx, "post", side_effect=AssertionError("appel à Google")
        ):
            with pytest.raises(google_auth.GoogleAuthError, match="2026-09-06"):
                google_auth.refresh_access_token(chemin)

    def test_revocation_of_lit_le_verdict(self, tmp_path):
        assert google_auth.revocation_of("") is None
        assert google_auth.revocation_of(_identifiants(tmp_path)) is None
        chemin = _identifiants(
            tmp_path, revoked_at="2026-09-06T03:00:00+00:00", revoked_reason="expiré"
        )
        assert google_auth.revocation_of(chemin) == (
            "2026-09-06T03:00:00+00:00",
            "expiré",
        )


class TestLaPhraseMontreeDitLeGesteUtile:
    def test_invalid_grant_se_traduit_en_reconnecter(self):
        from diapason.server.connectors_router import _translate_sync_error

        brut = (
            "Google revoked this access (invalid_grant: Token has been expired "
            "or revoked.); the connector is now marked disconnected"
        )
        phrase = _translate_sync_error(brut)
        assert "reconnect" in phrase and "diapason connect" in phrase
        assert "{" not in phrase, "plus de JSON brut à l'écran"

    def test_les_autres_traductions_sont_intactes(self):
        from diapason.server.connectors_router import _translate_sync_error

        assert "expired" in _translate_sync_error("HTTP 401 Unauthorized")
        assert "scopes" in _translate_sync_error("HTTP 403")
        assert _translate_sync_error("autre chose") == "autre chose"


class TestConnectDitPourquoiIlRedemande:
    def test_connect_nomme_la_revocation_avant_l_oauth(self, tmp_path):
        from diapason.cli import cli

        chemin = _identifiants(
            tmp_path,
            revoked_at="2026-09-06T03:00:00+00:00",
            revoked_reason="Token has been expired or revoked.",
        )
        # access_token vidé, comme _marquer_revoque le laisse.
        tokens = _lire(chemin)
        tokens["access_token"] = tokens["token"] = ""
        Path(chemin).write_text(json.dumps(tokens), encoding="utf-8")

        classe = mock.MagicMock()
        classe.auth_type = "oauth"
        instance = mock.MagicMock()
        instance.is_connected.return_value = False
        instance._credentials_path = chemin
        classe.return_value = instance

        with (
            mock.patch(
                "diapason.core.registry.ConnectorRegistry.contains", return_value=True
            ),
            mock.patch(
                "diapason.core.registry.ConnectorRegistry.get", return_value=classe
            ),
            # Pas de fournisseur : la commande s'arrête juste après le message,
            # sans ouvrir de navigateur.
            mock.patch(
                "diapason.connectors.oauth.get_provider_for_connector",
                return_value=None,
            ),
        ):
            result = CliRunner().invoke(cli, ["connect", "gmail"])

        assert result.exit_code == 0, result.output
        assert "revoked this access on 2026-09-06" in result.output
        assert "already connected" not in result.output
