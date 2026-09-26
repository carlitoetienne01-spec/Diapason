"""Les pièces : les images d'une conversation, détachées et chiffrées à part.

Conception : ``docs/development/compte-chiffre.md`` §4.7, §2.6 et l'étape 11
du §6.

Chaque « appareil » est un vrai ``ServiceCompte``, un vrai
``ConversationsStore`` sur disque et un vrai ``MoteurSynchro`` ; le VPS est
le service ``diapason_comptes`` derrière un ``httpx.MockTransport``
(``tests/compte/_banc.py``). Aucun octet ne quitte la machine.

Les images sont de vraies chaînes ``data:`` telles que ``FileReader`` les
rend, et les comparaisons se font sur la chaîne entière : « à l'octet
près » veut dire que l'autre appareil lit EXACTEMENT ce que la vue a écrit.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

pytest.importorskip("fastapi", reason="diapason[server] not installed")

from diapason.compte import cles  # noqa: E402
from diapason.compte import pieces as module_pieces  # noqa: E402
from diapason.compte.collections.conversations import (  # noqa: E402
    CollectionConversations,
)
from diapason.compte.enveloppe import sceller_piece  # noqa: E402
from diapason.compte.service import ServiceCompte  # noqa: E402
from diapason.compte.synchro import MoteurSynchro, _Registre  # noqa: E402
from diapason.compte.transport import (  # noqa: E402
    ServeurInjoignable,
    SortieRefusee,
    Transport,
)
from diapason.core import local_mode  # noqa: E402
from diapason.server import conversations_store as module_magasin  # noqa: E402
from diapason.server.conversations_store import ConversationsStore  # noqa: E402
from diapason_comptes.base import ecriture  # noqa: E402
from diapason_comptes.routes_synchro import avancer_seq  # noqa: E402
from tests.compte._banc import (  # noqa: E402
    EMAIL,
    MDP,
    MDP_2,
    Vps,
    appareil,
    argon_rapide,
    inscrire,
    reponse_json,
)
from tests.diapason_comptes._outils import JOUR_MS  # noqa: E402

EMAIL_2 = "autre-compte@exemple.test"
MODELE = "qwen3.5:9b"


# ----------------------------------------------------------------------
# Le banc
# ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _argon(monkeypatch):
    argon_rapide(monkeypatch)


@pytest.fixture
def vps(tmp_path):
    serveur = Vps(tmp_path / "vps")
    yield serveur
    serveur.fermer()


@pytest.fixture(autouse=True)
def _horloge_des_magasins(monkeypatch, vps):
    """Les magasins datent sur l'horloge du VPS : un jour, trente et un
    jours se franchissent en une ligne."""
    monkeypatch.setattr(module_magasin, "_now_ms", vps.horloge)


@dataclass
class Poste:
    service: ServiceCompte
    magasin: ConversationsStore
    moteur: MoteurSynchro

    def cycle(self) -> str:
        return self.moteur.cycle()

    def vivantes(self) -> dict[str, dict]:
        vivantes, _tombales, _seq = self.magasin.list()
        return {c["id"]: c for c in vivantes}

    def statut(self) -> dict:
        return self.service.statut()["sync"]

    def registre(self) -> _Registre:
        ouverture = self.service.serrure.exiger()
        return _Registre(self.service.etat, ouverture.account_id, ouverture.incarnation)


@pytest.fixture
def poste(tmp_path, vps):
    crees: list[Poste] = []

    def construire(nom: str) -> Poste:
        dossier = tmp_path / nom
        dossier.mkdir(parents=True, exist_ok=True)
        magasin = ConversationsStore(dossier / "conversations.db")
        service = appareil(vps, dossier, nom=f"Appareil {nom}")
        moteur = MoteurSynchro(
            service, [CollectionConversations(magasin)], horloge_ms=vps.horloge
        )
        service.moteur = moteur
        moteur.brancher(magasin, lambda **_k: None)
        construit = Poste(service, magasin, moteur)
        crees.append(construit)
        return construit

    yield construire
    for p in crees:
        p.service.fermer()
        p.magasin.close()


def _inscrit(poste, vps, nom: str = "a", email: str = EMAIL) -> Poste:
    p = poste(nom)
    inscrire(p.service, vps, email)
    p.service.consentir()
    return p


def _connecte(poste, nom: str = "b") -> Poste:
    p = poste(nom)
    p.service.connecter(EMAIL, MDP, False)
    p.service.consentir()
    return p


def _image(taille: int = 30_000) -> str:
    """Une vraie image PNG en ``data:``, comme ``FileReader`` la rend."""
    octets = b"\x89PNG\r\n\x1a\n" + os.urandom(taille)
    return "data:image/png;base64," + base64.b64encode(octets).decode("ascii")


def _fixes(taille: int) -> bytes:
    """Des octets d'image FIXES : pytest-xdist exige que chaque processus
    collecte les mêmes paramètres."""
    return hashlib.shake_256(b"diapason/test/pieces").digest(taille)


def _octets_de(image: str) -> bytes:
    return base64.b64decode(image.partition(",")[2])


def message(ident: str, contenu: str, ts: int, **autres: Any) -> dict:
    return {"id": ident, "role": "user", "content": contenu, "timestamp": ts, **autres}


def conversation(ident: str, messages: list[dict], maj: int, cree: int) -> dict:
    return {
        "id": ident,
        "title": f"Fil {ident}",
        "createdAt": cree,
        "updatedAt": maj,
        "model": MODELE,
        "pinned": False,
        "messages": messages,
    }


def _pieces_vps(vps: Vps) -> dict[str, tuple[bytes, int | None]]:
    with vps.ctx.base.lecture() as conn:
        return {
            p: (bytes(b), o)
            for p, b, o in conn.execute(
                "SELECT piece_id, blob, orpheline_jour FROM pieces"
            ).fetchall()
        }


def _objets_vps(vps: Vps) -> list[bytes]:
    with vps.ctx.base.lecture() as conn:
        return [bytes(b) for (b,) in conn.execute("SELECT blob FROM objets")]


def _requetes(vps: Vps, prefixe: str) -> list[str]:
    return [
        f"{r.methode} {r.chemin}"
        for r in vps.requetes
        if f"{r.methode} {r.chemin}".startswith(prefixe)
    ]


def _clair_serveur(p: Poste, vps: Vps, id_local: str) -> dict:
    """La version que le VPS tient, ouverte par CET appareil, SANS rattacher
    ses pièces : c'est ce que tout autre appareil tirera."""
    ouverture = p.service.serrure.exiger()
    object_id = ouverture.trousseau.identifiant_objet("conversations", id_local)
    with vps.ctx.base.lecture() as conn:
        rev, blob = conn.execute(
            "SELECT rev, blob FROM objets WHERE objet_id = ?", (object_id,)
        ).fetchone()
    return ouverture.trousseau.ouvrir_objet(
        bytes(blob),
        account_id=ouverture.account_id,
        incarnation=ouverture.incarnation,
        object_id=object_id,
        rev=rev,
    )


def _purger_sur_le_vps(vps: Vps, piece_id: str) -> None:
    """Ce que fait la purge à +30 jours d'une orpheline (§3.4)."""
    with vps.ctx.base.transaction() as conn:
        conn.execute("DELETE FROM pieces WHERE piece_id = ?", (piece_id,))


def _reclame_seq(vps: Vps, piece_id: str) -> int:
    with vps.ctx.base.lecture() as conn:
        (seq,) = conn.execute(
            "SELECT reclame_seq FROM pieces WHERE piece_id = ?", (piece_id,)
        ).fetchone()
    return seq


def _rejouer_la_precedente(vps: Vps, object_id: str) -> None:
    """Le VPS remet en tête la version d'avant, avec sa vraie ``rev`` et un
    ``seq`` neuf — ce que root sur la machine peut faire (§4.12)."""
    with vps.ctx.base.transaction() as conn:
        compte_id, rev, blob = conn.execute(
            "SELECT compte_id, rev_precedente, blob_precedent FROM objets"
            " WHERE objet_id = ?",
            (object_id,),
        ).fetchone()
        conn.execute(
            "UPDATE objets SET rev = ?, seq = ?, blob = ? WHERE objet_id = ?",
            (rev, avancer_seq(conn, compte_id), blob, object_id),
        )
        ecriture(conn)


def _refuser_les_depots(statut: int, code: str):
    """Un VPS qui refuse tout ``PUT /pieces/{id}`` avec ce statut."""

    def refuser(requete, _reponse):
        if requete.methode == "PUT" and requete.chemin.startswith("/api/v1/pieces/"):
            return reponse_json(statut, {"error": {"code": code}})
        return None

    return refuser


# ----------------------------------------------------------------------
# Le clair d'une pièce (§4.7)
# ----------------------------------------------------------------------


class TestFormeDUnePiece:
    @pytest.mark.parametrize(
        "image",
        [
            "data:image/png;base64,"
            + base64.b64encode(b"\x89PNG\r\n\x1a\n" + _fixes(2_000)).decode(),
            # base64 coupé de retours à la ligne : le ré-encodage ne le redonne
            # pas, la chaîne voyage entière.
            "data:image/png;base64,"
            + base64.encodebytes(b"\x89PNG\r\n\x1a\n" + _fixes(300)).decode(),
            # sans remplissage
            "data:image/gif;base64,"
            + base64.b64encode(b"GIF89a" + _fixes(31)).decode().rstrip("="),
            'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg">é</svg>',
            "data:,",
        ],
        ids=["compacte", "lignes", "sans-remplissage", "svg", "vide"],
    )
    def test_une_image_se_reconstruit_a_l_octet_pres(self, image):
        """§4.7 : décoder, puis vérifier que le ré-encodage redonne EXACTEMENT
        la chaîne ; sinon la chaîne entière. Échec évité : un décodage
        tolérant suivi d'un ré-encodage canonique rendait à l'autre appareil
        une image « égale » mais pas la même chaîne."""
        clair = module_pieces.emballer(image)
        assert module_pieces.deballer(clair) == image, (
            "la chaîne doit revenir telle quelle"
        )

    def test_la_forme_compacte_porte_les_octets_et_non_le_base64(self):
        """Échec évité : chiffrer le base64 coûtait un tiers de plus à chaque
        pièce, sur le quota et sur le fil."""
        image = _image(30_000)
        clair = module_pieces.emballer(image)
        assert _octets_de(image) in clair, "la charge est l'image décodée"
        assert len(clair) < len(image) * 0.8

    @pytest.mark.parametrize(
        "clair",
        [
            b"",
            b"\x00\x00\x00\x40{}",
            b"\x00\x00\x00\x02{}charge",
            b'\x00\x00\x00\x0f{"form":"brut"}data:',
            b'\x00\x00\x00\x0e{"form":"raw"}pas une image',
            b'\x00\x00\x00\x1c{"header":"http://x;base64,"}ab',
            b'\x00\x00\x00\x1d{"form":"raw","form":"raw"}data:',
        ],
        ids=["vide", "entete-hors", "entete-vide", "forme", "brute", "http", "double"],
    )
    def test_un_clair_de_piece_mal_forme_est_refuse(self, clair):
        """Échec évité : une pièce forgée par un porteur d'une ancienne DEK
        (§2.11 bis) qui entrait dans le magasin sous une forme que la vue ne
        sait pas afficher."""
        with pytest.raises(module_pieces.PieceIllisible):
            module_pieces.deballer(clair)


# ----------------------------------------------------------------------
# Réintégration
# ----------------------------------------------------------------------


class TestReintegration:
    def test_une_conversation_illustree_revient_a_l_octet_pres(self, poste, vps):
        """§4.7 : l'image devient ``"diapason-piece:<id>"`` dans l'objet et
        revient à l'identique sur l'autre appareil. Échec évité : une image
        qui repartait DANS l'objet à chaque poussée (1,57 Mo pour quelques
        mots), ou qui revenait différente de celle qu'on avait jointe."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        compacte = _image(60_000)
        brute = "data:image/png;base64," + base64.encodebytes(
            b"\x89PNG\r\n\x1a\n" + os.urandom(900)
        ).decode("ascii")
        m1 = message("m1", "Regarde", t, images=[compacte, brute])
        m2 = message("m2", "Et celle-ci", t + 1, images=[_image(5_000)])
        a.magasin.upsert(conversation("x", [m1, m2], t + 1, t))
        assert a.cycle() == "upToDate"

        assert len(_pieces_vps(vps)) == 3, "une pièce par image"
        (objet,) = _objets_vps(vps)
        assert len(objet) < 4096, f"l'objet ne porte plus les images : {len(objet)} o"
        serveur = _clair_serveur(a, vps, "x")
        references = serveur["data"]["messages"][0]["images"]
        assert all(r.startswith("diapason-piece:") for r in references)

        b = _connecte(poste)
        assert b.cycle() == "upToDate"
        assert b.vivantes()["x"] == a.vivantes()["x"], (
            "B doit lire exactement la conversation de A, images comprises"
        )
        assert b.vivantes()["x"]["messages"][0]["images"] == [compacte, brute]

    def test_l_echo_d_une_poussee_ne_telecharge_ni_ne_repousse_rien(
        self, poste, vps, monkeypatch
    ):
        """Échec évité : empreinter la forme reçue du serveur sans rattacher
        ses pièces — chaque tirage d'une conversation illustrée la voyait
        différente de la copie locale et la repoussait, pièces comprises.

        L'ingestion est ESPIONNÉE (24/09/2026) : une première passe qui
        empreintait la forme détachée faisait réingérer l'écho sans un octet
        de réseau, et le test restait vert."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[_image()])], t, t)
        )
        assert a.cycle() == "upToDate"
        b = _connecte(poste)
        assert b.cycle() == "upToDate"
        ingerees: list[str] = []
        for p in (a, b):
            collection = p.moteur._collections["conversations"]  # noqa: SLF001
            ingerer = collection.ingerer

            def espion(clair, ingerer=ingerer):
                ingerees.append(clair["id"])
                return ingerer(clair)

            monkeypatch.setattr(collection, "ingerer", espion)
        avant = len(vps.requetes)
        for p in (a, b, a, b):
            assert p.cycle() == "upToDate"
        nouvelles = [f"{r.methode} {r.chemin}" for r in vps.requetes[avant:]]
        assert not [r for r in nouvelles if "/pieces/" in r], (
            f"aucune pièce ne voyage sans écriture : {nouvelles}"
        )
        assert not [r for r in nouvelles if r.endswith("/sync/push")], (
            "aucune poussée sans écriture"
        )
        assert ingerees == [], f"l'écho n'est pas réingéré : {ingerees}"

    def test_une_vieille_version_rejouee_ne_telecharge_pas_ses_pieces(self, poste, vps):
        """§4.7, §4.12 : la première passe ne lit que les images déjà ici ;
        une version sous ``rev_max`` est réaffirmée sans que ses pièces
        soient demandées. Échec évité : un VPS qui rejoue une vieille
        version illustrée fait télécharger des images que l'appareil va de
        toute façon écraser."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[_image()])], t, t)
        )
        assert a.cycle() == "upToDate"
        vps.horloge.avancer(1000)
        a.magasin.delete("x")
        assert a.cycle() == "upToDate"
        id_x = a.service.serrure.exiger().trousseau.identifiant_objet(
            "conversations", "x"
        )
        _rejouer_la_precedente(vps, id_x)
        avant = len(vps.requetes)
        assert a.cycle() == "upToDate"
        nouvelles = [f"{r.methode} {r.chemin}" for r in vps.requetes[avant:]]
        assert not [r for r in nouvelles if r.startswith("GET /api/v1/pieces/")], (
            f"la vieille version ne fait rien télécharger : {nouvelles}"
        )
        assert "POST /api/v1/sync/push" in nouvelles, "elle est réaffirmée"
        assert "deleted" in _clair_serveur(a, vps, "x"), (
            "le serveur retient de nouveau la suppression"
        )


# ----------------------------------------------------------------------
# Ordre : la pièce avant l'objet
# ----------------------------------------------------------------------


class TestPieceAvantObjet:
    def test_un_objet_n_est_jamais_pousse_avant_sa_piece(self, poste, vps):
        """§4.3, étape 4 : « pièces d'abord ». Échec évité : un objet rangé
        sur le VPS pendant que le dépôt de son image échoue — tout appareil
        qui le tirait entre-temps le gardait sans image."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[_image()])], t, t)
        )

        def depot_en_panne(requete, _reponse):
            if requete.methode == "PUT" and requete.chemin.startswith(
                "/api/v1/pieces/"
            ):
                return reponse_json(503, {"error": {"code": "serverBusy"}})
            return None

        vps.falsifier = depot_en_panne
        assert a.cycle() != "upToDate", "un dépôt en échec ne se dit pas synchronisé"
        vps.falsifier = None
        assert _requetes(vps, "PUT /api/v1/pieces/"), "le dépôt a été tenté"
        assert not _requetes(vps, "POST /api/v1/sync/push"), (
            "l'objet ne part pas tant que sa pièce n'est pas déposée"
        )
        assert _objets_vps(vps) == []

        a.moteur._repli_jusqu_a = 0.0  # noqa: SLF001 - le repli n'est pas l'objet
        assert a.cycle() == "upToDate"
        chemins = [f"{r.methode} {r.chemin}" for r in vps.requetes]
        dernier_depot = max(
            i for i, c in enumerate(chemins) if c.startswith("PUT /api/v1/pieces/")
        )
        poussee = chemins.index("POST /api/v1/sync/push")
        assert dernier_depot < poussee, "la pièce est déposée avant l'objet"
        assert len(_pieces_vps(vps)) == 1


# ----------------------------------------------------------------------
# Dégradé (pièce en 404)
# ----------------------------------------------------------------------


class TestDegrade:
    def test_un_objet_degrade_n_efface_pas_l_image_du_serveur(self, poste, vps):
        """§4.7 : une pièce en 404 laisse l'objet appliqué SANS elle ;
        l'appareil dégradé pousse ensuite sans jamais effacer l'image, et la
        récupère quand l'appareil qui l'a la redépose. Échec évité : la
        première poussée d'un appareil dégradé réécrivait la conversation
        sans son image, pour tous."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        image = _image()
        m1 = message("m1", "Regarde", t, images=[image])
        a.magasin.upsert(conversation("x", [m1], t, t))
        assert a.cycle() == "upToDate"
        ((piece_id, _),) = _pieces_vps(vps).items()
        _purger_sur_le_vps(vps, piece_id)

        b = _connecte(poste)
        assert b.cycle() == "upToDate", "une pièce en 404 n'est jamais reportée"
        recu = b.vivantes()["x"]["messages"][0]
        assert "images" not in recu, "appliquée sans elle, sans référence cassée"
        assert recu["content"] == "Regarde", "le reste du message est là"

        # B écrit dans la conversation dégradée, et pousse.
        m2 = message("m2", "Écrit sur B", t + 5)
        b.magasin.upsert(conversation("x", [recu, m2], t + 5, t))
        assert b.cycle() == "upToDate"
        serveur = _clair_serveur(a, vps, "x")["data"]["messages"]
        assert [m["id"] for m in serveur] == ["m1", "m2"], "la poussée de B est là"
        assert serveur[0]["images"] == [f"diapason-piece:{piece_id}"], (
            "le serveur référence toujours l'image que B n'a pas"
        )

        assert a.cycle() == "upToDate"
        assert a.vivantes()["x"]["messages"][0]["images"] == [image], (
            "A garde son image"
        )

        # Un jour plus tard : A réclame, la retrouve manquante et la redépose ;
        # B la redemande et la retrouve.
        vps.horloge.avancer(JOUR_MS + 60_000)
        assert a.cycle() == "upToDate"
        assert piece_id in _pieces_vps(vps), "A a redéposé la pièce"
        assert b.cycle() == "upToDate"
        assert b.vivantes()["x"]["messages"][0]["images"] == [image], (
            "B retrouve l'image à l'octet près"
        )
        assert b.vivantes()["x"] == a.vivantes()["x"]
        poussees = len(_requetes(vps, "POST /api/v1/sync/push"))
        assert b.cycle() == "upToDate"
        assert a.cycle() == "upToDate"
        assert len(_requetes(vps, "POST /api/v1/sync/push")) == poussees, (
            "la réparation ne repousse rien"
        )

    def test_une_panne_passagere_d_une_piece_ne_dit_pas_synchronise(self, poste, vps):
        """§4.3 : « autre échec transitoire (5xx pièce) → a_reprendre ; le
        curseur AVANCE quand même ». Échec évité : dire « Synchronisé »
        avec une image qui n'est pas arrivée, ou bloquer le tirage sur elle."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        image = _image()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[image])], t, t)
        )
        assert a.cycle() == "upToDate"
        b = _connecte(poste)

        def lecture_en_panne(requete, _reponse):
            if requete.methode == "GET" and requete.chemin.startswith(
                "/api/v1/pieces/"
            ):
                return reponse_json(503, {"error": {"code": "serverBusy"}})
            return None

        vps.falsifier = lecture_en_panne
        assert b.cycle() == "pending", "une image en retard se dit"
        vps.falsifier = None
        assert b.service.etat.lire("curseurDistant") not in (None, "0"), (
            "le curseur a avancé malgré la pièce"
        )
        vps.horloge.avancer(60_000)
        assert b.cycle() == "upToDate"
        assert b.vivantes()["x"]["messages"][0]["images"] == [image]

    def test_un_appareil_degrade_reclame_les_pieces_qu_il_pousse_sans_les_avoir(
        self, poste, vps
    ):
        """§4.3 « pièces d'abord », §4.7 : la réclamation d'avant la poussée
        porte TOUTES les références de l'objet, trous compris. Échec évité :
        un appareil dégradé poussait sa référence sans la réclamer — le
        marquage orphelin concurrent d'un autre appareil, daté d'avant,
        passait, et l'image ne tenait plus qu'à la réclamation quotidienne."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "Regarde", t, images=[_image()])
        a.magasin.upsert(conversation("x", [m1], t, t))
        assert a.cycle() == "upToDate"
        (piece_id,) = _pieces_vps(vps)

        def piece_introuvable(requete, _reponse):
            if requete.methode == "GET" and requete.chemin.startswith(
                "/api/v1/pieces/"
            ):
                return reponse_json(404, {"error": {"code": "notFound"}})
            return None

        b = _connecte(poste)
        vps.falsifier = piece_introuvable
        assert b.cycle() == "upToDate"
        vps.falsifier = None
        recu = b.vivantes()["x"]["messages"][0]
        assert "images" not in recu, "témoin : B est dégradé"

        b.magasin.upsert(
            conversation("x", [recu, message("m2", "Écrit sur B", t + 5)], t + 5, t)
        )
        reclame_avant = _reclame_seq(vps, piece_id)
        avant = len(vps.requetes)
        assert b.cycle() == "upToDate"
        nouvelles = vps.requetes[avant:]
        chemins = [f"{r.methode} {r.chemin}" for r in nouvelles]
        poussee = chemins.index("POST /api/v1/sync/push")
        reclamations = [
            i
            for i, r in enumerate(nouvelles)
            if r.chemin == "/api/v1/pieces/missing" and piece_id in r.json()["pieceIds"]
        ]
        assert reclamations and reclamations[0] < poussee, (
            f"B réclame la pièce qu'il n'a pas avant de la référencer : {chemins}"
        )
        assert not [c for c in chemins if c.startswith("PUT /api/v1/pieces/")], (
            "sans les octets, rien n'est déposé"
        )
        assert _reclame_seq(vps, piece_id) > reclame_avant

    def test_un_objet_connu_apres_ses_trous_se_dit_degrade(self, poste, vps):
        """§4.3 « appliquer SANS la pièce, degrade=1 ». Échec évité : la
        relecture de la version précédente posait les trous AVANT de
        connaître l'objet ; l'``INSERT`` qui suivait écrivait
        ``degrade = 0`` sur un objet troué."""
        a = _inscrit(poste, vps)
        assert a.cycle() == "upToDate"
        registre = a.registre()
        registre.poser_trous(
            "conversations", "x", {"m1": ["diapason-piece:" + "A" * 22]}
        )
        registre.noter_connu(
            "conversations", "x", "objet-x", rev=1, seq=1, empreinte_=None
        )
        registre.noter_connu(
            "conversations", "y", "objet-y", rev=1, seq=2, empreinte_=None
        )
        with registre._base() as conn:  # noqa: SLF001
            degrades = dict(
                conn.execute("SELECT id_local, degrade FROM connus").fetchall()
            )
        assert degrades == {"x": 1, "y": 0}, (
            f"degrade dit la vérité de pieces_manquantes : {degrades}"
        )


# ----------------------------------------------------------------------
# Époques : déduplication, rotation
# ----------------------------------------------------------------------


class TestEpoques:
    def test_deduplication_dans_une_epoque_puis_nouvel_envoi_apres_une_rotation(
        self, poste, vps
    ):
        """§2.6, §4.7 : une même image n'est déposée qu'une fois par époque ;
        après une rotation, la prochaine poussée la renomme et la renvoie
        sous la DEK neuve, et l'ancienne devient orpheline quand plus rien
        ne la référence. Échec évité (§2.2) : ``/pieces/missing`` répondait
        « présente » et l'image restait sous la DEK compromise."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        image = _image()
        mx = message("mx", "x", t, images=[image])
        my = message("my", "y", t, images=[image])
        a.magasin.upsert(conversation("x", [mx], t, t))
        a.magasin.upsert(conversation("y", [my], t, t))
        assert a.cycle() == "upToDate"
        assert len(_requetes(vps, "PUT /api/v1/pieces/")) == 1, (
            "deux conversations, une image : un seul dépôt"
        )
        ((ancienne, (blob, _)),) = _pieces_vps(vps).items()
        assert blob[2:6] == (1).to_bytes(4, "big")

        a.magasin.upsert(
            conversation("x", [mx, message("mx2", "suite", t + 1)], t + 1, t)
        )
        assert a.cycle() == "upToDate"
        assert len(_requetes(vps, "PUT /api/v1/pieces/")) == 1, (
            "repousser la conversation ne redépose pas son image"
        )

        vps.horloge.avancer(61 * 60_000)
        a.service.changer_mot_de_passe(MDP, MDP_2)
        a.magasin.upsert(
            conversation(
                "x",
                [mx, message("mx2", "suite", t + 1), message("mx3", "après", t + 2)],
                t + 2,
                t,
            )
        )
        assert a.cycle() == "upToDate"
        pieces = _pieces_vps(vps)
        assert len(_requetes(vps, "PUT /api/v1/pieces/")) == 2, "renvoyée une fois"
        (neuve,) = set(pieces) - {ancienne}
        assert pieces[neuve][0][2:6] == (2).to_bytes(4, "big"), (
            "la pièce neuve est scellée sous l'époque 2"
        )
        assert pieces[ancienne][1] is None, (
            "« y » référence encore l'ancienne : elle n'est pas orpheline"
        )

        a.magasin.upsert(
            conversation("y", [my, message("my2", "suite", t + 3)], t + 3, t)
        )
        assert a.cycle() == "upToDate"
        assert len(_requetes(vps, "PUT /api/v1/pieces/")) == 2, (
            "dans l'époque 2, l'image de « y » est déjà là"
        )
        pieces = _pieces_vps(vps)
        assert pieces[ancienne][1] is not None, (
            "plus rien ne référence l'ancienne : marquée orpheline"
        )
        assert pieces[neuve][1] is None
        assert _clair_serveur(a, vps, "y")["data"]["messages"][0]["images"] == [
            f"diapason-piece:{neuve}"
        ]

    def test_une_rotation_entre_la_piece_et_l_objet_laisse_l_ancienne_orpheline(
        self, poste, vps
    ):
        """§2.2, §4.7 : une rotation tombe entre le dépôt d'une image et la
        poussée de son objet ; l'objet repart sous l'époque neuve, et la
        pièce déposée sous l'ancienne DEK — que rien ne référence — finit
        orpheline. Échec évité : une image chiffrée sous la clé que la
        rotation voulait retirer, gardée sur le VPS pour toujours, parce
        qu'aucune table de l'appareil ne la nommait."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        vps.horloge.avancer(61 * 60_000)
        rotations: list[threading.Thread] = []

        def rotation_apres_le_depot(requete, _reponse):
            if (
                not rotations
                and requete.methode == "PUT"
                and requete.chemin.startswith("/api/v1/pieces/")
            ):
                fil = threading.Thread(
                    target=a.service.changer_mot_de_passe, args=(MDP, MDP_2)
                )
                rotations.append(fil)
                fil.start()
                fil.join(10)
            return None

        vps.falsifier = rotation_apres_le_depot
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[_image()])], t, t)
        )
        assert a.cycle() == "upToDate"
        vps.falsifier = None
        assert rotations and not rotations[0].is_alive(), "la rotation a eu lieu"
        vps.horloge.avancer(60_000)
        assert a.cycle() == "upToDate"

        pieces = _pieces_vps(vps)
        par_epoque = {
            int.from_bytes(blob[2:6], "big"): (p, orpheline)
            for p, (blob, orpheline) in pieces.items()
        }
        assert set(par_epoque) == {1, 2}, f"une pièce par époque : {par_epoque}"
        neuve, orpheline_neuve = par_epoque[2]
        _ancienne, orpheline_ancienne = par_epoque[1]
        assert orpheline_ancienne is not None, (
            "la pièce de l'ancienne DEK, que rien ne référence, est orpheline"
        )
        assert orpheline_neuve is None
        assert _clair_serveur(a, vps, "x")["data"]["messages"][0]["images"] == [
            f"diapason-piece:{neuve}"
        ]


# ----------------------------------------------------------------------
# Orphelines et réclamation
# ----------------------------------------------------------------------


class TestOrphelines:
    def test_une_conversation_supprimee_libere_ses_pieces(self, poste, vps):
        """§4.7 (témoin de la course) : sans réclamation concurrente, la
        pièce d'une conversation supprimée est marquée orpheline. Échec
        évité : des images supprimées qui occupent le quota pour toujours."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[_image()])], t, t)
        )
        assert a.cycle() == "upToDate"
        vps.horloge.avancer(1000)
        a.magasin.delete("x")
        assert a.cycle() == "upToDate"
        ((_piece, (_blob, orpheline)),) = _pieces_vps(vps).items()
        assert orpheline is not None, "la pièce de la conversation supprimée part"

    def test_une_suppression_le_jour_de_la_reclamation_libere_quand_meme_sa_piece(
        self, poste, vps
    ):
        """§4.7 : le cycle qui pousse la suppression est aussi celui de la
        réclamation quotidienne, qui a réclamé la pièce après ``S`` ; le
        marquage reçoit 409 ``reclaimed`` et la pièce reste candidate pour
        le cycle suivant. Échec évité : un appareil seul l'oubliait sur ce
        409, et l'image occupait le quota pour toujours."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[_image()])], t, t)
        )
        assert a.cycle() == "upToDate"
        (piece_id,) = _pieces_vps(vps)
        vps.horloge.avancer(JOUR_MS + 60_000)
        a.magasin.delete("x")
        assert a.cycle() == "upToDate"
        assert _requetes(vps, f"DELETE /api/v1/pieces/{piece_id}"), (
            "témoin : le marquage a été tenté"
        )
        assert _pieces_vps(vps)[piece_id][1] is None, (
            "témoin : réclamée ce cycle-ci, le marquage est refusé"
        )
        vps.horloge.avancer(60_000)
        assert a.cycle() == "upToDate"
        assert _pieces_vps(vps)[piece_id][1] is not None, (
            "au cycle suivant, la pièce que plus rien ne référence est orpheline"
        )

    def test_une_reclamation_entre_le_tirage_et_la_poussee_fait_refuser_le_marquage(
        self, poste, vps
    ):
        """§4.7, revue protocole : ``asOfSeq`` est le ``until`` du TIRAGE,
        pas le ``serverSeq`` rendu par la poussée. B réclame et pousse entre
        le dernier ``GET /sync/changes`` de A et sa poussée ; le marquage de
        A est refusé. Échec évité : dater le marquage d'après la poussée —
        l'image de B, jamais tirée par A, était marquée puis purgée."""
        a = _inscrit(poste, vps)
        b = _connecte(poste)
        t = vps.horloge()
        image = _image()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[image])], t, t)
        )
        assert a.cycle() == "upToDate"
        assert b.cycle() == "upToDate"
        (piece_id,) = _pieces_vps(vps)
        b.magasin.upsert(
            conversation("y", [message("n", "y", t + 1, images=[image])], t + 1, t)
        )
        vps.horloge.avancer(1000)
        a.magasin.delete("x")
        jeton_a = a.service.jeton_de_session()
        tirages: list[int] = []
        marquages: list[tuple[int, int]] = []

        def b_passe_apres_le_tirage_de_a(requete, reponse):
            de_a = requete.en_tetes.get("authorization") == f"Bearer {jeton_a}"
            if de_a and requete.chemin.startswith("/api/v1/sync/changes"):
                tirages.append(reponse.json()["until"])
                if len(tirages) == 1:
                    assert b.cycle() == "upToDate"
            if de_a and requete.methode == "DELETE" and piece_id in requete.chemin:
                marquages.append((requete.json()["asOfSeq"], reponse.status_code))
            return None

        vps.falsifier = b_passe_apres_le_tirage_de_a
        assert a.cycle() == "upToDate"
        vps.falsifier = None
        assert tirages, "le scénario doit avoir fait passer B pendant A"
        assert marquages, "A a bien tenté de marquer la pièce orpheline"
        assert marquages[-1] == (tirages[-1], 409), (
            f"A marque au nom de son tirage, et le serveur refuse : {marquages}"
        )
        assert _pieces_vps(vps)[piece_id][1] is None
        vps.horloge.avancer(60_000)
        assert a.cycle() == "upToDate"
        assert _pieces_vps(vps)[piece_id][1] is None, (
            "A a tiré « y » depuis : la pièce n'est plus candidate"
        )
        assert a.vivantes()["y"]["messages"][0]["images"] == [image]

    def test_une_course_orpheline_perd_contre_la_reclamation(self, poste, vps):
        """§4.7, revue protocole : A a tiré jusqu'à S et ne voit plus rien
        qui référence la pièce ; pendant ce temps B la réclame pour un objet
        qu'il pousse. Le marquage de A, daté de S, est refusé (409
        ``reclaimed``) et la pièce survit à la purge. Échec évité : l'image
        de B purgée 30 jours plus tard."""
        a = _inscrit(poste, vps)
        b = _connecte(poste)
        t = vps.horloge()
        image = _image()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[image])], t, t)
        )
        assert a.cycle() == "upToDate"
        assert b.cycle() == "upToDate"
        (piece_id,) = _pieces_vps(vps)
        # B joint la même image à une autre conversation, sans avoir encore
        # synchronisé.
        b.magasin.upsert(
            conversation("y", [message("n", "y", t + 1, images=[image])], t + 1, t)
        )
        vps.horloge.avancer(1000)
        a.magasin.delete("x")
        jeton_a = a.service.jeton_de_session()
        declenche: list[bool] = []

        def b_reclame_apres_le_tirage_de_a(requete, _reponse):
            # Entre le tirage de A (serverSeq = S) et son marquage : B pousse
            # « y », et réclame la pièce.
            if (
                not declenche
                and requete.chemin == "/api/v1/sync/push"
                and requete.en_tetes.get("authorization") == f"Bearer {jeton_a}"
            ):
                declenche.append(True)
                assert b.cycle() == "upToDate"
            return None

        vps.falsifier = b_reclame_apres_le_tirage_de_a
        assert a.cycle() == "upToDate"
        vps.falsifier = None
        assert declenche, "le scénario doit avoir fait réclamer B pendant A"
        marquages = [
            r for r in vps.requetes if r.methode == "DELETE" and piece_id in r.chemin
        ]
        assert marquages, "A a bien tenté de marquer la pièce orpheline"
        with vps.ctx.base.lecture() as conn:
            (reclame_seq,) = conn.execute(
                "SELECT reclame_seq FROM pieces WHERE piece_id = ?", (piece_id,)
            ).fetchone()
        assert marquages[-1].json()["asOfSeq"] < reclame_seq, (
            "A marque au nom de son tirage, d'avant la réclamation de B"
        )
        assert _pieces_vps(vps)[piece_id][1] is None, (
            "réclamée après S : le marquage de A est refusé"
        )

        vps.horloge.avancer(31 * JOUR_MS)
        a.magasin.upsert(conversation("z", [message("o", "z", t + 2)], t + 2, t))
        assert a.cycle() == "upToDate"  # une poussée : le VPS purge ses retenues
        assert piece_id in _pieces_vps(vps), "la pièce survit à la purge"
        assert a.vivantes()["y"]["messages"][0]["images"] == [image], (
            "A lit l'image de B"
        )

    def test_la_reclamation_quotidienne_ranime_une_piece_marquee_a_tort(
        self, poste, vps
    ):
        """§4.7, A9 : un jeton volé marque orpheline une pièce encore
        référencée ; chaque appareil réclame, au plus une fois par jour,
        tout ce qu'il référence, et la ranime avant la purge. Échec évité :
        une image effacée 30 jours après un marquage que personne n'a vu."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[_image()])], t, t)
        )
        assert a.cycle() == "upToDate"
        (piece_id,) = _pieces_vps(vps)
        with vps.ctx.base.lecture() as conn:
            seq = conn.execute("SELECT MAX(seq) FROM comptes").fetchone()[0]
        vole = vps.client.request(
            "DELETE",
            f"/api/v1/pieces/{piece_id}",
            headers={"Authorization": f"Bearer {a.service.jeton_de_session()}"},
            json={"asOfSeq": seq},
        )
        assert vole.status_code == 204, vole.text
        assert _pieces_vps(vps)[piece_id][1] is not None

        avant = len(_requetes(vps, "POST /api/v1/pieces/missing"))
        assert a.cycle() == "upToDate"
        assert len(_requetes(vps, "POST /api/v1/pieces/missing")) == avant, (
            "pas deux réclamations le même jour"
        )

        vps.horloge.avancer(JOUR_MS + 60_000)
        assert a.cycle() == "upToDate"
        assert len(_requetes(vps, "POST /api/v1/pieces/missing")) == avant + 1, (
            "une réclamation, le lendemain"
        )
        assert _pieces_vps(vps)[piece_id][1] is None, "la pièce est ranimée"

        vps.horloge.avancer(31 * JOUR_MS)
        a.magasin.upsert(conversation("z", [message("o", "z", t + 2)], t + 2, t))
        assert a.cycle() == "upToDate"
        assert piece_id in _pieces_vps(vps), "la pièce survit à la purge"

    def test_une_reclamation_en_panne_ne_dit_pas_hors_ligne_et_se_retente(
        self, poste, vps
    ):
        """§4.7 : la réclamation est de l'entretien — un 5xx n'y perd rien
        et ne fait pas dire « hors ligne » à un cycle dont la
        synchronisation a abouti ; elle n'est pas datée, et repart au cycle
        suivant. Échec évité : un ``/pieces/missing`` en panne qui rendait
        tout le compte « hors ligne », ou une réclamation datée sans avoir
        eu lieu — un jour de protection perdu."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[_image()])], t, t)
        )
        assert a.cycle() == "upToDate"
        datee = a.service.etat.lire("reclamationPiecesMs")
        vps.horloge.avancer(JOUR_MS + 60_000)

        def reclamation_en_panne(requete, _reponse):
            if requete.chemin == "/api/v1/pieces/missing":
                return reponse_json(503, {"error": {"code": "serverBusy"}})
            return None

        vps.falsifier = reclamation_en_panne
        avant = len(_requetes(vps, "POST /api/v1/pieces/missing"))
        assert a.cycle() == "upToDate", "l'entretien en panne ne dit pas hors ligne"
        vps.falsifier = None
        assert len(_requetes(vps, "POST /api/v1/pieces/missing")) == avant + 1
        assert a.service.etat.lire("reclamationPiecesMs") == datee, (
            "une réclamation qui n'a pas abouti n'est pas datée"
        )
        assert a.cycle() == "upToDate"
        assert len(_requetes(vps, "POST /api/v1/pieces/missing")) == avant + 2, (
            "elle repart au cycle suivant"
        )
        assert a.service.etat.lire("reclamationPiecesMs") != datee


# ----------------------------------------------------------------------
# pieceId (§2.6)
# ----------------------------------------------------------------------


class TestIdentifiants:
    def test_piece_id_est_inverifiable_sans_k_piece(self, poste, vps):
        """§2.6 : ``pieceId = HMAC(K_piece_e, …)``. Échec évité : un
        identifiant tiré du contenu seul, qui laissait le VPS tester la
        présence d'une image connue et relier deux comptes qui l'ont
        envoyée."""
        a = _inscrit(poste, vps)
        c = _inscrit(poste, vps, "c", EMAIL_2)
        t = vps.horloge()
        image = _image()
        octets = _octets_de(image)
        for p in (a, c):
            p.magasin.upsert(
                conversation("x", [message("m", "x", t, images=[image])], t, t)
            )
            assert p.cycle() == "upToDate"
        pieces = _pieces_vps(vps)
        assert len(pieces) == 2, "même image, deux comptes : deux identifiants"

        clair = module_pieces.emballer(image)
        sans_cle = {
            cles.b64url(hashlib.sha256(x).digest()[:16])
            for x in (octets, clair, image.encode())
        }
        assert not sans_cle & set(pieces), "rien du contenu seul ne donne l'identifiant"
        for piece_id in pieces:
            recalcul = cles.identifiant_piece(os.urandom(32), clair)
            assert recalcul != piece_id, "une autre clé ne retrouve pas l'identifiant"
        for blob, _ in pieces.values():
            assert octets[:64] not in blob, "le blob ne porte pas l'image en clair"
            assert hashlib.sha256(octets).digest() not in blob
            assert hashlib.sha256(clair).digest() not in blob

        ouverture = a.service.serrure.exiger()
        (piece_a,) = [
            p for p in pieces if p == ouverture.trousseau.identifiant_piece(clair)
        ]
        assert piece_a == cles.identifiant_piece(
            cles.cle_piece(ouverture.trousseau.dek(1)), clair
        ), "avec K_piece, l'appareil le recalcule"

    def test_une_piece_permutee_n_est_jamais_montree_sous_un_autre_nom(
        self, poste, vps
    ):
        """§2.6, §4.12 : le VPS range le blob d'une image sous l'identifiant
        d'une autre. L'AAD lie le blob à son ``pieceId`` et l'appareil
        recalcule l'identifiant sur le clair : la conversation reste
        dégradée plutôt que de montrer la mauvaise image. Échec évité : un
        VPS qui choisit quelle image un message affiche."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        premiere, seconde = _image(), _image()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[premiere])], t, t)
        )
        a.magasin.upsert(
            conversation("y", [message("n", "y", t, images=[seconde])], t, t)
        )
        assert a.cycle() == "upToDate"
        ouverture = a.service.serrure.exiger()
        id_premiere = ouverture.trousseau.identifiant_piece(
            module_pieces.emballer(premiere)
        )
        id_seconde = ouverture.trousseau.identifiant_piece(
            module_pieces.emballer(seconde)
        )
        with vps.ctx.base.transaction() as conn:
            (blob_seconde,) = conn.execute(
                "SELECT blob FROM pieces WHERE piece_id = ?", (id_seconde,)
            ).fetchone()
            conn.execute(
                "UPDATE pieces SET blob = ? WHERE piece_id = ?",
                (blob_seconde, id_premiere),
            )

        with pytest.raises(module_pieces.PieceIllisible):
            module_pieces.ouvrir(
                ouverture.trousseau,
                bytes(blob_seconde),
                account_id=ouverture.account_id,
                incarnation=ouverture.incarnation,
                piece_id=id_premiere,
            )

        b = _connecte(poste)
        assert b.cycle() == "upToDate"
        assert "images" not in b.vivantes()["x"]["messages"][0], (
            "l'image permutée n'est pas montrée"
        )
        assert b.vivantes()["y"]["messages"][0]["images"] == [seconde]

    def test_un_porteur_de_dek_ne_substitue_pas_une_image_sous_son_identifiant(
        self, poste, vps
    ):
        """§2.11 bis : un porteur de la DEK (l'appareil perdu, complice du
        VPS) scelle une AUTRE image sous le ``pieceId`` existant, avec une
        AAD valide. Seul le recalcul de l'identifiant sur le clair l'attrape.
        Échec évité : l'autre appareil affichait l'image substituée."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        vraie, fausse = _image(), _image()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[vraie])], t, t)
        )
        assert a.cycle() == "upToDate"
        (piece_id,) = _pieces_vps(vps)
        ouverture = a.service.serrure.exiger()
        forgee = sceller_piece(
            ouverture.trousseau.dek_courante,
            module_pieces.emballer(fausse),
            account_id=ouverture.account_id,
            incarnation=ouverture.incarnation,
            piece_id=piece_id,
            key_epoch=ouverture.trousseau.current_epoch,
        )
        with vps.ctx.base.transaction() as conn:
            conn.execute(
                "UPDATE pieces SET blob = ? WHERE piece_id = ?", (forgee, piece_id)
            )

        b = _connecte(poste)
        assert b.cycle() == "upToDate"
        recu = b.vivantes()["x"]["messages"][0]
        assert "images" not in recu, "l'image substituée n'est jamais montrée"
        assert recu["content"] == "x", "le reste du message est là"


# ----------------------------------------------------------------------
# Refus d'une pièce par le VPS (§3.5, §4.3)
# ----------------------------------------------------------------------


class TestRefusDUnePiece:
    def test_un_quota_plein_sur_une_piece_retient_l_objet(self, poste, vps):
        """§3.5, §4.11 : un 507 ``quotaExceeded`` sur le dépôt d'une image
        retient l'objet qui la référence et le dit. Échec évité (§100) : un
        objet parti en référençant une pièce que le VPS a refusée, et une
        conversation qui se disait « Synchronisé » sans son image — que
        tous les autres appareils appliquaient dégradée."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[_image()])], t, t)
        )
        vps.falsifier = _refuser_les_depots(507, "quotaExceeded")
        assert a.cycle() == "quotaExceeded"
        vps.falsifier = None
        assert _requetes(vps, "PUT /api/v1/pieces/"), "le dépôt a été tenté"
        assert not _requetes(vps, "POST /api/v1/sync/push"), (
            "l'objet ne part pas sans sa pièce"
        )
        assert _objets_vps(vps) == []
        assert a.statut()["state"] == "quotaExceeded"

    @pytest.mark.parametrize(
        ("statut", "code"),
        [(413, "payloadTooLarge"), (422, "invalidEnvelope")],
        ids=["413", "422"],
    )
    def test_une_piece_refusee_pour_sa_forme_met_l_objet_en_quarantaine(
        self, poste, vps, statut, code
    ):
        """§4.3 : un refus de forme ne passera pas mieux au cycle suivant —
        quarantaine VISIBLE, et rien ne part. Échec évité : un objet poussé
        avec une référence vers rien, ou un dépôt retenté à chaque cycle."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[_image()])], t, t)
        )
        vps.falsifier = _refuser_les_depots(statut, code)
        assert a.cycle() == "quarantined"
        vps.falsifier = None
        assert not _requetes(vps, "POST /api/v1/sync/push")
        assert _objets_vps(vps) == []
        assert a.statut()["quarantinedCount"] == 1, "la quarantaine se compte"
        depots = len(_requetes(vps, "PUT /api/v1/pieces/"))
        vps.horloge.avancer(60_000)
        assert a.cycle() == "quarantined", "tant que rien n'est réécrit"
        assert len(_requetes(vps, "PUT /api/v1/pieces/")) == depots, (
            "le dépôt refusé n'est pas retenté à chaque cycle"
        )

    def test_une_image_plus_lourde_qu_une_piece_n_est_jamais_envoyee(
        self, poste, vps, monkeypatch
    ):
        """§3.5 (D10) : un blob au-delà de ``PIECE_MAX_OCTETS`` est refusé
        AVANT le PUT, en quarantaine visible ``rejected:pieceTooLarge``.
        Échec évité : un PUT voué au 413, renvoyé à chaque cycle. (La borne
        est abaissée ici : la vraie vaut 10 Mio.)"""
        monkeypatch.setattr(module_pieces, "PIECE_MAX_OCTETS", 20_000)
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("x", [message("m", "x", t, images=[_image(30_000)])], t, t)
        )
        assert a.cycle() == "quarantined"
        assert not _requetes(vps, "PUT /api/v1/pieces/"), "rien n'est déposé"
        assert not _requetes(vps, "POST /api/v1/sync/push")
        registre = a.registre()
        object_id = a.service.serrure.exiger().trousseau.identifiant_objet(
            "conversations", "x"
        )
        assert registre.motif_quarantaine(object_id) == "rejected:pieceTooLarge"
        assert a.statut()["quarantinedCount"] == 1


# ----------------------------------------------------------------------
# Lire une pièce : la frontière et la borne (§3.12, §3.5)
# ----------------------------------------------------------------------


class _Jeton:
    def __init__(self) -> None:
        self.lectures = 0

    def __call__(self) -> str:
        self.lectures += 1
        return "jeton-de-test"


def _transport(gerer, origine: str = "https://comptes.exemple.invalid") -> Transport:
    return Transport(
        actif=lambda: True,
        client_http=httpx.Client(transport=httpx.MockTransport(gerer)),
        origine=origine,
    )


class TestTelechargerUnePiece:
    PIECE = "A" * 22

    def test_local_only_refuse_avant_de_lire_le_jeton(self, monkeypatch):
        """§3.12 : ``telecharger`` refait la frontière de
        ``Transport._envoyer`` — AVANT le jeton. Échec évité : sous
        ``local_only``, le premier tirage d'une image partait vers une
        origine surchargée avec le jeton de session."""
        monkeypatch.setattr(local_mode, "local_only", lambda config=None: True)
        appels: list[httpx.Request] = []

        def gerer(requete):
            appels.append(requete)
            return httpx.Response(200, content=b"\x01")

        jeton = _Jeton()
        with pytest.raises(SortieRefusee):
            module_pieces.telecharger(_transport(gerer), self.PIECE, jeton=jeton)
        assert jeton.lectures == 0, "aucune lettre de créance n'a été touchée"
        assert appels == [], "rien n'est parti"

    def test_un_flux_sans_fin_n_est_pas_lu_au_dela_d_une_piece(self, monkeypatch):
        """§3.5 : un VPS hostile qui répond un flux sans fin. Échec évité :
        remplir la mémoire du serveur local avant de conclure."""
        monkeypatch.setattr(local_mode, "local_only", lambda config=None: False)
        mio = b"\x00" * (1024 * 1024)
        servis: list[int] = []

        def flux():
            for _ in range(64):
                servis.append(1)
                yield mio

        def gerer(_requete):
            return httpx.Response(200, content=flux())

        with pytest.raises(module_pieces.PieceIllisible):
            module_pieces.telecharger(_transport(gerer), self.PIECE, jeton=_Jeton())
        assert len(servis) <= 12, f"lecture arrêtée à la borne : {len(servis)} Mio"

    def test_une_redirection_est_refusee(self, monkeypatch):
        """§3.12 : une redirection mènerait ailleurs que l'origine vérifiée.
        Échec évité : suivre un 302 vers un hôte que la frontière n'a pas
        vu."""
        monkeypatch.setattr(local_mode, "local_only", lambda config=None: False)

        def gerer(_requete):
            return httpx.Response(
                302, headers={"Location": "https://ailleurs.invalid/"}
            )

        with pytest.raises(ServeurInjoignable):
            module_pieces.telecharger(_transport(gerer), self.PIECE, jeton=_Jeton())
