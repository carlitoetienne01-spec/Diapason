"""The device registry: enrolment, trust, and who decides what a device can do.

The headline property here is acceptance TEST I — a device that CLAIMS a
capability its platform cannot honour does not receive it. Declaration is
information; the grant is the server's.
"""

from __future__ import annotations

import base64
import sqlite3

import pytest

from diapason.mesh.capabilities import (
    ALL_CAPABILITIES,
    PLATFORM_CAPABILITIES,
    effective_capabilities,
    platform_allows,
)
from diapason.mesh.registry import (
    PAIRING_TTL_MS,
    DeviceRegistry,
    MeshError,
)
from diapason.security.signing import generate_keypair


@pytest.fixture
def registry(tmp_path) -> DeviceRegistry:
    return DeviceRegistry(tmp_path / "mesh.db")


def a_key() -> str:
    return base64.b64encode(generate_keypair().public_key).decode("ascii")


def enrol(
    registry: DeviceRegistry,
    *,
    device_id: str = "dev_phone",
    platform: str = "IOS",
    device_type: str = "PHONE",
    capabilities=(),
    key: str | None = None,
) -> dict:
    invitation = registry.create_pairing("iPhone de Carlito")
    return registry.redeem_pairing(
        invitation["pairingToken"],
        device_id=device_id,
        public_key_b64=key or a_key(),
        name="iPhone de Carlito",
        platform=platform,
        device_type=device_type,
        declared_capabilities=list(capabilities),
    )


class TestPairing:
    def test_a_device_can_be_enrolled(self, registry):
        device = enrol(registry)
        assert device["deviceId"] == "dev_phone"
        assert device["trustLevel"] == "TRUSTED"
        assert registry.list_devices()[0]["name"] == "iPhone de Carlito"

    def test_the_invitation_is_stored_hashed_and_spent_once(self, registry, tmp_path):
        invitation = registry.create_pairing("iPad")
        token = invitation["pairingToken"]

        with sqlite3.connect(tmp_path / "mesh.db") as conn:
            stored = conn.execute("SELECT token_hash FROM mesh_pairings").fetchone()[0]
        assert token not in stored  # never at rest in the clear

        registry.redeem_pairing(
            token,
            device_id="dev_ipad",
            public_key_b64=a_key(),
            name="iPad",
            platform="IPADOS",
            device_type="TABLET",
        )
        with pytest.raises(MeshError, match="déjà été utilisé"):
            registry.redeem_pairing(
                token,
                device_id="dev_autre",
                public_key_b64=a_key(),
                name="Intrus",
                platform="IPADOS",
                device_type="TABLET",
            )

    def test_two_devices_racing_on_one_invitation_cannot_both_get_in(
        self, registry, tmp_path
    ):
        """« Spent once » has to hold under a race, not just in sequence.

        Reading redeemed_at_ms and then writing it left a gap — sqlite3 opens
        its transaction at the first write — so two redemptions could both
        read "unused" and both succeed. The extra device was not the worst of
        it: the legitimate one succeeded too, so the « déjà utilisé » message
        that would have told the user their code was stolen never appeared.
        """
        import threading

        token = registry.create_pairing("MacBook de Carlito")["pairingToken"]
        gate = threading.Barrier(2)
        outcomes: dict[str, str] = {}

        def redeem(tag: str, device_id: str) -> None:
            # Its own connection, as two HTTP requests would have.
            peer = DeviceRegistry(db_path=tmp_path / "mesh.db")
            gate.wait()
            try:
                peer.redeem_pairing(
                    token,
                    device_id=device_id,
                    public_key_b64=a_key(),
                    name="MacBook de Carlito",
                    platform="MACOS",
                    device_type="LAPTOP",
                )
                outcomes[tag] = "admitted"
            except MeshError:
                outcomes[tag] = "refused"

        threads = [
            threading.Thread(target=redeem, args=("first", "dev_" + "a" * 20)),
            threading.Thread(target=redeem, args=("second", "dev_" + "b" * 20)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(outcomes.values()) == ["admitted", "refused"]
        assert len(registry.list_devices()) == 1

    def test_a_refusal_after_the_claim_leaves_the_invitation_usable(self, registry):
        """The claim is rolled back with the rest of the transaction.

        Otherwise presenting a revoked device — which is refused several
        checks later — would silently burn a perfectly good invitation and
        the user would have to mint another for no reason they could see.
        """
        enrol(registry, device_id="dev_pc", platform="WINDOWS", device_type="DESKTOP")
        registry.revoke("dev_pc")

        token = registry.create_pairing("PC")["pairingToken"]
        with pytest.raises(MeshError, match="révoqué"):
            registry.redeem_pairing(
                token,
                device_id="dev_pc",
                public_key_b64=a_key(),
                name="PC",
                platform="WINDOWS",
                device_type="DESKTOP",
            )
        # Same invitation, a device that may join: still good.
        device = registry.redeem_pairing(
            token,
            device_id="dev_portable",
            public_key_b64=a_key(),
            name="Portable",
            platform="MACOS",
            device_type="LAPTOP",
        )
        assert device["trustLevel"] == "TRUSTED"

    def test_an_expired_invitation_is_refused(self, registry, tmp_path):
        invitation = registry.create_pairing("Vieux PC")
        with sqlite3.connect(tmp_path / "mesh.db") as conn:
            conn.execute(
                "UPDATE mesh_pairings SET expires_at_ms = ?",
                (invitation["expiresAtMs"] - PAIRING_TTL_MS * 2,),
            )
            conn.commit()
        with pytest.raises(MeshError, match="expiré"):
            registry.redeem_pairing(
                invitation["pairingToken"],
                device_id="dev_pc",
                public_key_b64=a_key(),
                name="PC",
                platform="WINDOWS",
                device_type="DESKTOP",
            )

    def test_a_malformed_public_key_is_refused(self, registry):
        invitation = registry.create_pairing("Suspect")
        for bad in ("", "pas-du-base64!", base64.b64encode(b"trop court").decode()):
            with pytest.raises(MeshError):
                registry.redeem_pairing(
                    invitation["pairingToken"],
                    device_id="dev_bad",
                    public_key_b64=bad,
                    name="Suspect",
                    platform="MACOS",
                    device_type="LAPTOP",
                )


class TestCapabilityGrants:
    """Acceptance TEST I — a claim is not a grant."""

    def test_a_phone_claiming_host_automation_does_not_get_it(self, registry):
        device = enrol(
            registry,
            platform="IOS",
            capabilities=[
                "tasks.read",
                "app.navigate",
                "automation.approved.run",  # the lie
                "desktop.open",  # also impossible on iOS
            ],
        )
        # What it claimed is recorded honestly…
        assert "automation.approved.run" in device["declaredCapabilities"]
        # …and what it GETS excludes what iOS cannot honour.
        assert "automation.approved.run" not in device["capabilities"]
        # `desktop.open` and not a made-up verb: `effective_capabilities`
        # silently DROPS an unknown one (see the test below), so asserting
        # against a verb outside the vocabulary would pass while proving
        # nothing. This one is in the vocabulary and outside the iOS ceiling.
        assert "desktop.open" not in device["capabilities"]
        assert device["capabilities"] == ["app.navigate", "tasks.read"]

    def test_a_mac_gets_what_it_declares(self, registry):
        device = enrol(
            registry,
            device_id="dev_mac",
            platform="MACOS",
            device_type="LAPTOP",
            capabilities=["automation.approved.run", "tasks.write"],
        )
        assert set(device["capabilities"]) == {
            "automation.approved.run",
            "tasks.write",
        }

    def test_a_capability_the_device_never_claimed_is_never_granted(self, registry):
        device = enrol(registry, platform="MACOS", capabilities=["tasks.read"])
        # The ceiling is not the grant: macOS allows everything, this build
        # only implements one thing, so one thing is what it gets.
        assert device["capabilities"] == ["tasks.read"]

    def test_unknown_platforms_fall_back_to_read_only(self):
        granted = effective_capabilities(
            "TOASTER", ["tasks.write", "tasks.read", "automation.approved.run"]
        )
        assert granted == ("tasks.read",)

    def test_an_unknown_verb_is_dropped_not_fatal(self):
        granted = effective_capabilities("MACOS", ["tasks.read", "teleport.user"])
        assert granted == ("tasks.read",)

    def test_the_web_is_a_client_not_a_system_agent(self):
        assert not platform_allows("WEB", "automation.approved.run")
        assert not platform_allows("WEB", "desktop.open")
        assert platform_allows("WEB", "app.navigate")


class TestRevocation:
    def test_a_revoked_device_disappears_from_the_active_list(self, registry):
        enrol(registry)
        registry.revoke("dev_phone")
        assert registry.list_devices() == []
        assert len(registry.list_devices(include_revoked=True)) == 1

    def test_a_revoked_device_cannot_verify_commands(self, registry):
        enrol(registry)
        assert registry.public_key_of("dev_phone") is not None
        registry.revoke("dev_phone")
        # Returning None rather than the key makes it impossible to accept a
        # signature from a device the user deliberately cut off.
        assert registry.public_key_of("dev_phone") is None

    def test_revocation_cannot_be_laundered_by_re_pairing(self, registry):
        """Acceptance TEST H, hardened: a fresh invitation is not amnesty."""
        key = a_key()
        enrol(registry, key=key)
        registry.revoke("dev_phone")
        invitation = registry.create_pairing("iPhone de Carlito")
        with pytest.raises(MeshError, match="révoqué"):
            registry.redeem_pairing(
                invitation["pairingToken"],
                device_id="dev_phone",
                public_key_b64=key,
                name="iPhone de Carlito",
                platform="IOS",
                device_type="PHONE",
            )

    def test_forgetting_a_device_allows_a_clean_re_pairing(self, registry):
        enrol(registry)
        registry.revoke("dev_phone")
        registry.forget("dev_phone")
        again = enrol(registry)
        assert again["trustLevel"] == "TRUSTED"

    def test_a_known_id_with_a_different_key_is_refused(self, registry):
        """Impostor or reinstall — either way the human decides, not the code."""
        enrol(registry)
        invitation = registry.create_pairing("iPhone de Carlito")
        with pytest.raises(MeshError, match="autre clé"):
            registry.redeem_pairing(
                invitation["pairingToken"],
                device_id="dev_phone",
                public_key_b64=a_key(),  # different key, same id
                name="iPhone de Carlito",
                platform="IOS",
                device_type="PHONE",
            )

    def test_a_revoked_device_cannot_redeclare_capabilities(self, registry):
        enrol(registry, platform="MACOS", capabilities=["tasks.read"])
        registry.revoke("dev_phone")
        with pytest.raises(MeshError, match="autorisé"):
            registry.declare_capabilities("dev_phone", ["automation.approved.run"])


class TestAucunVerbeDeFichier:
    """§5 — une capacité que rien n'exerce est une promesse en attente.

    `filesystem.workspace.read` et `.write` ont vécu dans ce vocabulaire
    depuis le jour où il a été écrit, sans que personne ne les déclare
    jamais : un Diapason DÉRIVE sa déclaration du catalogue d'outils, qui
    compte cinq verbes dont aucun ne touche un fichier ; le client Dart en
    déclare trois ; les deux appareils réellement appairés en déclarent
    quatre et trois.

    Elles étaient pires qu'inertes : `mesh/files_routes.py` est juste à côté
    et écrit vraiment des fichiers, si bien qu'un relecteur y voyait la garde
    de cette route — qui ne les a jamais consultées. Retirées le 25 août
    2026. Ce test empêche qu'un verbe de fichier revienne sans le contrôle
    qui l'exerce.
    """

    def test_le_vocabulaire_ne_promet_aucune_ecriture_de_fichier(self):
        fautifs = sorted(c for c in ALL_CAPABILITIES if c.startswith("filesystem."))
        assert not fautifs, (
            f"{fautifs} : un verbe de fichier ne se déclare qu'avec le contrôle "
            "qui l'exerce, sinon il finit par se faire promettre."
        )

    def test_aucun_plafond_n_accorde_d_ecriture_de_fichier(self):
        for plateforme, plafond in PLATFORM_CAPABILITIES.items():
            fautifs = sorted(c for c in plafond if c.startswith("filesystem."))
            assert not fautifs, f"le plafond {plateforme} accorde {fautifs}"

    def test_le_plafond_android_ne_depasse_plus_celui_d_ios(self):
        """Le seul verbe qui les distinguait était `filesystem.workspace.read`.

        S'ils divergent de nouveau, que ce soit un choix écrit — pas un
        résidu.
        """
        assert PLATFORM_CAPABILITIES["ANDROID"] == PLATFORM_CAPABILITIES["IOS"]


def _cle_de_scellement() -> str:
    """Une clé X25519 valide — trente-deux octets, pas un de plus."""
    from diapason.mesh.coffre import nouvelle_demi_cle

    return nouvelle_demi_cle().publique_b64


class TestLaCleDeScellementDunPair:
    """Étape 2 du plan du 26 août 2026.

    Cette clé CHIFFRE, quand `public_key` SIGNE. Une clé, un usage.
    """

    def test_elle_s_enregistre_et_se_relit_avec_son_instant(self, registry):
        enrol(registry)
        cle = _cle_de_scellement()
        assert registry.record_seal_key("dev_phone", cle, 1_000) is True
        assert registry.seal_key_of("dev_phone") == (cle, 1_000)

    def test_une_publication_rejouee_ne_reinstalle_pas_une_vieille_cle(self, registry):
        """Sans quoi un attaquant rejouerait une publication périmée dont il
        détient, lui, la moitié privée."""
        enrol(registry)
        recente = _cle_de_scellement()
        ancienne = _cle_de_scellement()
        assert registry.record_seal_key("dev_phone", recente, 5_000) is True

        assert registry.record_seal_key("dev_phone", ancienne, 4_000) is False
        assert registry.record_seal_key("dev_phone", ancienne, 5_000) is False, (
            "à instant égal non plus : la comparaison doit être stricte"
        )
        assert registry.seal_key_of("dev_phone") == (recente, 5_000)

    def test_une_cle_qui_n_est_pas_une_cle_est_refusee(self, registry):
        enrol(registry)
        for mauvaise in (
            "",
            "pas du base64 !",
            base64.b64encode(b"trop court").decode(),
        ):
            assert registry.record_seal_key("dev_phone", mauvaise, 1_000) is False
        assert registry.seal_key_of("dev_phone") is None

    def test_un_appareil_revoque_n_a_plus_de_cle(self, registry):
        """Le même goulot que `public_key_of` : la révocation arrête tout au
        même endroit, sinon elle n'arrête rien."""
        enrol(registry)
        registry.record_seal_key("dev_phone", _cle_de_scellement(), 1_000)
        assert registry.seal_key_of("dev_phone") is not None

        registry.revoke("dev_phone")
        assert registry.seal_key_of("dev_phone") is None
        assert (
            registry.record_seal_key("dev_phone", _cle_de_scellement(), 2_000) is False
        )

    def test_un_pair_qui_n_a_jamais_publie_n_a_pas_de_cle(self, registry):
        enrol(registry)
        assert registry.seal_key_of("dev_phone") is None

    def test_oublier_ramene_au_clair_sans_attendre(self, registry):
        enrol(registry)
        registry.record_seal_key("dev_phone", _cle_de_scellement(), 1_000)
        registry.forget_seal_key("dev_phone")
        assert registry.seal_key_of("dev_phone") is None

    def test_un_re_appairage_efface_la_cle(self, registry):
        """LE PIÈGE, trouvé par deux juges avant qu'il ne soit écrit.

        Sans cette remise à zéro, une clé morte survivrait à l'appairage qui
        devait justement tout remettre à plat : on scellerait vers une clé
        que le pair réinstallé ne possède plus, et TOUT partirait en refus
        sur un maillage qui a pourtant l'air appairé.
        """
        identite = a_key()
        enrol(registry, key=identite)
        registry.record_seal_key("dev_phone", _cle_de_scellement(), 1_000)
        assert registry.seal_key_of("dev_phone") is not None

        # Le MÊME appareil se ré-appaire, avec la même clé d'identité. C'est
        # le seul ré-appairage qui atteigne la mise à jour : présenter une
        # AUTRE clé d'identité est refusé bien avant, et c'est très bien —
        # mais cela veut dire que ce chemin-ci sert exactement au cas qui
        # nous occupe : un pair qui garde son identité et a perdu sa clé de
        # scellement (réinstallation partielle, retour en arrière).
        enrol(registry, key=identite)
        assert registry.seal_key_of("dev_phone") is None, (
            "la clé de scellement a survécu au ré-appairage"
        )


class TestUneBaseAnterieureSOuvre:
    def test_un_registre_sans_les_colonnes_migre_tout_seul(self, tmp_path):
        """Le registre de quelqu'un qui met à jour n'a pas ces colonnes."""
        import sqlite3

        chemin = tmp_path / "ancienne.db"
        conn = sqlite3.connect(chemin)
        conn.executescript(
            """
            CREATE TABLE mesh_devices (
                device_id TEXT PRIMARY KEY,
                public_key TEXT NOT NULL,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                device_type TEXT NOT NULL,
                trust_level TEXT NOT NULL,
                declared_capabilities TEXT NOT NULL DEFAULT '[]',
                app_version TEXT NOT NULL DEFAULT '',
                created_at_ms INTEGER NOT NULL,
                last_seen_at_ms INTEGER,
                revoked_at_ms INTEGER
            );
            CREATE TABLE mesh_pairings (
                token_hash TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                expires_at_ms INTEGER NOT NULL,
                redeemed_at_ms INTEGER
            );
            """
        )
        conn.commit()
        conn.close()

        ancien = DeviceRegistry(chemin)
        enrol(ancien)
        cle = _cle_de_scellement()
        assert ancien.record_seal_key("dev_phone", cle, 1_000) is True
        assert ancien.seal_key_of("dev_phone") == (cle, 1_000)

    def test_l_instant_est_un_entier_et_se_compare_comme_tel(self, registry):
        """Rangé dans une colonne TEXT — la boucle de migration n'ajoute que
        du TEXT — « 9 » serait plus grand que « 10 »."""
        enrol(registry)
        assert registry.record_seal_key("dev_phone", _cle_de_scellement(), 9) is True
        cle = _cle_de_scellement()
        assert registry.record_seal_key("dev_phone", cle, 10) is True, (
            "10 doit être vu comme postérieur à 9"
        )
        assert registry.seal_key_of("dev_phone") == (cle, 10)

    def test_rejoindre_de_nouveau_un_hote_efface_aussi_sa_cle(self, registry):
        """La SECONDE porte d'appairage — celle du côté invité.

        Deux portes mènent au même piège : `redeem_pairing` quand on accueille,
        `enrol_host` quand on est accueilli. Corriger une seule laisserait la
        clé morte survivre par l'autre chemin.
        """
        identite = a_key()
        hote = dict(
            device_id="dev_hote",
            public_key_b64=identite,
            name="Le Mac du salon",
            platform="MACOS",
        )
        registry.enrol_host(**hote)
        registry.record_seal_key("dev_hote", _cle_de_scellement(), 1_000)
        assert registry.seal_key_of("dev_hote") is not None

        registry.enrol_host(**hote)
        assert registry.seal_key_of("dev_hote") is None, (
            "la clé a survécu au ré-enrôlement de l'hôte"
        )
