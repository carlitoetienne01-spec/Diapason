"""Les comptes restent fermés sur l'appareil tant qu'ils ne sont pas ouverts.

24/09/2026. La conception ne fermait les inscriptions que côté serveur
(``INSCRIPTIONS_OUVERTES=0``), en supposant que l'interface sortirait avec
l'ouverture. Or l'app se reconstruit depuis ``main`` au fil de l'eau, et le
service de comptes n'est déployé nulle part : l'écran d'accueil proposait un
compte qu'aucun serveur ne pouvait créer, et l'inscription échouait au premier
appel réseau. §5 du cahier : une capacité que rien n'exerce est une promesse en
attente.
"""

from __future__ import annotations

import httpx
import pytest

from diapason.compte import service as module_service
from diapason.compte.gardien import ProtecteurMemoire, preparer_dossier_compte
from diapason.compte.service import EtatRefuse, ServiceCompte


class _Compteur:
    """Un transport qui compte les requêtes au lieu de les servir."""

    def __init__(self) -> None:
        self.requetes: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requetes.append(request)
        return httpx.Response(599, json={"error": {"code": "neDevaitPasPartir"}})


def _service(tmp_path, compteur: _Compteur, **options) -> ServiceCompte:
    dossier = tmp_path / "config"
    dossier.mkdir()
    return ServiceCompte(
        dossier=preparer_dossier_compte(dossier, plateforme="linux"),
        protecteur=ProtecteurMemoire(),
        client_http=httpx.Client(transport=httpx.MockTransport(compteur)),
        **options,
    )


class TestLeDefautEstFerme:
    def test_la_constante_du_module_est_fermee(self):
        """Fil déclencheur délibéré : le commit d'ouverture (étape 13)
        passe COMPTES_OUVERTS à True ET met ce test à jour. Qu'il échoue
        sans que personne n'ait décidé d'ouvrir, c'est qu'on a ouvert par
        mégarde."""
        assert module_service.COMPTES_OUVERTS is False, (
            "les comptes ne s'ouvrent que dans le commit de l'étape 13"
        )

    def test_le_statut_le_dit(self, tmp_path):
        """L'interface lit ``accountsOpen`` pour ne proposer ni l'écran
        d'accueil ni l'inscription."""
        service = _service(tmp_path, _Compteur())
        assert service.statut()["accountsOpen"] is False, (
            "un appareil construit sans rien préciser doit se dire fermé"
        )

    @pytest.mark.parametrize(
        ("parcours", "appel"),
        [
            ("inscription", lambda s: s.inscription_debut("a@exemple.ca", True)),
            ("connexion", lambda s: s.connecter("a@exemple.ca", "x" * 16, False)),
            (
                "récupération",
                lambda s: s.recuperer("a@exemple.ca", "0" * 32, "x" * 16, False, False),
            ),
            ("réinitialisation", lambda s: s.reinit_demander("a@exemple.ca")),
        ],
    )
    def test_aucun_parcours_ne_joint_le_serveur(self, tmp_path, parcours, appel):
        """Le refus arrive AVANT tout appel réseau : sous local_only, une
        requête vers un serveur qui n'existe pas serait déjà une sortie."""
        compteur = _Compteur()
        service = _service(tmp_path, compteur)
        with pytest.raises(EtatRefuse) as refus:
            appel(service)
        assert refus.value.code == "accountsNotOpen", (
            f"{parcours} doit être refusé comme fermé, pas autrement"
        )
        assert compteur.requetes == [], (
            f"{parcours} a contacté le serveur alors que les comptes sont fermés"
        )


class TestParHttp:
    def test_la_route_rend_503_et_le_code(self, tmp_path):
        """Même statut que la fermeture côté serveur (signupClosed) : un 409
        laisserait croire à un conflit d'état que l'utilisateur pourrait
        résoudre."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from diapason.server.compte_routes import AccesCompte, create_compte_router

        compteur = _Compteur()
        service = _service(tmp_path, compteur)
        app = FastAPI()
        app.include_router(create_compte_router(AccesCompte(lambda: service)))
        client = TestClient(app)
        assert client.get("/v1/account/status").json()["accountsOpen"] is False
        reponse = client.post(
            "/v1/account/signup/start",
            json={"email": "a@exemple.ca", "termsAccepted": True},
        )
        assert reponse.status_code == 503, "fermé se dit en 503"
        assert reponse.json()["error"]["code"] == "accountsNotOpen", (
            "l'interface lit ce code pour dire pourquoi"
        )
        assert compteur.requetes == [], "aucune requête ne doit partir"


class TestOuvertExplicitement:
    def test_ouvert_le_statut_le_dit(self, tmp_path):
        service = _service(tmp_path, _Compteur(), ouverts=True)
        assert service.statut()["accountsOpen"] is True, (
            "ouvert explicitement, l'appareil doit le dire"
        )
