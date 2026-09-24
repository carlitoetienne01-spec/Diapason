"""La frontière ``local_only`` du compte, et la porte qui la porte.

Conception : ``docs/development/compte-chiffre.md`` §3.12 (D1) et étape 8
du §6 : « ``local_only`` : l'hôte constant passe, une surcharge et un clair
sont refusés ».

Chaque refus est vérifié DEUX fois : l'exception, et l'absence de toute
requête côté serveur — un refus levé après l'envoi serait un refus décoratif.
Aucun octet ne quitte la machine : le serveur est un ``httpx.MockTransport``.
"""

from __future__ import annotations

import httpx
import pytest

from diapason.compte import enveloppe
from diapason.compte.transport import (
    SERVEUR_COMPTES,
    VARIABLE_SURCHARGE,
    ClairRefuse,
    CompteInactif,
    EnveloppeChiffree,
    ErreurServeur,
    ServeurInjoignable,
    SortieRefusee,
    Transport,
    assert_may_reach_account_server,
    construire_client_http,
    origine_configuree,
)
from diapason.core import local_mode


class _Serveur:
    """Note chaque requête ; répond ``reponse`` (200 ``{}`` par défaut)."""

    def __init__(self, reponse: httpx.Response | None = None) -> None:
        self.requetes: list[httpx.Request] = []
        self.reponse = reponse

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requetes.append(request)
        return self.reponse or httpx.Response(200, json={})


def _transport(serveur: _Serveur, *, actif: bool = True, origine: str | None = None):
    return Transport(
        actif=lambda: actif,
        client_http=httpx.Client(transport=httpx.MockTransport(serveur)),
        origine=origine,
    )


@pytest.fixture
def local_only(monkeypatch):
    """Le mode local ACTIF, comme en production (la fixture commune le coupe)."""
    monkeypatch.setattr(local_mode, "local_only", lambda config=None: True)


@pytest.fixture
def hors_local_only(monkeypatch):
    monkeypatch.setattr(local_mode, "local_only", lambda config=None: False)


def _objet_scelle() -> bytes:
    return enveloppe.sceller_objet(
        bytes(32),
        b'{"v":1}',
        account_id="compte",
        incarnation=1,
        object_id="objet",
        rev=1,
        key_epoch=1,
    )


class TestLaFrontiereDuCompte:
    """§3.12 : quatre conditions, toutes nécessaires."""

    def test_l_hote_constant_passe_sous_local_only(self, local_only):
        """§3.12 condition 1 — sans cette exception, D1 ne vaudrait rien : le
        compte serait mort chez tous ceux qui gardent le mode local, c'est-à-
        dire par défaut."""
        serveur = _Serveur()
        _transport(serveur).requete("POST", "/login/params", corps={"email": "a@b.c"})
        assert len(serveur.requetes) == 1, "l'hôte constant doit être joint"
        assert str(serveur.requetes[0].url) == SERVEUR_COMPTES + "/api/v1/login/params"

    def test_une_origine_surchargee_est_refusee_sous_local_only(
        self, local_only, monkeypatch
    ):
        """§3.12 condition 1 : « une surcharge par DIAPASON_SERVEUR_COMPTES
        n'est pas exemptée ». Sinon une variable d'environnement — posée par
        n'importe quel programme de la session — ferait partir l'adresse et
        authKey ailleurs, mode local actif."""
        monkeypatch.setenv(VARIABLE_SURCHARGE, "https://ailleurs.example")
        assert origine_configuree() == "https://ailleurs.example"
        serveur = _Serveur()
        with pytest.raises(SortieRefusee) as refus:
            _transport(serveur).requete("POST", "/login", corps={"email": "a@b.c"})
        assert refus.value.code == "localOnly", "le code doit dire « mode local »"
        assert serveur.requetes == [], "rien ne doit être parti vers la surcharge"

    def test_une_surcharge_qui_imite_l_hote_ne_passe_pas(self, local_only):
        """Un sous-domaine ou un suffixe ne sont pas l'origine constante : la
        comparaison porte sur l'origine entière, pas sur un « contient »."""
        for url in (
            "https://diapason.flashprime.online.ailleurs.example/api/v1/login",
            "https://evil.diapason.flashprime.online/api/v1/login",
            "http://diapason.flashprime.online/api/v1/login",
            "https://diapason.flashprime.online:8443/api/v1/login",
        ):
            with pytest.raises(SortieRefusee):
                assert_may_reach_account_server(url, actif=True)

    def test_sans_local_only_une_surcharge_https_est_permise(self, hors_local_only):
        """La surcharge existe pour un serveur de développement : elle sert
        quand la personne a coupé le mode local, et seulement en HTTPS ou en
        boucle locale."""
        assert_may_reach_account_server("https://dev.example/api/v1/x", actif=True)
        assert_may_reach_account_server("http://127.0.0.1:8710/api/v1/x", actif=True)
        with pytest.raises(SortieRefusee):
            assert_may_reach_account_server("http://dev.example/api/v1/x", actif=True)

    def test_sans_compte_rien_ne_part_meme_hors_local_only(self, hors_local_only):
        """§3.12 condition 4 : « sans compte, rien ne part » est une règle du
        compte, pas du verrou local."""
        serveur = _Serveur()
        with pytest.raises(CompteInactif):
            _transport(serveur, actif=False).requete("GET", "/account")
        assert serveur.requetes == [], "aucune requête sans compte ni geste"

    def test_la_frontiere_passe_avant_la_lecture_du_jeton(self, local_only):
        """§4.3 étape 2 : ``assert_may_reach_account_server()`` AVANT de lire
        le jeton. Un refus ne doit avoir touché aucune lettre de créance."""
        lu = []
        serveur = _Serveur()
        transport = _transport(serveur, origine="https://ailleurs.example")
        with pytest.raises(SortieRefusee):
            transport.requete("GET", "/account", jeton=lambda: lu.append(1) or "dps1_x")
        assert lu == [], "le jeton a été lu avant que la frontière ne refuse"


class TestSeulesDesEnveloppesChiffreesVoyagent:
    """§3.12 condition 3 : « la synchronisation ne transporte que des
    EnveloppeChiffree. Le transport refuse tout autre type »."""

    @pytest.mark.parametrize(
        "clair",
        [
            b'{"v":1,"collection":"conversations","data":{"title":"secret"}}',
            '{"title":"secret"}',
            {"title": "secret"},
            bytearray(b"\x01\x01" + bytes(200)),
        ],
    )
    def test_un_clair_est_refuse_sans_rien_envoyer(self, local_only, clair):
        """Un clair poussé vers ``/sync/push`` partirait en toutes lettres au
        VPS : la promesse « le serveur ne peut pas lire » tomberait sur une
        seule faute d'appelant."""
        serveur = _Serveur()
        with pytest.raises(ClairRefuse) as refus:
            _transport(serveur).pousser_objets(
                incarnation=1,
                key_epoch=1,
                elements=[("objet", 0, clair)],
                jeton=lambda: "dps1_x",
            )
        assert refus.value.code == "plaintextRefused"
        assert serveur.requetes == [], "le clair ne doit pas avoir quitté l'appareil"

    def test_un_json_deguise_en_enveloppe_est_refuse_a_la_construction(self):
        """L'en-tête DPE1 est vérifié : emballer un JSON dans la classe ne
        suffit pas à le faire passer pour chiffré."""
        with pytest.raises(ClairRefuse):
            EnveloppeChiffree(b'{"title":"secret","messages":[]}' * 4)
        with pytest.raises(ClairRefuse):
            # En-tête DPE1 mais type 03 (AMK) : ce n'est pas une donnée.
            EnveloppeChiffree(b"\x01\x03" + bytes(100))

    def test_la_porte_generique_refuse_les_routes_de_donnees(self, local_only):
        """Sans ce refus, la condition 3 se contournait en appelant
        ``/sync/push`` par :meth:`Transport.requete` avec un corps en clair."""
        serveur = _Serveur()
        for chemin in (
            "/sync/push",
            "/pieces/abc",
            # Contre-épreuve du 24/09/2026 : une liste noire de préfixes
            # laissait passer ces formes, et httpx normalisait les deux
            # premières en ``/api/v1/sync/push``.
            "/./sync/push",
            "/account/../sync/push",
            "/sync%2Fpush",
            "//sync/push",
            "/SYNC/push",
        ):
            with pytest.raises(ClairRefuse):
                _transport(serveur).requete(
                    "POST", chemin, corps={"items": [{"blob": "clair"}]}
                )
        assert serveur.requetes == []

    def test_une_vraie_enveloppe_d_objet_part(self, local_only):
        """Témoin positif : la vérification ne bloque pas ce qu'elle protège."""
        serveur = _Serveur()
        blob = _objet_scelle()
        _transport(serveur).pousser_objets(
            incarnation=1,
            key_epoch=1,
            elements=[("objet", 0, EnveloppeChiffree(blob))],
            jeton=lambda: "dps1_x",
        )
        assert len(serveur.requetes) == 1, "l'enveloppe chiffrée doit partir"
        assert serveur.requetes[0].url.path == "/api/v1/sync/push"
        assert b"secret" not in serveur.requetes[0].content

    def test_une_sous_classe_ne_contourne_pas_le_type(self, local_only):
        """``type(...) is``, pas ``isinstance`` : une sous-classe pourrait
        redéfinir la vérification et laisser passer un clair."""

        class Complaisante(EnveloppeChiffree):
            def __post_init__(self) -> None:
                pass

        serveur = _Serveur()
        with pytest.raises(ClairRefuse):
            _transport(serveur).pousser_objets(
                incarnation=1,
                key_epoch=1,
                elements=[("objet", 0, Complaisante(b"clair"))],
                jeton=lambda: "dps1_x",
            )
        assert serveur.requetes == []


class TestLesReponsesDuServeur:
    def test_un_429_de_nginx_sans_corps_attend_soixante_secondes(self, local_only):
        """§3.9 : un 429 de nginx n'a ni corps JSON ni ``retryAfterS`` ; sans
        repli, le client réessaierait aussitôt et viderait la zone."""
        serveur = _Serveur(httpx.Response(429, text="<html>429</html>"))
        with pytest.raises(ErreurServeur) as refus:
            _transport(serveur).requete("POST", "/login", corps={})
        assert refus.value.statut == 429
        assert refus.value.retry_after_s == 60, "le repli sans corps est de 60 s"

    def test_le_code_et_l_attente_du_serveur_sont_repris(self, local_only):
        serveur = _Serveur(
            httpx.Response(
                429, json={"error": {"code": "tooManyAttempts", "retryAfterS": 17}}
            )
        )
        with pytest.raises(ErreurServeur) as refus:
            _transport(serveur).requete("POST", "/login", corps={})
        assert (refus.value.code, refus.value.retry_after_s) == ("tooManyAttempts", 17)

    def test_une_redirection_est_refusee(self, local_only):
        """Une redirection mènerait ailleurs que l'origine vérifiée."""
        serveur = _Serveur(
            httpx.Response(302, headers={"Location": "https://ailleurs.example/"})
        )
        with pytest.raises(ServeurInjoignable):
            _transport(serveur).requete("POST", "/login", corps={})

    def test_une_panne_reseau_ne_journalise_ni_url_ni_corps(self, local_only, caplog):
        """Le message d'une erreur httpx peut citer l'URL complète : seul le
        type d'erreur entre au journal."""

        def panne(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connexion refusée vers " + str(request.url))

        transport = Transport(
            actif=lambda: True,
            client_http=httpx.Client(transport=httpx.MockTransport(panne)),
        )
        caplog.set_level("DEBUG")
        with pytest.raises(ServeurInjoignable):
            transport.requete("POST", "/login", corps={"authKey": "canari-auth"})
        assert "canari-auth" not in caplog.text
        assert "flashprime" not in caplog.text, "l'URL n'entre pas au journal"


class TestLeClientDeProduction:
    """Ce que :func:`construire_client_http` construit — sans rien joindre."""

    def test_l_environnement_ne_detourne_pas_le_trafic_du_compte(self, monkeypatch):
        """§3.12 condition 1. Le 24/09/2026, avec le défaut d'httpx
        (``trust_env``), ``HTTPS_PROXY`` faisait passer l'adresse, ``authKey``
        et le jeton par un proxy local, et ``SSL_CERT_FILE`` choisissait le
        magasin de certificats : une interception complète, par deux
        variables que n'importe quel programme de la session peut poser —
        alors que ``DIAPASON_SERVEUR_COMPTES``, elle, est refusée."""
        for variable in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
            monkeypatch.setenv(variable, "http://127.0.0.1:9")
        monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/ca.pem")
        client = construire_client_http()
        try:
            assert client._mounts == {}, "un proxy de l'environnement est monté"
            assert client.trust_env is False
        finally:
            client.close()

    def test_sans_redirection_et_quinze_secondes(self):
        """Une redirection suivie renverrait le corps (``authKey``) à un
        autre hôte APRÈS le contrôle de la frontière ; 15 s, parce qu'aucune
        route du VPS ne calcule plus qu'un HMAC (§2.3)."""
        client = construire_client_http()
        try:
            assert client.follow_redirects is False, "les redirections sont suivies"
            assert client.timeout.read == 15.0
            assert client.timeout.connect == 15.0
        finally:
            client.close()


class TestLOrigineAnnoncee:
    def test_une_surcharge_refusee_sous_local_only_n_est_pas_permise(
        self, local_only, monkeypatch
    ):
        """L'écran d'activation nomme la destination : il doit savoir, avant
        le geste, qu'une surcharge sera refusée (§3.12)."""
        assert Transport(actif=lambda: True).origine_permise() is True
        monkeypatch.setenv(VARIABLE_SURCHARGE, "https://ailleurs.example")
        assert Transport(actif=lambda: True).origine_permise() is False
