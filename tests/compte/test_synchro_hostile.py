"""Face à un VPS hostile : le tableau du §4.12, ligne par ligne.

Conception : ``docs/development/compte-chiffre.md`` §4.12, §4.4 (planchers),
§4.6 (autoréparation) et §2.11 bis (quarantaine d'époque).

Le VPS est le vrai service ``diapason_comptes`` en mémoire ; un test joue
l'hôte hostile en écrivant DIRECTEMENT dans sa base (échanger deux blobs,
rejouer une vieille version, changer ``generation``) ou en falsifiant une
réponse (``Vps.falsifier``). Un « appareil perdu » qui détient une DEK est
simulé en scellant avec le trousseau d'un appareil du compte.

Chaque ligne du tableau a son test ; celles qui ne relèvent pas du moteur
(coffre, Argon2, enveloppe AMK) sont rejouées ici par le parcours de
connexion, pour que le tableau se lise en entier à un seul endroit.
"""

from __future__ import annotations

import base64
import sqlite3

import pytest

pytest.importorskip("fastapi", reason="diapason[server] not installed")

from diapason.compte.cles import DeclassementKdf  # noqa: E402
from diapason.compte.enveloppe import (  # noqa: E402
    EnveloppeIllisible,
    clair_objet,
    encoder_clair,
    sceller_objet,
)
from diapason.compte.trousseau import CleServeurInvalide  # noqa: E402
from diapason.server import conversations_store as module_magasin  # noqa: E402
from diapason_comptes.base import ecriture  # noqa: E402
from diapason_comptes.routes_synchro import avancer_seq  # noqa: E402
from tests.compte._banc import (  # noqa: E402
    EMAIL,
    MDP,
    MDP_2,
    Vps,
    argon_rapide,
    formes,
    inscrire,
    reponse_json,
)
from tests.compte.test_deux_appareils import (  # noqa: E402
    Poste,
    _clair_serveur,
    _corrompre,
    _objets,
    _poussees,
    _pousser_brut,
    _une_heure_plus_tard,
    construire_poste,
    conversation,
    message,
)
from tests.diapason_comptes._outils import JOUR_MS  # noqa: E402

EMAIL_2 = "autre-compte@exemple.test"
CANARI_TITRE = "Canari-titre-9Hq-jamais-en-clair"
CANARI_MESSAGE = "Canari-message-4Lr-jamais-en-clair"


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
    monkeypatch.setattr(module_magasin, "_now_ms", vps.horloge)


@pytest.fixture
def poste(tmp_path, vps):
    crees: list[Poste] = []

    def construire(nom: str = "a") -> Poste:
        construit = construire_poste(tmp_path / nom, vps)
        crees.append(construit)
        return construit

    yield construire
    for p in crees:
        p.service.fermer()
        p.magasin.close()


# ----------------------------------------------------------------------
# L'hôte hostile
# ----------------------------------------------------------------------


def _id(p: Poste, id_local: str) -> str:
    return p.service.serrure.exiger().trousseau.identifiant_objet(
        "conversations", id_local
    )


def _ligne(vps: Vps, object_id: str) -> tuple:
    with vps.ctx.base.lecture() as conn:
        return conn.execute(
            "SELECT rev, seq, blob, rev_precedente, blob_precedent FROM objets "
            "WHERE objet_id = ?",
            (object_id,),
        ).fetchone()


def _poser(
    vps: Vps,
    object_id: str,
    *,
    blob: bytes,
    rev: int,
    compte_id: str | None = None,
    generation: str | None = None,
    seq: int | None = None,
) -> None:
    """Le VPS range ce qu'il veut sous ``object_id``, avec un ``seq`` neuf —
    ce qu'aucune route ne permet, et que root sur la machine fait. Un
    ``seq`` imposé : le VPS le choisit aussi, il n'est authentifié par rien."""
    with vps.ctx.base.transaction() as conn:
        if compte_id is None:
            (compte_id,) = conn.execute(
                "SELECT compte_id FROM objets WHERE objet_id = ?", (object_id,)
            ).fetchone()
        if seq is None:
            seq = avancer_seq(conn, compte_id)
        conn.execute(
            "INSERT INTO objets (compte_id, objet_id, rev, seq, blob) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(compte_id, objet_id) DO UPDATE SET "
            "rev = excluded.rev, seq = excluded.seq, blob = excluded.blob",
            (compte_id, object_id, rev, seq, blob),
        )
        if generation is not None:
            conn.execute(
                "UPDATE meta SET valeur = ? WHERE cle = 'generation'", (generation,)
            )
        ecriture(conn)


def _forger(
    p: Poste,
    id_local_du_clair: str,
    data: dict,
    *,
    object_id: str,
    rev: int,
    epoque: int,
) -> bytes:
    """Ce qu'un appareil perdu, qui détient la DEK de ``epoque``, peut sceller."""
    ouverture = p.service.serrure.exiger()
    return sceller_objet(
        ouverture.trousseau.dek(epoque),
        encoder_clair(clair_objet("conversations", id_local_du_clair, data)),
        account_id=ouverture.account_id,
        incarnation=ouverture.incarnation,
        object_id=object_id,
        rev=rev,
        key_epoch=epoque,
    )


def _inscrit(poste, vps, nom: str = "a", email: str = EMAIL) -> Poste:
    p = poste(nom)
    inscrire(p.service, vps, email=email)
    p.service.consentir()
    return p


def _neuf(poste, nom: str = "c", mot_de_passe: str = MDP) -> Poste:
    """Un appareil qui n'a JAMAIS rien vu de ce compte."""
    p = poste(nom)
    p.service.connecter(EMAIL, mot_de_passe, False)
    return p


def _deux_appareils(poste, vps: Vps) -> tuple[Poste, Poste]:
    a = _inscrit(poste, vps)
    b = poste("b")
    b.service.connecter(EMAIL, MDP, False)
    b.service.consentir()
    return a, b


def _ids(conversation_: dict) -> list[str]:
    return [m["id"] for m in conversation_["messages"]]


def _espionner_ingestions(p: Poste, monkeypatch) -> list[str]:
    """Les identifiants que le moteur de ``p`` ingère, dans l'ordre."""
    collection = p.moteur._collections["conversations"]  # noqa: SLF001
    ingerer = collection.ingerer
    vus: list[str] = []

    def espion(clair):
        vus.append(clair["id"])
        return ingerer(clair)

    monkeypatch.setattr(collection, "ingerer", espion)
    return vus


def _deux_conversations(a: Poste, vps: Vps) -> None:
    t = vps.horloge()
    a.magasin.upsert(conversation("x", "Fil X", [message("mx", "user", "x", t)], t))
    a.magasin.upsert(conversation("y", "Fil Y", [message("my", "user", "y", t)], t))
    assert a.cycle() == "upToDate"


def _octets_du_vps(vps: Vps, tmp_path) -> bytes:
    """Les octets de ``comptes.db`` (et de son WAL), d'une sauvegarde faite
    comme ``sauvegarder.py`` la fait, et de ``evenements.jsonl``."""
    sauvegarde = tmp_path / "sauvegarde.db"
    destination = sqlite3.connect(sauvegarde)
    with vps.ctx.base.lecture() as conn:
        conn.backup(destination)
    destination.close()
    chemin = vps.ctx.base.chemin
    morceaux = [sauvegarde.read_bytes()]
    for fichier in (chemin, chemin.with_name(chemin.name + "-wal")):
        if fichier.exists():
            morceaux.append(fichier.read_bytes())
    journal = vps.ctx.configuration.chemin_journal
    if journal.exists():
        morceaux.append(journal.read_bytes())
    return b"".join(morceaux)


def _canari_absent(octets: bytes) -> None:
    for canari in (CANARI_TITRE, CANARI_MESSAGE):
        for forme in formes(canari.encode("utf-8")) + [canari.encode("utf-16-le")]:
            assert forme not in octets, f"le canari {canari!r} est lisible sur le VPS"


def _texte_local(p: Poste) -> str:
    vivantes, tombales, _seq = p.magasin.list()
    return repr(vivantes) + repr(tombales)


# ----------------------------------------------------------------------
# Le tableau du §4.12
# ----------------------------------------------------------------------


class TestPermutations:
    def test_deux_blobs_echanges_ne_s_ecrivent_pas(self, poste, vps):
        """§4.12 « échange deux blobs » : l'AAD lie ``objectId`` ; rien
        n'est écrit, tout est en quarantaine. Échec évité : la conversation
        X affichée sous l'identifiant de Y."""
        a = _inscrit(poste, vps)
        _deux_conversations(a, vps)
        id_x, id_y = _id(a, "x"), _id(a, "y")
        rev_x, _s, blob_x, _rp, _bp = _ligne(vps, id_x)
        rev_y, _s, blob_y, _rp, _bp = _ligne(vps, id_y)
        _poser(vps, id_x, blob=blob_y, rev=rev_y)
        _poser(vps, id_y, blob=blob_x, rev=rev_x)
        c = _neuf(poste)
        c.cycle()
        assert c.vivantes() == {}, "aucun blob échangé ne doit s'écrire"
        assert c.statut_synchro()["quarantinedCount"] == 2

    def test_un_blob_d_un_autre_compte_ne_s_ecrit_pas(self, poste, vps):
        """§4.12 « prend un blob d'un autre compte » : l'AAD lie ``a``."""
        a = _inscrit(poste, vps)
        _deux_conversations(a, vps)
        d = _inscrit(poste, vps, "d", EMAIL_2)
        t = vps.horloge()
        d.magasin.upsert(
            conversation("z", "Autre compte", [message("z", "user", "z", t)], t)
        )
        d.cycle()
        (_rev, _seq, blob_z, _rp, _bp) = _ligne(vps, _id(d, "z"))
        _poser(vps, _id(a, "x"), blob=blob_z, rev=5)
        c = _neuf(poste)
        c.cycle()
        assert "z" not in c.vivantes() and "x" not in c.vivantes(), (
            "un blob d'un autre compte ne s'ingère jamais"
        )
        assert c.statut_synchro()["quarantinedCount"] >= 1

    def test_un_clair_permute_par_un_porteur_de_dek_est_en_quarantaine(
        self, poste, vps
    ):
        """§2.5 : ``objectId`` est recalculé depuis le clair ; un clair de Y
        scellé sous l'identifiant de X est « permuté », et rien n'est écrit."""
        a = _inscrit(poste, vps)
        _deux_conversations(a, vps)
        id_x = _id(a, "x")
        rev_x = _ligne(vps, id_x)[0]
        t = vps.horloge()
        faux = _forger(
            a,
            "y",
            {
                "title": "Forgé",
                "createdAt": t,
                "updatedAt": t + 99,
                "model": "m",
                "pinned": False,
                "messages": [],
            },
            object_id=id_x,
            rev=rev_x + 1,
            epoque=1,
        )
        _poser(vps, id_x, blob=faux, rev=rev_x + 1)
        c = _neuf(poste)
        c.cycle()
        assert c.vivantes()["y"]["title"] == "Fil Y", "Y reste la vraie Y"
        assert "Forgé" not in _texte_local(c)
        assert c.statut_synchro()["quarantinedCount"] == 1

    def test_un_clair_permute_est_repare_par_l_appareil_qui_a_la_copie(
        self, poste, vps
    ):
        """§4.6 et §4.12 : chez l'appareil qui a la copie, un blob permuté se
        répare comme un blob illisible. Échec évité (contre-épreuve du
        24/09/2026) : quarantaine sans réparation, deux cycles
        « Synchronisé » de suite, et X introuvable pour un appareil neuf
        tant que A ne la réécrivait pas."""
        a = _inscrit(poste, vps)
        _deux_conversations(a, vps)
        id_x = _id(a, "x")
        rev_x = _ligne(vps, id_x)[0]
        t = vps.horloge()
        faux = _forger(
            a,
            "y",
            {
                "title": "Forgé",
                "createdAt": t,
                "updatedAt": t + 99,
                "model": "m",
                "pinned": False,
                "messages": [],
            },
            object_id=id_x,
            rev=rev_x + 1,
            epoque=1,
        )
        _poser(vps, id_x, blob=faux, rev=rev_x + 1)
        assert a.cycle() == "upToDate"
        statut = a.statut_synchro()
        assert statut["repairedCount"] == 1, "la copie d'ici réécrase le blob"
        assert statut["quarantinedCount"] == 0, "réparé, l'objet sort de quarantaine"
        assert _clair_serveur(a, vps, "x")["data"]["title"] == "Fil X"
        c = _neuf(poste)
        c.cycle()
        assert sorted(c.vivantes()) == ["x", "y"], "X existe de nouveau pour le compte"


class TestRevisions:
    def test_la_revision_3_presentee_comme_la_5_est_refusee(self, poste, vps):
        """§4.12 : ``r`` est dans l'AAD — InvalidTag ; l'appareil qui a la
        copie la réécrit."""
        a = _inscrit(poste, vps)
        _deux_conversations(a, vps)
        id_x = _id(a, "x")
        rev, _seq, blob, _rp, _bp = _ligne(vps, id_x)
        ouverture = a.service.serrure.exiger()
        with pytest.raises(EnveloppeIllisible):
            ouverture.trousseau.ouvrir_objet(
                blob,
                account_id=ouverture.account_id,
                incarnation=ouverture.incarnation,
                object_id=id_x,
                rev=rev + 2,
            )
        _poser(vps, id_x, blob=blob, rev=rev + 2)
        assert a.cycle() == "upToDate"
        assert a.statut_synchro()["repairedCount"] == 1
        assert _clair_serveur(a, vps, "x")["data"]["title"] == "Fil X"

    def test_une_vieille_version_rejouee_avec_sa_vraie_rev_est_reecrasee(
        self, poste, vps, monkeypatch
    ):
        """§4.12 : ``rev < rev_max`` — pas d'ingestion, réaffirmation. Échec
        évité : un VPS qui fait reculer une conversation en rejouant une
        version authentique.

        L'ingestion est ESPIONNÉE (24/09/2026) : ``fusionner_conversations``
        est une jointure, ingérer la vieille version ne changeait rien au
        magasin, et le test restait vert sans la défense — qui protégera
        les collections en dernier-écrit-gagne du §4.8."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "v1", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        a.cycle()
        a.magasin.upsert(
            conversation(
                "x", "Fil v2", [m1, message("m2", "user", "v2", t + 1)], t + 1, cree=t
            )
        )
        a.cycle()
        id_x = _id(a, "x")
        _rev, _seq, _blob, rev_ancienne, blob_ancien = _ligne(vps, id_x)
        _poser(vps, id_x, blob=bytes(blob_ancien), rev=rev_ancienne)
        ingerees = _espionner_ingestions(a, monkeypatch)
        en_file_avant_poussee: list[bool] = []
        pousser = a.moteur._pousser  # noqa: SLF001

        def espion_poussee(registre, ouverture):
            en_file_avant_poussee.append(registre.sortant_existe("conversations", "x"))
            return pousser(registre, ouverture)

        monkeypatch.setattr(a.moteur, "_pousser", espion_poussee)
        _v, _t, seq_local = a.magasin.list()
        assert a.cycle() == "upToDate"
        _v, _t, seq_apres = a.magasin.list()
        assert ingerees == [], f"la vieille version n'est pas ingérée : {ingerees}"
        assert en_file_avant_poussee == [True], (
            "le tirage met la copie d'ici en file AVANT la poussée (réaffirmation)"
        )
        assert seq_apres == seq_local, "le magasin n'a pas bougé"
        assert _clair_serveur(a, vps, "x")["data"]["title"] == "Fil v2", (
            "le serveur est réécrasé par la copie de l'appareil"
        )

    @pytest.mark.parametrize("rejouee", ["tombale purgee", "version vivante"])
    def test_une_vieille_version_rejouee_au_seq_deja_vu_est_reecrasee(
        self, poste, vps, rejouee
    ):
        """§4.12 : le ``seq`` vient du VPS, hors de l'AAD. Rejouée sous le
        ``seq`` que l'appareil a déjà vu, une vieille version doit être
        réécrasée comme les autres. Échec évité (contre-épreuve du
        24/09/2026) : « ``seq == connus.seq`` ⇒ notre propre écriture »
        faisait taire la réaffirmation — l'appareil disait « Synchronisé »
        pendant que le serveur tenait la version d'avant la suppression, et
        un appareil neuf ressuscitait la conversation."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        m1 = message("m", "user", "x", t)
        a.magasin.upsert(conversation("x", "Secret", [m1], t))
        assert a.cycle() == "upToDate"
        id_x = _id(a, "x")
        rev_v, _s, blob_v, _rp, _bp = _ligne(vps, id_x)
        vps.horloge.avancer(1000)
        if rejouee == "tombale purgee":
            a.magasin.delete("x")
        else:
            a.magasin.upsert(
                conversation(
                    "x", "Secret v2", [m1, message("n", "user", "y", t + 1)], t + 1
                )
            )
        assert a.cycle() == "upToDate"
        _rev, seq_vu, *_ = _ligne(vps, id_x)
        if rejouee == "tombale purgee":
            vps.horloge.avancer(41 * JOUR_MS)
            assert a.magasin.purger_tombales() == 1
        # La version d'avant, sous le ``seq`` que A a vu en dernier ; une
        # ``generation`` neuve fait tout retirer depuis 0.
        _poser(
            vps, id_x, blob=bytes(blob_v), rev=rev_v, seq=seq_vu, generation="hostile"
        )
        assert a.cycle() == "upToDate"
        serveur = _clair_serveur(a, vps, "x")
        if rejouee == "tombale purgee":
            assert "deleted" in serveur, "A réaffirme la tombale sur le serveur"
        else:
            assert serveur["data"]["title"] == "Secret v2", "A réaffirme sa version"
        c = _neuf(poste)
        c.cycle()
        if rejouee == "tombale purgee":
            assert "x" not in c.vivantes(), "un appareil neuf ne ressuscite rien"
        else:
            assert c.vivantes()["x"]["title"] == "Secret v2"

    def test_une_seule_reponse_forgee_ne_rend_pas_sourd_aux_autres(self, poste, vps):
        """§4.4 : ``rev_max`` ne monte que sur une révision authentifiée.
        Échec évité (contre-épreuve du 24/09/2026) : UNE réponse falsifiée,
        un blob illisible à ``rev = 10**12`` montré à A seul, relevait son
        plancher pour toujours — chaque écriture légitime de B passait
        ensuite pour « une vieille version », A ne la recevait jamais et
        réécrasait le serveur avec sa copie, cycle après cycle."""
        a, b = _deux_appareils(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "v1", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        a.cycle()
        b.cycle()
        id_x = _id(a, "x")
        fait: list[bool] = []

        def une_fois(requete, reponse):
            if fait or not requete.chemin.startswith("/api/v1/sync/changes"):
                return None
            fait.append(True)
            corps = reponse.json()
            corps["items"] = [
                {
                    "objectId": id_x,
                    "rev": 10**12,
                    "seq": corps["until"],
                    "blob": base64.urlsafe_b64encode(b"\x00" * 80).decode().rstrip("="),
                }
            ]
            return reponse_json(200, corps)

        vps.falsifier = une_fois
        a.cycle()
        vps.falsifier = None
        assert fait, "la réponse forgée a bien été servie"
        m2 = message("m2", "user", "écrit sur B", t + 5)
        b.magasin.upsert(conversation("x", "Fil", [m1, m2], t + 5, cree=t))
        assert b.cycle() == "upToDate"
        assert a.cycle() == "upToDate"
        assert _ids(a.vivantes()["x"]) == ["m1", "m2"], (
            "A reçoit toujours les écritures de B"
        )
        assert _ids(_clair_serveur(a, vps, "x")["data"]) == ["m1", "m2"], (
            "A n'a pas réécrasé l'écriture de B"
        )

    def test_un_until_au_dela_du_server_seq_est_refuse(self, poste, vps):
        """§6 bis : reprendre à ``until`` — mais jamais au-delà de ce que le
        serveur dit tenir. Échec évité (contre-épreuve du 24/09/2026) : une
        réponse à ``until = 10**12`` donnait « Synchronisé », puis
        ``serverRolledBack`` à chaque cycle suivant, jusqu'à une reconnexion."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        assert a.cycle() == "upToDate"
        fait: list[bool] = []

        def demesure(requete, reponse):
            if fait or not requete.chemin.startswith("/api/v1/sync/changes"):
                return None
            fait.append(True)
            corps = reponse.json()
            corps["until"] = 10**12
            return reponse_json(200, corps)

        vps.falsifier = demesure
        assert a.cycle() != "upToDate", "la réponse démesurée ne vaut rien"
        vps.falsifier = None
        a.moteur._repli_jusqu_a = 0.0  # noqa: SLF001 - le repli, sauté
        assert a.cycle() == "upToDate", "le cycle suivant repart du bon curseur"
        assert a.service.statut()["state"] != "serverRolledBack"

    @pytest.mark.parametrize("ou", ["sous le curseur", "au-delà de until"])
    def test_un_element_hors_de_la_page_est_refuse(self, poste, vps, ou):
        """§6 bis : un élément de ``seq <= since`` ou ``> until`` n'est pas
        de cette page. Accepté, il permettait à un VPS de glisser sous le
        curseur un blob étiqueté d'un ``seq`` ancien — sous la borne d'une
        époque — hors de tout tirage complet."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        assert a.cycle() == "upToDate"
        assert a.cycle() == "upToDate"
        (_o, rev, seq, blob) = _objets(vps)[0]
        assert int(a.service.etat.lire("curseurDistant")) >= seq

        def hors_page(requete, reponse):
            if not requete.chemin.startswith("/api/v1/sync/changes"):
                return None
            corps = reponse.json()
            corps["items"] = [
                {
                    "objectId": _id(a, "x"),
                    "rev": rev,
                    "seq": seq if ou == "sous le curseur" else corps["until"] + 1,
                    "blob": base64.urlsafe_b64encode(blob).decode().rstrip("="),
                }
            ]
            return reponse_json(200, corps)

        vps.falsifier = hors_page
        assert a.cycle() == "offline", "la page incohérente fait abandonner le cycle"
        vps.falsifier = None
        assert a.statut_synchro()["errorCode"] == "serverError"


class TestSuppressionDefendue:
    def test_generation_changee_puis_version_d_avant_une_suppression_de_40_jours(
        self, poste, vps, tmp_path
    ):
        """§4.4 et §4.12 : le VPS change ``generation`` et rejoue la version
        d'avant une suppression vieille de 40 jours, avec sa vraie ``rev``
        et une AAD valide. La conversation reste supprimée, le canari reste
        absent. Échec évité (revues cryptographie et protocole) : vider
        ``connus`` sur une ``generation`` que rien n'authentifie, et voir la
        conversation ressusciter partout."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation(
                "x", CANARI_TITRE, [message("m", "user", CANARI_MESSAGE, t)], t
            )
        )
        assert a.cycle() == "upToDate"
        id_x = _id(a, "x")
        rev_vivante, _seq, blob_vivant, _rp, _bp = _ligne(vps, id_x)
        vps.horloge.avancer(1000)
        a.magasin.delete("x")
        assert a.cycle() == "upToDate"
        vps.horloge.avancer(41 * JOUR_MS)
        assert a.magasin.purger_tombales() == 1, "confirmée, la tombale se purge"
        assert "x" not in a.tombales(), "plus rien de X dans le magasin de A"

        _poser(
            vps, id_x, blob=bytes(blob_vivant), rev=rev_vivante, generation="hostile"
        )
        assert a.cycle() == "upToDate"
        assert "x" not in a.vivantes(), "la conversation supprimée ne revient pas"
        assert CANARI_TITRE not in _texte_local(a)
        assert CANARI_MESSAGE not in _texte_local(a)
        assert _clair_serveur(a, vps, "x")["deleted"], (
            "le serveur tient de nouveau la tombale"
        )
        b = _neuf(poste, "b")
        b.cycle()
        assert "x" not in b.vivantes(), "un appareil neuf reçoit la tombale"
        assert CANARI_TITRE not in _texte_local(b)
        _canari_absent(_octets_du_vps(vps, tmp_path))

    def test_un_perdant_de_dek_rejoue_la_version_d_avant_la_suppression(
        self, poste, vps
    ):
        """§4.3 : une copie vivante qui n'a pas vu une suppression connue —
        même à une révision NEUVE, scellée par un appareil perdu qui détient
        la DEK courante — n'est pas ingérée ; la tombale repart. Échec évité :
        une suppression défaite par qui garde encore une clé."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("x", "À supprimer", [message("m", "user", "x", t)], t)
        )
        a.cycle()
        vps.horloge.avancer(1000)
        a.magasin.delete("x")
        a.cycle()
        vps.horloge.avancer(41 * JOUR_MS)
        a.magasin.purger_tombales()
        id_x = _id(a, "x")
        rev = _ligne(vps, id_x)[0]
        faux = _forger(
            a,
            "x",
            {
                "title": "Ressuscitée",
                "createdAt": t,
                "updatedAt": t,
                "model": "m",
                "pinned": False,
                "messages": [message("m", "user", "x", t)],
            },
            object_id=id_x,
            rev=rev + 1,
            epoque=1,
        )
        _poser(vps, id_x, blob=faux, rev=rev + 1)
        assert a.cycle() == "upToDate"
        assert "x" not in a.vivantes(), "le plancher de suppression tient"
        assert _clair_serveur(a, vps, "x")["deleted"], "la tombale est repoussée"

    def test_une_tombale_cachee_a_un_appareil_neuf_est_un_risque_assume(
        self, poste, vps
    ):
        """§4.12 « cache une tombale à un appareil qui ne l'a jamais vue » :
        AUCUNE défense, et on l'écrit. L'appareil qui a vu la suppression,
        lui, réécrase le serveur."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        a.cycle()
        vps.horloge.avancer(1000)
        a.magasin.delete("x")
        a.cycle()
        id_x = _id(a, "x")
        _rev, _seq, _blob, rev_precedente, blob_precedent = _ligne(vps, id_x)
        _poser(vps, id_x, blob=bytes(blob_precedent), rev=rev_precedente)
        c = _neuf(poste)
        c.cycle()
        assert "x" in c.vivantes(), (
            "risque assumé : un appareil neuf ne peut pas savoir ce qu'on lui cache"
        )
        a.cycle()
        assert _clair_serveur(a, vps, "x")["deleted"], "A réaffirme la tombale"


class TestCoffreEtEntetes:
    def test_un_en_tete_retouche_est_refuse(self, poste, vps):
        """§4.12 : l'en-tête est dans l'AAD — InvalidTag, quarantaine."""
        a = _inscrit(poste, vps)
        _deux_conversations(a, vps)
        id_x = _id(a, "x")
        rev, _seq, blob, _rp, _bp = _ligne(vps, id_x)
        retouche = bytearray(blob)
        retouche[10] ^= 0x01  # un octet du sel HKDF, dans l'en-tête
        ouverture = a.service.serrure.exiger()
        with pytest.raises(EnveloppeIllisible):
            ouverture.trousseau.ouvrir_objet(
                bytes(retouche),
                account_id=ouverture.account_id,
                incarnation=ouverture.incarnation,
                object_id=id_x,
                rev=rev,
            )
        _poser(vps, id_x, blob=bytes(retouche), rev=rev)
        c = _neuf(poste)
        c.cycle()
        assert "x" not in c.vivantes()
        assert c.statut_synchro()["quarantinedCount"] == 1

    def test_un_coffre_ancien_annonce_par_meta_est_un_retour_arriere(self, poste, vps):
        """§4.12 « rejoue un coffre ou un trousseau ancien » : planchers —
        ``meta`` sous ``vault_version_max`` arrête tout. Le refus du coffre
        lui-même (``serverKeyStale``) est éprouvé par ``test_parcours``."""
        a = _inscrit(poste, vps)
        _une_heure_plus_tard(vps)
        a.service.changer_mot_de_passe(MDP, MDP_2)

        def vieux_coffre(requete, reponse):
            if requete.chemin.startswith("/api/v1/sync/changes"):
                corps = reponse.json()
                corps["meta"]["vaultVersion"] = 1
                corps["meta"]["keyringVersion"] = 1
                corps["meta"]["keyEpoch"] = 1
                return reponse_json(200, corps)
            return None

        vps.falsifier = vieux_coffre
        assert a.cycle() == "serverRolledBack"
        vps.falsifier = None
        assert _poussees(vps) == [], "rien ne part vers un serveur revenu en arrière"

    def test_un_argon2_affaibli_est_refuse(self, poste, vps):
        """§4.12 « impose un Argon2 faible » : ``kdfDowngrade``, avant tout
        calcul."""
        _inscrit(poste, vps)

        def faible(requete, reponse):
            if requete.chemin == "/api/v1/login/params":
                corps = reponse.json()
                corps["kdfVersion"] = 0
                return reponse_json(200, corps)
            return None

        vps.falsifier = faible
        c = poste("c")
        with pytest.raises(DeclassementKdf):
            c.service.connecter(EMAIL, MDP, False)

    def test_une_epoque_annoncee_differente_du_trousseau_est_refusee(self, poste, vps):
        """§4.12 « rend une enveloppe forgée » : ce que le serveur annonce
        doit concorder avec le trousseau authentifié — ``serverKeyInvalid``."""
        _inscrit(poste, vps)

        def epoque_forgee(requete, reponse):
            if requete.chemin == "/api/v1/login":
                corps = reponse.json()
                corps["keyEpoch"] = 7
                return reponse_json(200, corps)
            return None

        vps.falsifier = epoque_forgee
        c = poste("c")
        with pytest.raises(CleServeurInvalide):
            c.service.connecter(EMAIL, MDP, False)


class TestAutoreparationEtQuarantaine:
    def test_un_blob_aleatoire_sans_copie_locale_est_restaure(self, poste, vps):
        """§4.12 « écrase un objet avec un blob aléatoire (jeton volé) » :
        sans copie locale, la version précédente ; l'objet est restauré,
        ``repairedCount`` = 1."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "v1", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        a.cycle()
        a.magasin.upsert(
            conversation(
                "x", "Fil", [m1, message("m2", "user", "v2", t + 1)], t + 1, cree=t
            )
        )
        a.cycle()
        id_x = _id(a, "x")
        rev, _seq, blob, _rp, _bp = _ligne(vps, id_x)
        _pousser_brut(
            vps,
            a.service.jeton_de_session(),
            {
                "incarnation": 1,
                "keyEpoch": 1,
                "items": [
                    {
                        "objectId": id_x,
                        "baseRev": rev,
                        "blob": base64.urlsafe_b64encode(_corrompre(blob))
                        .decode()
                        .rstrip("="),
                    }
                ],
            },
        )
        c = _neuf(poste)
        assert c.cycle() == "upToDate"
        assert [m["id"] for m in c.vivantes()["x"]["messages"]] == ["m1", "m2"], (
            "C relit la version précédente, intacte"
        )
        assert c.statut_synchro()["repairedCount"] == 1
        assert _clair_serveur(a, vps, "x")["data"]["messages"][1]["id"] == "m2", (
            "le serveur tient de nouveau un objet lisible"
        )

    @pytest.mark.parametrize("decalage", [1, 0], ids=["rev+1", "rev egale"])
    def test_une_revision_neuve_sous_une_ancienne_epoque_est_en_quarantaine(
        self, poste, vps, decalage
    ):
        """§2.11 bis : le trousseau garde les anciennes DEK pour l'historique ;
        un porteur d'une DEK d'avant la rotation ne doit pas faire accepter
        une écriture postérieure à celle-ci. Échec évité : l'appareil perdu
        qui écrit encore, après sa déconnexion, dans les conversations du
        compte.

        À révision ÉGALE aussi (24/09/2026) : la garde n'exigeait que
        ``rev > rev_max`` ; forgé à ``rev_max`` avec un ``seq`` neuf, le
        contenu était ingéré, puis rescellé sous l'époque COURANTE et
        propagé à tous les appareils."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "v1", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        a.cycle()
        _une_heure_plus_tard(vps)
        a.service.changer_mot_de_passe(MDP, MDP_2)
        a.magasin.upsert(
            conversation(
                "x", "Fil", [m1, message("m2", "user", "v2", t + 1)], t + 1, cree=t
            )
        )
        assert a.cycle() == "upToDate"
        id_x = _id(a, "x")
        rev = _ligne(vps, id_x)[0]
        faux = _forger(
            a,
            "x",
            {
                "title": "Écrit par l'appareil perdu",
                "createdAt": t,
                "updatedAt": t + 10_000,
                "model": "m",
                "pinned": False,
                "messages": [m1, message("pirate", "user", "INJECTÉ", t + 10_000)],
            },
            object_id=id_x,
            rev=rev + decalage,
            epoque=1,
        )
        _poser(vps, id_x, blob=faux, rev=rev + decalage)
        assert a.cycle() == "upToDate"
        assert a.vivantes()["x"]["title"] == "Fil", "rien de forgé n'est ingéré"
        assert "pirate" not in _ids(a.vivantes()["x"])
        assert a.statut_synchro()["repairedCount"] == 1
        assert _ligne(vps, id_x)[2][2:6] == (2).to_bytes(4, "big"), (
            "le serveur tient de nouveau un objet de l'époque courante"
        )
        c = _neuf(poste, "c", MDP_2)
        c.cycle()
        assert _ids(c.vivantes()["x"]) == ["m1", "m2"], (
            "un appareil neuf ne reçoit rien de forgé"
        )

    def test_a_revision_egale_sous_un_seq_ancien_le_contenu_trahit_la_forgerie(
        self, poste, vps
    ):
        """§2.11 bis, ce que le ``seq`` ne suffit pas à dire : un VPS complice
        étiquette sa forgerie d'un ``seq`` ANCIEN (sous la borne d'époque)
        et change ``generation`` pour la faire retirer depuis 0. À
        ``rev_max``, deux contenus sous la même révision trahissent la
        forgerie : le comparer-et-échanger d'un VPS honnête ne les produit
        jamais. Échec évité : le contenu forgé ingéré puis propagé."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "v1", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        a.cycle()
        id_x = _id(a, "x")
        _rev, seq_ancien, *_ = _ligne(vps, id_x)
        _une_heure_plus_tard(vps)
        a.service.changer_mot_de_passe(MDP, MDP_2)
        a.magasin.upsert(
            conversation(
                "x", "Fil", [m1, message("m2", "user", "v2", t + 1)], t + 1, cree=t
            )
        )
        assert a.cycle() == "upToDate"
        rev = _ligne(vps, id_x)[0]
        faux = _forger(
            a,
            "x",
            {
                "title": "Forgé",
                "createdAt": t,
                "updatedAt": t + 10_000,
                "model": "m",
                "pinned": False,
                "messages": [m1, message("pirate", "user", "INJECTÉ", t + 10_000)],
            },
            object_id=id_x,
            rev=rev,
            epoque=1,
        )
        _poser(vps, id_x, blob=faux, rev=rev, seq=seq_ancien, generation="complice")
        a.cycle()
        assert "pirate" not in _ids(a.vivantes()["x"]), "rien de forgé n'est ingéré"
        assert "pirate" not in _ids(_clair_serveur(a, vps, "x")["data"]), (
            "le serveur est réécrasé par la copie de l'appareil"
        )

    def test_un_objet_neuf_sous_une_ancienne_epoque_n_entre_pas(self, poste, vps):
        """§2.11 bis : la quarantaine d'époque vaut aussi pour un objet que
        l'appareil ne connaît pas. Échec évité (contre-épreuve du
        24/09/2026) : une conversation entière, forgée sous la DEK 1 après
        la rotation, entrait chez un appareil à jour."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        a.cycle()
        _une_heure_plus_tard(vps)
        a.service.changer_mot_de_passe(MDP, MDP_2)
        assert a.cycle() == "upToDate"
        ouverture = a.service.serrure.exiger()
        id_neuve = ouverture.trousseau.identifiant_objet("conversations", "neuve")
        faux = _forger(
            a,
            "neuve",
            {
                "title": "Injectée",
                "createdAt": t,
                "updatedAt": t,
                "model": "m",
                "pinned": False,
                "messages": [message("pirate", "user", "INJECTÉ", t)],
            },
            object_id=id_neuve,
            rev=1,
            epoque=1,
        )
        (compte_id,) = _compte_id(vps)
        _poser(vps, id_neuve, blob=faux, rev=1, compte_id=compte_id)
        a.cycle()
        assert "neuve" not in a.vivantes(), "une conversation forgée n'entre pas"
        assert a.statut_synchro()["quarantinedCount"] == 1


def _compte_id(vps: Vps) -> tuple[str]:
    with vps.ctx.base.lecture() as conn:
        return conn.execute("SELECT id FROM comptes").fetchone()


class TestRotationHonnete:
    """§2.8 et §2.11 bis face à un serveur HONNÊTE : la quarantaine d'époque
    ne doit jamais toucher une écriture légitime faite avant la rotation."""

    @pytest.mark.parametrize("rotation", ["mot de passe", "appareil deconnecte"])
    def test_l_ecriture_confirmee_juste_avant_la_rotation_survit(
        self, poste, vps, rotation
    ):
        """Échec évité (bloquant, contre-épreuve du 24/09/2026) : B écrit et
        confirme sous l'époque 1 ; A fait tourner les clés sans avoir tiré.
        La règle « révision neuve sous une ancienne époque », appliquée sans
        ordre, prenait l'écriture de B pour une forgerie, l'effaçait du
        serveur sous la copie de A et affichait « Synchronisé » avec une
        fausse alerte « réparé ». Déconnecté par la rotation, B ne la
        repousserait jamais."""
        a, b = _deux_appareils(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "v1", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        assert a.cycle() == "upToDate"
        assert b.cycle() == "upToDate"
        m2 = message("m2", "user", "dernière note écrite sur B", t + 5)
        b.magasin.upsert(conversation("x", "Fil", [m1, m2], t + 5, cree=t))
        assert b.cycle() == "upToDate"
        _une_heure_plus_tard(vps)
        if rotation == "mot de passe":
            a.service.changer_mot_de_passe(MDP, MDP_2)
        else:
            a.service.deconnecter_appareil(b.service.etat.lire("sessionId"), MDP)
        assert a.cycle() == "upToDate"
        assert _ids(a.vivantes()["x"]) == ["m1", "m2"], "A reçoit l'écriture de B"
        assert _ids(_clair_serveur(a, vps, "x")["data"]) == ["m1", "m2"], (
            "le serveur garde l'écriture de B"
        )
        statut = a.statut_synchro()
        assert statut["repairedCount"] == 0, "aucune fausse alerte « réparé »"
        assert statut["quarantinedCount"] == 0, "rien de légitime en quarantaine"


class TestQuarantaineVisible:
    def test_un_objet_connu_en_quarantaine_sans_reparation_n_est_pas_synchronise(
        self, poste, vps
    ):
        """§100 : un objet que cet appareil connaît, que le compte ne tient
        plus sous une forme utilisable, et que rien ici ne réécrit — l'état
        le dit. Échec évité (contre-épreuve du 24/09/2026) : ``_conclure``
        ne regardait que les refus de poussée, et « Synchronisé » s'affichait
        pendant qu'un objet connu restait en quarantaine."""
        a = _inscrit(poste, vps)
        _deux_conversations(a, vps)
        id_x = _id(a, "x")
        rev_x = _ligne(vps, id_x)[0]
        t = vps.horloge()
        faux = _forger(
            a,
            "x",
            {
                "title": "Invalide",
                "createdAt": t,
                "updatedAt": "pas une date",
                "model": "m",
                "pinned": False,
                "messages": [],
            },
            object_id=id_x,
            rev=rev_x + 1,
            epoque=1,
        )
        _poser(vps, id_x, blob=faux, rev=rev_x + 1)
        assert a.cycle() == "quarantined"
        assert a.statut_synchro()["state"] == "quarantined"
        assert a.statut_synchro()["quarantinedCount"] == 1
        assert a.vivantes()["x"]["title"] == "Fil X", "rien d'invalide n'est écrit"


class TestRetenueEtLecture:
    def test_retenir_se_voit_a_l_anciennete_de_last_confirmed_at(self, poste, vps):
        """§4.12 « retient ou efface » : aucune défense ; l'ancienneté de
        ``lastConfirmedAt`` le montre, et « Synchronisé » ne se dit plus."""
        a = _inscrit(poste, vps)
        _deux_conversations(a, vps)
        confirme = a.statut_synchro()["lastConfirmedAt"]
        assert confirme is not None

        def occupe(requete, _reponse):
            if "/sync/" in requete.chemin:
                return reponse_json(
                    503, {"error": {"code": "serverBusy", "retryAfterS": 5}}
                )
            return None

        vps.falsifier = occupe
        vps.horloge.avancer(3_600_000)
        assert a.cycle() == "offline"
        vps.falsifier = None
        statut = a.statut_synchro()
        assert statut["lastConfirmedAt"] == confirme, "la date ne ment pas"
        assert statut["errorCode"] == "serverBusy"
        assert a.moteur.repli_restant() <= 5, "le repli suit retryAfterS"

    def test_le_canari_est_introuvable_sur_le_vps(self, poste, vps, tmp_path):
        """§4.12 « lit » : un titre et un message uniques, introuvables dans
        les octets de ``comptes.db``, de sa sauvegarde et du journal."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation(
                "x", CANARI_TITRE, [message("m", "user", CANARI_MESSAGE, t)], t
            )
        )
        assert a.cycle() == "upToDate"
        c = _neuf(poste)
        c.cycle()
        assert c.vivantes()["x"]["title"] == CANARI_TITRE, "le canari a bien voyagé"
        _canari_absent(_octets_du_vps(vps, tmp_path))
        for requete in vps.requetes:
            _canari_absent(requete.contenu)
        assert len(_objets(vps)) == 1
