"""L'enveloppe qui demande une session — plan de la phase 2, étape 2 (26/09/2026).

Chaque test nomme l'attaque qu'il refuse : le rejeu, l'audience étrangère,
l'appareil révoqué, l'expiration trop lointaine, le flottant (CLAUDE.md §4 :
Python écrit ``1e-07``, Dart ``1e-7``), et la confusion des genres — un
ORDRE de commande présenté comme une ouverture de session, et l'inverse.
"""

from __future__ import annotations

import base64
import json

import pytest

from diapason.mesh.commands import (
    CommandError,
    CommandRejected,
    NonceStore,
    build_command,
    verify_command,
)
from diapason.mesh.identity import canonical_bytes
from diapason.mesh.registry import DeviceRegistry
from diapason.mesh.sessions import (
    SESSION_REQUEST_FIELDS,
    SESSION_REQUEST_MAX_TTL_MS,
    DeviceSessions,
    build_session_request,
    verify_session_request,
)
from diapason.mesh.signed import SignedRejected, signable
from diapason.security.signing import generate_keypair, sign_b64

MAC = "dev_atelier"
OWNER = "owner_la_flotte_de_carlito"
PHONE = "dev_le_telephone"


@pytest.fixture
def monde(tmp_path):
    registry = DeviceRegistry(tmp_path / "mesh.db")
    nonces = NonceStore(tmp_path / "mesh.db")
    cles = generate_keypair()
    invitation = registry.create_pairing("Téléphone")
    registry.redeem_pairing(
        invitation["pairingToken"],
        device_id=PHONE,
        public_key_b64=base64.b64encode(cles.public_key).decode(),
        name="Téléphone",
        platform="ANDROID",
        device_type="PHONE",
        declared_capabilities=["app.navigate"],
    )
    return registry, nonces, cles.private_key


def _signer(charge: dict, cle_privee: bytes) -> dict:
    """Signer exactement comme le téléphone : la liste de champs, pas le tout."""
    signature = sign_b64(
        canonical_bytes(signable(charge, SESSION_REQUEST_FIELDS)), cle_privee
    )
    return {**charge, "signature": signature}


def _demande(monde, **remplacements) -> dict:
    _, _, cle = monde
    charge = build_session_request(owner_id=OWNER, device_id=PHONE, audience=MAC)
    charge.update(remplacements)
    return _signer(charge, cle)


def _verifier(brut, monde, **kwargs) -> str:
    registry, nonces, _ = monde
    return verify_session_request(
        brut,
        registry=registry,
        local_device_id=MAC,
        local_owner_id=OWNER,
        nonces=nonces,
        **kwargs,
    )


def _refus(brut, monde, **kwargs) -> SignedRejected:
    with pytest.raises(SignedRejected) as exc:
        _verifier(brut, monde, **kwargs)
    return exc.value


class TestLeCheminNominal:
    def test_une_demande_signee_rend_l_appareil_puis_un_ticket(self, monde):
        registry, _, _ = monde
        assert _verifier(_demande(monde), monde) == PHONE

        sessions = DeviceSessions(registry)
        ticket = sessions.issue_ticket(PHONE)["ticket"]
        ouverte = sessions.redeem_ticket(ticket)
        assert sessions.verify_session(ouverte["sessionToken"])["deviceId"] == PHONE

    def test_l_enveloppe_ne_porte_que_des_entiers_et_des_chaines(self):
        """§4 de CLAUDE.md : aucun flottant dans une enveloppe signée."""
        charge = build_session_request(owner_id=OWNER, device_id=PHONE, audience=MAC)
        relu = json.loads(canonical_bytes(charge))
        assert set(relu) == set(SESSION_REQUEST_FIELDS)
        for champ, valeur in relu.items():
            assert type(valeur) in (int, str), f"{champ} n'est ni entier ni chaîne"
        assert relu["purpose"] == "webview-session"
        assert relu["expiresAtMs"] - relu["issuedAtMs"] == 60_000

    def test_une_validite_de_soixante_secondes_pile_passe(self, monde):
        _, _, cle = monde
        charge = build_session_request(
            owner_id=OWNER,
            device_id=PHONE,
            audience=MAC,
            ttl_ms=SESSION_REQUEST_MAX_TTL_MS,
        )
        assert _verifier(_signer(charge, cle), monde) == PHONE


class TestLeRejeu:
    def test_une_demande_rejouee_est_refusee(self, monde):
        brut = _demande(monde)
        assert _verifier(brut, monde) == PHONE
        refus = _refus(brut, monde)
        assert refus.code == "DENIED"
        assert "déjà été reçue" in refus.message

    def test_un_refus_pour_une_autre_raison_ne_brule_pas_le_nonce(self, monde):
        """Sinon l'émetteur légitime qui réessaie serait pris pour un rejeu."""
        brut = _demande(monde)
        trop_tard = brut["expiresAtMs"] + 10 * 60_000
        assert _refus(brut, monde, now=trop_tard).code == "EXPIRED"
        assert _verifier(brut, monde) == PHONE


class TestLAdresse:
    def test_une_audience_etrangere_est_refusee(self, monde):
        """Une demande signée pour un autre Mac ne s'échange pas ici."""
        refus = _refus(_demande(monde, audience="dev_un_autre_mac"), monde)
        assert refus.code == "DENIED"
        assert "autre appareil" in refus.message

    def test_une_autre_flotte_est_refusee(self, monde):
        refus = _refus(_demande(monde, ownerId="owner_quelqu_un_d_autre"), monde)
        assert "autre ensemble" in refus.message

    def test_un_appareil_revoque_est_refuse(self, monde):
        registry, _, _ = monde
        brut = _demande(monde)
        registry.revoke(PHONE)
        refus = _refus(brut, monde)
        assert refus.code == "DENIED"
        assert "pas autorisé" in refus.message

    def test_un_appareil_inconnu_est_refuse(self, monde):
        refus = _refus(_demande(monde, deviceId="dev_inconnu"), monde)
        assert "pas autorisé" in refus.message

    def test_le_mac_ne_s_ouvre_pas_de_session_a_lui_meme(self, monde):
        refus = _refus(_demande(monde, deviceId=MAC), monde)
        assert "lui-même" in refus.message


class TestLaDuree:
    def test_une_expiration_trop_lointaine_est_refusee(self, monde):
        brut = _demande(monde)
        _, _, cle = monde
        charge = {k: v for k, v in brut.items() if k != "signature"}
        charge["expiresAtMs"] = charge["issuedAtMs"] + SESSION_REQUEST_MAX_TTL_MS + 1
        refus = _refus(_signer(charge, cle), monde)
        assert refus.code == "DENIED"
        assert "trop longtemps" in refus.message

    def test_une_demande_expiree_est_refusee(self, monde):
        brut = _demande(monde)
        refus = _refus(brut, monde, now=brut["expiresAtMs"] + 31_000)
        assert refus.code == "EXPIRED"

    def test_une_demande_datee_du_futur_est_refusee(self, monde):
        brut = _demande(monde)
        refus = _refus(brut, monde, now=brut["issuedAtMs"] - 31_000)
        assert "futur" in refus.message

    def test_une_validite_inversee_est_refusee(self, monde):
        brut = _demande(monde)
        _, _, cle = monde
        charge = {k: v for k, v in brut.items() if k != "signature"}
        charge["expiresAtMs"] = charge["issuedAtMs"]
        assert _refus(_signer(charge, cle), monde).code == "EXPIRED"


class TestLesTypes:
    def test_un_flottant_signe_est_refuse(self, monde):
        """Même bien signé en Python : le Dart ne l'aurait jamais reproduit."""
        brut = _demande(monde)
        _, _, cle = monde
        charge = {k: v for k, v in brut.items() if k != "signature"}
        charge["issuedAtMs"] = float(charge["issuedAtMs"])
        refus = _refus(_signer(charge, cle), monde)
        assert refus.code == "DENIED"
        assert "nombre à virgule" in refus.message

    def test_un_flottant_hors_des_champs_signes_est_refuse(self, monde):
        brut = {**_demande(monde), "ecart": 1e-07}
        assert "nombre à virgule" in _refus(brut, monde).message

    def test_un_booleen_n_est_pas_une_version(self, monde):
        """True vaut 1 en Python, mais se canonise en `true`."""
        brut = _demande(monde)
        _, _, cle = monde
        charge = {k: v for k, v in brut.items() if k != "signature"}
        charge["version"] = True
        assert "mal formée" in _refus(_signer(charge, cle), monde).message

    def test_une_version_inconnue_est_refusee(self, monde):
        assert _refus(_demande(monde, version=2), monde).code == "UNSUPPORTED"

    def test_un_autre_but_est_refuse(self, monde):
        refus = _refus(_demande(monde, purpose="command"), monde)
        assert "ne demande pas une session" in refus.message

    def test_un_nonce_trop_court_est_refuse(self, monde):
        assert "mal formée" in _refus(_demande(monde, nonce="abc"), monde).message

    def test_une_signature_alteree_est_refusee(self, monde):
        brut = _demande(monde)
        brut["nonce"] = brut["nonce"][::-1]
        assert "signature" in _refus(brut, monde).message

    @pytest.mark.parametrize("brut", [None, [], "demande", 42, {}])
    def test_une_charge_illisible_est_un_refus_pas_une_exception(self, monde, brut):
        assert _refus(brut, monde).code == "DENIED"


def _commande_signee(cle: bytes) -> dict:
    commande = build_command(
        owner_id=OWNER,
        origin_device_id=PHONE,
        target_device_id=MAC,
        tool="app.navigate",
        arguments={"route": "success://tasks"},
    )
    charge = commande.to_dict(with_signature=False)
    return {**charge, "signature": sign_b64(canonical_bytes(charge), cle)}


class TestUnOrdreNEstPasUneOuverture:
    def test_une_commande_signee_n_ouvre_pas_de_session(self, monde):
        """Réutiliser l'enveloppe des commandes aurait fait accepter un ordre
        comme une ouverture de session (étape 2 du plan)."""
        _, nonces, cle = monde
        commande = _commande_signee(cle)
        refus = _refus(commande, monde)
        assert refus.code == "DENIED"
        assert "forme attendue" in refus.message

        # Et le refus n'a rien consommé : la même commande reste recevable
        # par son vrai destinataire, preuve qu'aucun nonce n'a brûlé.
        registry, _, _ = monde
        recue = verify_command(
            commande,
            registry=registry,
            local_device_id=MAC,
            local_owner_id=OWNER,
            nonces=nonces,
        )
        assert recue.tool == "app.navigate"

    def test_une_cle_en_trop_est_refusee_meme_signee(self, monde):
        """La forme est EXACTE, pas un minimum : une demande valide à laquelle
        on ajoute un champ de commande est refusée avant toute signature."""
        brut = {**_demande(monde), "commandId": "cmd_x"}
        refus = _refus(brut, monde)
        assert refus.code == "DENIED"
        assert "forme attendue" in refus.message

    def test_une_ouverture_de_session_n_est_pas_un_ordre(self, monde):
        """L'inverse : présentée au bus des commandes, elle n'y entre pas."""
        registry, nonces, _ = monde
        with pytest.raises((CommandError, CommandRejected)):
            verify_command(
                _demande(monde),
                registry=registry,
                local_device_id=MAC,
                local_owner_id=OWNER,
                nonces=nonces,
            )

    def test_sa_signature_ne_vaut_pas_pour_un_ordre_habille_autour(self, monde):
        """Un attaquant complète la demande des champs d'une commande pour
        passer la forme : la signature, calculée sur ``purpose`` et
        ``audience``, ne couvre pas les octets d'une commande."""
        registry, nonces, _ = monde
        demande = _demande(monde)
        habillee = {
            **demande,
            "commandId": "cmd_forgee",
            "originDeviceId": PHONE,
            "targetDeviceId": MAC,
            "tool": "app.navigate",
            "arguments": {"route": "success://tasks"},
            "createdAtMs": demande["issuedAtMs"],
            "idempotencyKey": "idem_forgee",
            "requiresConfirmation": False,
        }
        with pytest.raises(CommandRejected) as exc:
            verify_command(
                habillee,
                registry=registry,
                local_device_id=MAC,
                local_owner_id=OWNER,
                nonces=nonces,
            )
        assert "signature" in exc.value.message
