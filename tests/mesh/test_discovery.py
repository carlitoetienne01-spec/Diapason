"""mDNS may find a socket; only pairing and signatures may make it a peer."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import pytest
from zeroconf import ServiceStateChange

from diapason.mesh import discovery as d


class FakeRegistry:
    def __init__(self):
        self.key = bytes(range(32))
        self.device = {
            "deviceId": "dev_pc",
            "name": "PC du bureau",
            "platform": "WINDOWS",
            "trustLevel": "TRUSTED",
            "address": "http://192.168.0.9:8001",
            "capabilities": ["app.navigate"],
        }

    def list_devices(self, *, include_revoked=False):
        return [dict(self.device)]

    def public_key_of(self, device_id):
        if device_id != self.device["deviceId"]:
            return None
        if self.device["trustLevel"] != "TRUSTED":
            return None
        return self.key

    def find(self, device_id):
        return dict(self.device) if device_id == self.device["deviceId"] else None


class TestLePseudonymeTourneSansPublierLIdentite:
    def test_meme_cle_meme_heure_meme_nom(self):
        key = b"k" * 32
        assert d.service_token(key, now_ms=3_700_000) == d.service_token(
            key, now_ms=3_799_999
        )

    def test_le_nom_change_a_l_heure_suivante(self):
        key = b"k" * 32
        assert d.service_token(key, now_ms=3_599_999) != d.service_token(
            key, now_ms=3_600_000
        )

    def test_deux_cles_ne_portent_pas_le_meme_nom(self):
        assert d.service_token(b"a" * 32, now_ms=0) != d.service_token(
            b"b" * 32, now_ms=0
        )

    def test_la_tolerance_couvre_les_deux_heures_voisines(self):
        registry = FakeRegistry()
        expected = d.expected_names(registry, now_ms=4 * d.DISCOVERY_EPOCH_MS)
        for offset in (-1, 0, 1):
            token = d.service_token(
                registry.key,
                now_ms=4 * d.DISCOVERY_EPOCH_MS,
                offset=offset,
            )
            assert expected[token] == "dev_pc"

    def test_lenregistrement_public_ne_contient_aucun_profil(self):
        """Le fusible de vie privée : personne n'ajoute « juste le nom pour
        déboguer » sans casser ce test."""
        registry = FakeRegistry()
        token = d.service_token(registry.key, now_ms=0)
        public = json.dumps(
            {
                "type": d.DISCOVERY_TYPE,
                "name": f"{token}.{d.DISCOVERY_TYPE}",
                "txt": {str(k): str(v) for k, v in d.txt_properties().items()},
            }
        )
        interdits = {
            "deviceId": registry.device["deviceId"],
            "name": registry.device["name"],
            "platform": registry.device["platform"],
            "ownerId": "owner_test",
            "publicKey": base64.b64encode(registry.key).decode(),
            "capability": "app.navigate",
        }
        for field, value in interdits.items():
            assert value not in public, f"{field} ne doit jamais être publié en mDNS"


class TestUneAnnonceNEstJamaisUnePreuve:
    def test_un_inconnu_ne_recoit_pas_un_octet(self):
        registry = FakeRegistry()
        calls = []
        assert not d.consider_candidate(
            name=f"inconnu.{d.DISCOVERY_TYPE}",
            addresses=["192.168.0.42"],
            port=8001,
            properties={b"v": b"1"},
            registry=registry,
            announce=lambda *a, **k: calls.append((a, k)) or True,
            now_ms=0,
        )
        assert calls == [], "un pseudonyme inconnu ne doit recevoir aucun contact"

    def test_un_pair_est_contacte_a_ladresse_candidate_sans_ecriture(self):
        registry = FakeRegistry()
        before = dict(registry.device)
        calls = []
        token = d.service_token(registry.key, now_ms=0)

        assert d.consider_candidate(
            name=f"{token}.{d.DISCOVERY_TYPE}",
            addresses=["192.168.0.42"],
            port=8001,
            properties={b"v": b"1"},
            registry=registry,
            announce=lambda device, **kw: calls.append((device, kw)) or True,
            now_ms=0,
        )
        assert len(calls) == 1
        assert calls[0][0]["address"] == "http://192.168.0.42:8001"
        assert registry.device == before, "mDNS ne doit jamais écrire dans le registre"

    def test_un_pair_revoque_disparait_immediatement(self):
        registry = FakeRegistry()
        token = d.service_token(registry.key, now_ms=0)
        registry.device["trustLevel"] = "REVOKED"
        calls = []
        assert not d.consider_candidate(
            name=f"{token}.{d.DISCOVERY_TYPE}",
            addresses=["192.168.0.42"],
            port=8001,
            properties={b"v": b"1"},
            registry=registry,
            announce=lambda *a, **k: calls.append((a, k)) or True,
            now_ms=0,
        )
        assert calls == []

    @pytest.mark.parametrize(
        "addresses",
        [
            ["127.0.0.1"],
            ["169.254.10.2"],
            ["fe80::1"],
            ["8.8.8.8"],
            ["0.0.0.0"],
            ["224.0.0.251"],
        ],
    )
    def test_une_adresse_qui_n_est_pas_le_lan_est_refusee(self, addresses):
        registry = FakeRegistry()
        token = d.service_token(registry.key, now_ms=0)
        assert not d.consider_candidate(
            name=f"{token}.{d.DISCOVERY_TYPE}",
            addresses=addresses,
            port=8001,
            properties={b"v": b"1"},
            registry=registry,
            announce=lambda *_a, **_k: True,
            now_ms=0,
        )

    def test_une_version_inconnue_ne_declenche_rien(self):
        registry = FakeRegistry()
        token = d.service_token(registry.key, now_ms=0)
        assert not d.consider_candidate(
            name=f"{token}.{d.DISCOVERY_TYPE}",
            addresses=["192.168.0.42"],
            port=8001,
            properties={b"v": b"2"},
            registry=registry,
            announce=lambda *_a, **_k: True,
            now_ms=0,
        )


class TestOnNAnnonceQueCeQuiEcouteVraiment:
    @pytest.fixture(autouse=True)
    def restore_endpoint(self):
        from diapason.mesh import beacon

        before = beacon._endpoint
        yield
        beacon._endpoint = before

    def test_avant_le_choix_du_socket_rien_n_est_publie(self):
        from diapason.mesh import beacon

        beacon._endpoint = None
        assert d.current_advertisement(now_ms=0) is None

    def test_la_loopback_n_est_jamais_publiee(self):
        from diapason.mesh.beacon import set_local_endpoint

        set_local_endpoint("127.0.0.1", 8001)
        assert d.current_advertisement(now_ms=0) is None

    def test_le_socket_lan_publie_seulement_ladresse_et_le_port(self, monkeypatch):
        from diapason.mesh import beacon
        from diapason.mesh.beacon import set_local_endpoint

        set_local_endpoint("0.0.0.0", 8001)  # noqa: S104 - cas testé
        monkeypatch.setattr(beacon, "_lan_address", lambda: "192.168.0.121")

        class Identity:
            public_key_b64 = base64.b64encode(b"m" * 32).decode()

        monkeypatch.setattr(
            "diapason.mesh.identity.device_identity", lambda: Identity()
        )
        ad = d.current_advertisement(now_ms=0)
        assert ad is not None
        assert ad.address == "192.168.0.121"
        assert ad.port == 8001
        assert ad.properties == {b"v": b"1"}


class _Banc:
    """Ce que les doublures observent pendant qu'un ``run_discovery`` tourne."""

    def __init__(self) -> None:
        self.gestionnaires: list[Any] = []
        self.navigateur_pret = asyncio.Event()
        self.candidats: list[dict[str, Any]] = []


def _doublures_zeroconf(banc: _Banc):
    """Le quintuplé de ``_imports`` sans un seul socket multicast.

    Seul ``ServiceStateChange`` est le vrai : c'est contre lui que le
    gestionnaire compare l'état reçu, et un faux enum validerait un
    gestionnaire qui ne comprend pas celui de python-zeroconf.
    """

    class ServiceInfo:
        def __init__(self, type_, name, **kw):
            self.type = type_
            self.name = name
            self.port = kw.get("port")
            self.addresses = kw.get("addresses")

    class AsyncServiceInfo:
        def __init__(self, service_type, name):
            self.name = name
            self.port = 8001
            self.properties = {b"v": b"1"}

        async def async_request(self, zc, timeout_ms):
            return True

        def parsed_scoped_addresses(self):
            return ["192.168.0.9"]

    class AsyncServiceBrowser:
        def __init__(self, zc, types, *, handlers):
            banc.gestionnaires.extend(handlers)
            banc.navigateur_pret.set()

        async def async_cancel(self):
            pass

    class AsyncZeroconf:
        zeroconf = object()

        async def async_register_service(self, info):
            pass

        async def async_unregister_service(self, info):
            pass

        async def async_close(self):
            pass

    return (
        ServiceInfo,
        ServiceStateChange,
        AsyncServiceBrowser,
        AsyncServiceInfo,
        AsyncZeroconf,
    )


class TestLeNavigateurAppelleLeGestionnaireParMotsCles:
    """python-zeroconf 0.150 n'appelle un gestionnaire QU'AVEC des mots-clés.

    ``_fire_service_state_changed_event`` (zeroconf/_services/browser.py)
    fait ``fire(zeroconf=…, service_type=…, name=…, state_change=…)``. Du
    26 août au 20 septembre 2026, ``changed`` nommait ses paramètres ``_zc``
    et ``state`` : chaque paquet multicast levait ``TypeError: unexpected
    keyword argument 'zeroconf'`` sur la boucle — 251 956 fois dans
    serve.err.log (465 Mo) — et aucun appareil n'a jamais été découvert,
    sans qu'un test le sache (§5 : ne jamais faire semblant). Ces tests
    appellent le gestionnaire exactement comme python-zeroconf le fait ;
    ils sont rouges sur l'ancienne signature.
    """

    @pytest.fixture
    def banc(self, monkeypatch):
        banc = _Banc()
        annonce = d.Advertisement(
            token="a" * 16,
            address="192.168.0.121",
            port=8001,
            properties={b"v": b"1"},
        )
        monkeypatch.setattr(d, "_enabled", lambda: True)
        monkeypatch.setattr(d, "current_advertisement", lambda now_ms=None: annonce)
        monkeypatch.setattr(d, "_imports", lambda: _doublures_zeroconf(banc))
        monkeypatch.setattr(
            d,
            "consider_candidate",
            lambda **kw: banc.candidats.append(kw) or True,
        )
        return banc

    async def _gestionnaire(self, banc: _Banc):
        """Le gestionnaire que ``run_discovery`` a confié au navigateur."""
        await asyncio.wait_for(banc.navigateur_pret.wait(), 2)
        assert len(banc.gestionnaires) == 1, "un seul gestionnaire attendu"
        return banc.gestionnaires[0]

    async def _laisser_inspecter(self, banc: _Banc) -> None:
        """``inspect`` tourne en tâche puis dans un fil : lui céder la boucle."""
        for _ in range(50):
            if banc.candidats:
                return
            await asyncio.sleep(0.01)

    @pytest.mark.asyncio
    async def test_un_ajout_recu_par_mots_cles_declenche_une_inspection(self, banc):
        tache = asyncio.create_task(
            d.run_discovery(registry=FakeRegistry(), announce=lambda **kw: True)
        )
        try:
            gestionnaire = await self._gestionnaire(banc)
            gestionnaire(
                zeroconf=object(),
                service_type=d.DISCOVERY_TYPE,
                name=f"{'b' * 16}.{d.DISCOVERY_TYPE}",
                state_change=ServiceStateChange.Added,
            )
            await self._laisser_inspecter(banc)
        finally:
            tache.cancel()
            with pytest.raises(asyncio.CancelledError):
                await tache

        assert len(banc.candidats) == 1, (
            "un ajout annoncé par le navigateur doit lancer une inspection"
        )
        assert banc.candidats[0]["name"] == f"{'b' * 16}.{d.DISCOVERY_TYPE}"
        assert banc.candidats[0]["addresses"] == ["192.168.0.9"]
        assert banc.candidats[0]["port"] == 8001

    @pytest.mark.asyncio
    async def test_un_retrait_ne_contacte_personne(self, banc):
        tache = asyncio.create_task(
            d.run_discovery(registry=FakeRegistry(), announce=lambda **kw: True)
        )
        try:
            gestionnaire = await self._gestionnaire(banc)
            gestionnaire(
                zeroconf=object(),
                service_type=d.DISCOVERY_TYPE,
                name=f"{'b' * 16}.{d.DISCOVERY_TYPE}",
                state_change=ServiceStateChange.Removed,
            )
            await self._laisser_inspecter(banc)
        finally:
            tache.cancel()
            with pytest.raises(asyncio.CancelledError):
                await tache

        assert banc.candidats == [], (
            "un service qui disparaît ne doit déclencher aucun contact"
        )
