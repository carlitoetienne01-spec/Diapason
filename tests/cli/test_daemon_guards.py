"""``diapason start`` ne crée pas de second serveur ; ``stop`` ne tue pas un inconnu.

Ces gardes ont été refaits après une réfutation qui a mesuré, sur cette
machine, six défauts bloquants. Le fil commun : le code DÉDUISAIT des faits à
partir d'indices — une liaison qui échoue, un 200 sur un port, une ligne de
commande recollée — au lieu de DEMANDER au noyau. Chaque test ci-dessous
correspond à un défaut constaté, pas à une inquiétude théorique.
"""

from __future__ import annotations

import socket
import subprocess

import pytest
from click.testing import CliRunner

from diapason.cli.daemon_cmd import (
    DEAD,
    INCONNU,
    LIBRE,
    OCCUPE,
    SERVING,
    SILENT,
    USURPED,
    _is_diapason_server,
    _listeners_on,
    _looks_like_serve_argv,
    _port_state,
    _read_pid,
    _wait_until_serving,
    daemon,
)


class FauxProcessus:
    """Un processus dont on décide s'il est vivant."""

    def __init__(self, pid: int = 4242, code_sortie: int | None = None) -> None:
        self.pid = pid
        self._code = code_sortie

    def poll(self) -> int | None:
        return self._code

    def terminate(self) -> None:
        self._code = -15


# --- le noyau voit ce que les sondes ne voyaient pas ---------------------


def test_un_detenteur_sur_une_adresse_tierce_est_vu() -> None:
    """Le défaut bloquant : le cas que le dépôt installe lui-même.

    ``serve-service install --allow-network`` lie le serveur à l'adresse du
    Mac sur le réseau, pour que le téléphone du maillage l'atteigne. MESURÉ :
    les anciennes sondes, qui essayaient quatre adresses littérales, rendaient
    « libre » — et ``diapason start`` lançait un second serveur.
    """
    adresse = socket.gethostbyname(socket.gethostname())
    prise = socket.socket()
    prise.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        prise.bind((adresse, 0))
    except OSError:
        pytest.skip(f"pas d'adresse locale utilisable ({adresse})")
    prise.listen(1)
    port = prise.getsockname()[1]
    try:
        etat, detail = _port_state(port)
        assert etat == OCCUPE, f"{adresse} devrait être vue ; détail={detail!r}"
        assert str(port) in detail
    finally:
        prise.close()


@pytest.mark.parametrize("adresse", ["127.0.0.1", "0.0.0.0"])
def test_un_detenteur_local_est_vu(adresse: str) -> None:
    prise = socket.socket()
    prise.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    prise.bind((adresse, 0))
    prise.listen(1)
    try:
        assert _port_state(prise.getsockname()[1])[0] == OCCUPE
    finally:
        prise.close()


def test_un_port_libre_est_dit_libre() -> None:
    prise = socket.socket()
    prise.bind(("127.0.0.1", 0))
    port = prise.getsockname()[1]
    prise.close()
    assert _port_state(port)[0] == LIBRE


def test_le_detenteur_est_nomme_avec_son_pid() -> None:
    """La confirmation d'après-lancement a besoin de ce PID."""
    import os

    prise = socket.socket()
    prise.bind(("127.0.0.1", 0))
    prise.listen(1)
    try:
        auditeurs = _listeners_on(prise.getsockname()[1])
        assert auditeurs is not None
        assert any(pid == os.getpid() for pid, _ in auditeurs)
    finally:
        prise.close()


# --- le port qui répond ne prouve pas QUI sert ---------------------------


def test_un_tiers_qui_sert_n_est_pas_notre_serveur(monkeypatch) -> None:
    """MESURÉ : un /bin/sleep passait pour « en marche ».

    L'ancienne version se contentait d'un 200 sur le port. Deux ``start``
    concurrents produisaient donc ceci : le perdant de la course était inscrit
    dans le fichier PID, mourait, et le vrai serveur devenait introuvable.
    """
    monkeypatch.setattr("diapason.cli.daemon_cmd._http_status", lambda *a, **k: 200)
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._listeners_on", lambda _p: [(999_999, "*:8000")]
    )
    monkeypatch.setattr("diapason.cli.daemon_cmd._descendants", lambda _p: {4242})
    assert _wait_until_serving(FauxProcessus(), "127.0.0.1", 8000, timeout_s=2) == (
        USURPED
    )


def test_notre_propre_processus_qui_sert_est_reconnu(monkeypatch) -> None:
    monkeypatch.setattr("diapason.cli.daemon_cmd._http_status", lambda *a, **k: 200)
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._listeners_on", lambda _p: [(4242, "*:8000")]
    )
    monkeypatch.setattr("diapason.cli.daemon_cmd._descendants", lambda _p: {4242})
    assert _wait_until_serving(FauxProcessus(), "127.0.0.1", 8000, timeout_s=2) == (
        SERVING
    )


def test_un_descendant_qui_sert_compte_aussi(monkeypatch) -> None:
    """Un lanceur peut s'intercaler : « uv run » tient l'enfant qui sert."""
    monkeypatch.setattr("diapason.cli.daemon_cmd._http_status", lambda *a, **k: 200)
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._listeners_on", lambda _p: [(7777, "*:8000")]
    )
    monkeypatch.setattr("diapason.cli.daemon_cmd._descendants", lambda _p: {4242, 7777})
    assert _wait_until_serving(FauxProcessus(), "127.0.0.1", 8000, timeout_s=2) == (
        SERVING
    )


def test_un_processus_mort_est_signale_comme_tel() -> None:
    assert (
        _wait_until_serving(FauxProcessus(code_sortie=1), "127.0.0.1", 1, timeout_s=1)
        == DEAD
    )


def test_un_processus_vivant_mais_muet_n_est_pas_declare_mort(monkeypatch) -> None:
    """La distinction qui évite d'orphaniser un serveur encore en chargement."""
    monkeypatch.setattr("diapason.cli.daemon_cmd._http_status", lambda *a, **k: None)
    assert _wait_until_serving(FauxProcessus(), "127.0.0.1", 1, timeout_s=1) == SILENT


def test_un_503_est_une_reponse_pas_un_silence(monkeypatch) -> None:
    """« Moteur pas encore prêt » signifie que le serveur SERT déjà le port."""
    monkeypatch.setattr("diapason.cli.daemon_cmd._http_status", lambda *a, **k: 503)
    monkeypatch.setattr("diapason.cli.daemon_cmd._listeners_on", lambda _p: None)
    assert (
        _wait_until_serving(FauxProcessus(), "127.0.0.1", 8000, timeout_s=2) == SERVING
    )


# --- « je ne sais pas » n'est pas « non » --------------------------------


def test_un_pid_indetermine_ne_fait_pas_effacer_le_fichier(
    monkeypatch, tmp_path
) -> None:
    """Effacer sur un doute rendait un serveur vivant introuvable."""
    fichier = tmp_path / "server.pid"
    fichier.write_text("4242")
    monkeypatch.setattr("diapason.cli.daemon_cmd._PID_FILE", fichier)
    monkeypatch.setattr("diapason.cli.daemon_cmd._is_diapason_server", lambda *_a: None)
    assert _read_pid(8000) == 4242
    assert fichier.exists()


def test_un_pid_refute_fait_effacer_le_fichier(monkeypatch, tmp_path) -> None:
    fichier = tmp_path / "server.pid"
    fichier.write_text("4242")
    monkeypatch.setattr("diapason.cli.daemon_cmd._PID_FILE", fichier)
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._is_diapason_server", lambda *_a: False
    )
    assert _read_pid(8000) is None
    assert not fichier.exists()


def test_l_identite_se_prouve_par_le_port_avant_la_ligne_de_commande(
    monkeypatch,
) -> None:
    """Le noyau tranche ; la ligne de commande n'est qu'un repli."""
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._listeners_on", lambda _p: [(4242, "*:8000")]
    )
    assert _is_diapason_server(4242, 8000) is True
    assert _is_diapason_server(9999, 8000) is False


def test_sans_reponse_du_systeme_on_ne_conclut_rien(monkeypatch) -> None:
    monkeypatch.setattr("diapason.cli.daemon_cmd._listeners_on", lambda _p: None)
    monkeypatch.setattr("diapason.cli.daemon_cmd._run", lambda *_a, **_k: None)
    assert _is_diapason_server(4242, 8000) is None


# --- la ligne de commande, quand il faut s'en contenter ------------------


@pytest.mark.parametrize(
    "ligne, attendu, quoi",
    [
        (
            "/Users/c/.venv/bin/python -m diapason.cli serve --host 0.0.0.0",
            True,
            "vrai serveur",
        ),
        ("/usr/local/bin/diapason serve --port 8000", True, "script console"),
        (
            "/Users/John Smith/Diapason/.venv/bin/python -m diapason.cli serve",
            True,
            "espace dans le chemin — rendait le serveur inarrêtable",
        ),
        (
            "/Users/c/Library/Mobile Docs/D/.venv/bin/python -m diapason.cli serve",
            True,
            "chemin iCloud",
        ),
        ("/usr/local/bin/uv run diapason serve --port 8000", True, "via uv"),
        ("/bin/zsh -c pgrep -f 'diapason.cli serve'", False, "un shell qui en parle"),
        (".venv/bin/python -", False, "python interactif"),
        ("/usr/bin/python3 -m diapason.cli dictate", False, "la dictée"),
        ("", False, "ligne vide"),
        ("python", False, "un seul jeton"),
    ],
)
def test_reconnaissance_par_la_ligne_de_commande(
    ligne: str, attendu: bool, quoi: str
) -> None:
    assert _looks_like_serve_argv(ligne) is attendu, quoi


# --- un détenteur qui ne parle pas HTTP ----------------------------------


def test_un_detenteur_muet_ne_fait_pas_planter(monkeypatch) -> None:
    """Il levait ``BadStatusLine``, qui n'hérite pas de OSError."""
    from diapason.cli.daemon_cmd import _http_status

    serveur = socket.socket()
    serveur.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    serveur.bind(("127.0.0.1", 0))
    serveur.listen(1)
    port = serveur.getsockname()[1]
    try:
        assert _http_status("127.0.0.1", port, timeout=1.0) is None
    finally:
        serveur.close()


# --- le refus est visible, et le doute aussi ----------------------------


def test_start_refuse_quand_le_port_est_pris(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("diapason.cli.daemon_cmd._PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr("diapason.cli.daemon_cmd._read_pid", lambda *_a: None)
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._port_state", lambda _p: (OCCUPE, "PID 1 sur *:8000")
    )
    resultat = CliRunner().invoke(daemon, ["start"])
    assert resultat.exit_code == 1
    assert "already in use" in resultat.output


def test_start_refuse_quand_il_ne_peut_pas_verifier(monkeypatch, tmp_path) -> None:
    """Fail-closed : un doublon silencieux coûte plus qu'un démarrage refusé."""
    monkeypatch.setattr("diapason.cli.daemon_cmd._PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr("diapason.cli.daemon_cmd._read_pid", lambda *_a: None)
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._port_state", lambda _p: (INCONNU, "lsof absent")
    )
    resultat = CliRunner().invoke(daemon, ["start"])
    assert resultat.exit_code == 1
    assert "Cannot verify" in resultat.output


def test_start_ne_lance_rien_quand_il_refuse(monkeypatch, tmp_path) -> None:
    """Un refus qui lancerait quand même serait pire que pas de garde du tout."""
    lances: list = []
    monkeypatch.setattr("diapason.cli.daemon_cmd._PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr("diapason.cli.daemon_cmd._read_pid", lambda *_a: None)
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._port_state", lambda _p: (OCCUPE, "PID 1 sur *:8000")
    )
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: lances.append(a) or FauxProcessus()
    )
    CliRunner().invoke(daemon, ["start"])
    assert lances == []


# --- le garde ne doit jamais se bloquer lui-même -------------------------


def test_sans_lsof_on_retombe_sur_la_liaison_directe(monkeypatch) -> None:
    """Un garde qui refuse toujours de démarrer serait une panne, pas un garde.

    Là où ``lsof`` n'existe pas — Windows, un conteneur minimal — la première
    voie rend None. Sans repli, ``_port_state`` répondrait « je ne sais pas » à
    l'infini et ``start``, qui refuse dans le doute, ne démarrerait jamais.
    """
    monkeypatch.setattr("diapason.cli.daemon_cmd._listeners_on", lambda _p: None)

    prise = socket.socket()
    prise.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    prise.bind(("127.0.0.1", 0))
    prise.listen(1)
    port = prise.getsockname()[1]
    try:
        assert _port_state(port)[0] == OCCUPE
    finally:
        prise.close()

    libre = socket.socket()
    libre.bind(("127.0.0.1", 0))
    port_libre = libre.getsockname()[1]
    libre.close()
    assert _port_state(port_libre)[0] == LIBRE


def test_quand_rien_ne_repond_on_dit_qu_on_ne_sait_pas(monkeypatch) -> None:
    """Et seulement là : INCONNU est le dernier recours, pas le premier."""
    monkeypatch.setattr("diapason.cli.daemon_cmd._listeners_on", lambda _p: None)
    monkeypatch.setattr(
        "diapason.cli.daemon_cmd._port_occupe_par_liaison", lambda _p: None
    )
    assert _port_state(8000)[0] == INCONNU
