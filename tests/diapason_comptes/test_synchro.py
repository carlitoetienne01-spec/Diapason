"""Synchronisation côté serveur : comparer-et-échanger, seq, pages, gardes.

Conception : ``docs/development/compte-chiffre.md`` §3.4, §4.3 à §4.6, et
étape 5 du §6.
"""

from __future__ import annotations

import base64
import dataclasses
import os
import threading

from diapason_comptes import jetons, routes_synchro
from diapason_comptes.validation import b64url
from tests.diapason_comptes._outils import (
    JOUR_MS,
    amk_mdp,
    trousseau,
)
from tests.diapason_comptes._synchro import (
    blob_objet,
    blob_piece,
    element,
    nouvel_id,
    octets_du_compte,
    pousser,
    pousser_un,
    server_seq,
    tirer,
)

CLES_META = {
    "generation",
    "incarnation",
    "keyEpoch",
    "vaultVersion",
    "keyringVersion",
    "serverSeq",
    "pendingResetAt",
}


def _octets(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def _tourner(service, inscrit) -> None:
    """Une rotation : l'époque passe à 2, la session courante est remplacée."""
    r = service.post(
        "/vault/commit", service.corps_commit(inscrit), headers=inscrit.bearer
    )
    assert r.status_code == 200, r.text
    inscrit.jeton = r.json()["sessionToken"]
    inscrit.vault_version = inscrit.keyring_version = inscrit.key_epoch = 2


def _reinitialiser(service, inscrit) -> None:
    """``reset/confirm`` puis ``reset/complete`` après l'échéance : incarnation 2."""

    def poser(code: str) -> None:
        with service.ctx.base.transaction() as conn:
            jetons.enregistrer_code(
                conn,
                service.secrets,
                service.secrets.index_courriel(inscrit.email),
                "reinitialisation",
                code,
                service.horloge(),
            )

    poser("424242")
    r = service.post("/reset/confirm", {"email": inscrit.email, "code": "424242"})
    assert r.status_code == 202, r.text
    service.horloge.ms = r.json()["effectiveAt"] + 1
    poser("434343")
    r = service.post(
        "/reset/complete",
        {
            "email": inscrit.email,
            "code": "434343",
            "kdfVersion": 1,
            "authKey": b64url(inscrit.auth_key),
            "wrappedMasterKey": b64url(amk_mdp(inscrit.account_id)),
            "recovery": None,
            "keyring": b64url(trousseau(inscrit.account_id)),
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["incarnation"] == 2, "incarnation + 1"
    inscrit.jeton = r.json()["sessionToken"]


def _health_seq(service) -> int:
    return service.get("/health").json()["globalSeq"]


# ----------------------------------------------------------------------
# Comparer-et-échanger
# ----------------------------------------------------------------------


class TestComparerEchanger:
    def test_de_deux_poussees_sur_la_meme_base_une_seule_gagne(self, service):
        """§4.5 — deux appareils modifient la même conversation depuis la
        révision 1 : sans comparer-et-échanger, le second écrasait le premier
        sans l'avoir vu, et sa modification disparaissait partout."""
        inscrit = service.inscrire("cas@exemple.org")
        oid = nouvel_id()
        assert pousser_un(service, inscrit, oid, 0)["status"] == "stored"
        premier = blob_objet(inscrit, oid, 2)
        second = blob_objet(inscrit, oid, 2)
        r1 = pousser(service, inscrit, [element(oid, 1, premier)])
        r2 = pousser(service, inscrit, [element(oid, 1, second)])
        assert r1.json()["results"][0]["status"] == "stored", "le premier gagne"
        perdu = r2.json()["results"][0]
        assert perdu["status"] == "conflict", "le second perd"
        assert perdu["current"]["rev"] == 2, "current rend la révision gagnante"
        assert _octets(perdu["current"]["blob"]) == premier, (
            "current porte le blob du gagnant, que le perdant ingère et fusionne"
        )

    def test_deux_poussees_simultanees_n_ont_qu_un_gagnant(self, service):
        """§4.5 — la même course, cette fois dans deux fils à la fois : le
        verrou de la base et la lecture de ``rev`` DANS la transaction font
        qu'un seul voit la révision 0."""
        inscrit = service.inscrire("course@exemple.org")
        oid = nouvel_id()
        depart = threading.Barrier(2)
        issues: list[str] = []

        def pousser_depuis(ip: str) -> None:
            client = service.depuis(ip)
            blob = blob_objet(inscrit, oid, 1)
            depart.wait()
            r = pousser(service, inscrit, [element(oid, 0, blob)], client=client)
            issues.append(r.json()["results"][0]["status"])

        fils = [
            threading.Thread(target=pousser_depuis, args=(ip,))
            for ip in ("198.51.100.1", "203.0.113.1")
        ]
        for f in fils:
            f.start()
        for f in fils:
            f.join(10)
        assert sorted(issues) == ["conflict", "stored"], f"un seul gagnant : {issues}"

    def test_un_conflit_sur_un_objet_absent_rend_current_null(self, service):
        """§3.4 — un objet absent a pour ``rev`` 0 ; un ``baseRev`` qui ne
        correspond pas rend TOUJOURS un conflit, jamais une erreur. Un 404
        aurait fait mettre l'objet en quarantaine au lieu de le repousser en
        ``baseRev`` 0."""
        inscrit = service.inscrire("absent@exemple.org")
        oid = nouvel_id()
        r = pousser(service, inscrit, [element(oid, 3, blob_objet(inscrit, oid, 4))])
        assert r.status_code == 200, r.text
        assert r.json()["results"] == [{"status": "conflict", "current": None}], (
            "conflit avec current null"
        )

    def test_la_revision_stockee_est_base_rev_plus_un(self, service):
        """§2.5 — ``r`` est dans l'AAD : le client scelle en ``baseRev + 1``,
        le serveur doit ranger sous cette même révision, sinon l'objet
        devient illisible au tirage suivant."""
        inscrit = service.inscrire("rev@exemple.org")
        oid = nouvel_id()
        assert pousser_un(service, inscrit, oid, 0)["rev"] == 1, "rev 1"
        assert pousser_un(service, inscrit, oid, 1)["rev"] == 2, "rev 2"

    def test_les_conflits_au_dela_de_8_mio_sont_differes(self, service, monkeypatch):
        """§4.3 — cinquante conflits sur des objets de 4 Mio faisaient une
        réponse de 200 Mio, au-delà du ``MemoryMax=300M`` du service. Passé
        le budget, les éléments suivants sont ``deferred`` : rien n'est
        écrit pour eux, le client les renvoie."""
        monkeypatch.setattr(routes_synchro, "CONFLITS_OCTETS_MAX", 1500)
        inscrit = service.inscrire("differe@exemple.org")
        ids = [nouvel_id() for _ in range(3)]
        for oid in ids:
            pousser_un(service, inscrit, oid, 0)
        seq = server_seq(service, inscrit)
        r = pousser(
            service,
            inscrit,
            [element(oid, 0, blob_objet(inscrit, oid, 1)) for oid in ids],
        )
        statuts = [x["status"] for x in r.json()["results"]]
        assert statuts == ["conflict", "deferred", "deferred"], statuts
        assert r.json()["meta"]["serverSeq"] == seq, "rien n'a été écrit"


# ----------------------------------------------------------------------
# seq et pagination
# ----------------------------------------------------------------------


class TestSeqEtPages:
    def test_seq_est_monotone_et_suit_chaque_ecriture(self, service):
        """§3.4 — le curseur d'un appareil est un ``seq`` : un ``seq`` qui
        stagnerait ou reculerait ferait sauter une écriture au tirage."""
        inscrit = service.inscrire("seq@exemple.org")
        a, b = nouvel_id(), nouvel_id()
        vus = [
            pousser_un(service, inscrit, a, 0)["seq"],
            pousser_un(service, inscrit, b, 0)["seq"],
            pousser_un(service, inscrit, a, 1)["seq"],
        ]
        assert vus == sorted(set(vus)), f"seq strictement croissant : {vus}"
        page = tirer(service, inscrit).json()
        assert [(i["objectId"], i["seq"]) for i in page["items"]] == [
            (b, vus[1]),
            (a, vus[2]),
        ], "chaque objet une fois, à son dernier seq, dans l'ordre de seq"
        assert page["meta"]["serverSeq"] == vus[2], "serverSeq = dernier seq"

    def test_la_pagination_reprend_au_curseur_until(self, service):
        """§4.3 — au plus 200 éléments par page ; ``until`` et ``hasMore``
        disent où reprendre. Un curseur mal rendu répète ou saute une page."""
        inscrit = service.inscrire("pages@exemple.org")
        ids = [nouvel_id() for _ in range(7)]
        r = pousser(
            service,
            inscrit,
            [element(oid, 0, blob_objet(inscrit, oid, 1)) for oid in ids],
        )
        assert [x["status"] for x in r.json()["results"]] == ["stored"] * 7
        vus: list[str] = []
        depuis, pages = 0, 0
        while True:
            page = tirer(service, inscrit, since=depuis, limit=3).json()
            pages += 1
            vus += [i["objectId"] for i in page["items"]]
            assert page["until"] >= depuis, "le curseur n'avance que"
            depuis = page["until"]
            if not page["hasMore"]:
                break
        assert vus == ids, "tous les objets, une fois chacun, dans l'ordre"
        assert pages == 3, "7 éléments en pages de 3"
        assert depuis == page["meta"]["serverSeq"], "la dernière page rend serverSeq"
        fin = tirer(service, inscrit, since=depuis).json()
        assert fin["items"] == [] and not fin["hasMore"], "rien après serverSeq"

    def test_une_page_s_arrete_au_budget_d_octets_mais_jamais_vide(
        self, service, monkeypatch
    ):
        """§4.3 — ≤ 8 Mio par page ; mais un objet plus gros que le budget
        doit passer seul, sinon le curseur ne bouge plus jamais."""
        inscrit = service.inscrire("octets@exemple.org")
        for _ in range(3):
            pousser_un(service, inscrit, nouvel_id(), 0)
        monkeypatch.setattr(routes_synchro, "PAGE_OCTETS_MAX", 2500)
        page = tirer(service, inscrit).json()
        assert len(page["items"]) == 2 and page["hasMore"], "deux blobs de 1 090 o"
        monkeypatch.setattr(routes_synchro, "PAGE_OCTETS_MAX", 10)
        page = tirer(service, inscrit).json()
        assert len(page["items"]) == 1, "au moins un élément par page"
        assert page["until"] == page["items"][0]["seq"], "until = dernier rendu"

    def test_des_parametres_mal_formes_sont_refuses_sans_echo(self, service):
        """§3.1 — ``since`` et ``limit`` en chiffres ASCII seulement ; un 422
        ne nomme que le champ."""
        inscrit = service.inscrire("params@exemple.org")
        for chaine, champ in (
            ("since=-1", "since"),
            ("since=%D9%A3", "since"),
            ("limit=0", "limit"),
            ("limit=201", "limit"),
            ("since=1&since=2", "since"),
        ):
            r = service.get(f"/sync/changes?{chaine}", headers=inscrit.bearer)
            assert r.status_code == 422, chaine
            assert r.json()["error"] == {"code": "invalidRequest", "field": champ}


# ----------------------------------------------------------------------
# Forme des blobs
# ----------------------------------------------------------------------


class TestForme:
    def test_une_taille_hors_padme_ou_sous_le_plancher_est_refusee(self, service):
        """§2.5 — le VPS vérifie que ``taille − 66`` est une valeur de Padmé
        au moins égale au plancher. Un blob qui ne l'est pas ne vient pas
        d'un client Diapason : stocké, il aurait été resservi à chaque
        appareil, qui l'aurait mis en quarantaine pour toujours."""
        inscrit = service.inscrire("padme@exemple.org")
        oid = nouvel_id()
        valide = blob_objet(inscrit, oid, 1)
        assert len(valide) == 66 + 1024, "un petit objet fait le plancher"
        en_tete = bytes([1, 1, 0, 0, 0, 1])
        fautifs = {
            "un octet de trop": valide + b"\0",
            "Padmé sous le plancher": en_tete + os.urandom(60 + 512),
            "une pièce": blob_piece(inscrit, oid),
            "époque nulle": bytes([1, 1, 0, 0, 0, 0]) + valide[6:],
            "époque d'en-tête ≠ keyEpoch": bytes([1, 1, 0, 0, 0, 2]) + valide[6:],
            "format inconnu": bytes([2]) + valide[1:],
        }
        for nom, blob in fautifs.items():
            r = pousser(service, inscrit, [element(oid, 0, blob)])
            assert r.status_code == 200, r.text
            assert r.json()["results"] == [
                {"status": "rejected", "code": "invalidEnvelope"}
            ], nom
        assert pousser_un(service, inscrit, oid, 0)["status"] == "stored", (
            "le blob valide passe"
        )

    def test_un_objet_de_plus_de_4_mio_est_refuse(self, service):
        """§3.5 (D10) — objet ≤ 4 Mio : au-delà, c'est qu'une image n'a pas
        été détachée en pièce, et le serveur ne doit pas le cacher."""
        inscrit = service.inscrire("gros@exemple.org")
        oid = nouvel_id()
        blob = blob_objet(inscrit, oid, 1, clair=b"x" * (4 * 1024 * 1024))
        r = pousser(service, inscrit, [element(oid, 0, blob)])
        assert r.json()["results"] == [
            {"status": "rejected", "code": "objectTooLarge"}
        ], "refus par élément"

    def test_le_lot_est_borne_a_50_elements_et_8_mio(self, service, monkeypatch):
        """§3.4 — au plus 50 éléments et 8 Mio : un lot sans borne faisait
        tenir au service tout ce qu'un client voulait bien envoyer."""
        inscrit = service.inscrire("lot@exemple.org")
        oid = nouvel_id()
        blob = blob_objet(inscrit, oid, 1)
        r = pousser(service, inscrit, [element(nouvel_id(), 0, blob)] * 51)
        assert r.status_code == 422, "51 éléments"
        assert r.json()["error"] == {"code": "invalidRequest", "field": "items"}
        monkeypatch.setattr(routes_synchro, "POUSSEE_OCTETS_MAX", 2000)
        r = pousser(service, inscrit, [element(nouvel_id(), 0, blob)] * 2)
        assert r.status_code == 413, "2 180 o décodés au-delà de 2 000"
        assert r.json()["error"]["code"] == "payloadTooLarge"

    def test_le_corps_est_borne_a_12_mio_apres_la_session(self, service):
        """§3.9 — nginx accorde 12 Mio à ``/sync/`` ; l'application aussi.
        Et la session se vérifie AVANT la lecture : sans elle, n'importe qui
        faisait lire 12 Mio au service."""
        inscrit = service.inscrire("corps@exemple.org")
        gros = b"{" + b" " * (12 * 1024 * 1024) + b"}"
        r = service.client.post(
            "/api/v1/sync/push",
            content=gros,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 401, "sans session : 401 avant toute lecture"
        r = service.client.post(
            "/api/v1/sync/push",
            content=gros,
            headers={**inscrit.bearer, "Content-Type": "application/json"},
        )
        assert r.status_code == 413, "avec session : 413"


# ----------------------------------------------------------------------
# Rotation et réinitialisation
# ----------------------------------------------------------------------


class TestEpoqueEtIncarnation:
    def test_une_poussee_sous_l_ancienne_epoque_rend_key_epoch_changed(self, service):
        """§2.8 — après une rotation, toute écriture neuve se scelle sous
        ``DEK_{e+1}`` : un appareil qui pousse encore sous l'ancienne DEK
        écrirait ce qu'un appareil déconnecté peut toujours lire."""
        inscrit = service.inscrire("epoque@exemple.org")
        oid = nouvel_id()
        pousser_un(service, inscrit, oid, 0)
        _tourner(service, inscrit)
        r = pousser(service, inscrit, [element(oid, 1, blob_objet(inscrit, oid, 2))])
        assert r.status_code == 409, r.text
        assert r.json()["error"] == {"code": "keyEpochChanged"}
        assert r.json()["meta"]["keyEpoch"] == 2, "meta dit l'époque à recharger"
        issue = pousser_un(service, inscrit, oid, 1, key_epoch=2)
        assert issue["status"] == "stored", "sous l'époque courante, ça passe"

    def test_une_poussee_d_avant_la_reinitialisation_rend_incarnation_changed(
        self, service
    ):
        """§3.6, §4.5 — après ``reset/complete``, un blob scellé sous
        l'ancienne incarnation ne vaut plus rien : l'accepter aurait mêlé
        l'ancien compte au nouveau."""
        inscrit = service.inscrire("incarnation@exemple.org")
        oid = nouvel_id()
        pousser_un(service, inscrit, oid, 0)
        _reinitialiser(service, inscrit)
        r = pousser(service, inscrit, [element(oid, 0, blob_objet(inscrit, oid, 1))])
        assert r.status_code == 409, r.text
        assert r.json()["error"] == {"code": "incarnationChanged"}
        assert r.json()["meta"]["incarnation"] == 2, "meta dit la nouvelle incarnation"
        page = tirer(service, inscrit).json()
        assert page["items"] == [], "reset/complete a effacé les objets"
        issue = pousser_un(service, inscrit, oid, 0, incarnation=2)
        assert issue["status"] == "stored", "sous l'incarnation 2, ça passe"
        assert issue["seq"] > 1, "seq n'est pas remis à zéro par la réinitialisation"


# ----------------------------------------------------------------------
# Version précédente
# ----------------------------------------------------------------------


class TestVersionPrecedente:
    def test_la_version_remplacee_est_gardee_trente_jours(self, service):
        """§4.6 — un jeton volé écrase un objet par du bruit (A9) ; l'appareil
        sans copie locale relit la version précédente et répare. Au-delà de
        30 jours, elle disparaît, et sa place est rendue au compte."""
        inscrit = service.inscrire("precedente@exemple.org")
        oid = nouvel_id()
        premier = blob_objet(inscrit, oid, 1)
        pousser(service, inscrit, [element(oid, 0, premier)])
        pousser_un(service, inscrit, oid, 1)
        avant = octets_du_compte(service, inscrit)
        assert avant == 2 * len(premier), "la précédente compte dans le quota"

        r = service.get(f"/sync/previous/{oid}", headers=inscrit.bearer)
        assert r.status_code == 200, r.text
        assert r.json()["rev"] == 1, "la révision remplacée"
        assert _octets(r.json()["blob"]) == premier, "le blob remplacé, intact"

        service.horloge.avancer(30 * JOUR_MS)
        r = service.get(f"/sync/previous/{oid}", headers=inscrit.bearer)
        assert r.status_code == 200, "encore là au 30e jour"
        service.horloge.avancer(JOUR_MS)
        r = service.get(f"/sync/previous/{oid}", headers=inscrit.bearer)
        assert r.status_code == 404, "partie au 31e jour, purge passée ou non"
        assert r.json()["error"] == {"code": "notFound"}

        pousser_un(service, inscrit, nouvel_id(), 0)
        assert octets_du_compte(service, inscrit) == avant, (
            "la poussée suivante purge la précédente : −1 090 o, +1 090 o neufs"
        )
        with service.ctx.base.lecture() as conn:
            (reste,) = conn.execute(
                "SELECT blob_precedent FROM objets WHERE objet_id = ?", (oid,)
            ).fetchone()
        assert reste is None, "la précédente est effacée de la base"

    def test_les_octets_comptes_egalent_ce_que_la_base_garde(self, service):
        """§3.5 — ``usedBytes`` est ce que le quota compare : il doit valoir
        la somme des blobs courants, des précédentes et des pièces, après
        des remplacements EN CHAÎNE (la précédente libérée à chaque fois),
        des dépôts, une marque et une purge. Un écart s'accumule à chaque
        poussée et finit en refus sans cause, ou en quota sans borne."""
        inscrit = service.inscrire("invariant@exemple.org")

        def verifier(etape: str) -> None:
            with service.ctx.base.lecture() as conn:
                (reel,) = conn.execute(
                    "SELECT (SELECT COALESCE(SUM(length(blob)), 0) "
                    "+ COALESCE(SUM(length(blob_precedent)), 0) FROM objets "
                    "WHERE compte_id = ?1) + (SELECT COALESCE(SUM(length(blob)), 0) "
                    "FROM pieces WHERE compte_id = ?1)",
                    (inscrit.account_id,),
                ).fetchone()
            assert octets_du_compte(service, inscrit) == reel, etape

        oid = nouvel_id()
        for rev, taille in enumerate((10, 3000, 50, 9000, 20), start=1):
            blob = blob_objet(inscrit, oid, rev, clair=os.urandom(taille))
            r = pousser(service, inscrit, [element(oid, rev - 1, blob)])
            assert r.json()["results"][0]["status"] == "stored", r.text
            verifier(f"après le remplacement {rev}")
        pid = nouvel_id()
        r = service.client.put(
            f"/api/v1/pieces/{pid}",
            content=blob_piece(inscrit, pid),
            headers={**inscrit.bearer, "Content-Type": "application/octet-stream"},
        )
        assert r.status_code == 201, r.text
        verifier("après un dépôt")
        r = service.client.request(
            "DELETE",
            f"/api/v1/pieces/{pid}",
            json={"asOfSeq": server_seq(service, inscrit)},
            headers=inscrit.bearer,
        )
        assert r.status_code == 204, r.text
        verifier("après une marque")
        service.horloge.avancer(31 * JOUR_MS)
        pousser_un(service, inscrit, nouvel_id(), 0)
        verifier("après la purge de la précédente et de l'orpheline")

    def test_au_trentieme_jour_une_poussee_ne_purge_rien(self, service):
        """§3.4 — ``/sync/previous`` promet la précédente jusqu'au 30e jour
        inclus, et l'orpheline vit 30 jours aussi. Une purge qui partirait un
        jour trop tôt ferait mentir cette promesse au premier appareil qui
        pousse ce jour-là."""
        inscrit = service.inscrire("frontiere@exemple.org")
        oid = nouvel_id()
        pousser_un(service, inscrit, oid, 0)
        pousser_un(service, inscrit, oid, 1)
        pid = nouvel_id()
        r = service.client.put(
            f"/api/v1/pieces/{pid}",
            content=blob_piece(inscrit, pid),
            headers={**inscrit.bearer, "Content-Type": "application/octet-stream"},
        )
        assert r.status_code == 201, r.text
        r = service.client.request(
            "DELETE",
            f"/api/v1/pieces/{pid}",
            json={"asOfSeq": server_seq(service, inscrit)},
            headers=inscrit.bearer,
        )
        assert r.status_code == 204, r.text
        service.horloge.avancer(30 * JOUR_MS)
        pousser_un(service, inscrit, nouvel_id(), 0)
        r = service.get(f"/sync/previous/{oid}", headers=inscrit.bearer)
        assert r.status_code == 200, "la précédente, au 30e jour après une poussée"
        r = service.get(f"/pieces/{pid}", headers=inscrit.bearer)
        assert r.status_code == 200, "l'orpheline, au 30e jour après une poussée"

    def test_un_objet_sans_precedente_rend_404(self, service):
        """§3.4 — ``GET /sync/previous`` sur un objet jamais remplacé."""
        inscrit = service.inscrire("sansprec@exemple.org")
        oid = nouvel_id()
        pousser_un(service, inscrit, oid, 0)
        r = service.get(f"/sync/previous/{oid}", headers=inscrit.bearer)
        assert r.status_code == 404, r.text


# ----------------------------------------------------------------------
# meta
# ----------------------------------------------------------------------


class TestMeta:
    def test_meta_est_present_sur_chaque_reponse_de_sync(self, service):
        """§3.4 — ``meta`` rend visibles, sans appel de plus, une rotation
        faite ailleurs, une réinitialisation en attente et un retour arrière.
        Une seule réponse sans lui, et l'appareil passe à côté."""
        inscrit = service.inscrire("meta@exemple.org")
        oid = nouvel_id()
        pousser_un(service, inscrit, oid, 0)
        pousser_un(service, inscrit, oid, 1)
        reponses = {
            "changes": tirer(service, inscrit),
            "push": pousser(
                service, inscrit, [element(oid, 2, blob_objet(inscrit, oid, 3))]
            ),
            "previous": service.get(f"/sync/previous/{oid}", headers=inscrit.bearer),
            "previous 404": service.get(
                f"/sync/previous/{nouvel_id()}", headers=inscrit.bearer
            ),
            "push 409": pousser(service, inscrit, [], key_epoch=9),
        }
        generation = service.get("/health").json()["generation"]
        for nom, r in reponses.items():
            assert set(r.json().get("meta", {})) == CLES_META, f"meta dans {nom}"
            assert r.json()["meta"]["generation"] == generation, nom

    def test_meta_accompagne_aussi_les_refus_rendus_apres_la_session(
        self, service, monkeypatch
    ):
        """§3.4 — ``meta`` sur CHAQUE réponse de ``/sync/*`` une fois la
        session établie : jusqu'au 24/09/2026, un 507 ``serverFull``, un 413
        ou un 422 n'en portaient pas, parce qu'ils étaient levés avant la
        transaction. Seuls le 401 (pas de compte à décrire) et le 503
        ``serverBusy`` (qui ne doit pas attendre la base) s'en passent."""
        inscrit = service.inscrire("metarefus@exemple.org")
        oid = nouvel_id()
        monkeypatch.setattr(routes_synchro, "POUSSEE_OCTETS_MAX", 1000)
        reponses = {
            "push 413": pousser(
                service, inscrit, [element(oid, 0, blob_objet(inscrit, oid, 1))]
            ),
            "push 422": service.client.post(
                "/api/v1/sync/push", json={"items": []}, headers=inscrit.bearer
            ),
            "changes 422": service.get("/sync/changes?limit=0", headers=inscrit.bearer),
            "previous 422": service.get(
                "/sync/previous/pas-un-id", headers=inscrit.bearer
            ),
        }
        service.ctx.configuration = dataclasses.replace(
            service.ctx.configuration, garde_base_octets=1
        )
        reponses["push 507"] = pousser(service, inscrit, [])
        attendus = {
            "push 413": 413,
            "push 422": 422,
            "changes 422": 422,
            "previous 422": 422,
            "push 507": 507,
        }
        for nom, r in reponses.items():
            assert r.status_code == attendus[nom], f"{nom} : {r.text}"
            assert set(r.json().get("meta", {})) == CLES_META, f"meta dans {nom}"
        r = service.get("/sync/changes")
        assert r.status_code == 401 and "meta" not in r.json(), "401 : aucun compte"

    def test_le_meta_d_une_poussee_est_celui_d_apres_l_ecriture(self, service):
        """§3.4 — ``meta.serverSeq`` d'une poussée qui a stocké égale le
        ``seq`` qu'elle vient de rendre. Un ``meta`` lu avant l'écriture
        ferait croire à l'appareil que le serveur est en retard sur lui."""
        inscrit = service.inscrire("metafrais@exemple.org")
        ids = [nouvel_id(), nouvel_id()]
        r = pousser(
            service,
            inscrit,
            [element(oid, 0, blob_objet(inscrit, oid, 1)) for oid in ids],
        )
        dernier = r.json()["results"][-1]
        assert dernier["status"] == "stored", r.text
        assert r.json()["meta"]["serverSeq"] == dernier["seq"], (
            "meta décrit le compte APRÈS la poussée"
        )

    def test_meta_porte_la_reinitialisation_en_attente(self, service):
        """§3.6 — ``pendingResetAt`` dans ``meta`` : c'est l'appareil connecté
        qui affiche le bandeau et peut annuler, pas le courriel (A3)."""
        inscrit = service.inscrire("attente@exemple.org")
        with service.ctx.base.transaction() as conn:
            jetons.enregistrer_code(
                conn,
                service.secrets,
                service.secrets.index_courriel(inscrit.email),
                "reinitialisation",
                "515151",
                service.horloge(),
            )
        r = service.post("/reset/confirm", {"email": inscrit.email, "code": "515151"})
        effectif = r.json()["effectiveAt"]
        assert tirer(service, inscrit).json()["meta"]["pendingResetAt"] == effectif


# ----------------------------------------------------------------------
# Quotas et gardes
# ----------------------------------------------------------------------


class TestQuotas:
    def test_le_quota_d_octets_refuse_par_element(self, service):
        """§3.5 (D10) — 256 Mio par compte. Un refus par élément, pas du lot :
        le reste passe, et l'état ``quotaExceeded`` s'affiche (§4.11)."""
        inscrit = service.inscrire("quota@exemple.org")
        with service.ctx.base.transaction() as conn:
            conn.execute(
                "UPDATE comptes SET quota_octets = 2500 WHERE id = ?",
                (inscrit.account_id,),
            )
        a, b, c = nouvel_id(), nouvel_id(), nouvel_id()
        r = pousser(
            service,
            inscrit,
            [element(x, 0, blob_objet(inscrit, x, 1)) for x in (a, b, c)],
        )
        assert [x["status"] for x in r.json()["results"]] == [
            "stored",
            "stored",
            "rejected",
        ], "le troisième dépasse 2 500 o"
        assert r.json()["results"][2]["code"] == "quotaExceeded"
        plus_gros = blob_objet(inscrit, a, 2, clair=b"x" * 2000)
        r = pousser(service, inscrit, [element(a, 1, plus_gros)])
        assert r.json()["results"] == [
            {"status": "rejected", "code": "quotaExceeded"}
        ], "remplacer par plus gros fait grossir le compte : refusé"

    def test_au_quota_une_tombale_passe_et_libere_la_place(self, service):
        """§3.5, §4.6 — au quota, une suppression était REFUSÉE : la tombale
        remplaçait 200 Kio par 1 Kio, mais les 200 Kio restaient comptés 30
        jours comme version précédente, et le compte « grossissait » de
        1 Kio. La suppression ne se synchronisait pas, et l'état
        ``quotaExceeded`` (§4.11) ne se levait qu'un mois plus tard
        (24/09/2026). Une écriture qui ne fait pas grossir la version
        courante passe toujours ; la précédente reste gardée 30 jours."""
        inscrit = service.inscrire("tombale@exemple.org")
        oid = nouvel_id()
        gros = blob_objet(inscrit, oid, 1, clair=os.urandom(200 * 1024))
        r = pousser(service, inscrit, [element(oid, 0, gros)])
        assert r.json()["results"][0]["status"] == "stored", r.text
        occupes = octets_du_compte(service, inscrit)
        with service.ctx.base.transaction() as conn:
            conn.execute(
                "UPDATE comptes SET quota_octets = ? WHERE id = ?",
                (occupes + 500, inscrit.account_id),
            )
        tombale = blob_objet(inscrit, oid, 2, clair=b'{"v":1,"deleted":true}')
        r = pousser(service, inscrit, [element(oid, 1, tombale)])
        assert r.json()["results"][0]["status"] == "stored", (
            f"la tombale passe au quota : {r.json()['results']}"
        )
        assert octets_du_compte(service, inscrit) == len(gros) + len(tombale), (
            "la précédente reste comptée, au-delà du quota"
        )
        r = service.get(f"/sync/previous/{oid}", headers=inscrit.bearer)
        assert _octets(r.json()["blob"]) == gros, "et reste relisible 30 jours"
        autre = nouvel_id()
        issue = pousser_un(service, inscrit, autre, 0)
        assert issue == {"status": "rejected", "code": "quotaExceeded"}, (
            "au-delà du quota, rien ne grossit"
        )
        service.horloge.avancer(31 * JOUR_MS)
        r = pousser(service, inscrit, [element(oid, 2, blob_objet(inscrit, oid, 3))])
        assert r.json()["results"][0]["status"] == "stored", r.text
        assert octets_du_compte(service, inscrit) == len(tombale) + 1090, (
            "la purge rend la place des 200 Kio"
        )
        assert pousser_un(service, inscrit, autre, 0)["status"] == "stored", (
            "le compte est revenu sous son quota"
        )

    def test_le_nombre_d_objets_est_borne(self, service, monkeypatch):
        """§3.5 — 50 000 objets par compte ; remplacer un objet existant ne
        compte pas comme un objet de plus."""
        monkeypatch.setattr(routes_synchro, "OBJETS_MAX", 2)
        inscrit = service.inscrire("nombre@exemple.org")
        a = nouvel_id()
        pousser_un(service, inscrit, a, 0)
        pousser_un(service, inscrit, nouvel_id(), 0)
        assert pousser_un(service, inscrit, nouvel_id(), 0) == {
            "status": "rejected",
            "code": "quotaExceeded",
        }, "le troisième objet"
        assert pousser_un(service, inscrit, a, 1)["status"] == "stored", (
            "remplacer un objet existant passe"
        )

    def test_la_garde_des_20_go_libres_refuse_la_poussee_en_507(self, fabrique):
        """§3.5 (D10) — Flashprime tourne sur le même disque : moins de
        20 Go libres, et toute écriture qui fait grossir la base est refusée.
        La lecture, elle, continue."""
        libre = {"octets": 100 * 10**9}
        service = fabrique(espace_libre=lambda _chemin: libre["octets"])
        inscrit = service.inscrire("disque@exemple.org")
        oid = nouvel_id()
        pousser_un(service, inscrit, oid, 0)
        libre["octets"] = 19 * 10**9
        r = pousser(service, inscrit, [element(oid, 1, blob_objet(inscrit, oid, 2))])
        assert r.status_code == 507, r.text
        assert r.json()["error"] == {"code": "serverFull"}
        assert tirer(service, inscrit).status_code == 200, "le tirage continue"

    def test_la_garde_de_2_go_de_la_base_refuse_la_poussee_en_507(self, service):
        """§3.5 (D10) — ``comptes.db`` au-delà de sa garde : 507 aussi."""
        inscrit = service.inscrire("base@exemple.org")
        service.ctx.configuration = dataclasses.replace(
            service.ctx.configuration, garde_base_octets=1
        )
        r = pousser(service, inscrit, [])
        assert r.status_code == 507, r.text
        assert r.json()["error"] == {"code": "serverFull"}

    def test_au_dela_de_quatre_requetes_lourdes_le_service_repond_503(self, service):
        """§3.1 — quarante poussées de 12 Mio à la fois dépassaient le
        ``MemoryMax=300M`` du service. Le cinquième passage lourd reçoit
        503 ``serverBusy`` aussitôt, sans occuper un fil à attendre."""
        inscrit = service.inscrire("occupe@exemple.org")
        pris = 0
        while service.ctx.portillon.entrer():
            pris += 1
        oid = nouvel_id()
        try:
            assert pris == 4, "quatre passages"
            r = tirer(service, inscrit)
            assert r.status_code == 503, r.text
            assert r.json()["error"] == {"code": "serverBusy", "retryAfterS": 5}
            assert r.headers["retry-after"] == "5"
            assert service.get("/health").status_code == 200, "/health passe"
            for nom, r in (
                (
                    "push",
                    pousser(
                        service, inscrit, [element(oid, 0, blob_objet(inscrit, oid, 1))]
                    ),
                ),
                (
                    "previous",
                    service.get(f"/sync/previous/{oid}", headers=inscrit.bearer),
                ),
            ):
                assert r.status_code == 503, nom
                assert r.json()["error"]["code"] == "serverBusy", nom
        finally:
            for _ in range(pris):
                service.ctx.portillon.sortir()
        assert tirer(service, inscrit).status_code == 200, "les passages sont rendus"

    def test_un_appel_sans_session_ne_prend_aucun_passage(self, service):
        """§3.1 — le portillon était pris AVANT la session : pendant qu'une
        poussée de 8 Mio tenait la base, quatre appels munis d'un faux jeton
        prenaient les quatre passages en attendant le verrou, et le titulaire
        recevait 503 ``serverBusy`` (24/09/2026). La session d'abord."""
        inscrit = service.inscrire("fauxjeton@exemple.org")
        faux = {"Authorization": "Bearer dps1_" + "A" * 43}
        statuts: list[int] = []
        libres = 0
        with service.ctx.base.transaction():
            fils = [
                threading.Thread(
                    target=lambda ip=ip: statuts.append(
                        service.depuis(ip)
                        .get("/api/v1/sync/changes", headers=faux)
                        .status_code
                    )
                )
                for ip in ("198.51.100.7", "198.51.100.8", "203.0.113.7", "203.0.113.8")
            ]
            for f in fils:
                f.start()
            # Le temps qu'ils atteignent le verrou de la base, qu'ils
            # attendent tant que cette transaction le tient.
            threading.Event().wait(0.5)
            while service.ctx.portillon.entrer():
                libres += 1
            for _ in range(libres):
                service.ctx.portillon.sortir()
        for f in fils:
            f.join(10)
        assert statuts == [401] * 4, statuts
        assert libres == 4, f"les faux jetons tenaient {4 - libres} passage(s)"
        assert tirer(service, inscrit).status_code == 200, "le titulaire passe"


# ----------------------------------------------------------------------
# globalSeq, cloisonnement, canari
# ----------------------------------------------------------------------


class TestGlobalSeqEtCloisons:
    def test_global_seq_est_monotone(self, service):
        """§3.10 — ``globalSeq`` révèle un retour arrière de toute la machine
        parce qu'il ne recule JAMAIS ; il avance à chaque écriture, pas à
        une lecture ni à un lot entièrement refusé."""
        inscrit = service.inscrire("global@exemple.org")
        oid = nouvel_id()
        vus = [_health_seq(service)]
        pousser_un(service, inscrit, oid, 0)
        vus.append(_health_seq(service))
        tirer(service, inscrit)
        vus.append(_health_seq(service))
        assert vus[2] == vus[1], "un tirage n'écrit rien"
        pousser(service, inscrit, [element(oid, 0, blob_objet(inscrit, oid, 1))])
        vus.append(_health_seq(service))
        assert vus[3] == vus[2], "un lot tout en conflit n'écrit rien"
        pousser_un(service, inscrit, oid, 1)
        vus.append(_health_seq(service))
        assert vus[4] > vus[3], "une écriture avance globalSeq"
        assert vus == sorted(vus), f"jamais de recul : {vus}"

    def test_aucun_acces_a_un_autre_compte(self, service):
        """§3.4 — chaque requête se limite au compte de la session. Un
        ``objectId`` connu d'un autre compte ne donne ni son blob, ni sa
        version précédente, ni un conflit qui la montrerait."""
        alice = service.inscrire("alice@exemple.org")
        bob = service.inscrire("bob@exemple.org")
        oid = nouvel_id()
        pousser_un(service, alice, oid, 0)
        pousser_un(service, alice, oid, 1)
        assert tirer(service, bob).json()["items"] == [], "Bob ne tire rien d'Alice"
        r = service.get(f"/sync/previous/{oid}", headers=bob.bearer)
        assert r.status_code == 404, "ni sa version précédente"
        blob_bob = blob_objet(bob, oid, 1)
        r = pousser(service, bob, [element(oid, 0, blob_bob)])
        issue = r.json()["results"][0]
        assert issue["status"] == "stored" and issue["rev"] == 1, (
            "le même objectId chez Bob est un autre objet, sans conflit"
        )
        page = tirer(service, bob).json()
        assert [_octets(i["blob"]) for i in page["items"]] == [blob_bob], (
            "Bob tire SON blob, pas celui d'Alice"
        )
        r = pousser(service, bob, [element(oid, 0, blob_objet(bob, oid, 1))])
        conflit = r.json()["results"][0]
        assert conflit["status"] == "conflict", r.text
        assert _octets(conflit["current"]["blob"]) == blob_bob, (
            "le conflit montre la version de Bob, jamais celle d'Alice"
        )
        page = tirer(service, alice).json()
        assert [i["rev"] for i in page["items"]] == [2], "l'objet d'Alice est intact"

    def test_le_serveur_ne_garde_aucun_clair(self, service):
        """§4.12 (canari) — un titre unique poussé depuis le vrai client est
        introuvable dans les octets de ``comptes.db`` et du journal."""
        inscrit = service.inscrire("canari@exemple.org")
        oid = nouvel_id()
        canari = b"canari-" + os.urandom(8).hex().encode()
        clair = b'{"v":1,"data":{"title":"' + canari + b'"}}'
        blob = blob_objet(inscrit, oid, 1, clair=clair)
        r = pousser(service, inscrit, [element(oid, 0, blob)])
        assert r.json()["results"][0]["status"] == "stored"
        assert canari not in service.octets_sur_disque(), "rien en clair dans la base"
        journal = service.configuration.chemin_journal
        assert canari not in journal.read_bytes(), "rien en clair dans le journal"
