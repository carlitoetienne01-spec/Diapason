"""Un port tenu ne fait plus mourir ``diapason serve`` en boucle sous launchd.

Du 26 août au 20 septembre 2026, ``serve`` chargeait moteur, mémoire et voix
puis mourait au bind (uvicorn sort 3 sur EADDRINUSE) ; launchd le relançait
dix secondes plus tard, et ainsi de suite tant qu'un autre ``serve`` tenait
le port. serve.err.log : 837 cycles (1 674 « Errno 48 »), 67 démarrages
réussis, 465 Mo. Le contrôle vit désormais avant tout chargement, et il
attend au lieu de mourir.
"""

from __future__ import annotations

import http.server
import importlib
import io
import threading
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner
from rich.console import Console

from diapason.core import ports

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

serve_mod = importlib.import_module("diapason.cli.serve")


def _console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=200)


def _texte(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[attr-defined]


def _etats(*suite: tuple[str, str]):
    """Un ``port_state`` qui déroule une suite d'états puis reste sur le dernier."""
    restant = list(suite)

    def etat_du_port(port: int) -> tuple[str, str]:
        if len(restant) > 1:
            return restant.pop(0)
        return restant[0]

    return etat_du_port


def _jamais(*_a, **_k):
    raise AssertionError("ne devait pas être appelé")


class TestUnPortTenuSeConstateAvantDeCharger:
    """§ « Reconstruire l'app / recharger le serveur » — un seul serveur par port."""

    def test_un_port_libre_ne_fait_ni_sondage_ni_attente(self):
        console = _console()
        tours = serve_mod.attendre_le_port(
            "127.0.0.1",
            8000,
            console=console,
            etat_du_port=_etats((ports.LIBRE, "")),
            sonder=_jamais,
            dormir=_jamais,
        )
        assert tours == 0, "un port libre ne coûte aucun tour"
        assert _texte(console) == "", "un port libre ne mérite aucun message"

    def test_un_etat_inconnu_laisse_uvicorn_trancher(self):
        """Refuser de démarrer sur une ignorance ferait boucler launchd autant."""
        tours = serve_mod.attendre_le_port(
            "127.0.0.1",
            8000,
            console=_console(),
            etat_du_port=_etats((ports.INCONNU, "ni lsof ni liaison")),
            sonder=_jamais,
            dormir=_jamais,
        )
        assert tours == 0, "dans l'ignorance, le bind d'uvicorn reste l'arbitre"

    def test_un_diapason_sain_est_attendu_jusqua_ce_quil_rende_le_port(self):
        console = _console()
        sommeils: list[float] = []
        tenu = (ports.OCCUPE, "PID 42 sur 127.0.0.1:8000")
        tours = serve_mod.attendre_le_port(
            "127.0.0.1",
            8000,
            console=console,
            etat_du_port=_etats(tenu, tenu, tenu, (ports.LIBRE, "")),
            sonder=lambda h, p: serve_mod.DIAPASON_SAIN,
            dormir=sommeils.append,
        )
        assert tours == 3, "trois sondages avant que le port se libère"
        assert sommeils == [serve_mod._ATTENTE_PORT_S] * 3, (
            "on dort le pas d'attente entre chaque sondage, pas plus"
        )
        texte = _texte(console)
        assert "PID 42" in texte, "le message nomme le détenteur"
        assert "un autre Diapason, qui répond" in texte
        assert "15 s" in texte, "le message final dit combien on a attendu"

    def test_un_processus_etranger_est_nomme_et_attendu_aussi(self):
        """Mourir ferait relancer launchd toutes les dix secondes, sans issue."""
        console = _console()
        tenu = (ports.OCCUPE, "PID 7 sur 127.0.0.1:8000")
        tours = serve_mod.attendre_le_port(
            "127.0.0.1",
            8000,
            console=console,
            etat_du_port=_etats(tenu, (ports.LIBRE, "")),
            sonder=lambda h, p: None,
            dormir=lambda s: None,
        )
        assert tours == 1
        assert "n'est pas un Diapason" in _texte(console)

    def test_un_diapason_dont_le_moteur_charge_est_distingue(self):
        console = _console()
        tenu = (ports.OCCUPE, "PID 9 sur 127.0.0.1:8000")
        serve_mod.attendre_le_port(
            "127.0.0.1",
            8000,
            console=console,
            etat_du_port=_etats(tenu, (ports.LIBRE, "")),
            sonder=lambda h, p: serve_mod.DIAPASON_CHARGE,
            dormir=lambda s: None,
        )
        assert "moteur charge encore" in _texte(console)

    def test_le_message_dattente_nest_imprime_quune_fois(self):
        """465 Mo de journal : la ligne unique est le contrat, pas un détail."""
        console = _console()
        tenu = (ports.OCCUPE, "PID 42 sur 127.0.0.1:8000")
        serve_mod.attendre_le_port(
            "127.0.0.1",
            8000,
            console=console,
            etat_du_port=_etats(*([tenu] * 50), (ports.LIBRE, "")),
            sonder=lambda h, p: serve_mod.DIAPASON_SAIN,
            dormir=lambda s: None,
        )
        assert _texte(console).count("déjà tenu") == 1, (
            "cinquante tours d'attente, un seul message"
        )


class _Repondeur(http.server.BaseHTTPRequestHandler):
    statut = 200
    corps = b'{"status": "ok"}'

    def do_GET(self):  # noqa: N802 - nom imposé par http.server
        self.send_response(self.statut)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.corps)

    def log_message(self, *_a):
        pass


@pytest.fixture
def serveur_local():
    """Un vrai serveur HTTP sur un port éphémère, paramétré par test."""

    def demarrer(statut: int, corps: bytes):
        gestionnaire = type("R", (_Repondeur,), {"statut": statut, "corps": corps})
        httpd = http.server.HTTPServer(("127.0.0.1", 0), gestionnaire)
        fil = threading.Thread(target=httpd.serve_forever, daemon=True)
        fil.start()
        serveurs.append(httpd)
        return httpd.server_address[1]

    serveurs: list[http.server.HTTPServer] = []
    yield demarrer
    for httpd in serveurs:
        httpd.shutdown()
        httpd.server_close()


class TestLaSondeReconnaitUnDiapason:
    def test_un_diapason_sain_repond_status_ok(self, serveur_local):
        port = serveur_local(200, b'{"status": "ok"}')
        assert serve_mod.sonder_diapason("127.0.0.1", port) == serve_mod.DIAPASON_SAIN

    def test_un_503_est_un_diapason_dont_le_moteur_charge(self, serveur_local):
        port = serveur_local(503, b'{"detail": "Engine unhealthy"}')
        assert serve_mod.sonder_diapason("127.0.0.1", port) == serve_mod.DIAPASON_CHARGE

    def test_un_200_qui_nest_pas_le_notre_nest_pas_un_diapason(self, serveur_local):
        port = serveur_local(200, b"<html>bienvenue</html>")
        assert serve_mod.sonder_diapason("127.0.0.1", port) is None

    def test_un_port_qui_refuse_nest_pas_un_diapason(self, serveur_local):
        port = serveur_local(200, b'{"status": "ok"}')
        # Un port voisin, fermé : refus de connexion, pas d'exception qui fuit.
        assert (
            serve_mod.sonder_diapason(
                "127.0.0.1", port + 1 if port < 65535 else port - 1
            )
            is None
        )

    def test_une_adresse_joker_est_sondee_en_loopback(self, serveur_local):
        port = serveur_local(200, b'{"status": "ok"}')
        assert serve_mod.sonder_diapason("0.0.0.0", port) == serve_mod.DIAPASON_SAIN  # noqa: S104


class TestLeControleALieuAvantLeMoteur:
    """Le contrôle vivait après trente secondes de chargement : il n'y était pas."""

    def test_serve_verifie_le_port_avant_de_charger_le_moteur(
        self, tmp_path, monkeypatch
    ):
        from diapason.core.config import DiapasonConfig

        config = DiapasonConfig()
        config.server.host = "127.0.0.1"
        config.server.port = 8123
        monkeypatch.setattr(serve_mod, "load_config", lambda *a, **k: config)
        monkeypatch.setattr(serve_mod, "inject_credentials", lambda: None)

        appels: list[tuple[str, int]] = []

        def attendre(host, port, *, console):
            appels.append((host, port))
            # On s'arrête ici : le reste du démarrage n'est pas l'objet du test.
            raise SystemExit(0)

        monkeypatch.setattr(serve_mod, "attendre_le_port", attendre)
        trop_tot = MagicMock(
            side_effect=AssertionError(
                "le moteur a été chargé avant le contrôle du port"
            )
        )
        monkeypatch.setattr(serve_mod, "register_builtin_models", trop_tot)
        monkeypatch.setattr(serve_mod, "get_engine", trop_tot)

        from diapason.cli import cli

        result = CliRunner().invoke(cli, ["serve"], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert appels == [("127.0.0.1", 8123)], (
            "le port résolu (config) est contrôlé une fois, avant le moteur"
        )
        trop_tot.assert_not_called()
