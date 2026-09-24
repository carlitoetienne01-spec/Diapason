"""La serrure et la limite de déverrouillage.

Conception : ``docs/development/compte-chiffre.md`` §2.10 (un seul objet
``Serrure``) et §3.8 (``unlock`` : 5 essais, puis 30 s).
"""

from __future__ import annotations

import pytest

from diapason.compte.serrure import (
    CompteVerrouille,
    LimiteDeverrouillage,
    Serrure,
    TropDEssais,
)
from diapason.compte.trousseau import nouveau_trousseau


class TestLaSerrure:
    def test_verrouillee_elle_repond_423_et_jamais_401(self):
        """§3.8 : un compte verrouillé rend 423 ``accountLocked`` ; un 401
        ferait rafraîchir la clé d'API locale en boucle (``api.ts:191``)."""
        with pytest.raises(CompteVerrouille) as refus:
            Serrure().exiger()
        assert refus.value.code == "accountLocked"
        # Le statut vient de la table des routes : le vérifier ici, et non
        # seulement le code, est ce que le nom de ce test promet
        # (contre-épreuve du 24/09/2026 : 409 le laissait vert).
        routes = pytest.importorskip("diapason.server.compte_routes")
        assert routes._statut_de(refus.value.code) == 423, (
            "un compte verrouillé doit rendre 423"
        )

    def test_fermer_ecrase_l_amk(self):
        """§2.10 : l'AMK vit dans un ``bytearray`` écrasé après usage."""
        serrure = Serrure()
        serrure.ouvrir(
            b"\x07" * 32, nouveau_trousseau(None), account_id="a", incarnation=1
        )
        tampon = serrure._amk
        serrure.fermer()
        assert tampon == bytearray(32), "l'AMK n'a pas été écrasée à la fermeture"
        assert not serrure.ouverte

    def test_la_trace_d_une_ouverture_ne_montre_pas_l_amk(self):
        serrure = Serrure()
        serrure.ouvrir(
            b"\x42" * 32, nouveau_trousseau(None), account_id="a", incarnation=1
        )
        assert "BBBB" not in repr(serrure.exiger()), "l'AMK apparaît dans repr()"


class TestLaLimiteDeDeverrouillage:
    """§3.8 : « ``POST /v1/account/unlock`` est strict : 5 essais, puis 30 s
    d'attente, en plus du seau »."""

    def test_cinq_echecs_puis_trente_secondes(self):
        maintenant = [0.0]
        limite = LimiteDeverrouillage(horloge=lambda: maintenant[0])
        for _ in range(4):
            limite.verifier()
            limite.echec()
        limite.verifier()  # le cinquième essai est permis
        limite.echec()
        with pytest.raises(TropDEssais) as refus:
            limite.verifier()
        assert refus.value.retry_after_s == 30
        maintenant[0] = 29.5
        with pytest.raises(TropDEssais):
            limite.verifier()
        maintenant[0] = 30.0
        limite.verifier()  # l'attente est finie : cinq essais de nouveau
        for _ in range(4):
            limite.echec()
            limite.verifier()  # quatre échecs après l'attente ne bloquent pas
        limite.echec()
        with pytest.raises(TropDEssais):
            limite.verifier()

    def test_une_reussite_remet_le_compte_a_zero(self):
        """Ce sont les ÉCHECS qui comptent : quatre fautes puis le bon mot de
        passe ne doivent pas faire attendre au prochain lancement."""
        limite = LimiteDeverrouillage(horloge=lambda: 0.0)
        for _ in range(4):
            limite.echec()
        limite.reussite()
        for _ in range(4):
            limite.echec()
        limite.verifier()
