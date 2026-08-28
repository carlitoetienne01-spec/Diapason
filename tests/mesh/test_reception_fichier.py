"""Un pair jumelé reçoit sans second clic, jamais sans preuve."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from diapason.mesh import files_routes as routes


def _requete(jeton: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"x-transfer-token", jeton.encode())],
        }
    )


@pytest.fixture()
def offre(tmp_path, monkeypatch):
    """Une offre signée déjà vérifiée ; le test porte sur la confiance."""
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "maison"))
    routes.reinitialiser_pour_tests()
    monkeypatch.setattr(
        "diapason.mesh.signed.verify_payload", lambda *_a, **_k: "pair-1"
    )
    monkeypatch.setattr(
        "diapason.mesh.registry.DeviceRegistry.find",
        lambda _self, _id: {
            "deviceId": "pair-1",
            "name": "PC du bureau",
            "trustLevel": "TRUSTED",
        },
    )
    monkeypatch.setattr(routes, "_repondre", lambda corps: dict(corps))
    dossier = tmp_path / "reçus"
    monkeypatch.setattr(routes, "dossier_de_reception", lambda: dossier)

    from diapason.mesh.coffre import nouvelle_demi_cle

    demi = nouvelle_demi_cle()
    body = routes.Offre(
        version=1,
        ownerId="owner",
        deviceId="pair-1",
        sentAtMs=1,
        sessionNonce="nonce",
        manifest={
            "name": "rapport.pdf",
            "size": 4,
            "sha256": hashlib.sha256(b"test").hexdigest(),
            "mimeType": "application/pdf",
            "chunks": 1,
        },
        ephemeralPublicKey=demi.publique_b64,
        signature="sig",
    )
    yield body, dossier
    routes.reinitialiser_pour_tests()


class TestLeJumelageVautAutorisation:
    """§5 — TRUSTED est la décision durable, pas une question par fichier."""

    def test_le_nom_affiche_ne_peut_pas_inverser_la_carte(self):
        nom = routes._display_name("  PC\u202eexe.jpg\n bureau  ")
        assert nom == "PCexe.jpg bureau"

    def test_l_offre_ouvre_la_session_sans_demande(self, offre):
        body, dossier = offre

        reponse = routes.offrir(body)

        assert reponse["status"] == "ACCEPTED"
        assert reponse["sessionId"]
        assert reponse["uploadToken"]
        assert "requestId" not in reponse
        assert "requestToken" not in reponse
        assert dossier.is_dir()
        assert len(routes._sessions) == 1, "l'offre doit ouvrir une seule session"

    def test_un_appareil_qui_n_est_plus_trusted_est_refuse(self, offre, monkeypatch):
        body, dossier = offre
        monkeypatch.setattr(
            "diapason.mesh.registry.DeviceRegistry.find",
            lambda _self, _id: {
                "deviceId": "pair-1",
                "name": "PC révoqué",
                "trustLevel": "REVOKED",
            },
        )
        monkeypatch.setattr(
            "diapason.mesh.transfert.deja_present",
            lambda *_a, **_k: pytest.fail(
                "un pair révoqué ne doit pas apprendre qu'un fichier existe"
            ),
        )

        with pytest.raises(HTTPException) as refus:
            routes.offrir(body)

        assert refus.value.status_code == 403
        assert not dossier.exists(), "un pair révoqué ne doit rien créer"
        assert not routes._sessions, "un pair révoqué n'obtient aucun jeton"

    def test_un_jeton_invente_ne_depose_rien(self, offre):
        body, dossier = offre
        proposition = routes.offrir(body)

        with pytest.raises(HTTPException) as refus:
            routes.finir(proposition["sessionId"], _requete("inventé"))

        assert refus.value.status_code == 403
        assert not list(dossier.glob("rapport.pdf"))


class TestLArriveeVisibleDitLaVerite:
    """§100 — l'animation ne naît qu'après l'empreinte finale vérifiée."""

    def test_la_fin_publie_le_fichier_et_l_appareil(self, offre, monkeypatch):
        body, _dossier = offre
        evenements: list[dict] = []
        monkeypatch.setattr("diapason.mesh.executor.shell_is_collecting", lambda: True)
        monkeypatch.setattr(
            "diapason.mesh.executor.push_shell_event",
            lambda entree: evenements.append(entree) or True,
        )
        proposition = routes.offrir(body)
        session = routes._sessions[proposition["sessionId"]]
        session.reception.ecrire(0, b"test")

        reponse = routes.finir(
            proposition["sessionId"], _requete(proposition["uploadToken"])
        )

        assert reponse["status"] == "COMPLETE"
        assert len(evenements) == 1
        arrivee = evenements[0]["fileReceived"]
        assert arrivee == {
            "fileName": "rapport.pdf",
            "sizeBytes": 4,
            "mimeType": "application/pdf",
            "sourceDeviceId": "pair-1",
            "sourceDeviceName": "PC du bureau",
        }

    def test_une_fenetre_fermee_n_empeche_pas_le_transfert(self, offre, monkeypatch):
        body, dossier = offre
        monkeypatch.setattr("diapason.mesh.executor.shell_is_collecting", lambda: False)
        monkeypatch.setattr(
            "diapason.mesh.executor.push_shell_event",
            lambda _entree: pytest.fail(
                "aucun événement ne doit attendre sans fenêtre"
            ),
        )
        proposition = routes.offrir(body)
        session = routes._sessions[proposition["sessionId"]]
        session.reception.ecrire(0, b"test")

        reponse = routes.finir(
            proposition["sessionId"], _requete(proposition["uploadToken"])
        )

        assert reponse["status"] == "COMPLETE"
        assert (dossier / "rapport.pdf").read_bytes() == b"test"

    def test_une_empreinte_fausse_ne_declenche_aucune_animation(
        self, offre, monkeypatch
    ):
        body, _dossier = offre
        evenements: list[dict] = []
        monkeypatch.setattr("diapason.mesh.executor.shell_is_collecting", lambda: True)
        monkeypatch.setattr(
            "diapason.mesh.executor.push_shell_event",
            lambda entree: evenements.append(entree) or True,
        )
        proposition = routes.offrir(body)
        session = routes._sessions[proposition["sessionId"]]
        session.reception.ecrire(0, b"faux")

        with pytest.raises(HTTPException) as refus:
            routes.finir(proposition["sessionId"], _requete(proposition["uploadToken"]))

        assert refus.value.status_code == 422
        assert evenements == [], "un fichier rejeté n'est jamais annoncé comme arrivé"


class TestLEmetteurResteCompatibleAvecUnAncienRecepteur:
    def _fichier(self, tmp_path: Path) -> Path:
        source = tmp_path / "note.txt"
        source.write_bytes(b"quatre octets de confiance")
        return source

    def _appareil(self) -> dict:
        return {
            "deviceId": "pair-1",
            "name": "PC du bureau",
            "address": "http://192.168.1.20:8001",
            "trustLevel": "TRUSTED",
        }

    def test_aucun_morceau_ne_part_avant_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "envoyeur"))
        monkeypatch.setattr(
            "diapason.mesh.envoi_fichier._verifier_reponse",
            lambda reponse, _device: reponse,
        )
        from diapason.mesh.coffre import nouvelle_demi_cle
        from diapason.mesh.envoi_fichier import envoyer_fichier

        recepteur = nouvelle_demi_cle()
        etats = iter(
            [
                {"status": "PENDING", "requestId": "r1", "pollAfterMs": 1},
                {
                    "status": "ACCEPTED",
                    "requestId": "r1",
                    "sessionId": "s1",
                    "uploadToken": "u1",
                    "ephemeralPublicKey": recepteur.publique_b64,
                },
            ]
        )
        appels: list[str] = []

        def poster(url, _corps, _jeton):
            appels.append(url)
            if url.endswith("/offer"):
                return {
                    "status": "PENDING",
                    "requestId": "r1",
                    "requestToken": "t1",
                    "pollAfterMs": 1,
                    "expiresInS": 120,
                    "userSafeMessage": "En attente du PC du bureau.",
                }
            if "/requests/" in url:
                return next(etats)
            if "/chunk" in url:
                return {"received": 0}
            return {
                "status": "COMPLETE",
                "sessionId": "s1",
                "path": "/reçus/note.txt",
                "bytes": 25,
                "userSafeMessage": "« note.txt » est arrivé.",
            }

        annonces: list[str] = []
        resultat = envoyer_fichier(
            self._fichier(tmp_path),
            self._appareil(),
            poster=poster,
            attente=annonces.append,
            dormir=lambda _s: None,
        )

        requetes = [i for i, url in enumerate(appels) if "/requests/" in url]
        morceaux = [i for i, url in enumerate(appels) if "/chunk" in url]
        assert len(requetes) == 2
        assert morceaux and morceaux[0] > requetes[-1]
        assert resultat.statut == "COMPLETE"
        assert annonces == ["En attente du PC du bureau."]

    def test_un_non_ne_transmet_aucun_morceau(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "envoyeur-refuse"))
        monkeypatch.setattr(
            "diapason.mesh.envoi_fichier._verifier_reponse",
            lambda reponse, _device: reponse,
        )
        from diapason.mesh.envoi_fichier import envoyer_fichier

        appels: list[str] = []

        def poster(url, _corps, _jeton):
            appels.append(url)
            if url.endswith("/offer"):
                return {
                    "status": "PENDING",
                    "requestId": "r1",
                    "requestToken": "t1",
                    "pollAfterMs": 1,
                }
            return {
                "status": "DENIED",
                "requestId": "r1",
                "userSafeMessage": "Le fichier a été refusé.",
            }

        resultat = envoyer_fichier(
            self._fichier(tmp_path),
            self._appareil(),
            poster=poster,
            dormir=lambda _s: None,
        )

        assert resultat.statut == "DENIED"
        assert not any("/chunk" in url for url in appels)
