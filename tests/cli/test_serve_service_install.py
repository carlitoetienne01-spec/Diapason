"""`serve-service install` — la porte par laquelle l'exposition est entrée.

Le 26 août 2026, ce Mac servait ses deux cent dix routes sur le Wi-Fi. Le
plist du dépôt, lui, était irréprochable : il portait 127.0.0.1. Mais ce
n'est pas lui qui s'installe — c'est `serve-service install` qui écrit le
LaunchAgent réellement chargé, et cette commande acceptait `--host 0.0.0.0`
dès qu'on ajoutait `--allow-network`.

Le motif de cette échappatoire était réel : « un téléphone ne peut pas
joindre 127.0.0.1 ». Il n'y avait alors pas d'autre réponse. Il y en a une
depuis — un second socket qui ne porte que neuf routes du maillage — donc
l'échappatoire n'a plus de raison d'être, et ces tests l'empêchent de
revenir.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from diapason.cli.serve_service_cmd import serve_service

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="LaunchAgent : macOS seulement"
)


@pytest.fixture(autouse=True)
def _ne_rien_installer():
    """Aucun test ne pose de LaunchAgent sur la machine qui l'exécute.

    Sans ce filet, le jour où un garde disparaît, les tests censés le
    vérifier ne rougiraient pas : ils INSTALLERAIENT le service exposé
    qu'ils étaient chargés d'empêcher. Un test ne doit pas pouvoir faire ce
    qu'il interdit.
    """
    with (
        patch(
            "diapason.desktop.launch_agent.install", return_value="/tmp/faux.plist"
        ) as pose,
        patch("diapason.desktop.launch_agent.is_loaded", return_value=True),
        patch("diapason.core.ports.port_state", return_value=("libre", "")),
    ):
        yield pose


def _invoquer(*args: str):
    return CliRunner().invoke(serve_service, ["install", *args])


class TestLApplicationCompleteNeSortJamais:
    def test_une_adresse_reseau_est_refusee(self, _ne_rien_installer):
        resultat = _invoquer("--host", "0.0.0.0")
        assert resultat.exit_code == 1
        assert "Refusing to bind" in resultat.output
        _ne_rien_installer.assert_not_called()

    def test_aucune_echappatoire_ne_la_rouvre(self, _ne_rien_installer):
        """`--allow-network` mettait les deux cent dix routes sur le réseau."""
        resultat = _invoquer("--host", "0.0.0.0", "--allow-network")
        assert resultat.exit_code == 1, "l'échappatoire fonctionne encore"
        _ne_rien_installer.assert_not_called()

    def test_l_ancienne_option_echoue_au_lieu_de_faire_autre_chose(self):
        """Elle aurait pu devenir un alias silencieux du nouveau chemin.

        Une commande qui se met à faire autre chose sans le dire est pire
        qu'une commande qui disparaît : celui qui la tape croit obtenir ce
        qu'il obtenait avant.
        """
        resultat = _invoquer("--allow-network")
        assert resultat.exit_code == 1
        assert "n'existe plus" in resultat.output
        assert "--maillage-reseau" in resultat.output, (
            "un refus doit nommer ce qui remplace"
        )


class TestLeMaillagePasseParSaProprePorte:
    def test_sans_rien_demander_aucun_socket_reseau(self, _ne_rien_installer):
        _invoquer("--host", "127.0.0.1", "--port", "8000")
        args = _ne_rien_installer.call_args.kwargs["args"]
        assert "--lan-host" not in args, "un socket réseau est apparu sans demande"

    def test_demande_explicitement_le_socket_s_ajoute(self, _ne_rien_installer):
        _invoquer("--host", "127.0.0.1", "--port", "8000", "--maillage-reseau")
        args = _ne_rien_installer.call_args.kwargs["args"]
        assert args[args.index("--host") + 1] == "127.0.0.1", (
            "l'application complète doit rester sur la loopback"
        )
        assert args[args.index("--lan-host") + 1] == "0.0.0.0"
        assert args[args.index("--lan-port") + 1] == "8001"

    def test_le_meme_port_pour_les_deux_est_refuse(self):
        resultat = _invoquer(
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--maillage-reseau",
            "--lan-port",
            "8000",
        )
        assert resultat.exit_code == 1
        assert "même port" in resultat.output

    def test_ouvrir_le_maillage_se_dit_a_voix_haute(self):
        """Un réseau partagé reste un réseau partagé, même pour neuf routes."""
        resultat = _invoquer("--host", "127.0.0.1", "--maillage-reseau")
        assert "0.0.0.0" in resultat.output
        assert "réseau local pourra l'atteindre" in resultat.output
