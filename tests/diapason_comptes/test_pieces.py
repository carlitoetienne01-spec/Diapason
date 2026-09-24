"""Pièces côté serveur : réclamation, dépôt immuable, orphelines sans course.

Conception : ``docs/development/compte-chiffre.md`` §3.4, §4.7 et étape 5
du §6.
"""

from __future__ import annotations

import os

from diapason_comptes import routes_pieces
from tests.diapason_comptes._outils import JOUR_MS
from tests.diapason_comptes._synchro import (
    blob_objet,
    blob_piece,
    deposer,
    marquer,
    nouvel_id,
    octets_du_compte,
    pousser_un,
    reclamer,
    server_seq,
    tirer,
)


def _deposer_une(service, inscrit, **kw) -> tuple[str, bytes]:
    pid = nouvel_id()
    blob = blob_piece(inscrit, pid, **kw)
    r = deposer(service, inscrit, pid, blob)
    assert r.status_code == 201, r.text
    return pid, blob


def _deuxieme_session(service, inscrit):
    """Un autre appareil du même compte."""
    r = service.connecter(inscrit)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['sessionToken']}"}


class TestDepot:
    def test_une_piece_deposee_se_relit_a_l_octet_pres(self, service):
        """§3.4 — ``PUT`` puis ``GET`` en ``application/octet-stream`` : les
        zéros finaux d'une image chiffrée ne sont ni rognés ni réencodés."""
        inscrit = service.inscrire("depot@exemple.org")
        pid, blob = _deposer_une(service, inscrit)
        r = service.get(f"/pieces/{pid}", headers=inscrit.bearer)
        assert r.status_code == 200, r.text
        assert r.content == blob, "les octets déposés, intacts"
        assert r.headers["content-type"] == "application/octet-stream"
        assert r.headers["cache-control"] == "no-store", "§3.1 sur chaque réponse"

    def test_une_piece_est_immuable(self, service):
        """§3.4 — un second ``PUT`` du même ``pieceId`` (chiffré sous un autre
        sel) rend 200 et ne remplace rien : un appareil qui relit une pièce
        pendant qu'un autre la renvoie voit toujours les mêmes octets."""
        inscrit = service.inscrire("immuable@exemple.org")
        pid, blob = _deposer_une(service, inscrit)
        octets = octets_du_compte(service, inscrit)
        r = deposer(service, inscrit, pid, blob_piece(inscrit, pid))
        assert r.status_code == 200, "déjà là"
        assert service.get(f"/pieces/{pid}", headers=inscrit.bearer).content == blob
        assert octets_du_compte(service, inscrit) == octets, "rien de plus compté"

    def test_une_piece_mal_formee_est_refusee(self, service):
        """§2.5 — ``taille − 66`` doit être une valeur de Padmé d'au moins
        4 096 o, et le type celui d'une pièce."""
        inscrit = service.inscrire("forme@exemple.org")
        pid = nouvel_id()
        valide = blob_piece(inscrit, pid)
        assert len(valide) == 66 + 4096, "une petite pièce fait le plancher"
        fautifs = {
            "un octet de trop": valide + b"\0",
            "sous le plancher": bytes([1, 2, 0, 0, 0, 1]) + os.urandom(60 + 1024),
            "un objet": blob_objet(inscrit, pid, 1),
            "vide": b"",
        }
        for nom, blob in fautifs.items():
            r = deposer(service, inscrit, pid, blob)
            assert r.status_code == 422, nom
            assert r.json() == {"error": {"code": "invalidEnvelope"}}, nom
        r = service.client.put(
            "/api/v1/pieces/pas-un-identifiant", content=valide, headers=inscrit.bearer
        )
        assert r.status_code == 422, "identifiant de 16 o seulement"
        assert r.json()["error"] == {"code": "invalidRequest", "field": "pieceId"}

    def test_une_piece_de_l_ancienne_epoque_rend_key_epoch_changed(self, service):
        """§4.7 — après une rotation, une image se renvoie sous ``K_piece`` et
        la DEK de l'époque neuve ; l'ancienne DEK est peut-être aux mains
        d'un appareil déconnecté."""
        inscrit = service.inscrire("rotation@exemple.org")
        r = service.post(
            "/vault/commit", service.corps_commit(inscrit), headers=inscrit.bearer
        )
        assert r.status_code == 200, r.text
        inscrit.jeton = r.json()["sessionToken"]
        pid = nouvel_id()
        r = deposer(service, inscrit, pid, blob_piece(inscrit, pid, key_epoch=1))
        assert r.status_code == 409, r.text
        assert r.json() == {"error": {"code": "keyEpochChanged"}}
        r = deposer(service, inscrit, pid, blob_piece(inscrit, pid, key_epoch=2))
        assert r.status_code == 201, "sous l'époque 2, ça passe"

    def test_une_piece_de_plus_de_10_mio_est_refusee(self, service):
        """§3.5 (D10) — pièce ≤ 10 Mio, refusée sur ``Content-Length`` avant
        d'être lue."""
        inscrit = service.inscrire("grosse@exemple.org")
        pid = nouvel_id()
        r = deposer(service, inscrit, pid, bytes(10 * 1024 * 1024 + 1))
        assert r.status_code == 413, r.text
        assert r.json() == {"error": {"code": "payloadTooLarge"}}


class TestReclamation:
    def test_missing_rend_les_absentes_et_n_avance_seq_que_s_il_reclame(self, service):
        """§3.4 — une liste d'absentes ne change rien au serveur ; une
        réclamation, si : elle devient un événement de la suite des ``seq``."""
        inscrit = service.inscrire("missing@exemple.org")
        absente = nouvel_id()
        seq = server_seq(service, inscrit)
        r = reclamer(service, inscrit, [absente, absente], seq)
        assert r.status_code == 200, r.text
        assert r.json() == {"missing": [absente]}, "absente, une fois"
        assert server_seq(service, inscrit) == seq, "rien réclamé : seq inchangé"
        pid, _ = _deposer_une(service, inscrit)
        seq = server_seq(service, inscrit)
        r = reclamer(service, inscrit, [pid, absente], seq)
        assert r.json() == {"missing": [absente]}, "la déposée est là"
        assert server_seq(service, inscrit) == seq + 1, "la réclamation prend un seq"

    def test_delete_est_refuse_si_la_piece_a_ete_reclamee_apres_as_of_seq(
        self, service
    ):
        """§4.7 (revue protocole) — A a tiré jusqu'à S et ne voit plus la
        pièce ; B la réclame pour un objet qu'il va pousser. Si A pouvait la
        marquer orpheline sur la foi de S, l'image de B serait purgée 30
        jours plus tard."""
        inscrit = service.inscrire("course@exemple.org")
        appareil_b = _deuxieme_session(service, inscrit)
        pid, _ = _deposer_une(service, inscrit)
        vu_par_a = server_seq(service, inscrit)
        r = service.post(
            "/pieces/missing",
            {"asOfSeq": vu_par_a, "pieceIds": [pid]},
            headers=appareil_b,
        )
        assert r.json() == {"missing": []}, "B la réclame"
        r = marquer(service, inscrit, pid, vu_par_a)
        assert r.status_code == 409, r.text
        assert r.json() == {"error": {"code": "reclaimed"}}
        r = marquer(service, inscrit, pid, server_seq(service, inscrit))
        assert r.status_code == 204, "après avoir tiré plus loin, A peut conclure"

    def test_un_as_of_seq_au_dela_du_serveur_est_refuse(self, service):
        """§3.10 — un appareil qui a vu plus loin que le serveur a vu un état
        que le serveur n'a plus (retour arrière de la machine) : marquer sur
        cette foi effacerait une pièce réclamée depuis."""
        inscrit = service.inscrire("devant@exemple.org")
        pid, _ = _deposer_une(service, inscrit)
        seq = server_seq(service, inscrit)
        r = marquer(service, inscrit, pid, seq + 1)
        assert r.status_code == 409, r.text
        assert r.json() == {"error": {"code": "serverBehind"}}
        r = reclamer(service, inscrit, [pid], seq + 1)
        assert r.status_code == 409, "missing aussi"

    def test_missing_ranime_une_orpheline(self, service):
        """§3.4 — une pièce orpheline réclamée n'est plus orpheline, et elle
        est comptée manquante : l'appareil la renvoie. Sans cela, une pièce
        marquée à tort (jeton volé, §3.7) était purgée au 31e jour.

        AUCUN ``PUT`` ici : jusqu'au 24/09/2026 ce test en faisait un après
        la réclamation, et le ``PUT`` ranimant lui aussi, un ``missing`` qui
        ne ranimait plus rien passait sans bruit."""
        inscrit = service.inscrire("ranime@exemple.org")
        pid, _ = _deposer_une(service, inscrit)
        r = marquer(service, inscrit, pid, server_seq(service, inscrit))
        assert r.status_code == 204, r.text
        r = reclamer(service, inscrit, [pid], server_seq(service, inscrit))
        assert r.json() == {"missing": [pid]}, "l'orpheline est à renvoyer"
        service.horloge.avancer(31 * JOUR_MS)
        pousser_un(service, inscrit, nouvel_id(), 0)
        r = service.get(f"/pieces/{pid}", headers=inscrit.bearer)
        assert r.status_code == 200, "ranimée par missing seul, elle survit"

    def test_un_put_seul_ranime_une_orpheline(self, service):
        """§3.4 — le ré-envoi d'une pièce la confirme vivante, même sans
        ``missing`` avant lui (une reprise après un 5xx). L'autre moitié du
        test précédent : les deux chemins se masquaient l'un l'autre."""
        inscrit = service.inscrire("ranimeput@exemple.org")
        pid, blob = _deposer_une(service, inscrit)
        r = marquer(service, inscrit, pid, server_seq(service, inscrit))
        assert r.status_code == 204, r.text
        assert deposer(service, inscrit, pid, blob).status_code == 200, "déjà là"
        service.horloge.avancer(31 * JOUR_MS)
        pousser_un(service, inscrit, nouvel_id(), 0)
        r = service.get(f"/pieces/{pid}", headers=inscrit.bearer)
        assert r.status_code == 200, "ranimée par le PUT seul, elle survit"

    def test_un_put_sur_une_orpheline_echue_la_recree(self, service):
        """§100 — orpheline depuis 32 jours, pas encore purgée faute de
        poussée : le ``PUT`` purgeait la pièce DANS sa transaction, après
        avoir vu qu'elle existait, puis répondait 200 « déjà là ». Le GET
        suivant rendait 404 et l'appareil la croyait déposée (24/09/2026)."""
        inscrit = service.inscrire("echue@exemple.org")
        pid, blob = _deposer_une(service, inscrit)
        avant = octets_du_compte(service, inscrit)
        r = marquer(service, inscrit, pid, server_seq(service, inscrit))
        assert r.status_code == 204, r.text
        service.horloge.avancer(32 * JOUR_MS)
        r = deposer(service, inscrit, pid, blob)
        assert r.status_code == 201, "purgée puis recréée : 201, pas 200"
        r = service.get(f"/pieces/{pid}", headers=inscrit.bearer)
        assert r.status_code == 200, "la pièce est là après le PUT"
        assert r.content == blob, "les octets renvoyés"
        assert octets_du_compte(service, inscrit) == avant, "comptée une fois"

    def test_un_delete_est_refuse_apres_un_put_de_re_envoi(self, service):
        """§4.7 — un ``PUT`` d'une pièce déjà là la RÉCLAME : A, qui a tiré
        jusqu'à S avant ce ré-envoi, n'a pas le droit de la marquer."""
        inscrit = service.inscrire("renvoi@exemple.org")
        pid, blob = _deposer_une(service, inscrit)
        vu_par_a = server_seq(service, inscrit)
        assert deposer(service, inscrit, pid, blob).status_code == 200, "ré-envoi"
        r = marquer(service, inscrit, pid, vu_par_a)
        assert r.status_code == 409, r.text
        assert r.json() == {"error": {"code": "reclaimed"}}

    def test_until_franchit_les_seq_sans_objet(self, service):
        """§4.3 — une réclamation consomme un ``seq`` sans objet. ``until``
        doit rendre ``serverSeq``, pas le ``seq`` du dernier objet : sinon
        l'appareil ne dépasse jamais la réclamation, et chaque pièce réclamée
        reste 409 ``reclaimed`` pour toujours."""
        inscrit = service.inscrire("trou@exemple.org")
        pid, _ = _deposer_une(service, inscrit)
        dernier = pousser_un(service, inscrit, nouvel_id(), 0)["seq"]
        r = reclamer(service, inscrit, [pid], server_seq(service, inscrit))
        assert r.json() == {"missing": []}, r.text
        page = tirer(service, inscrit, since=0).json()
        assert page["items"][-1]["seq"] == dernier, "le dernier objet"
        assert page["meta"]["serverSeq"] > dernier, "la réclamation a pris un seq"
        assert page["until"] == page["meta"]["serverSeq"], "until = serverSeq"
        r = marquer(service, inscrit, pid, page["until"])
        assert r.status_code == 204, "au curseur until, l'appareil peut conclure"

    def test_une_orpheline_est_purgee_apres_trente_jours(self, service):
        """§3.1 — purgée à la poussée suivante du compte, jamais par un
        minuteur ; une seconde marque ne repousse pas l'échéance, et la place
        est rendue au quota."""
        inscrit = service.inscrire("purge@exemple.org")
        pid, blob = _deposer_une(service, inscrit)
        avant = octets_du_compte(service, inscrit)
        r = marquer(service, inscrit, pid, server_seq(service, inscrit))
        assert r.status_code == 204, "première marque, jour 0"
        service.horloge.avancer(20 * JOUR_MS)
        r = marquer(service, inscrit, pid, server_seq(service, inscrit))
        assert r.status_code == 204, "seconde marque, jour 20 : idempotente"
        service.horloge.avancer(11 * JOUR_MS)
        r = service.get(f"/pieces/{pid}", headers=inscrit.bearer)
        assert r.status_code == 200, "marquée n'est pas effacée : rien sans poussée"
        pousser_un(service, inscrit, nouvel_id(), 0)
        r = service.get(f"/pieces/{pid}", headers=inscrit.bearer)
        assert r.status_code == 404, "purgée au 31e jour de la PREMIÈRE marque"
        assert octets_du_compte(service, inscrit) == avant - len(blob) + 1090, (
            "la pièce rend sa place ; l'objet poussé prend la sienne"
        )


class TestQuotasEtCloisons:
    def test_le_quota_des_pieces_rend_507(self, service, monkeypatch):
        """§3.5 (D10) — 5 000 pièces et 256 Mio par compte."""
        inscrit = service.inscrire("quota@exemple.org")
        monkeypatch.setattr(routes_pieces, "PIECES_MAX", 1)
        _deposer_une(service, inscrit)
        pid = nouvel_id()
        r = deposer(service, inscrit, pid, blob_piece(inscrit, pid))
        assert r.status_code == 507, r.text
        assert r.json() == {"error": {"code": "quotaExceeded"}}
        monkeypatch.setattr(routes_pieces, "PIECES_MAX", 5_000)
        with service.ctx.base.transaction() as conn:
            conn.execute(
                "UPDATE comptes SET quota_octets = 5000 WHERE id = ?",
                (inscrit.account_id,),
            )
        r = deposer(service, inscrit, pid, blob_piece(inscrit, pid))
        assert r.status_code == 507, "4 162 + 4 162 o au-delà de 5 000"

    def test_la_garde_disque_refuse_le_depot_en_507(self, fabrique):
        """§3.5 (D10) — moins de 20 Go libres : 507 ``serverFull``."""
        libre = {"octets": 100 * 10**9}
        service = fabrique(espace_libre=lambda _chemin: libre["octets"])
        inscrit = service.inscrire("disque@exemple.org")
        libre["octets"] = 19 * 10**9
        pid = nouvel_id()
        r = deposer(service, inscrit, pid, blob_piece(inscrit, pid))
        assert r.status_code == 507, r.text
        assert r.json() == {"error": {"code": "serverFull"}}

    def test_aucun_acces_aux_pieces_d_un_autre_compte(self, service):
        """§3.4 — un ``pieceId`` connu d'un autre compte ne se lit, ne se
        marque ni ne se réclame."""
        alice = service.inscrire("alice@exemple.org")
        bob = service.inscrire("bob@exemple.org")
        pid, blob = _deposer_une(service, alice)
        assert service.get(f"/pieces/{pid}", headers=bob.bearer).status_code == 404
        assert marquer(service, bob, pid, server_seq(service, bob)).status_code == 404
        r = reclamer(service, bob, [pid], server_seq(service, bob))
        assert r.json() == {"missing": [pid]}, "chez Bob, elle n'existe pas"
        r = marquer(service, alice, pid, server_seq(service, alice))
        assert r.status_code == 204, "la réclamation de Bob n'a pas touché Alice"
        assert service.get(f"/pieces/{pid}", headers=alice.bearer).content == blob

    def test_sans_session_rien_ne_passe(self, service):
        """§3.7 — chaque route des pièces exige un Bearer."""
        pid = nouvel_id()
        for methode, corps in (
            ("GET", None),
            ("PUT", b"x"),
            ("DELETE", b'{"asOfSeq":0}'),
        ):
            r = service.client.request(methode, f"/api/v1/pieces/{pid}", content=corps)
            assert r.status_code == 401, methode
            assert r.json() == {"error": {"code": "sessionRevoked"}}, methode
        r = service.post("/pieces/missing", {"asOfSeq": 0, "pieceIds": []})
        assert r.status_code == 401, "missing"

    def test_un_put_de_11_mio_sans_session_rend_401_avant_toute_lecture(self, service):
        """§3.7 — la session se vérifie AVANT le corps : un inconnu ne fait
        pas lire 10 Mio au service. Un 413 dirait qu'il a été mesuré."""
        pid = nouvel_id()
        r = service.client.put(
            f"/api/v1/pieces/{pid}",
            content=bytes(11 * 1024 * 1024),
            headers={"Content-Type": "application/octet-stream"},
        )
        assert r.status_code == 401, "401, pas 413"


class TestGlobalSeqDesPieces:
    def test_chaque_ecriture_de_piece_avance_global_seq(self, service):
        """§3.10 — ``globalSeq`` dit un retour arrière de la machine parce
        qu'il avance à CHAQUE écriture : une réclamation, un dépôt, une
        première marque. Une seconde marque n'écrit rien."""
        inscrit = service.inscrire("globalpieces@exemple.org")

        def g() -> int:
            return service.get("/health").json()["globalSeq"]

        avant = g()
        pid, _ = _deposer_une(service, inscrit)
        assert g() == avant + 1, "le dépôt avance globalSeq"
        avant = g()
        reclamer(service, inscrit, [pid], server_seq(service, inscrit))
        assert g() == avant + 1, "la réclamation avance globalSeq"
        avant = g()
        r = marquer(service, inscrit, pid, server_seq(service, inscrit))
        assert r.status_code == 204, r.text
        assert g() == avant + 1, "la première marque avance globalSeq"
        avant = g()
        marquer(service, inscrit, pid, server_seq(service, inscrit))
        assert g() == avant, "une seconde marque n'écrit rien"


class TestPortillonDesPieces:
    def test_depot_et_lecture_prennent_un_passage_lourd(self, service):
        """§3.1 — un dépôt tient jusqu'à 10 Mio en mémoire, une lecture
        aussi : sans passage, quarante à la fois dépassaient ``MemoryMax``."""
        inscrit = service.inscrire("portillonpieces@exemple.org")
        pid, blob = _deposer_une(service, inscrit)
        pris = 0
        while service.ctx.portillon.entrer():
            pris += 1
        try:
            for nom, r in (
                ("PUT", deposer(service, inscrit, pid, blob)),
                ("GET", service.get(f"/pieces/{pid}", headers=inscrit.bearer)),
            ):
                assert r.status_code == 503, nom
                assert r.json()["error"]["code"] == "serverBusy", nom
        finally:
            for _ in range(pris):
                service.ctx.portillon.sortir()
