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
    text = _read("launchd/com.diapason.serve.plist")
    # Personal-device default: loopback, not the network.
    assert "<string>127.0.0.1</string>" in text
    assert "<string>0.0.0.0</string>" not in text


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
