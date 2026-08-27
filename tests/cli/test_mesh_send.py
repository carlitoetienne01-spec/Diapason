"""`diapason mesh send` — le premier appelant du transfert de fichiers.

Le cœur existait depuis le 25 août 2026 : manifeste, morceaux d'1 Mio,
reprise, chiffrement X25519 + AES-GCM, et un banc à deux processus qui fait
passer 2 Mo avec deux tentatives d'intrusion refusées. Mais `envoyer_fichier`
n'avait AUCUN appelant en production — ni interface, ni commande, ni outil.
Un moteur qu'on ne peut pas démarrer n'est pas un moteur.

Cette commande est le chemin le plus court qui prouve un vrai transfert entre
deux machines. L'interface se construira par-dessus.
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from diapason.cli.mesh_cmd import mesh


def _appareil(nom="PC du bureau", identifiant="dev_pc"):
    return {
        "deviceId": identifiant,
        "name": nom,
        "trustLevel": "TRUSTED",
        "address": "http://192.168.1.20:8000",
    }


def _fichier(tmp_path, nom="rapport.pdf", octets=b"x" * 2048):
    chemin = tmp_path / nom
    chemin.write_bytes(octets)
    return str(chemin)


class TestCeQuElleRefuseDeDeviner:
    """§34 — une phrase qui désigne deux appareils n'en désigne aucun.

    Envoyer un document à un appareil choisi au hasard est l'échec le plus
    grave que ce chantier puisse produire.
    """

    def test_sans_flotte_elle_dit_quoi_faire(self, tmp_path):
        with patch(
            "diapason.mesh.registry.DeviceRegistry.list_devices", return_value=[]
        ):
            r = CliRunner().invoke(mesh, ["send", _fichier(tmp_path), "mon PC"])
        assert r.exit_code == 1
        assert "join" in r.output, "un refus doit dire par où commencer"

    def test_un_nom_ambigu_repose_la_question(self, tmp_path):
        with (
            patch(
                "diapason.mesh.registry.DeviceRegistry.list_devices",
                return_value=[
                    _appareil("PC du bureau"),
                    _appareil("PC du salon", "dev_2"),
                ],
            ),
            patch("diapason.mesh.envoi_fichier.envoyer_fichier") as envoi,
        ):
            r = CliRunner().invoke(mesh, ["send", _fichier(tmp_path), "PC"])
        assert r.exit_code == 1
        envoi.assert_not_called(), "rien ne part vers un appareil deviné"

    def test_un_nom_inconnu_ne_part_pas_au_hasard(self, tmp_path):
        with (
            patch(
                "diapason.mesh.registry.DeviceRegistry.list_devices",
                return_value=[_appareil()],
            ),
            patch("diapason.mesh.envoi_fichier.envoyer_fichier") as envoi,
        ):
            r = CliRunner().invoke(
                mesh, ["send", _fichier(tmp_path), "la télévision du salon"]
            )
        assert r.exit_code == 1
        envoi.assert_not_called()

    def test_un_fichier_absent_est_refuse_avant_tout(self, tmp_path):
        r = CliRunner().invoke(mesh, ["send", str(tmp_path / "néant.pdf"), "PC"])
        assert r.exit_code != 0


class TestUnEnvoiQuiAboutit:
    def test_le_fichier_part_vers_l_appareil_resolu(self, tmp_path):
        from diapason.mesh.envoi_fichier import Envoi

        with (
            patch(
                "diapason.mesh.registry.DeviceRegistry.list_devices",
                return_value=[_appareil()],
            ),
            patch(
                "diapason.mesh.envoi_fichier.envoyer_fichier",
                return_value=Envoi(
                    statut="COMPLETE",
                    message="rapport.pdf est arrivé.",
                    chemin_distant="~/.diapason/transfers/rapport.pdf",
                    octets=2048,
                    morceaux=1,
                ),
            ) as envoi,
        ):
            r = CliRunner().invoke(mesh, ["send", _fichier(tmp_path), "PC du bureau"])
        assert r.exit_code == 0
        assert envoi.call_args[0][1]["deviceId"] == "dev_pc"
        assert "est arrivé" in r.output

    def test_la_phrase_vient_du_destinataire(self, tmp_path):
        """Fabriquer la phrase à l'émission, c'est promettre ce qu'on n'a pas
        constaté — la règle du §100, ici aussi."""
        from diapason.mesh.envoi_fichier import Envoi

        with (
            patch(
                "diapason.mesh.registry.DeviceRegistry.list_devices",
                return_value=[_appareil()],
            ),
            patch(
                "diapason.mesh.envoi_fichier.envoyer_fichier",
                return_value=Envoi(statut="COMPLETE", message="Reçu, et vérifié."),
            ),
        ):
            r = CliRunner().invoke(mesh, ["send", _fichier(tmp_path), "PC du bureau"])
        assert "Reçu, et vérifié." in r.output

    def test_un_refus_du_transport_se_relaie_tel_quel(self, tmp_path):
        """Le destinataire ou le transport sait pourquoi ; nous non."""
        from diapason.mesh.envoi_fichier import EnvoiRefuse

        with (
            patch(
                "diapason.mesh.registry.DeviceRegistry.list_devices",
                return_value=[_appareil()],
            ),
            patch(
                "diapason.mesh.envoi_fichier.envoyer_fichier",
                side_effect=EnvoiRefuse("PC du bureau n'a pas répondu."),
            ),
        ):
            r = CliRunner().invoke(mesh, ["send", _fichier(tmp_path), "PC du bureau"])
        assert r.exit_code == 1
        assert "n'a pas répondu" in r.output


class TestLaTailleSeLitSansCompterLesZeros:
    def test_les_unites(self):
        from diapason.cli.mesh_cmd import _lisible

        assert _lisible(512) == "512 o"
        assert _lisible(2048) == "2.0 Ko"
        assert _lisible(3 * (1 << 20)) == "3.0 Mo"
        assert _lisible(1 << 30) == "1.0 Go"


class TestAucunStatutInvente:
    """Le défaut le plus bête, et le plus difficile à voir.

    La commande a colorié son verdict d'après « RECU » pendant une heure —
    une chaîne qui n'existait NULLE PART dans `src/`. Le récepteur rend
    `COMPLETE` ou `ALREADY_PRESENT` (`mesh/files_routes.py`). Un transfert
    parfaitement réussi s'affichait donc en jaune, comme une réserve.

    Le test ne l'a pas vu parce que son propre double rendait « RECU » : le
    double était plus commode que ce qu'il doublait. Cette classe compare la
    commande au CODE, pas à un double.
    """

    def test_les_statuts_reconnus_sont_ceux_que_le_recepteur_produit(self):
        import re
        from pathlib import Path

        from diapason.cli.mesh_cmd import _ABOUTIS

        source = Path("src/diapason/mesh/files_routes.py").read_text()
        produits = set(re.findall(r'"status":\s*"([A-Z_]+)"', source))
        inconnus = _ABOUTIS - produits
        assert not inconnus, (
            f"{sorted(inconnus)} : la commande colorie d'après un statut que "
            "le récepteur ne produit pas. C'est ainsi qu'un succès s'affiche "
            "comme un doute."
        )

    def test_un_transfert_abouti_s_affiche_comme_un_succes(self):
        from diapason.cli.mesh_cmd import _ABOUTIS

        assert "COMPLETE" in _ABOUTIS
        # La déduplication par contenu est un succès, pas une réserve : le
        # fichier est là, entier et vérifié — il n'a simplement pas eu besoin
        # de repasser sur le fil.
        assert "ALREADY_PRESENT" in _ABOUTIS


class TestLAideNePrometPasCeQueLeResolveurRefuse:
    """`--help` annonçait qu'APPAREIL pouvait être un identifiant.

    Le résolveur ne compare que des noms, des types d'appareil et des
    plateformes : sur un identifiant il rend « inconnu ». Et `mesh devices`
    AFFICHE cet identifiant, ce qui invite précisément à le copier — donc
    l'aide envoyait vers l'échec (constaté le 26 août 2026).

    Ce test lie les deux : si le résolveur se met un jour à accepter un
    identifiant, il rougit, et la docstring redevient à écrire.
    """

    def test_le_resolveur_refuse_un_identifiant(self):
        from diapason.mesh.resolver import resolve_device

        flotte = [
            {
                "deviceId": "dev_abc123",
                "name": "Mon téléphone",
                "platform": "ANDROID",
                "trustLevel": "TRUSTED",
            }
        ]
        par_nom = resolve_device("Mon téléphone", flotte, local_device_id="moi")
        assert par_nom["status"] == "RESOLVED"

        par_id = resolve_device("dev_abc123", flotte, local_device_id="moi")
        assert par_id["status"] != "RESOLVED", (
            "le résolveur accepte désormais un identifiant : la docstring de "
            "`mesh send` et docs/user-guide/cli.md disent le contraire"
        )

    def test_l_aide_ne_promet_pas_l_identifiant(self):
        from diapason.cli.mesh_cmd import send

        aide = send.__doc__ or ""
        assert "PAS par son identifiant" in aide, (
            "l'aide doit dire ce que le résolveur fait vraiment"
        )
