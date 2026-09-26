"""Les sessions d'un appareil, vues et fermées depuis le Mac — phase 2, étape 9.

26/09/2026. Sans ces routes, le Mac ne voyait rien des sessions ouvertes
par le téléphone à travers la passerelle du tailnet, et ne pouvait y
mettre fin qu'en révoquant l'appareil — ce qui jette aussi sa clé et oblige
à le réappairer. Le plan : « Fermer les sessions depuis le Mac fait répondre
401 à la requête suivante. »
"""

from __future__ import annotations

import base64

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from diapason.mesh.commands import NonceStore  # noqa: E402
from diapason.mesh.identity import canonical_bytes  # noqa: E402
from diapason.mesh.registry import DeviceRegistry  # noqa: E402
from diapason.mesh.routes import router, set_registry_for_tests  # noqa: E402
from diapason.mesh.sessions import (  # noqa: E402
    SESSION_REQUEST_FIELDS,
    DeviceSessions,
    build_session_request,
)
from diapason.mesh.signed import signable  # noqa: E402
from diapason.security.signing import generate_keypair, sign_b64  # noqa: E402
from diapason.server.auth_middleware import AuthMiddleware  # noqa: E402
from diapason.server.passerelle_tailnet import (  # noqa: E402
    COOKIE_APPAREIL,
    PasserelleTailnet,
)

# Une fausse clé locale ; gitleaks voit une chaîne longue affectée à KEY.
KEY = "diapason_sk_test_key_for_the_session_routes_0000"  # gitleaks:allow
MAC = "dev_atelier"
OWNER = "owner_la_flotte_de_carlito"
PHONE = "dev_le_telephone"
ICI = "https://testserver"
CLE = {"Authorization": f"Bearer {KEY}"}


@pytest.fixture
def banc(tmp_path):
    registry = DeviceRegistry(tmp_path / "mesh.db")
    set_registry_for_tests(registry)
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

    app = FastAPI()
    app.add_middleware(AuthMiddleware, api_key=KEY)
    app.include_router(router)

    @app.get("/v1/models")
    def _modeles():
        return {"data": []}

    passerelle = PasserelleTailnet(
        app,
        sessions=DeviceSessions(registry),
        registre=registry,
        nonces=NonceStore(tmp_path / "mesh.db"),
        identite=lambda: (MAC, OWNER),
        adresse="",
    )
    mac = TestClient(app)
    telephone = TestClient(passerelle, base_url=ICI)

    charge = build_session_request(owner_id=OWNER, device_id=PHONE, audience=MAC)
    signee = {
        **charge,
        "signature": sign_b64(
            canonical_bytes(signable(charge, SESSION_REQUEST_FIELDS)), cles.private_key
        ),
    }
    ticket = telephone.post("/v1/appareil/session", json=signee).json()["ticket"]
    ouverture = telephone.post(
        "/v1/appareil/ouvrir", data={"ticket": ticket}, follow_redirects=False
    )
    jeton = ouverture.cookies[COOKIE_APPAREIL]
    yield mac, telephone, jeton
    set_registry_for_tests(None)


class TestLeMacVoitLesSessions:
    def test_la_liste_dit_la_session_et_jamais_le_jeton(self, banc):
        mac, _telephone, jeton = banc
        reponse = mac.get(f"/v1/mesh/devices/{PHONE}/sessions", headers=CLE)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["count"] == 1
        assert corps["lastUsedAtMs"] == corps["sessions"][0]["lastUsedAtMs"]
        assert jeton not in reponse.text, "le jeton de session a fuité vers la page"
        assert type(corps["lastUsedAtMs"]) is int, "aucun flottant sur le fil"

    def test_un_appareil_inconnu_rend_404(self, banc):
        mac, _, _ = banc
        reponse = mac.get("/v1/mesh/devices/dev_inconnu/sessions", headers=CLE)
        assert reponse.status_code == 404

    def test_sans_la_cle_locale_rien(self, banc):
        mac, _, _ = banc
        assert mac.get(f"/v1/mesh/devices/{PHONE}/sessions").status_code == 401
        assert mac.post(f"/v1/mesh/devices/{PHONE}/sessions/close").status_code == 401


class TestFermerSansRevoquer:
    def test_fermer_depuis_le_mac_rend_401_a_la_requete_suivante(self, banc):
        """La preuve du plan, étape 9."""
        mac, telephone, jeton = banc
        entete = {"Cookie": f"{COOKIE_APPAREIL}={jeton}"}
        assert telephone.get("/v1/models", headers=entete).status_code == 200
        fermeture = mac.post(f"/v1/mesh/devices/{PHONE}/sessions/close", headers=CLE)
        assert fermeture.json() == {"ok": True, "deviceId": PHONE, "closed": 1}
        assert telephone.get("/v1/models", headers=entete).status_code == 401

    def test_l_appareil_reste_appaire(self, banc):
        """Distinct de la révocation : la clé du téléphone vaut toujours."""
        mac, _, _ = banc
        mac.post(f"/v1/mesh/devices/{PHONE}/sessions/close", headers=CLE)
        appareil = mac.get(f"/v1/mesh/devices/{PHONE}", headers=CLE).json()
        assert appareil["trustLevel"] == "TRUSTED"
        liste = mac.get(f"/v1/mesh/devices/{PHONE}/sessions", headers=CLE).json()
        assert liste == {
            "deviceId": PHONE,
            "sessions": [],
            "count": 0,
            "lastUsedAtMs": None,
        }

    def test_le_telephone_ne_peut_ni_lister_ni_fermer(self, banc):
        """La famille /v1/mesh/ est refusée par la passerelle : un
        téléphone ne voit pas les sessions d'un autre, ni les siennes."""
        _, telephone, jeton = banc
        entetes = {"Cookie": f"{COOKIE_APPAREIL}={jeton}", "Origin": ICI}
        for methode, chemin in (
            ("GET", f"/v1/mesh/devices/{PHONE}/sessions"),
            ("POST", f"/v1/mesh/devices/{PHONE}/sessions/close"),
        ):
            reponse = telephone.request(methode, chemin, headers=entetes)
            assert reponse.status_code == 403, f"{methode} {chemin}"


class TestLAdresseAffichee:
    def test_nulle_tant_que_carlito_ne_l_a_pas_posee(self, banc):
        from diapason.core.config import load_config

        # Une configuration mise en cache par un test précédent ne doit pas
        # répondre à la place du foyer vide de celui-ci.
        load_config.cache_clear()
        mac, _, _ = banc
        invitation = mac.post(
            "/v1/mesh/pairings", json={"deviceName": "Neuf"}, headers=CLE
        ).json()
        assert "tailnetAddress" in invitation
        assert invitation["tailnetAddress"] is None, "une adresse devinée"

    def test_celle_de_la_configuration_quand_elle_est_posee(self, banc):
        """load_config est mis en cache : la clé posée à la main vaut au
        redémarrage suivant du serveur (ou après /v1/config/set, qui vide
        le cache). Le cache est vidé ici pour simuler ce redémarrage."""
        from diapason.core.config import load_config
        from diapason.core.paths import get_config_dir

        (get_config_dir() / "config.toml").write_text(
            '[tailnet]\nadresse = "atelier.tail6efbba.ts.net"\n', encoding="utf-8"
        )
        load_config.cache_clear()
        try:
            mac, _, _ = banc
            invitation = mac.post(
                "/v1/mesh/pairings", json={"deviceName": "Neuf"}, headers=CLE
            ).json()
        finally:
            load_config.cache_clear()
        assert invitation["tailnetAddress"] == "https://atelier.tail6efbba.ts.net"
