"""The signed command envelope and the eleven checks of spec §9.

Each test names the attack it refuses. A command bus that passes only the
happy path is not a bus, it is a demo.
"""

from __future__ import annotations

import base64

import pytest

from diapason.mesh.commands import (
    MAX_CLOCK_SKEW_MS,
    CommandRejected,
    NonceStore,
    RemoteCommand,
    build_command,
    now_ms,
    verify_command,
)
from diapason.mesh.registry import DeviceRegistry
from diapason.mesh.tools import (
    FORBIDDEN_PARAMETER_NAMES,
    REMOTE_TOOLS,
    list_remote_tools,
)
from diapason.security.signing import generate_keypair, sign_b64

LOCAL_DEVICE = "dev_this_mac"
LOCAL_OWNER = "owner_shared_fleet_identity"
REMOTE_DEVICE = "dev_the_phone"


@pytest.fixture
def world(tmp_path):
    """A registry holding one trusted peer, plus that peer's private key."""
    registry = DeviceRegistry(tmp_path / "mesh.db")
    nonces = NonceStore(tmp_path / "mesh.db")

    peer_keys = generate_keypair()
    invitation = registry.create_pairing("Téléphone")
    registry.redeem_pairing(
        invitation["pairingToken"],
        device_id=REMOTE_DEVICE,
        public_key_b64=base64.b64encode(peer_keys.public_key).decode(),
        name="Téléphone",
        platform="IOS",
        device_type="PHONE",
        declared_capabilities=["app.navigate", "app.show_resource"],
    )
    # This device too, so capability checks have something to read.
    invitation2 = registry.create_pairing("Ce Mac")
    registry.redeem_pairing(
        invitation2["pairingToken"],
        device_id=LOCAL_DEVICE,
        public_key_b64=base64.b64encode(generate_keypair().public_key).decode(),
        name="Ce Mac",
        platform="MACOS",
        device_type="LAPTOP",
        declared_capabilities=["app.navigate", "app.show_resource", "app.open"],
    )
    return registry, nonces, peer_keys


def sign_as_peer(command: RemoteCommand, private_key: bytes) -> dict:
    """Sign exactly as the sending device would."""
    from diapason.mesh.identity import canonical_bytes

    payload = command.to_dict(with_signature=False)
    signature = sign_b64(canonical_bytes(payload), private_key)
    return {**payload, "signature": signature}


def a_command(**overrides) -> RemoteCommand:
    base = dict(
        owner_id=LOCAL_OWNER,
        origin_device_id=REMOTE_DEVICE,
        target_device_id=LOCAL_DEVICE,
        tool="app.navigate",
        arguments={"route": "success://projects/flashprime"},
    )
    base.update(overrides)
    return build_command(**base)


def check(raw, world, **kwargs):
    registry, nonces, _ = world
    return verify_command(
        raw,
        registry=registry,
        local_device_id=LOCAL_DEVICE,
        local_owner_id=LOCAL_OWNER,
        nonces=nonces,
        **kwargs,
    )


class TestHappyPath:
    def test_a_properly_signed_command_is_accepted(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(), keys.private_key)
        verified = check(raw, world)
        assert verified.tool == "app.navigate"
        assert verified.arguments["route"] == "success://projects/flashprime"


class TestSignature:
    def test_an_unsigned_command_is_refused(self, world):
        raw = a_command().to_dict(with_signature=False)
        with pytest.raises(CommandRejected, match="pas signée") as exc:
            check(raw, world)
        assert exc.value.code == "DENIED"

    def test_a_tampered_argument_breaks_the_signature(self, world):
        """The whole point: sign the envelope, not a summary of it."""
        _, _, keys = world
        raw = sign_as_peer(a_command(), keys.private_key)
        raw["arguments"] = {"route": "success://projects/QUELQUE_CHOSE_DAUTRE"}
        with pytest.raises(CommandRejected, match="signature"):
            check(raw, world)

    def test_a_command_signed_by_a_stranger_is_refused(self, world):
        stranger = generate_keypair()
        raw = sign_as_peer(a_command(), stranger.private_key)
        with pytest.raises(CommandRejected, match="signature"):
            check(raw, world)

    def test_a_revoked_device_can_no_longer_command(self, world):
        """Acceptance TEST H at the bus level."""
        registry, _, keys = world
        registry.revoke(REMOTE_DEVICE)
        raw = sign_as_peer(a_command(), keys.private_key)
        with pytest.raises(CommandRejected, match="pas autorisé"):
            check(raw, world)


class TestReplay:
    def test_a_nonce_may_be_spent_only_once(self, world):
        """Replaying a captured command is how 'open this' becomes 'open this
        forty times'. The signature stays perfect; the nonce does not."""
        _, _, keys = world
        raw = sign_as_peer(a_command(), keys.private_key)
        check(raw, world)
        with pytest.raises(CommandRejected, match="déjà été reçue"):
            check(raw, world)

    def test_a_rejected_command_does_not_burn_its_nonce(self, world):
        """The nonce is spent LAST, so a command refused for another reason
        leaves the legitimate sender able to retry."""
        _, _, keys = world
        command = a_command(tool="app.open")  # phone lacks app.open capability
        raw = sign_as_peer(command, keys.private_key)
        with pytest.raises(CommandRejected):
            check(raw, world)
        # Same nonce, now on a tool the device does have: still accepted.
        second = RemoteCommand(**{**a_command().__dict__, "nonce": command.nonce})
        raw2 = sign_as_peer(second, keys.private_key)
        assert check(raw2, world).nonce == command.nonce


class TestAddressing:
    def test_a_command_for_another_device_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(
            a_command(target_device_id="dev_someone_else"), keys.private_key
        )
        with pytest.raises(CommandRejected, match="ne s'adresse pas"):
            check(raw, world)

    def test_a_command_from_another_fleet_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(owner_id="owner_someone_else"), keys.private_key)
        with pytest.raises(CommandRejected, match="autre ensemble"):
            check(raw, world)

    def test_an_unknown_origin_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(origin_device_id="dev_ghost"), keys.private_key)
        with pytest.raises(CommandRejected, match="pas autorisé"):
            check(raw, world)


class TestExpiry:
    def test_an_expired_command_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(ttl_ms=1_000), keys.private_key)
        future = now_ms() + 1_000 + MAX_CLOCK_SKEW_MS + 1_000
        with pytest.raises(CommandRejected, match="expiré") as exc:
            check(raw, world, now=future)
        assert exc.value.code == "EXPIRED"

    def test_clock_skew_is_tolerated_within_bounds(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(ttl_ms=1_000), keys.private_key)
        # Slightly past expiry but inside the skew window: still honoured.
        assert check(raw, world, now=now_ms() + 1_000 + MAX_CLOCK_SKEW_MS - 500)

    def test_a_command_from_the_future_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(), keys.private_key)
        raw["createdAtMs"] = now_ms() + MAX_CLOCK_SKEW_MS + 60_000
        raw["expiresAtMs"] = raw["createdAtMs"] + 60_000
        # Re-sign so it fails on the date, not the signature.
        raw = sign_as_peer(RemoteCommand.from_dict(raw), keys.private_key)
        with pytest.raises(CommandRejected, match="futur"):
            check(raw, world)


class TestToolDiscipline:
    def test_an_unknown_tool_is_unsupported(self, world):
        """Acceptance TEST J: the assistant asking for a shell finds nothing."""
        _, _, keys = world
        raw = sign_as_peer(
            a_command(tool="system.execute_shell", arguments={}), keys.private_key
        )
        with pytest.raises(CommandRejected, match="n'existe pas") as exc:
            check(raw, world)
        assert exc.value.code == "UNSUPPORTED"

    def test_an_unknown_parameter_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(
            a_command(
                arguments={"route": "success://today", "extra": "rm -rf /"},
            ),
            keys.private_key,
        )
        with pytest.raises(CommandRejected, match="non reconnu"):
            check(raw, world)

    def test_a_missing_required_parameter_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(arguments={}), keys.private_key)
        with pytest.raises(CommandRejected, match="obligatoire"):
            check(raw, world)

    def test_an_enum_is_enforced(self, world):
        _, _, keys = world
        raw = sign_as_peer(
            a_command(
                tool="app.show_resource",
                arguments={"resourceType": "database", "resourceId": "x"},
            ),
            keys.private_key,
        )
        with pytest.raises(CommandRejected, match="non autorisée"):
            check(raw, world)

    def test_a_capability_this_platform_forbids_is_unsupported(
        self, world, monkeypatch
    ):
        """The receiver's ceiling comes from its PLATFORM, not from a
        registry row.

        The earlier version of this test read the ceiling from a registry
        entry for the local device — which the fixture helpfully created and
        the real world never does. A device is not listed in its own
        registry, so the lookup returned None and the check silently allowed
        everything. The test was constructing the only world in which the
        code worked.
        """
        _, _, keys = world
        import diapason.mesh.capabilities as caps

        monkeypatch.setattr(
            caps, "local_capabilities", lambda: frozenset({"app.navigate"})
        )
        raw = sign_as_peer(
            a_command(tool="notifications.show", arguments={"title": "Bonjour"}),
            keys.private_key,
        )
        with pytest.raises(CommandRejected, match="ne peut pas exécuter"):
            check(raw, world)

    def test_the_receiver_does_not_take_the_sender_s_word_for_its_own_limits(
        self, world
    ):
        """What the sender recorded about us is exactly what an attacker
        would have tampered with, so it cannot be what authorises us."""
        registry, _, keys = world
        # Wipe every capability the registry believes this Mac has.
        registry.declare_capabilities(LOCAL_DEVICE, [])
        raw = sign_as_peer(
            a_command(tool="app.navigate", arguments={"route": "success://today"}),
            keys.private_key,
        )
        # Still accepted: macOS genuinely allows it, and that is our call.
        assert check(raw, world).tool == "app.navigate"


class TestNoUniversalTool:
    """Spec §21, enforced on the whole registry rather than per review."""

    def test_no_tool_accepts_a_passthrough_parameter(self):
        for name, spec in REMOTE_TOOLS.items():
            offending = set(spec.parameters) & FORBIDDEN_PARAMETER_NAMES
            assert not offending, (
                f"L'outil « {name} » expose un paramètre fourre-tout : {offending}. "
                "Un outil distant doit nommer explicitement ce qu'il accepte."
            )

    def test_every_parameter_declares_a_concrete_type(self):
        for name, spec in REMOTE_TOOLS.items():
            for key, rule in spec.parameters.items():
                assert rule.get("type") in {"string", "integer", "boolean"}, (
                    f"« {name}.{key} » n'a pas de type borné."
                )

    def test_every_tool_maps_to_a_known_capability(self):
        from diapason.mesh.capabilities import ALL_CAPABILITIES

        for name, spec in REMOTE_TOOLS.items():
            assert spec.capability in ALL_CAPABILITIES, (
                f"« {name} » réclame une capacité inconnue : {spec.capability}."
            )

    def test_every_tool_declares_an_offline_policy(self):
        allowed = {"DROP_IF_OFFLINE", "QUEUE_UNTIL_EXPIRATION", "REQUIRE_ONLINE"}
        for name, spec in REMOTE_TOOLS.items():
            assert spec.offline_policy in allowed, f"« {name} » : politique inconnue."

    def test_the_catalogue_is_advertisable(self):
        catalogue = list_remote_tools()
        assert catalogue
        assert all("name" in entry and "parameters" in entry for entry in catalogue)


class TestLaFormeSurLeFilNeBougePas:
    """Étape 3 du plan du 26 août 2026 — le test qui garde tout le contrat.

    Un client Flutter figé est déjà déployé. Le scellement ne vaut que s'il
    est INVISIBLE pour lui : une commande claire doit produire exactement les
    mêmes octets qu'avant. Comparé ici à un vecteur écrit à la main depuis la
    spécification, et non régénéré depuis le code — sans quoi le test
    entérinerait n'importe quelle dérive au lieu de la refuser.
    """

    def _commande(self) -> RemoteCommand:
        return RemoteCommand(
            command_id="cmd-fige",
            owner_id="owner-fige",
            origin_device_id="dev_origine",
            target_device_id="dev_cible",
            tool="app.navigate",
            arguments={"route": "success://projects/x"},
            created_at_ms=1_700_000_000_000,
            expires_at_ms=1_700_000_060_000,
            nonce="nonce-fige",
            idempotency_key="idem-fige",
        )

    def test_une_commande_claire_produit_le_vecteur_attendu(self):
        assert self._commande().to_dict(with_signature=False) == {
            "version": 1,
            "commandId": "cmd-fige",
            "ownerId": "owner-fige",
            "originDeviceId": "dev_origine",
            "targetDeviceId": "dev_cible",
            "tool": "app.navigate",
            "arguments": {"route": "success://projects/x"},
            "createdAtMs": 1_700_000_000_000,
            "expiresAtMs": 1_700_000_060_000,
            "nonce": "nonce-fige",
            "idempotencyKey": "idem-fige",
            "requiresConfirmation": False,
        }

    def test_les_octets_canoniques_aussi(self):
        """C'est sur eux que porte la signature : un octet de plus et toutes
        les enveloppes déjà en vol deviennent invérifiables."""
        from diapason.mesh.identity import canonical_bytes

        octets = canonical_bytes(self._commande().to_dict(with_signature=False))
        assert octets == (
            b'{"arguments":{"route":"success://projects/x"},'
            b'"commandId":"cmd-fige","createdAtMs":1700000000000,'
            b'"expiresAtMs":1700000060000,"idempotencyKey":"idem-fige",'
            b'"nonce":"nonce-fige","originDeviceId":"dev_origine",'
            b'"ownerId":"owner-fige","requiresConfirmation":false,'
            b'"targetDeviceId":"dev_cible","tool":"app.navigate","version":1}'
        )

    def test_une_enveloppe_venue_du_telephone_traverse_l_aller_retour(self, world):
        """`from_dict` → `to_dict` → vérification, sur les douze clés que le
        client Dart écrit. C'est le chemin exact d'une commande reçue."""
        _registry, _nonces, peer_keys = world
        envoyee = sign_as_peer(a_command(), peer_keys.private_key)
        assert len(envoyee) == 13, "douze champs plus la signature"

        relue = RemoteCommand.from_dict(envoyee)
        assert relue.to_dict() == envoyee, (
            "l'aller-retour a changé l'enveloppe : la signature ne vaut plus"
        )

    def test_une_commande_claire_n_est_pas_scellee(self):
        assert self._commande().est_scelle is False


class TestUneCommandeScelleeReemetSonSceau:
    """L'invariant qui fait tenir tout le reste : les champs de l'objet
    portent le CLAIR des deux côtés, et ``_extra["scelle"]`` porte ce qui a
    été signé. ``to_dict`` réémet le scellé.

    Sans cela, le récepteur rangerait dans sa file une enveloppe portant le
    clair sous une signature calculée sur le chiffré — donc une enveloppe qui
    ne vérifierait plus sa propre signature.
    """

    def _scellee(self) -> RemoteCommand:
        from diapason.mesh.scellement import SENTINELLE

        return RemoteCommand(
            command_id="cmd-s",
            owner_id="owner",
            origin_device_id="dev_a",
            target_device_id="dev_b",
            tool="notifications.show",
            arguments={"title": "Rendez-vous chez le notaire"},
            created_at_ms=1,
            expires_at_ms=2,
            nonce="n",
            idempotency_key="i",
            _extra={
                "scelle": {
                    "tool": SENTINELLE,
                    "arguments": {"s": "AAAA", "e": "BBBB", "k": "cafe1234"},
                    "requiresConfirmation": True,
                }
            },
        )

    def test_les_champs_de_l_objet_portent_le_clair(self):
        commande = self._scellee()
        assert commande.tool == "notifications.show"
        assert commande.arguments == {"title": "Rendez-vous chez le notaire"}
        assert commande.est_scelle is True

    def test_le_fil_ne_porte_que_le_scelle(self):
        sur_le_fil = self._scellee().to_dict(with_signature=False)
        assert sur_le_fil["tool"] == "mesh.sealed"
        assert sur_le_fil["arguments"] == {"s": "AAAA", "e": "BBBB", "k": "cafe1234"}
        assert sur_le_fil["requiresConfirmation"] is True
        entier = str(sur_le_fil)
        assert "notifications.show" not in entier
        assert "notaire" not in entier

    def test_le_jeu_de_cles_est_le_meme_que_pour_une_commande_claire(self):
        """Aucun champ nouveau : c'est tout le mécanisme. Un champ ajouté au
        niveau supérieur ne serait pas reproduit par `from_dict`, donc le
        récepteur réémettrait une enveloppe amputée et la signature
        tomberait."""
        claire = RemoteCommand(
            command_id="c",
            owner_id="o",
            origin_device_id="a",
            target_device_id="b",
            tool="app.open",
            arguments={},
            created_at_ms=1,
            expires_at_ms=2,
            nonce="n",
            idempotency_key="i",
        )
        assert set(self._scellee().to_dict(with_signature=False)) == set(
            claire.to_dict(with_signature=False)
        )

    def test_la_sentinelle_n_est_pas_un_outil_du_catalogue(self):
        """C'est une marque de transport. Si elle entrait dans le catalogue,
        un appareil pourrait se la voir demander comme un verbe."""
        from diapason.mesh.scellement import SENTINELLE
        from diapason.mesh.tools import REMOTE_TOOLS

        assert SENTINELLE not in REMOTE_TOOLS
        assert SENTINELLE not in {t["name"] for t in list_remote_tools()}

    def test_signer_ne_perd_pas_le_sceau(self, tmp_path, monkeypatch):
        """`sign_command` reconstruit l'objet depuis son `__dict__` : le
        souligné de `_extra` y survit parce que les dataclasses le gardent
        dans `__init__`. Toute l'étape suivante en dépend — si cela cessait
        d'être vrai, on signerait le chiffré et on émettrait le clair.
        """
        from diapason.mesh.commands import sign_command

        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "maison"))
        signee = sign_command(self._scellee())
        assert signee.est_scelle is True
        assert signee.to_dict()["tool"] == "mesh.sealed"
        assert signee.tool == "notifications.show", "l'objet doit garder le clair"
        assert signee.signature, "la signature manque"


class TestOuvrirUnSceauALaReception:
    """Étape 6 : le contrôle « 6 bis », et sa place dans l'ordre.

    APRÈS la signature — un inconnu du réseau ne doit pas pouvoir nous faire
    calculer un X25519 par paquet. AVANT le contrôle de l'outil — la
    sentinelle n'existe pas dans le catalogue. Et AVANT le nonce, dépensé en
    dernier : un descellement raté ne doit pas le brûler.
    """

    @pytest.fixture(autouse=True)
    def _chez_soi(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "maison"))
        yield

    def _scellee_vers_moi(self, **surcharges):
        """Une commande que le pair scelle vers NOTRE clé locale."""
        from diapason.mesh.scellement import paire_locale, sceller_commande

        commande = a_command(**surcharges)
        return sceller_commande(commande, paire_locale().publique_b64)

    def test_une_commande_scellee_s_ouvre_et_s_execute(self, world):
        _registry, _nonces, peer_keys = world
        brute = sign_as_peer(self._scellee_vers_moi(), peer_keys.private_key)
        assert brute["tool"] == "mesh.sealed", "le fil doit porter la sentinelle"

        ouverte = check(brute, world)
        assert ouverte.tool == "app.navigate"
        assert ouverte.arguments == {"route": "success://projects/flashprime"}

    def test_l_enveloppe_ouverte_verifie_encore_sa_signature(self, world):
        """Le récepteur range cette enveloppe dans sa file. Si `to_dict` ne
        réémettait pas le scellé, elle porterait le clair sous une signature
        calculée sur le chiffré — et ne se vérifierait plus elle-même."""
        from diapason.mesh.identity import verify_envelope

        _registry, _nonces, peer_keys = world
        brute = sign_as_peer(self._scellee_vers_moi(), peer_keys.private_key)
        ouverte = check(brute, world)

        assert verify_envelope(
            ouverte.to_dict(with_signature=False),
            ouverte.signature,
            peer_keys.public_key,
        ), "l'enveloppe rangée ne vérifie plus sa propre signature"
        assert ouverte.to_dict() == brute

    def test_un_sceau_altere_est_refuse_sans_bruler_le_nonce(self, world):
        """LE point délicat : le nonce est dépensé en dernier. Un
        descellement raté ne doit pas le consommer, sinon l'émetteur
        légitime qui réessaie se ferait refuser pour rejeu — une panne dont
        la cause serait introuvable."""
        import base64

        _registry, _nonces, peer_keys = world
        bonne = self._scellee_vers_moi()

        # L'attaquant change un octet du chiffré, puis resigne (il ne peut
        # pas, mais supposons le pire : c'est le pair lui-même qui déraille).
        abimee = dict(bonne._extra["scelle"])
        brut = bytearray(base64.b64decode(abimee["arguments"]["s"]))
        brut[0] ^= 0xFF
        abimee["arguments"] = {
            **abimee["arguments"],
            "s": base64.b64encode(bytes(brut)).decode(),
        }
        from dataclasses import replace

        cassee = replace(bonne, _extra={"scelle": abimee})
        brute_cassee = sign_as_peer(cassee, peer_keys.private_key)

        with pytest.raises(CommandRejected) as refus:
            check(brute_cassee, world)
        assert "scellée n'a pas pu être ouverte" in refus.value.message

        # Le MÊME nonce doit encore passer : rien n'a été dépensé.
        bonne_brute = sign_as_peer(bonne, peer_keys.private_key)
        assert bonne_brute["nonce"] == brute_cassee["nonce"], "test mal construit"
        ouverte = check(bonne_brute, world)
        assert ouverte.tool == "app.navigate"

    def test_un_sceau_deplace_vers_une_autre_enveloppe_est_refuse(self, world):
        """Le blob est collé à SON en-tête de routage : le recoller ailleurs
        casse le tag avant que la signature ait son mot à dire."""
        from dataclasses import replace

        _registry, _nonces, peer_keys = world
        premiere = self._scellee_vers_moi()
        seconde = a_command()

        # On recolle le sceau de la première sur l'en-tête de la seconde.
        greffee = replace(seconde, _extra={"scelle": premiere._extra["scelle"]})
        with pytest.raises(CommandRejected, match="n'a pas pu être ouverte"):
            check(sign_as_peer(greffee, peer_keys.private_key), world)
