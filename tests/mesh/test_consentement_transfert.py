"""Une offre de fichier attend un oui réel avant de toucher le disque."""

from __future__ import annotations

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
    """Une offre signée déjà vérifiée ; le test porte sur le consentement."""
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "maison"))
    routes.reinitialiser_pour_tests()
    monkeypatch.setattr(
        "diapason.mesh.signed.verify_payload", lambda *_a, **_k: "pair-1"
    )
    monkeypatch.setattr(
        "diapason.mesh.registry.DeviceRegistry.find",
        lambda _self, _id: {"deviceId": "pair-1", "name": "PC du bureau"},
    )
    monkeypatch.setattr(
        "diapason.mesh.demande_de_reception.poser", lambda *_a, **_k: "action-1"
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
            "sha256": "a" * 64,
            "mimeType": "application/pdf",
            "chunks": 1,
        },
        ephemeralPublicKey=demi.publique_b64,
        signature="sig",
    )
    yield body, dossier
    routes.reinitialiser_pour_tests()


class TestLaDecisionPrecedeLeDisque:
    """§5 et §100 — PENDING n'est ni accepté, ni commencé."""

    def test_l_offre_ne_cree_ni_dossier_ni_session(self, offre):
        body, dossier = offre

        reponse = routes.offrir(body)

        assert reponse["status"] == "PENDING"
        assert reponse["requestId"]
        assert reponse["requestToken"]
        assert not dossier.exists(), "demander n'est pas encore recevoir"
        assert not routes._sessions, "aucune clé d'envoi ne doit exister avant le oui"

    def test_accepter_ouvre_une_seule_session(self, offre, monkeypatch):
        body, dossier = offre
        proposition = routes.offrir(body)
        monkeypatch.setattr(
            "diapason.mesh.demande_de_reception.decision",
            lambda _id: "ACCEPTED",
        )

        premiere = routes.etat_demande(
            proposition["requestId"], _requete(proposition["requestToken"])
        )
        seconde = routes.etat_demande(
            proposition["requestId"], _requete(proposition["requestToken"])
        )

        assert premiere["status"] == "ACCEPTED"
        assert premiere["sessionId"] == seconde["sessionId"]
        assert premiere["uploadToken"] == seconde["uploadToken"]
        assert dossier.is_dir()
        assert len(routes._sessions) == 1, "deux sondages ne créent pas deux sessions"

    def test_refuser_ne_touche_jamais_le_disque(self, offre, monkeypatch):
        body, dossier = offre
        proposition = routes.offrir(body)
        monkeypatch.setattr(
            "diapason.mesh.demande_de_reception.decision", lambda _id: "DENIED"
        )

        reponse = routes.etat_demande(
            proposition["requestId"], _requete(proposition["requestToken"])
        )

        assert reponse["status"] == "DENIED"
        assert not dossier.exists()
        assert not routes._sessions

    def test_un_jeton_invente_ne_lit_pas_la_decision(self, offre):
        body, _dossier = offre
        proposition = routes.offrir(body)

        with pytest.raises(HTTPException) as refus:
            routes.etat_demande(proposition["requestId"], _requete("inventé"))

        assert refus.value.status_code == 403


class TestLaClochePorteLaVraieDemande:
    def test_nom_taille_et_appareil_sont_visibles(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "cloche"))
        annonces: list[tuple[str, str]] = []
        monkeypatch.setattr(
            "diapason.server.approval_bridge.announce_approval",
            lambda titre, corps: annonces.append((titre, corps)),
        )
        from diapason.mesh.demande_de_reception import poser
        from diapason.mesh.transfert import Manifeste
        from diapason.tools.approval_store import ApprovalStore

        action_id = poser(
            Manifeste(
                nom="rapport\u202egnp.exe",
                taille=2 * (1 << 20),
                hachage="a" * 64,
                type_mime="application/octet-stream",
                morceaux=2,
            ),
            {"deviceId": "pair-1", "name": "PC\u202e du bureau"},
        )

        store = ApprovalStore()
        try:
            action = store.get_action(action_id)
        finally:
            store.close()
        assert action is not None
        assert action.action_type == "file_transfer"
        assert action.payload["fileName"] == "rapportgnp.exe"
        assert action.payload["deviceName"] == "PC du bureau"
        assert "2.0 Mo" in action.description
        assert annonces and "accepte ou refuse" in annonces[0][1]

    def test_le_oui_est_consomme_une_seule_fois(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "decision"))
        monkeypatch.setattr(
            "diapason.server.approval_bridge.announce_approval",
            lambda *_a: None,
        )
        from diapason.mesh.demande_de_reception import decision, poser
        from diapason.mesh.transfert import Manifeste
        from diapason.tools.approval_store import (
            STATUS_APPROVED,
            STATUS_EXECUTED,
            ApprovalStore,
        )

        action_id = poser(
            Manifeste("note.txt", 1, "a" * 64, "text/plain", 1),
            {"deviceId": "pair-1", "name": "PC"},
        )
        store = ApprovalStore()
        try:
            store.update_status(action_id, STATUS_APPROVED)
        finally:
            store.close()

        assert decision(action_id) == "ACCEPTED"
        store = ApprovalStore()
        try:
            assert store.get_action(action_id).status == STATUS_EXECUTED
        finally:
            store.close()
        assert decision(action_id) == "ACCEPTED"


class TestLEmetteurAttendLaReponse:
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
