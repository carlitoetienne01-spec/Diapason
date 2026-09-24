"""L'état local ``compte/etat.key`` et ses planchers.

Conception : ``docs/development/compte-chiffre.md`` §4.2, §4.4, §2.10 et
§6 bis (``incarnation_max``, exigé de l'étape 8).
"""

from __future__ import annotations

import os
import stat
from unittest.mock import MagicMock

import pytest

from diapason.compte.etat import (
    EnveloppeLocale,
    EtatLocal,
    RetourArriereServeur,
    accueil_fait,
    marquer_accueil,
)
from diapason.compte.gardien import CheminRefuse, preparer_dossier_compte
from diapason.server.conversations_store import ConversationsStore


@pytest.fixture
def dossier(tmp_path):
    return preparer_dossier_compte(tmp_path, plateforme="linux")


class TestLeFichierNExisteQueSIlYAUnCompte:
    """``ConversationsStore`` cesse de purger les tombales dès que
    ``compte/etat.key`` existe. Un sondage de ``/status`` ou un « Plus
    tard » qui le créeraient bloqueraient la purge chez qui n'a pas de
    compte."""

    def test_les_lectures_ne_creent_pas_le_fichier(self, dossier):
        """§4.11 : l'état se recalcule à chaque lecture, sans rien écrire."""
        etat = EtatLocal(dossier)
        assert etat.tout() == {}
        assert etat.planchers() is None
        assert etat.enveloppe_locale() is None
        assert not etat.existe(), "une lecture a créé etat.key"

    def test_le_premier_lancement_ne_cree_pas_l_etat(self, dossier, tmp_path):
        """§3.11 P1 « Plus tard » : le drapeau vit à part, et le magasin des
        conversations continue de purger."""
        marquer_accueil(dossier)
        assert accueil_fait(dossier), "le drapeau du premier lancement est perdu"
        assert not EtatLocal(dossier).existe(), "« Plus tard » a créé etat.key"
        magasin = ConversationsStore(tmp_path / "conversations.db")
        try:
            assert not magasin._compte_present(), (
                "le magasin croit à un compte après « Plus tard »"
            )
        finally:
            magasin.close()

    def test_la_premiere_ecriture_cree_un_fichier_prive(self, dossier):
        """§2.10 : ``etat.key`` porte l'enveloppe AMK et les planchers ; né en
        0644 par l'umask, il serait lisible des autres comptes de la machine."""
        etat = EtatLocal(dossier)
        etat.ecrire(accountId="compte")
        assert etat.existe()
        mode = stat.S_IMODE(os.stat(etat.chemin).st_mode)
        assert mode == 0o600, f"etat.key doit naître en 0600, pas {oct(mode)}"

    def test_detruire_efface_le_fichier_et_rend_la_purge(self, dossier, tmp_path):
        """§4.4 « une déconnexion ou un autre compte vide tout » : le fichier
        disparaît, sinon sa présence seule bloquerait encore la purge."""
        etat = EtatLocal(dossier)
        etat.ecrire(accountId="compte")
        etat.relever_planchers(
            "compte", 1, vault_version=1, keyring_version=1, key_epoch=1
        )
        etat.detruire()
        assert not etat.existe(), "etat.key a survécu à la déconnexion"
        assert etat.tout() == {} and etat.planchers() is None

    def test_un_double_de_test_n_est_pas_un_dossier(self):
        """CLAUDE.md §5 : ``Path(MagicMock())`` a fait dormir 42 bases à la
        racine du dépôt ; ici, ce serait une clé."""
        with pytest.raises(CheminRefuse):
            EtatLocal(MagicMock())  # type: ignore[arg-type]


class TestLesPlanchers:
    """§4.4 : « ce qu'aucune valeur serveur ne remet à zéro »."""

    def test_les_planchers_ne_descendent_jamais(self, dossier):
        etat = EtatLocal(dossier)
        etat.relever_planchers("a", 1, vault_version=3, keyring_version=3, key_epoch=3)
        etat.relever_planchers("a", 1, vault_version=1, keyring_version=2, key_epoch=1)
        p = etat.planchers()
        assert (p.vault_version_max, p.keyring_version_max, p.key_epoch_max) == (
            3,
            3,
            3,
        ), "un coffre plus ancien a fait reculer un plancher"

    def test_une_incarnation_inferieure_est_un_retour_arriere(self, dossier):
        """§6 bis : le VPS qui rejoue le coffre d'avant une réinitialisation
        annonce aussi l'incarnation d'avant ; refusée AVANT tout essai de
        clé, sinon elle se lisait comme un mauvais mot de passe."""
        etat = EtatLocal(dossier)
        etat.relever_planchers("a", 2, vault_version=1, keyring_version=1, key_epoch=1)
        with pytest.raises(RetourArriereServeur) as refus:
            etat.planchers_pour("a", 1)
        assert refus.value.code == "serverRolledBack"
        with pytest.raises(RetourArriereServeur):
            etat.relever_planchers(
                "a", 1, vault_version=9, keyring_version=9, key_epoch=9
            )

    def test_une_incarnation_superieure_repart_de_zero(self, dossier):
        """Après ``reset/complete``, le coffre recommence à la version 1 : des
        planchers gardés à 5 refuseraient le coffre neuf pour toujours."""
        etat = EtatLocal(dossier)
        etat.relever_planchers("a", 1, vault_version=5, keyring_version=5, key_epoch=5)
        assert etat.planchers_pour("a", 2).vault_version_max == 0
        etat.relever_planchers("a", 2, vault_version=1, keyring_version=1, key_epoch=1)
        p = etat.planchers()
        assert (p.incarnation_max, p.vault_version_max) == (2, 1)

    def test_un_autre_compte_n_herite_pas_des_planchers(self, dossier):
        """Les planchers de A ne jugent pas le coffre de B."""
        etat = EtatLocal(dossier)
        etat.relever_planchers("a", 3, vault_version=5, keyring_version=5, key_epoch=5)
        p = etat.planchers_pour("b", 1)
        assert (p.account_id, p.incarnation_max, p.vault_version_max) == ("b", 1, 0)

    def test_l_enveloppe_locale_s_efface_sans_toucher_aux_planchers(self, dossier):
        """§3.7 : sur ``sessionRevoked``, l'enveloppe part ; les planchers
        restent, sinon la reconnexion suivante accepterait un coffre rejoué."""
        etat = EtatLocal(dossier)
        etat.relever_planchers("a", 1, vault_version=4, keyring_version=4, key_epoch=4)
        etat.ranger_enveloppe_locale(
            EnveloppeLocale(1, bytes(32), b"amk", b"trousseau", 4, 4)
        )
        etat.effacer_enveloppe_locale()
        assert etat.enveloppe_locale() is None
        assert etat.planchers().vault_version_max == 4, "le plancher est parti avec"
