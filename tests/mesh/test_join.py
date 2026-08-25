"""Rejoindre une flotte : le côté invité, et le défaut qu'il corrige.

Spatial Mesh, phase 0 — 25 août 2026. Deux Diapason obtenaient TRUSTED des
deux côtés puis se refusaient mutuellement chaque échange, parce que
personne n'appelait ``adopt_owner_id`` : chacun gardait l'identifiant de
flotte aléatoire frappé à son premier démarrage, et ``signed.py`` refuse
une enveloppe d'un autre propriétaire AVANT de regarder la signature.

Les tests existants masquaient le défaut en injectant le même propriétaire
des deux côtés. Ceux-ci ne l'injectent nulle part : ils font ce que fait
la vraie vie.
"""

from __future__ import annotations

import pytest

from diapason.mesh.join import JoinError, join_fleet


def _reponse_hote(owner: str, device_id: str = "dev_" + "a" * 24) -> dict:
    """Ce que renvoie réellement POST /v1/mesh/pairings/redeem."""
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    brut = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    return {
        "device": {"deviceId": "dev_moi", "capabilities": ["app.navigate"]},
        "host": {
            "deviceId": device_id,
            "publicKey": base64.b64encode(brut).decode("ascii"),
            "name": "iMac du salon",
            "platform": "MACOS",
            "ownerId": owner,
            "address": "http://192.168.0.5:8000",
            "capabilities": ["app.navigate", "notifications.show"],
        },
    }


class TestAdoptionDeLaFlotte:
    def test_rejoindre_adopte_l_identite_de_flotte_de_l_hote(self):
        """LE défaut corrigé : sans cette adoption, les deux appareils se
        refusent mutuellement chaque enveloppe."""
        from diapason.mesh.identity import owner_id

        avant = owner_id()  # notre identifiant aléatoire de naissance
        hote = "owner_" + "b" * 32
        assert avant != hote

        resultat = join_fleet(
            "http://192.168.0.5:8000",
            "jeton-valide",
            my_address="http://192.168.0.9:8000",
            poster=lambda url, corps: _reponse_hote(hote),
        )

        assert resultat.owner_id == hote
        assert owner_id() == hote, "l'identité de flotte doit être adoptée sur disque"

    def test_l_hote_entre_dans_notre_registre(self):
        """Le jumelage est mutuel : savoir lui parler ne suffit pas, il faut
        savoir le reconnaître quand il répond."""
        from diapason.mesh.registry import DeviceRegistry

        reponse = _reponse_hote("owner_" + "c" * 32)
        resultat = join_fleet(
            "http://192.168.0.5:8000",
            "jeton",
            my_address="",
            poster=lambda url, corps: reponse,
        )
        inscrit = DeviceRegistry().find(resultat.host_device_id)
        assert inscrit is not None
        assert inscrit["name"] == "iMac du salon"
        assert inscrit["trustLevel"] == "TRUSTED"

    def test_on_ne_change_pas_de_flotte_en_silence(self):
        """Un appareil déjà membre d'une flotte refuse d'en rejoindre une
        autre : ce serait perdre tous ses pairs d'un coup."""
        join_fleet(
            "http://a", "j", my_address="",
            poster=lambda u, c: _reponse_hote("owner_" + "d" * 32),
        )
        with pytest.raises(JoinError, match="autre ensemble"):
            join_fleet(
                "http://b", "j", my_address="",
                poster=lambda u, c: _reponse_hote("owner_" + "e" * 32),
            )

    def test_un_hote_sans_identite_de_flotte_est_refuse(self):
        """Version trop ancienne : on le dit, on ne devine pas."""
        reponse = _reponse_hote("")
        reponse["host"].pop("ownerId")
        with pytest.raises(JoinError, match="identité de flotte"):
            join_fleet("http://a", "j", my_address="", poster=lambda u, c: reponse)


class TestCeQuOnEnvoie:
    def test_l_invitation_part_avec_notre_identite_publique(self):
        from diapason.mesh.identity import device_identity

        vus = {}

        def espion(url, corps):
            vus["url"] = url
            vus["corps"] = corps
            return _reponse_hote("owner_" + "f" * 32)

        join_fleet("192.168.0.5:8000", "  mon-jeton  ", my_address="http://moi",
                   poster=espion)
        moi = device_identity()
        assert vus["url"] == "http://192.168.0.5:8000/v1/mesh/pairings/redeem"
        assert vus["corps"]["pairingToken"] == "mon-jeton"  # espaces retirés
        assert vus["corps"]["deviceId"] == moi.device_id
        assert vus["corps"]["publicKey"] == moi.public_key_b64
        assert vus["corps"]["platform"] == moi.platform
        assert "app.navigate" in vus["corps"]["capabilities"]
        # jamais la clé privée, sous aucun nom
        assert "privateKey" not in vus["corps"]
        assert "private" not in str(vus["corps"]).lower()


class TestAdressesRefusees:
    @pytest.mark.parametrize(
        "url,motif",
        [
            ("", "adresse"),
            ("ftp://192.168.0.5", "http"),
            ("http://user:pass@192.168.0.5", "identifiants"),
        ],
    )
    def test_une_adresse_douteuse_est_refusee_avant_tout_envoi(self, url, motif):
        def interdit(*_a, **_k):
            raise AssertionError("rien ne doit partir vers une adresse refusée")

        with pytest.raises(JoinError, match=motif):
            join_fleet(url, "jeton", poster=interdit)

    def test_un_jeton_vide_ne_part_pas(self):
        def interdit(*_a, **_k):
            raise AssertionError("rien ne doit partir sans invitation")

        with pytest.raises(JoinError, match="invitation"):
            join_fleet("http://a", "   ", poster=interdit)
