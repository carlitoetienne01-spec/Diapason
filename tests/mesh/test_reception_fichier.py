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


class TestNePlusDemanderNEstPasSansLimite:
    """Ce que le retrait du consentement, le 28 août 2026, a laissé ouvert.

    Un pair jumelé n'a plus à demander : c'est le bon choix pour l'usage —
    être questionné à chaque fichier transforme une garde en réflexe. Mais ce
    choix a emporté la SEULE borne qui existait, et rien ne l'a remplacée. Un
    audit l'a reproduit sur ce code : trois cents fichiers déposés d'affilée,
    fenêtre fermée, sans un accord ni un événement ; et vingt manifestes
    annonçant deux gibioctets chacun acceptés sans que rien ne les additionne.

    Ces tests tiennent les deux bornes qui remplacent la question.
    """

    def test_un_dossier_plein_refuse_le_fichier_suivant(self, offre, monkeypatch):
        body, dossier = offre
        monkeypatch.setattr(
            routes, "_volume_recu", lambda: routes._VOLUME_MAX_RECEPTION
        )

        with pytest.raises(HTTPException) as capture:
            routes.offrir(body)

        assert capture.value.status_code == 507, (
            "un disque plein n'est ni un refus d'autorisation (403) ni un "
            "contretemps (429) : le distinguer change ce que l'émetteur fait"
        )
        assert "plein" in str(capture.value.detail)
        assert str(dossier) in str(capture.value.detail), (
            "un refus que l'utilisateur ne peut pas lever vaut à peine mieux "
            "qu'un silence : le message doit dire QUEL dossier vider"
        )

    def test_le_cumul_est_compte_et_pas_seulement_le_fichier(self, offre, monkeypatch):
        """La faille exacte : chaque fichier passait sous le plafond
        individuel, et personne n'additionnait."""
        body, _ = offre
        monkeypatch.setattr(
            routes, "_volume_recu", lambda: routes._VOLUME_MAX_RECEPTION - 2
        )
        # Le manifeste ne pèse que 4 octets — largement sous TAILLE_MAX_DEFAUT.
        with pytest.raises(HTTPException) as capture:
            routes.offrir(body)
        assert capture.value.status_code == 507

    def test_un_disque_presque_plein_refuse_meme_un_dossier_vide(
        self, offre, monkeypatch
    ):
        """Deux gardes, deux questions. Un plafond de dossier ne protège pas
        une machine dont le disque est déjà pris par autre chose."""
        body, _ = offre
        monkeypatch.setattr(routes, "_volume_recu", lambda: 0)
        monkeypatch.setattr(
            routes, "_espace_libre", lambda: routes._ESPACE_LIBRE_MINIMUM
        )

        with pytest.raises(HTTPException) as capture:
            routes.offrir(body)
        assert capture.value.status_code == 507
        assert "place" in str(capture.value.detail)

    def test_un_disque_muet_n_est_pas_un_disque_plein(self, offre, monkeypatch):
        """None n'est pas zéro. Refuser tout parce qu'un appel a échoué
        serait la même famille de mensonge qu'accepter tout."""
        body, _ = offre
        monkeypatch.setattr(routes, "_volume_recu", lambda: 0)
        monkeypatch.setattr(routes, "_espace_libre", lambda: None)

        reponse = routes.offrir(body)
        assert reponse["status"] == "ACCEPTED"

    def test_les_partiels_comptent_dans_le_cumul(self, offre, tmp_path, monkeypatch):
        """Un pair qui ouvre des sessions sans jamais les finir passerait
        sous le plafond éternellement si seuls les fichiers finis comptaient."""
        _, dossier = offre
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / ".abc.partiel").write_bytes(b"x" * 4096)

        assert routes._volume_recu() >= 4096

    def test_de_la_place_laisse_passer(self, offre, monkeypatch):
        """L'autre sens — sans quoi les tests ci-dessus passeraient aussi si
        le transfert était simplement cassé."""
        body, _ = offre
        monkeypatch.setattr(routes, "_volume_recu", lambda: 0)
        monkeypatch.setattr(routes, "_espace_libre", lambda: 100 * 1024**3)

        assert routes.offrir(body)["status"] == "ACCEPTED"


class TestUneArriveeLaisseUneTrace:
    """L'autre moitié du choix du 28 août.

    La seule trace d'un fichier reçu était l'animation de la fenêtre, et
    `_publish_received_file` la jette quand aucune fenêtre ne relève. Un
    fichier pouvait donc arriver en ne laissant qu'une ligne de `logger.info`
    dans un fichier que personne ne lit : impossible de savoir qui avait
    envoyé quoi, ni quand.
    """

    def _session(self, dossier):
        class FauxManifeste:
            type_mime = "application/pdf"

        class FausseReception:
            manifeste = FauxManifeste()

        return routes._Session(
            session_id="s1",
            jeton="j",
            device_id="pair-1",
            device_name="PC du bureau",
            reception=FausseReception(),
            cle=b"0" * 32,
        )

    def test_la_trace_est_ecrite_meme_sans_fenetre(self, offre, tmp_path, monkeypatch):
        _, dossier = offre
        monkeypatch.setattr(
            "diapason.mesh.executor.shell_is_collecting", lambda **_k: False
        )
        cible = tmp_path / "rapport.pdf"
        cible.write_bytes(b"test")

        routes._record_arrival(self._session(dossier), cible, 4)

        import json

        journal = routes.journal_des_receptions()
        assert journal.exists(), "sans fenêtre, il ne restait RIEN"
        entree = json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])
        assert entree["fileName"] == "rapport.pdf"
        assert entree["sourceDeviceName"] == "PC du bureau"
        assert entree["sizeBytes"] == 4

    def test_le_journal_s_ajoute_et_ne_se_reecrit_pas(self, offre, tmp_path):
        _, dossier = offre
        cible = tmp_path / "a.pdf"
        cible.write_bytes(b"test")

        for _ in range(3):
            routes._record_arrival(self._session(dossier), cible, 4)

        lignes = (
            routes.journal_des_receptions().read_text(encoding="utf-8").splitlines()
        )
        assert len(lignes) == 3, "un journal qui se réécrit n'est pas un journal"

    def test_un_journal_illisible_ne_perd_pas_le_fichier(
        self, offre, tmp_path, monkeypatch
    ):
        """Le fichier EST arrivé. Perdre sa ligne ne doit pas défaire cela,
        ni transformer un transfert réussi en erreur pour l'émetteur."""
        _, dossier = offre
        cible = tmp_path / "a.pdf"
        cible.write_bytes(b"test")
        monkeypatch.setattr(
            routes,
            "journal_des_receptions",
            lambda: tmp_path / "nulle-part" / "x.jsonl",
        )
        monkeypatch.setattr(
            "diapason.security.file_utils.secure_create",
            lambda _p: (_ for _ in ()).throw(OSError("disque en lecture seule")),
        )

        routes._record_arrival(self._session(dossier), cible, 4)  # ne lève pas
