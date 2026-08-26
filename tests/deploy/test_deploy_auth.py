"""Deployment configs must not ship an unauthenticated public server (#221).

Every shipped deployment method must either bind loopback (no network
exposure) or require an API key, so that following the docs never yields an
open `0.0.0.0:8000` server. `check_bind_safety` is the runtime backstop;
these tests guard the static config files that drive it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "deploy"


def _read(rel: str) -> str:
    return (DEPLOY / rel).read_text()


def test_docker_compose_requires_api_key():
    text = _read("docker/docker-compose.yml")
    # The container binds 0.0.0.0, so the key must be a *required* variable
    # (compose's ${VAR:?...} fails fast when unset).
    assert "DIAPASON_API_KEY" in text
    assert "DIAPASON_API_KEY:?" in text


def test_docker_env_example_present():
    assert (DEPLOY / "docker" / ".env.example").is_file()
    assert "DIAPASON_API_KEY" in _read("docker/.env.example")


def test_systemd_unit_binds_public_and_requires_env_file():
    text = _read("systemd/diapason.service")
    # Public bind -> must pull in an EnvironmentFile (no leading '-', so the
    # unit fails to start if it's missing).
    assert "--host 0.0.0.0" in text
    assert "EnvironmentFile=/etc/diapason/env" in text
    assert "\n-EnvironmentFile" not in text and "=-/etc" not in text


def test_launchd_plist_binds_loopback():
    """L'application complète reste sur la loopback — la règle n'a pas changé.

    Ce qui a changé, le 25 août 2026 : un SECOND socket peut exposer neuf
    routes du maillage sur le réseau. La règle n'est donc plus « le mot
    0.0.0.0 n'apparaît pas », qui interdisait aussi le cas légitime, mais
    « l'option host, celle qui porte les deux cent dix routes, vaut
    127.0.0.1 ».
    """
    import plistlib

    args = plistlib.loads(
        (DEPLOY / "launchd" / "com.diapason.serve.plist").read_bytes()
    )["ProgramArguments"]
    assert args[args.index("--host") + 1] == "127.0.0.1", (
        "l'application complète — chat, voix, Succès, outils — ne doit "
        "jamais écouter hors de cette machine"
    )


def test_le_plist_livre_n_ecoute_nulle_part_hors_de_cette_machine():
    """Aucun socket réseau par défaut — et ce test est le seul à le dire.

    Le filet d'origine était « le mot 0.0.0.0 n'apparaît pas ». Il a été
    remplacé le 25 août 2026 par une version qui se terminait par
    `if "--lan-host" not in args: return`, c'est-à-dire qui ne vérifiait
    plus rien dès lors que le plist n'exposait pas — l'exact contraire de
    ce qu'un garde-fou doit faire. Pendant ce temps le plist livré, lui,
    portait `--lan-host 0.0.0.0` actif : l'exposition était passée d'un
    choix à un héritage, sans que rien ne rougisse.

    Exposer un socket reste possible et documenté dans le plist. Mais cela
    s'ajoute à la main, sur une machine précise, par quelqu'un qui sait ce
    qu'il fait — jamais par un fichier livré à tout le monde.
    """
    import plistlib

    args = plistlib.loads(
        (DEPLOY / "launchd" / "com.diapason.serve.plist").read_bytes()
    )["ProgramArguments"]
    assert "--lan-host" not in args, (
        "le plist livré ouvrirait un socket réseau chez tous ceux qui "
        "l'installent : l'ouverture doit rester une décision, pas un défaut"
    )
    assert "0.0.0.0" not in args, (
        "aucune adresse d'écoute universelle dans le fichier livré"
    )


def test_un_second_socket_ne_peut_pas_partager_le_port_du_premier():
    """Si quelqu'un ouvre le maillage, les deux sockets doivent différer.

    Deux serveurs sur le même port se lient en silence sur macOS et
    échouent sur Linux. Le garde vit dans `serve`, qui refuse explicitement
    `--lan-port` égal à `--port` ; ce test vérifie que ce refus existe
    toujours, sans quoi le conseil écrit dans le plist serait un piège.
    """
    from click.testing import CliRunner

    from diapason.cli.serve import serve

    resultat = CliRunner().invoke(
        serve,
        [
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--lan-host",
            "0.0.0.0",
            "--lan-port",
            "8000",
        ],
    )
    assert resultat.exit_code != 0, "deux sockets sur le même port ont été acceptés"
    # Vérifier le MOTIF, pas seulement l'échec : un test qui accepte
    # n'importe quel code non nul passe le jour où la commande échoue pour
    # une raison sans rapport, et cesse alors de garder quoi que ce soit.
    assert "doit différer de --port" in (resultat.output or ""), (
        f"refus pour une autre raison que la collision de ports : "
        f"{(resultat.output or '')[-200:]}"
    )


@pytest.mark.parametrize(
    ("host", "api_key", "should_exit"),
    [
        ("127.0.0.1", "", False),
        ("localhost", "", False),
        ("0.0.0.0", "oj_sk_x", False),
        ("0.0.0.0", "", True),
        ("192.168.1.10", "", True),
    ],
)
def test_check_bind_safety(host, api_key, should_exit):
    from diapason.server.auth_middleware import check_bind_safety

    if should_exit:
        with pytest.raises(SystemExit):
            check_bind_safety(host, api_key=api_key)
    else:
        check_bind_safety(host, api_key=api_key)  # must not raise


def test_le_plist_livre_porte_l_etiquette_que_le_code_gere():
    """Une seconde étiquette ferait tourner DEUX serveurs, sans un mot.

    Le dépôt livrait `com.diapason.plist` étiqueté « com.diapason », tandis que
    `serve-service install` installe « com.diapason.serve ». Étiquettes
    différentes : launchd fait tourner les deux jobs simultanément, et le code
    n'inspecte jamais la première. La documentation disait de copier ce plist
    dans ~/Library/LaunchAgents — c'était donc un doublon documenté.

    Une seule étiquette, c'est launchd lui-même qui devient le verrou : un
    bootstrap sur une étiquette déjà chargée remplace, il ne duplique pas.
    """
    import plistlib

    from diapason.desktop.launch_agent import SERVE_LABEL

    chemin = DEPLOY / "launchd" / "com.diapason.serve.plist"
    donnees = plistlib.loads(chemin.read_bytes())
    assert donnees["Label"] == SERVE_LABEL


def test_le_nom_du_plist_livre_suit_son_etiquette():
    """Un fichier nommé autrement que son étiquette est un piège en soi."""
    import plistlib

    chemin = DEPLOY / "launchd" / "com.diapason.serve.plist"
    donnees = plistlib.loads(chemin.read_bytes())
    assert chemin.name == f"{donnees['Label']}.plist"


def test_le_port_venu_de_la_configuration_est_verifie_aussi(monkeypatch):
    """Le port peut venir de la configuration, pas de la ligne de commande.

    Le contrôle porte donc sur les valeurs RÉSOLUES, et il est placé juste
    après leur résolution — avant la recherche d'un moteur d'inférence.
    Placé après, il n'était jamais atteint sur une machine sans Ollama, et
    le test censé le garder passait sur un tout autre échec.
    """
    from click.testing import CliRunner

    from diapason.cli.serve import serve

    resultat = CliRunner().invoke(
        serve, ["--host", "127.0.0.1", "--lan-host", "0.0.0.0", "--lan-port", "8000"]
    )
    sortie = resultat.output or ""
    assert resultat.exit_code == 2, f"attendu 2, obtenu {resultat.exit_code}"
    assert "doit différer de --port" in sortie, (
        f"refus pour une autre raison : {sortie[-200:]}"
    )
    assert "No inference engine" not in sortie, (
        "le contrôle est encore placé après la recherche du moteur"
    )
