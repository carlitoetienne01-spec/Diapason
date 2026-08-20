"""``diapason start`` ne crée pas de second serveur ; ``stop`` ne tue pas un inconnu.

Deux fenêtres constatées le 20 août 2026 :

* le garde ne lisait qu'un fichier PID, que seuls SES propres démarrages
  écrivent — un serveur de launchd, du bureau ou d'un terminal lui était
  invisible, et il en lançait tranquillement un second ;
* ``os.kill(pid, 0)`` prouve qu'un processus existe, pas que c'est le nôtre.
  Sur un PID recyclé, ``stop`` envoyait SIGTERM puis SIGKILL à un inconnu.
"""

from __future__ import annotations

import socket

import pytest
from click.testing import CliRunner

from diapason.cli.daemon_cmd import (
    _is_diapason_server,
    _looks_like_serve_argv,
    _port_holder,
    _read_pid,
    daemon,
)

# --- ce qui ressemble à un serveur, et ce qui fait seulement semblant ------


@pytest.mark.parametrize(
    "ligne, attendu, quoi",
    [
        (
            "/Users/c/.venv/bin/python -m diapason.cli serve --host 0.0.0.0",
            True,
            "vrai serveur",
        ),
        ("/usr/local/bin/diapason serve --port 8000", True, "script console"),
        ("/bin/zsh -c pgrep -f 'diapason.cli serve'", False, "un shell qui en parle"),
        (".venv/bin/python -", False, "python interactif"),
        ("/Applications/E.app/MacOS/e /Users/c/Diapason/serve.py", False, "un éditeur"),
        ("/usr/bin/python3 -m diapason.cli dictate", False, "la dictée"),
        ("/usr/bin/python3 -m diapason.cli x --note serveur", False, "« serveur »"),
        ("", False, "ligne vide"),
        ("python", False, "un seul jeton"),
    ],
)
def test_seul_un_vrai_serveur_est_reconnu(ligne: str, attendu: bool, quoi: str) -> None:
    """Chercher deux mots dans la ligne ne prouvait rien.

    Mesuré : le shell qui lançait les tests contenait « diapason » et « serve »,
    et passait donc pour un serveur. ``stop`` l'aurait tué.
    """
    assert _looks_like_serve_argv(ligne) is attendu, quoi


def test_un_pid_inexistant_n_est_pas_un_serveur() -> None:
    assert _is_diapason_server(999_999) is False


# --- le fichier PID ne suffit pas, et ne doit pas nuire -------------------


def test_un_pid_etranger_est_ecarte_et_le_fichier_efface(monkeypatch, tmp_path) -> None:
    """Un PID recyclé ne doit ni être rendu, ni rester en embuscade."""
    fichier = tmp_path / "server.pid"
    fichier.write_text("4242")
    monkeypatch.setattr("diapason.cli.daemon_cmd._PID_FILE", fichier)
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._is_diapason_server", lambda _pid: False
    )
    assert _read_pid() is None
    assert not fichier.exists()


def test_un_pid_a_nous_est_rendu(monkeypatch, tmp_path) -> None:
    fichier = tmp_path / "server.pid"
    fichier.write_text("4242")
    monkeypatch.setattr("diapason.cli.daemon_cmd._PID_FILE", fichier)
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._is_diapason_server", lambda _pid: True
    )
    assert _read_pid() == 4242


# --- le port, lui, voit tout le monde ------------------------------------


def test_un_port_libre_ne_rend_rien() -> None:
    prise = socket.socket()
    prise.bind(("127.0.0.1", 0))
    port = prise.getsockname()[1]
    prise.close()
    assert _port_holder(port) is None


def test_un_detenteur_muet_est_vu() -> None:
    """Le cas exact du serveur zombie : il tient le port et ne répond pas.

    Le détenteur est sur 127.0.0.1 et la sonde tente 0.0.0.0. MESURÉ : sans
    ``SO_REUSEADDR`` — que Python ne pose pas — ce recouvrement est refusé,
    donc la sonde le voit. Avec SO_REUSEADDR elle serait aveugle, et c'est
    précisément l'erreur qu'avait le contrôle de port de l'application.
    """
    prise = socket.socket()
    prise.bind(("127.0.0.1", 0))
    prise.listen(1)
    port = prise.getsockname()[1]
    try:
        assert _port_holder(port) == "held, but not answering /health"
    finally:
        prise.close()


# --- et le refus est visible ---------------------------------------------


def test_start_refuse_quand_le_port_est_pris(monkeypatch, tmp_path) -> None:
    """Le fichier PID est vide de tout : seul le port dit la vérité."""
    monkeypatch.setattr("diapason.cli.daemon_cmd._PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._port_holder", lambda _port: "answering /health"
    )
    resultat = CliRunner().invoke(daemon, ["start"])
    assert resultat.exit_code == 1
    assert "already in use" in resultat.output


# --- trois issues après lancement, qu'il ne faut pas confondre -----------


class FauxProcessus:
    """Un processus dont on décide s'il est vivant."""

    pid = 4242

    def __init__(self, code_sortie: int | None = None) -> None:
        self._code = code_sortie

    def poll(self) -> int | None:
        return self._code


def test_un_processus_mort_est_signale_comme_tel() -> None:
    from diapason.cli.daemon_cmd import DEAD, _wait_until_serving

    assert _wait_until_serving(FauxProcessus(1), 1, timeout_s=1.0) == DEAD


def test_un_processus_vivant_mais_muet_n_est_pas_declare_mort() -> None:
    """La distinction qui évite d'orphaniser un serveur.

    Un premier démarrage charge un modèle et peut rester longtemps sans
    répondre. Le confondre avec un échec ferait effacer le fichier PID, et
    ``diapason stop`` ne saurait plus quoi arrêter.
    """
    from diapason.cli.daemon_cmd import SILENT, _wait_until_serving

    assert _wait_until_serving(FauxProcessus(None), 1, timeout_s=1.0) == SILENT


def test_le_fichier_pid_survit_a_un_serveur_encore_muet(monkeypatch, tmp_path) -> None:
    from diapason.cli.daemon_cmd import SILENT

    fichier = tmp_path / "server.pid"
    monkeypatch.setattr("diapason.cli.daemon_cmd._PID_FILE", fichier)
    monkeypatch.setattr("diapason.cli.daemon_cmd.DEFAULT_CONFIG_DIR", tmp_path)
    monkeypatch.setattr("diapason.cli.daemon_cmd._read_pid", lambda: None)
    monkeypatch.setattr("diapason.cli.daemon_cmd._port_holder", lambda _p: None)
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd.subprocess.Popen", lambda *a, **k: FauxProcessus(None)
    )
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._wait_until_serving", lambda *a, **k: SILENT
    )
    resultat = CliRunner().invoke(daemon, ["start"])
    assert resultat.exit_code == 1
    assert fichier.exists(), "effacer le PID orphelinerait le processus"


def test_le_fichier_pid_est_efface_quand_le_serveur_est_mort(
    monkeypatch, tmp_path
) -> None:
    from diapason.cli.daemon_cmd import DEAD

    fichier = tmp_path / "server.pid"
    monkeypatch.setattr("diapason.cli.daemon_cmd._PID_FILE", fichier)
    monkeypatch.setattr("diapason.cli.daemon_cmd.DEFAULT_CONFIG_DIR", tmp_path)
    monkeypatch.setattr("diapason.cli.daemon_cmd._read_pid", lambda: None)
    monkeypatch.setattr("diapason.cli.daemon_cmd._port_holder", lambda _p: None)
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd.subprocess.Popen", lambda *a, **k: FauxProcessus(1)
    )
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._wait_until_serving", lambda *a, **k: DEAD
    )
    resultat = CliRunner().invoke(daemon, ["start"])
    assert resultat.exit_code == 1
    assert not fichier.exists()


def test_un_port_qui_sort_de_time_wait_est_libre() -> None:
    """``diapason restart`` doit pouvoir redémarrer ce qu'il vient d'arrêter.

    Régression mesurée pendant l'écriture de ce garde : une liaison SANS
    ``SO_REUSEADDR`` voit un port fraîchement libéré comme occupé, parce qu'il
    reste en ``TIME_WAIT``. ``restart`` refusait alors de repartir. Un garde qui
    empêche le service de tourner est pire que le doublon qu'il prévient.
    """
    import threading
    import time

    serveur = socket.socket()
    serveur.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    serveur.bind(("127.0.0.1", 0))
    serveur.listen(1)
    port = serveur.getsockname()[1]

    def accepte() -> None:
        connexion, _ = serveur.accept()
        connexion.recv(16)
        connexion.close()

    threading.Thread(target=accepte, daemon=True).start()
    client = socket.socket()
    client.connect(("127.0.0.1", port))
    client.send(b"x")
    time.sleep(0.3)
    client.close()
    serveur.close()
    time.sleep(0.3)

    assert _port_holder(port) is None, "TIME_WAIT ne doit pas passer pour occupé"


def test_un_auditeur_sur_le_joker_est_vu() -> None:
    """L'autre moitié : sans les DEUX adresses, ce cas échapperait au test."""
    prise = socket.socket()
    prise.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    prise.bind(("0.0.0.0", 0))
    prise.listen(1)
    try:
        assert _port_holder(prise.getsockname()[1]) is not None
    finally:
        prise.close()


@pytest.mark.parametrize(
    "adresse, v6only, quoi",
    [
        ("::1", True, "loopback IPv6 restreint"),
        ("::", True, "joker IPv6 restreint"),
        ("::", False, "joker IPv6 en pile double"),
    ],
)
def test_un_detenteur_ipv6_est_vu(adresse: str, v6only: bool, quoi: str) -> None:
    """Un serveur en IPv6 pur échappait entièrement aux sondes IPv4.

    Mesuré : un détenteur lié à « ::1 » en mode v6only laissait passer les
    liaisons sur 0.0.0.0 comme sur 127.0.0.1. La sonde essaie donc aussi les
    deux formes IPv6.
    """
    prise = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    prise.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    prise.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1 if v6only else 0)
    prise.bind((adresse, 0))
    prise.listen(1)
    try:
        assert _port_holder(prise.getsockname()[1]) is not None, quoi
    finally:
        prise.close()


def test_une_erreur_de_liaison_autre_que_l_occupation_ne_bloque_pas(
    monkeypatch,
) -> None:
    """Un contrôle ne doit jamais se transformer en panne.

    La sonde essaie quatre adresses, dont deux IPv6. Sur une machine sans pile
    IPv6, ou derrière une politique qui refuse une liaison, l'erreur n'est PAS
    une preuve d'occupation — la traiter comme telle empêcherait le serveur de
    démarrer, ce qui est pire que le doublon qu'on prévient.
    """
    import errno as _errno

    vraie_prise = socket.socket

    class PriseRetive:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def setsockopt(self, *_args) -> None:
            pass

        def bind(self, _addr) -> None:
            raise OSError(_errno.EACCES, "refusé par la politique")

        def close(self) -> None:
            pass

    monkeypatch.setattr(socket, "socket", PriseRetive)
    try:
        assert _port_holder(9999) is None
    finally:
        monkeypatch.setattr(socket, "socket", vraie_prise)
