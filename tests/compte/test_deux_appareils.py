"""Deux appareils, deux magasins, deux serrures, un VPS en mémoire.

Conception : ``docs/development/compte-chiffre.md`` §4 et l'étape 10 du §6.

Chaque « appareil » est un vrai ``ServiceCompte`` (le banc de l'étape 8), un
vrai ``ConversationsStore`` sur disque et un vrai ``MoteurSynchro`` ; le VPS
est le service ``diapason_comptes`` derrière un ``httpx.MockTransport``
(``tests/compte/_banc.py``). Aucun octet ne quitte la machine.

L'horloge du magasin (``conversations_store._now_ms``) est celle du VPS de
test : avancer de 40 jours vieillit les tombales comme les sessions.

La dernière classe éprouve l'exigence de la session principale du
24/09/2026 : sans compte déverrouillé, le moteur DORT — aucune requête,
aucune tâche qui boucle, et une fermeture immédiate.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any

import pytest

pytest.importorskip("fastapi", reason="diapason[server] not installed")

from diapason.compte.collections.conversations import (  # noqa: E402
    CollectionConversations,
)
from diapason.compte.service import ServiceCompte  # noqa: E402
from diapason.compte.synchro import MoteurSynchro  # noqa: E402
from diapason.server import conversations_store as module_magasin  # noqa: E402
from diapason.server.conversations_store import ConversationsStore  # noqa: E402
from diapason_comptes.base import ecriture, generation  # noqa: E402
from tests.compte._banc import (  # noqa: E402
    EMAIL,
    MDP,
    MDP_2,
    Vps,
    appareil,
    argon_rapide,
    extrait,
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
    """Le magasin date ses tombales et mesure leur âge sur l'horloge du VPS
    de test : 40 jours se franchissent en une ligne."""
    monkeypatch.setattr(module_magasin, "_now_ms", vps.horloge)


@dataclass
class Poste:
    """Un appareil : son service de compte, son magasin, son moteur."""

    service: ServiceCompte
    magasin: ConversationsStore
    moteur: MoteurSynchro

    def cycle(self) -> str:
        return self.moteur.cycle()

    def vivantes(self) -> dict[str, dict]:
        vivantes, _tombales, _seq = self.magasin.list()
        return {c["id"]: c for c in vivantes}

    def tombales(self) -> dict[str, int]:
        _vivantes, tombales, _seq = self.magasin.list()
        return {t["id"]: t["deletedAt"] for t in tombales}

    def statut_synchro(self) -> dict:
        return self.service.statut()["sync"]


def construire_poste(dossier, vps: Vps, *, decalage_ms: int = 0) -> Poste:
    """Un appareil complet dans ``dossier`` : ``compte/`` et
    ``conversations.db`` côte à côte, comme dans ``~/.diapason``."""
    dossier.mkdir(parents=True, exist_ok=True)
    magasin = ConversationsStore(dossier / "conversations.db")

    def compter() -> int:
        vivantes, _t, _s = magasin.list()
        return sum(1 for c in vivantes if c["messages"])

    service = appareil(vps, dossier, nom=f"Appareil {dossier.name}", compter=compter)
    moteur = MoteurSynchro(
        service,
        [CollectionConversations(magasin)],
        horloge_ms=lambda: vps.horloge() + decalage_ms,
    )
    service.moteur = moteur
    # Ce que ``servir`` fait au premier réveil (server/app.py).
    moteur.brancher(magasin, lambda **_k: None)
    return Poste(service, magasin, moteur)


@pytest.fixture
def poste(tmp_path, vps):
    crees: list[Poste] = []

    def construire(nom: str = "a", *, decalage_ms: int = 0) -> Poste:
        construit = construire_poste(tmp_path / nom, vps, decalage_ms=decalage_ms)
        crees.append(construit)
        return construit

    yield construire
    for p in crees:
        p.service.fermer()
        p.magasin.close()


def message(ident: str, role: str, contenu: str, ts: int, **autres: Any) -> dict:
    return {"id": ident, "role": role, "content": contenu, "timestamp": ts, **autres}


def conversation(
    ident: str, titre: str, messages: list[dict], maj: int, *, cree: int | None = None
) -> dict:
    return {
        "id": ident,
        "title": titre,
        "createdAt": cree if cree is not None else maj,
        "updatedAt": maj,
        "model": MODELE,
        "pinned": False,
        "messages": messages,
    }


def _objets(vps: Vps) -> list[tuple[str, int, int, bytes]]:
    with vps.ctx.base.lecture() as conn:
        return [
            (o, r, s, bytes(b))
            for o, r, s, b in conn.execute(
                "SELECT objet_id, rev, seq, blob FROM objets ORDER BY seq"
            ).fetchall()
        ]


def _seq_du_compte(vps: Vps) -> int:
    with vps.ctx.base.lecture() as conn:
        return conn.execute("SELECT MAX(seq) FROM comptes").fetchone()[0]


def _poussees(vps: Vps) -> list[dict]:
    return [r.json() for r in vps.requetes if r.chemin == "/api/v1/sync/push"]


def _requetes_de_synchro(vps: Vps, jeton: str | None = None) -> list[str]:
    return [
        f"{r.methode} {r.chemin}"
        for r in vps.requetes
        if "/sync/" in r.chemin
        and (jeton is None or r.en_tetes.get("authorization") == f"Bearer {jeton}")
    ]


def _clair_serveur(p: Poste, vps: Vps, id_local: str) -> dict:
    """Ce que le VPS tient pour cette conversation, ouvert par CET appareil."""
    ouverture = p.service.serrure.exiger()
    object_id = ouverture.trousseau.identifiant_objet("conversations", id_local)
    for o, rev, _seq, blob in _objets(vps):
        if o == object_id:
            return ouverture.trousseau.ouvrir_objet(
                blob,
                account_id=ouverture.account_id,
                incarnation=ouverture.incarnation,
                object_id=o,
                rev=rev,
            )
    raise AssertionError(f"{id_local} absente du VPS")


def _inscrit(poste, vps, nom: str = "a") -> Poste:
    """P1, puis l'étape 5 « Ce qui se synchronise » : le consentement."""
    p = poste(nom)
    inscrire(p.service, vps)
    p.service.consentir()
    return p


def _deux_appareils(poste, vps) -> tuple[Poste, Poste]:
    a = _inscrit(poste, vps)
    b = poste("b")
    b.service.connecter(EMAIL, MDP, False)
    b.service.consentir()
    return a, b


def _une_heure_plus_tard(vps: Vps) -> None:
    """3 courriels par heure et par adresse (§3.5) : une inscription, une
    rotation et son avis suffisent à retenir le code suivant."""
    vps.horloge.avancer(61 * 60_000)


# ----------------------------------------------------------------------
# Convergence
# ----------------------------------------------------------------------


class TestConvergence:
    def test_des_messages_concurrents_sont_fusionnes(self, poste, vps):
        """§4.1 : pousser la jointure de ce qu'on a et de ce qu'on a vu fait
        converger. Échec évité : un dernier-écrit-gagne perdait la question
        posée sur l'autre appareil."""
        a, b = _deux_appareils(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "Bonjour", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        assert a.cycle() == "upToDate"
        assert b.cycle() == "upToDate"
        assert "x" in b.vivantes(), "B doit avoir reçu la conversation de A"

        m2 = message("m2", "assistant", "Réponse écrite sur A", t + 10)
        m3 = message("m3", "user", "Question écrite sur B", t + 20)
        a.magasin.upsert(conversation("x", "Fil", [m1, m2], t + 10, cree=t))
        b.magasin.upsert(conversation("x", "Fil", [m1, m3], t + 20, cree=t))
        a.cycle()
        b.cycle()
        a.cycle()

        ids_a = [m["id"] for m in a.vivantes()["x"]["messages"]]
        ids_b = [m["id"] for m in b.vivantes()["x"]["messages"]]
        assert ids_a == ["m1", "m2", "m3"], "A doit voir la question écrite sur B"
        assert ids_b == ids_a, "les deux appareils doivent converger à l'identique"
        assert a.vivantes()["x"] == b.vivantes()["x"]

    def test_un_conflit_est_rejoue(self, poste, vps):
        """§4.5 : comparer-et-échanger sur ``rev`` ; un conflit rend
        ``current``, que l'appareil ingère avant de rejouer. Échec évité :
        une poussée qui écraserait une écriture qu'elle n'a pas vue."""
        a, b = _deux_appareils(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "Premier", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        a.cycle()
        b.cycle()
        a.magasin.upsert(
            conversation("x", "Fil", [m1, message("ma", "user", "de A", t + 5)], t + 5)
        )
        b.magasin.upsert(
            conversation("x", "Fil", [m1, message("mb", "user", "de B", t + 6)], t + 6)
        )
        jeton_b = b.service.jeton_de_session()
        declenche = []

        def a_pousse_pendant_le_tirage_de_b(requete, reponse):
            # A pousse ENTRE le tirage et la poussée de B : la poussée de B
            # part avec une ``baseRev`` dépassée.
            if (
                not declenche
                and requete.chemin.startswith("/api/v1/sync/changes")
                and requete.en_tetes.get("authorization") == f"Bearer {jeton_b}"
            ):
                declenche.append(True)
                assert a.cycle() == "upToDate"
            return None

        vps.falsifier = a_pousse_pendant_le_tirage_de_b
        assert b.cycle() == "upToDate"
        vps.falsifier = None
        assert declenche, "le scénario doit avoir fait pousser A pendant B"
        poussees_b = [
            p
            for r, p in zip(
                [r for r in vps.requetes if r.chemin == "/api/v1/sync/push"],
                _poussees(vps),
                strict=True,
            )
            if r.en_tetes.get("authorization") == f"Bearer {jeton_b}"
        ]
        assert len(poussees_b) == 2, "B doit avoir rejoué sa poussée après le conflit"
        assert [i["baseRev"] for i in poussees_b[0]["items"]] == [1]
        assert [i["baseRev"] for i in poussees_b[1]["items"]] == [2], (
            "le rejeu part de la révision que le conflit a rendue"
        )
        a.cycle()
        ids = sorted(m["id"] for m in a.vivantes()["x"]["messages"])
        assert ids == ["m1", "ma", "mb"], "aucune des deux écritures n'est perdue"
        assert a.vivantes()["x"] == b.vivantes()["x"]

    def test_le_seq_reste_stable_au_second_cycle(self, poste, vps):
        """§4.3 : sans écriture, un second cycle ne pousse rien. Échec
        évité : un moteur qui repousserait l'écho de ses propres écritures
        à chaque tirage, et ferait tourner le ``seq`` du VPS à vide."""
        a, b = _deux_appareils(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "a", t)], t))
        a.cycle()
        b.cycle()
        a.cycle()
        seq = _seq_du_compte(vps)
        poussees = len(_poussees(vps))
        for p in (a, b, a, b):
            assert p.cycle() == "upToDate"
        assert _seq_du_compte(vps) == seq, "le seq du VPS ne doit plus bouger"
        assert len(_poussees(vps)) == poussees, "aucune poussée sans écriture"
        assert b.statut_synchro()["pendingCount"] == 0

    def test_l_audio_est_retire_sans_boucle(self, poste, vps):
        """§4.7 : ``messages[].audio`` désigne cette machine ; il ne part
        pas, et l'empreinte se calcule sur la projection. Échec évité : un
        appareil qui porte l'audio repousserait la conversation à chaque
        cycle."""
        a, b = _deux_appareils(poste, vps)
        t = vps.horloge()
        avec_audio = message(
            "m", "user", "dicté", t, audio="http://127.0.0.1:8000/v1/audio/abc"
        )
        a.magasin.upsert(conversation("x", "Dicté", [avec_audio], t))
        a.cycle()
        assert "audio" not in _clair_serveur(a, vps, "x")["data"]["messages"][0]
        b.cycle()
        assert "audio" not in b.vivantes()["x"]["messages"][0]
        assert a.vivantes()["x"]["messages"][0]["audio"], "A garde son audio local"
        poussees = len(_poussees(vps))
        a.cycle()
        a.cycle()
        assert len(_poussees(vps)) == poussees, "l'audio ne doit pas faire boucler"


# ----------------------------------------------------------------------
# Suppressions
# ----------------------------------------------------------------------


class TestSuppressions:
    def test_une_suppression_se_propage(self, poste, vps):
        """§4.6 : la tombale part comme un objet chiffré, et l'autre appareil
        l'applique par ``appliquer_tombale``."""
        a, b = _deux_appareils(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "a", t)], t))
        a.cycle()
        b.cycle()
        assert "x" in b.vivantes()
        vps.horloge.avancer(1000)
        date = a.magasin.delete("x")
        a.cycle()
        assert b.cycle() == "upToDate"
        assert "x" not in b.vivantes(), "la suppression faite sur A doit atteindre B"
        assert b.tombales()["x"] == date, "même date de tombale partout"

    @pytest.mark.parametrize("suppression_apres", [True, False])
    def test_suppression_contre_modification_concurrente(
        self, poste, vps, suppression_apres
    ):
        """§4.6, règle d'``upsert`` : la tombale gagne si ``deletedAt >=
        updatedAt``, sinon la conversation revient — et les deux appareils
        tranchent PAREIL. Échec évité : deux appareils qui divergent, l'un
        affichant la conversation, l'autre non."""
        a, b = _deux_appareils(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "a", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        a.cycle()
        b.cycle()
        vps.horloge.avancer(10_000)
        if suppression_apres:
            b.magasin.upsert(
                conversation(
                    "x", "Fil", [m1, message("m2", "user", "b", t + 5000)], t + 5000
                )
            )
            a.magasin.delete("x")  # datée t + 10 000
        else:
            a.magasin.delete("x")  # datée t + 10 000
            b.magasin.upsert(
                conversation(
                    "x", "Fil", [m1, message("m2", "user", "b", t + 20_000)], t + 20_000
                )
            )
        for p in (a, b, a, b):
            p.cycle()
        if suppression_apres:
            assert "x" not in a.vivantes() and "x" not in b.vivantes(), (
                "une suppression postérieure à la modification l'emporte partout"
            )
        else:
            assert "x" in a.vivantes() and "x" in b.vivantes(), (
                "une modification que la suppression n'a pas vue la fait revenir"
            )
            assert a.vivantes()["x"] == b.vivantes()["x"]

    def test_un_appareil_revient_apres_soixante_jours(self, poste, vps):
        """§4.6 : la tombale vit sur le VPS toute la vie du compte ; purgée
        de A après confirmation, elle atteint B revenu 60 jours plus tard.
        Échec évité : purger à l'âge seul, et laisser B ressusciter la
        conversation depuis sa vieille copie."""
        a, b = _deux_appareils(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("x", "Supprimé", [message("m", "user", "x", t)], t)
        )
        a.magasin.upsert(conversation("y", "Gardé", [message("n", "user", "y", t)], t))
        a.cycle()
        b.cycle()
        vps.horloge.avancer(1000)
        a.magasin.delete("x")
        assert a.cycle() == "upToDate"
        # B, éteint, modifie « y » hors ligne.
        b.magasin.upsert(
            conversation(
                "y",
                "Gardé",
                [
                    message("n", "user", "y", t),
                    message("o", "user", "hors ligne", t + 2),
                ],
                t + 2000,
                cree=t,
            )
        )
        vps.horloge.avancer(41 * JOUR_MS)
        assert a.magasin.purger_tombales() == 1, (
            "confirmée par le serveur, la tombale de 41 jours se purge sur A"
        )
        assert "x" not in a.tombales()
        vps.horloge.avancer(19 * JOUR_MS)
        assert b.cycle() == "upToDate"
        assert "x" not in b.vivantes(), "B apprend la suppression après 60 jours"
        a.cycle()
        assert "x" not in a.vivantes(), "A ne voit pas revenir ce qu'il a supprimé"
        assert [m["id"] for m in a.vivantes()["y"]["messages"]] == ["n", "o"], (
            "la modification faite hors ligne par B atteint A"
        )

    def test_une_tombale_non_confirmee_ne_se_purge_pas(self, poste, vps):
        """§4.6 : la purge est bornée par la CONFIRMATION. Échec évité : une
        tombale exportée mais jamais acceptée par le serveur, purgée à 30
        jours, rendue au premier tirage de la copie distante."""
        a, _b = _deux_appareils(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        a.cycle()
        vps.horloge.avancer(1000)
        a.magasin.delete("x")
        a.moteur._exporter(  # noqa: SLF001 - l'export seul, sans poussée
            _registre(a)
        )
        plancher = _registre(a).plancher_suppression("conversations", "x")
        assert plancher == a.tombales()["x"], (
            "l'export relève le plancher de suppression, avant toute poussée"
        )
        vps.horloge.avancer(41 * JOUR_MS)
        assert a.magasin.purger_tombales() == 0, (
            "une tombale non confirmée par le serveur doit survivre"
        )
        assert "x" in a.tombales()


class TestPeutPurger:
    """§4.6 : les TROIS conditions de ``peut_purger``, chacune seule. Une
    tombale confirmée, puis une seule condition défaite : la purge refuse."""

    def _confirmee(self, poste, vps) -> tuple[Poste, int]:
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        a.cycle()
        vps.horloge.avancer(1000)
        date = a.magasin.delete("x")
        assert a.cycle() == "upToDate"
        assert a.moteur.peut_purger("x", date), "témoin : confirmée, elle se purge"
        return a, date

    def test_une_ligne_sortante_empeche_la_purge(self, poste, vps):
        """Condition 1 — échec évité : purger ce qui doit encore partir."""
        a, date = self._confirmee(poste, vps)
        _registre(a).ajouter_sortant("conversations", "x", date)
        assert not a.moteur.peut_purger("x", date), "une ligne sortants la retient"

    def test_une_empreinte_qui_n_est_pas_celle_de_la_tombale_empeche_la_purge(
        self, poste, vps
    ):
        """Condition 2 — échec évité : purger une tombale que le serveur n'a
        pas confirmée (il tient une autre version)."""
        a, date = self._confirmee(poste, vps)
        registre = _registre(a)
        connu = registre.connu("conversations", "x")
        registre.noter_connu(
            "conversations",
            "x",
            connu.object_id,
            rev=connu.rev_max,
            seq=connu.seq,
            empreinte_=b"\x00" * 32,
        )
        assert not a.moteur.peut_purger("x", date), (
            "le serveur doit tenir CETTE tombale"
        )

    def test_sans_plancher_de_suppression_la_tombale_reste(self, poste, vps):
        """Condition 3 — échec évité : purger une suppression que plus rien
        ne défendrait contre une vieille copie."""
        a, date = self._confirmee(poste, vps)
        with sqlite3.connect(a.service.etat.chemin) as conn:
            conn.execute("DELETE FROM planchers_suppression")
        assert not a.moteur.peut_purger("x", date), "sans plancher, rien ne part"


def _registre(p: Poste):
    from diapason.compte.synchro import _Registre

    ouverture = p.service.serrure.exiger()
    return _Registre(p.service.etat, ouverture.account_id, ouverture.incarnation)


# ----------------------------------------------------------------------
# Horloges, consentement, cycles concurrents
# ----------------------------------------------------------------------


class TestHorlogesEtCycles:
    def test_une_horloge_decalee_de_dix_minutes(self, poste, vps):
        """§4.9 : entre deux modifications concurrentes, l'appareil en avance
        l'emporte sur les métadonnées ; les messages s'unissent ; l'écart est
        mesuré sur l'en-tête ``Date``. Échec évité : un écart silencieux, ou
        des messages perdus."""
        a = _inscrit(poste, vps)
        b = poste("b", decalage_ms=10 * 60_000)
        b.service.connecter(EMAIL, MDP, False)
        t = vps.horloge()
        m1 = message("m1", "user", "base", t)
        a.magasin.upsert(conversation("x", "Base", [m1], t))
        a.cycle()
        b.cycle()
        a.magasin.upsert(
            conversation(
                "x",
                "Titre de A",
                [m1, message("ma", "user", "A", t + 60_000)],
                t + 60_000,
                cree=t,
            )
        )
        # B écrit AVANT A en temps réel, mais son horloge avance de 10 min.
        b.magasin.upsert(
            conversation(
                "x",
                "Titre de B",
                [m1, message("mb", "user", "B", t + 600_000)],
                t + 600_000,
                cree=t,
            )
        )

        def date_du_vps(_requete, reponse):
            reponse.headers["date"] = time.strftime(
                "%a, %d %b %Y %H:%M:%S GMT", time.gmtime(vps.horloge() / 1000)
            )
            return reponse

        vps.falsifier = date_du_vps
        for p in (a, b, a):
            p.cycle()
        vps.falsifier = None
        assert a.vivantes()["x"] == b.vivantes()["x"], "les deux copies convergent"
        assert a.vivantes()["x"]["title"] == "Titre de B", (
            "sur des métadonnées concurrentes, l'horloge en avance l'emporte"
        )
        assert {m["id"] for m in a.vivantes()["x"]["messages"]} == {"m1", "ma", "mb"}
        ecart = b.service.statut()["clockSkewMs"]
        assert ecart is not None and abs(ecart - 600_000) <= 1000, (
            f"l'écart de B doit être mesuré à 10 min près d'une seconde : {ecart}"
        )

    def test_des_conversations_locales_demandent_le_consentement(self, poste, vps):
        """§3.11 P3 : un appareil qui a déjà des conversations ne les envoie
        qu'après [Ajouter]. Échec évité : partir sans accord."""
        a = _inscrit(poste, vps)
        b = poste("b")
        t = vps.horloge()
        b.magasin.upsert(
            conversation("locale", "À moi", [message("m", "user", "b", t)], t)
        )
        b.service.connecter(EMAIL, MDP, False)
        jeton_b = b.service.jeton_de_session()
        assert b.cycle() == "needsConsent"
        assert b.statut_synchro()["state"] == "needsConsent"
        assert _requetes_de_synchro(vps, jeton_b) == [], (
            "sans consentement, aucune requête de synchronisation ne part"
        )
        b.service.consentir()
        assert b.cycle() == "upToDate"
        assert a.cycle() == "upToDate"
        assert "locale" in a.vivantes(), "après [Ajouter], la conversation arrive"

    def test_deux_cycles_simultanes_ne_perdent_aucune_reexportation(self, poste, vps):
        """§4.3 : « Synchroniser maintenant » et la tâche ne se chevauchent
        jamais, et une écriture faite PENDANT une poussée repart. Échec
        évité : une ligne ``sortants`` effacée par la poussée d'une version
        plus ancienne."""
        a, b = _deux_appareils(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "avant", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        en_vol = threading.Event()
        relache = threading.Event()

        def retenir_la_premiere_poussee(requete, _reponse):
            if requete.chemin == "/api/v1/sync/push" and not en_vol.is_set():
                en_vol.set()
                assert relache.wait(10), "la poussée retenue n'a jamais été relâchée"
            return None

        vps.falsifier = retenir_la_premiere_poussee
        issues: dict[str, str] = {}
        premier = threading.Thread(target=lambda: issues.update(t1=a.cycle()))
        premier.start()
        assert en_vol.wait(10), "la première poussée doit partir"
        a.magasin.upsert(
            conversation(
                "x", "Fil", [m1, message("m2", "user", "pendant", t + 1)], t + 1, cree=t
            )
        )
        second = threading.Thread(
            target=lambda: issues.update(t2=a.moteur.cycle(attente_s=10))
        )
        second.start()
        time.sleep(0.05)
        assert a.moteur.en_cours, "le premier cycle tient encore le verrou"
        relache.set()
        premier.join(10)
        second.join(10)
        vps.falsifier = None
        assert issues == {"t1": "pending", "t2": "upToDate"}, (
            "le premier cycle voit l'écriture arrivée pendant sa poussée et ne "
            "se dit pas « à jour » ; le second la pousse"
        )
        b.cycle()
        assert [m["id"] for m in b.vivantes()["x"]["messages"]] == ["m1", "m2"], (
            "l'écriture faite pendant la poussée doit atteindre l'autre appareil"
        )

    def test_une_reexportation_pendant_la_poussee_survit_a_son_accuse(self, poste, vps):
        """§4.3 : ``DELETE FROM sortants … AND empreinte_poussee = H
        poussée``. Échec évité : une exportation faite PENDANT le vol d'une
        poussée (l'export tourne « toujours, même verrouillé ») dont la
        ligne était effacée par l'accusé de la version plus ancienne — le
        curseur d'export ayant avancé, rien ne la remettait en file.

        Le test d'avant ne l'exerçait pas : sous le verrou, l'export du
        cycle suivant repassait de toute façon (mutation restée verte)."""
        a, b = _deux_appareils(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "avant", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        en_vol = threading.Event()
        relache = threading.Event()

        def retenir_la_premiere_poussee(requete, _reponse):
            if requete.chemin == "/api/v1/sync/push" and not en_vol.is_set():
                en_vol.set()
                assert relache.wait(10), "la poussée retenue n'a jamais été relâchée"
            return None

        vps.falsifier = retenir_la_premiere_poussee
        issues: dict[str, str] = {}
        premier = threading.Thread(target=lambda: issues.update(t1=a.cycle()))
        premier.start()
        assert en_vol.wait(10), "la première poussée doit partir"
        a.magasin.upsert(
            conversation(
                "x", "Fil", [m1, message("m2", "user", "pendant", t + 1)], t + 1, cree=t
            )
        )
        a.moteur._exporter(_registre(a))  # noqa: SLF001 - l'export hors du cycle
        relache.set()
        premier.join(10)
        vps.falsifier = None
        assert issues == {"t1": "upToDate"}
        assert len(_poussees(vps)) == 2, (
            "la ré-exportation faite pendant le vol est restée en file et part "
            "à la passe suivante du MÊME cycle"
        )
        b.cycle()
        assert [m["id"] for m in b.vivantes()["x"]["messages"]] == ["m1", "m2"], (
            "l'écriture faite pendant la poussée atteint l'autre appareil"
        )

    def test_une_ingestion_ne_reveille_pas_le_moteur(self, poste, vps):
        """§4.3 : le crochet ``sur_ecriture`` réveille le moteur pour une
        écriture de la VUE, pas pour l'écho de sa propre ingestion. Échec
        évité : chaque tirage qui ingère déclenchait un second cycle pour
        exporter ce qu'il venait d'écrire."""
        a, b = _deux_appareils(poste, vps)
        reveils: list[bool] = []
        b.moteur.brancher(b.magasin, lambda **k: reveils.append(k["urgent"]))
        b.moteur.eveille = True
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "a", t)], t))
        a.cycle()
        assert b.cycle() == "upToDate"
        assert "x" in b.vivantes(), "B a bien ingéré la conversation de A"
        assert reveils == [], "l'ingestion ne réveille pas le moteur"
        b.magasin.upsert(
            conversation("y", "Locale", [message("n", "user", "b", t + 1)], t + 1)
        )
        assert reveils == [False], "une écriture de la vue le réveille, sans urgence"

    def test_une_incarnation_superieure_dans_meta_pose_account_reset(self, poste, vps):
        """§3.6 : ``meta.incarnation`` au-dessus de celle de l'appareil — une
        réinitialisation a eu lieu ailleurs. Échec évité : pousser sous
        l'incarnation morte, ou dire « Synchronisé »."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "a", t)], t))

        def reinitialise_ailleurs(requete, reponse):
            if requete.chemin.startswith("/api/v1/sync/changes"):
                corps = reponse.json()
                corps["meta"]["incarnation"] = 2
                return reponse_json(200, corps)
            return None

        vps.falsifier = reinitialise_ailleurs
        assert a.cycle() == "accountReset"
        vps.falsifier = None
        assert a.service.statut()["state"] == "accountReset"
        assert _poussees(vps) == [], "rien ne part sous l'incarnation morte"
        assert a.moteur.actif() is False, "le moteur s'arrête jusqu'au geste"


# ----------------------------------------------------------------------
# Portée, réinitialisation, rotation
# ----------------------------------------------------------------------


def _reinitialiser(a: Poste, vps: Vps, nouveau: str = MDP_2) -> None:
    _une_heure_plus_tard(vps)
    avant = vps.nombre(EMAIL, "code_reinitialisation")
    a.service.reinit_demander(EMAIL)
    a.service.reinit_confirmer(
        EMAIL, vps.code(EMAIL, "code_reinitialisation", avant + 1)
    )
    vps.horloge.avancer(7 * JOUR_MS + 1)
    a.service.reinit_demander(EMAIL)
    code = vps.code(EMAIL, "code_reinitialisation", avant + 2)
    rendu = a.service.reinit_terminer(EMAIL, code, nouveau, False)
    a.service.nouvelle_cle_confirmer(extrait(rendu))


def _incarnation_du_vps(vps: Vps) -> int:
    with vps.ctx.base.lecture() as conn:
        return conn.execute("SELECT incarnation FROM comptes").fetchone()[0]


class TestPortee:
    def test_reinitialisation_repousse_tout(self, poste, vps):
        """§4.5 : après ``reset/complete``, le VPS est vide ; la portée
        change, tout repart, et ``upToDate`` n'apparaît qu'une fois les N
        objets confirmés. Échec évité (défaut bloquant de la revue) :
        « Synchronisé » face à un serveur vide."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(
            conversation("c3", "Ancienne", [message("m3", "user", "x", t)], t)
        )
        assert a.cycle() == "upToDate"
        vps.horloge.avancer(1000)
        a.magasin.delete("c3")
        assert a.cycle() == "upToDate"
        vps.horloge.avancer(41 * JOUR_MS)
        assert a.magasin.purger_tombales() == 1, "confirmée, la tombale est purgée"
        assert "c3" not in a.tombales()
        t = vps.horloge()
        for i in range(3):
            a.magasin.upsert(
                conversation(f"c{i}", f"Fil {i}", [message(f"m{i}", "user", "x", t)], t)
            )
        a.magasin.delete("c2")
        assert a.cycle() == "upToDate"
        _reinitialiser(a, vps)
        assert _incarnation_du_vps(vps) == 2
        assert _objets(vps) == [], "reset/complete efface les objets du VPS"
        assert a.statut_synchro()["state"] != "upToDate", (
            "l'état confirmé sous l'incarnation 1 ne vaut pas pour la 2"
        )
        au_moment: list[int] = []
        enregistrer = a.moteur._enregistrer  # noqa: SLF001

        def espion(registre, etat, **arguments):
            if etat == "upToDate":
                au_moment.append(len(_objets(vps)))
            return enregistrer(registre, etat, **arguments)

        a.moteur._enregistrer = espion  # noqa: SLF001
        assert a.cycle() == "upToDate"
        assert au_moment == [4], (
            "les quatre objets (deux vivants, deux tombales) doivent être sur le "
            "VPS AVANT que « Synchronisé » ne soit dit"
        )
        assert _clair_serveur(a, vps, "c2")["deleted"], "la tombale repart aussi"
        assert _clair_serveur(a, vps, "c3")["deleted"], (
            "§4.5 : la suppression PURGÉE du magasin depuis des mois repart aussi, "
            "par son plancher — sans elle, une vieille copie la ressusciterait "
            "sous la nouvelle incarnation"
        )
        with sqlite3.connect(a.service.etat.chemin) as conn:
            anciennes = conn.execute(
                "SELECT COUNT(*) FROM connus WHERE incarnation = 1"
            ).fetchone()[0]
        assert anciennes == 0, "les tables de portée de l'incarnation 1 sont vidées"

    def test_la_connexion_a_un_autre_compte_purge_la_portee(self, poste, vps):
        """§4.4 : « une déconnexion ou un autre compte vide tout ». Échec
        évité : les révisions et empreintes d'un compte jugeant l'autre."""
        c = poste("c")
        inscrire(c.service, vps, email=EMAIL_2)
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        assert a.cycle() == "upToDate"
        premier = a.service.etat.lire("accountId")
        a.service.deconnecter(False)
        a.service.connecter(EMAIL_2, MDP, False)
        assert a.cycle() == "needsConsent"
        a.service.consentir()
        assert a.cycle() == "upToDate"
        with sqlite3.connect(a.service.etat.chemin) as conn:
            comptes = {r[0] for r in conn.execute("SELECT account_id FROM connus")}
        assert premier not in comptes, "rien du premier compte ne reste dans la portée"
        assert c.cycle() == "upToDate"
        assert "x" in c.vivantes(), "les conversations locales partent sous le second"

    def test_une_rotation_en_cours_de_synchronisation_recharge_le_trousseau(
        self, poste, vps
    ):
        """§2.8 : le VPS refuse une poussée d'une autre époque (409
        ``keyEpochChanged``) ; la rotation faite ici, le moteur recharge le
        trousseau et rescelle. Échec évité : un objet scellé sous la DEK que
        l'appareil perdu connaît encore."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        tourne = []

        def rotation_pendant_le_tirage(requete, _reponse):
            if not tourne and requete.chemin.startswith("/api/v1/sync/changes"):
                tourne.append(True)
                _une_heure_plus_tard(vps)
                a.service.changer_mot_de_passe(MDP, MDP_2)
            return None

        vps.falsifier = rotation_pendant_le_tirage
        assert a.cycle() == "upToDate"
        vps.falsifier = None
        epoques = [p["keyEpoch"] for p in _poussees(vps)]
        assert epoques == [1, 2], (
            f"une poussée refusée sous l'époque 1, puis rescellée sous la 2 : {epoques}"
        )
        ((_o, _rev, _seq, blob),) = _objets(vps)
        assert blob[2:6] == (2).to_bytes(4, "big"), "le blob rangé est de l'époque 2"


# ----------------------------------------------------------------------
# Autoréparation, attente de réinitialisation, restauration
# ----------------------------------------------------------------------


def _corrompre(blob: bytes) -> bytes:
    """Même taille, même en-tête : un octet du chiffré retourné."""
    octets = bytearray(blob)
    octets[60] ^= 0xFF
    return bytes(octets)


def _pousser_brut(vps: Vps, jeton: str, corps: dict) -> dict:
    reponse = vps.client.post(
        "/api/v1/sync/push", headers={"Authorization": f"Bearer {jeton}"}, json=corps
    )
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


def _instantane(vps: Vps) -> sqlite3.Connection:
    copie = sqlite3.connect(":memory:")
    with vps.ctx.base.lecture() as conn:
        conn.backup(copie)
    return copie


def _restaurer(vps: Vps, copie: sqlite3.Connection) -> None:
    with vps.ctx.base.lecture() as conn:
        copie.backup(conn)


class TestServeurQuiBouge:
    def test_un_blob_illisible_avec_copie_locale_est_repare_en_un_cycle(
        self, poste, vps
    ):
        """§4.6 : un jeton volé écrase un objet par du bruit ; l'appareil qui
        en a la copie le réécrase aussitôt, une fois. Échec évité : un blob
        illisible qui bloque, ou une réparation qui boucle."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        a.cycle()
        ((object_id, rev, _seq, blob),) = _objets(vps)
        from base64 import urlsafe_b64encode

        _pousser_brut(
            vps,
            a.service.jeton_de_session(),
            {
                "incarnation": 1,
                "keyEpoch": 1,
                "items": [
                    {
                        "objectId": object_id,
                        "baseRev": rev,
                        "blob": urlsafe_b64encode(_corrompre(blob))
                        .decode()
                        .rstrip("="),
                    }
                ],
            },
        )
        assert a.cycle() == "upToDate"
        assert a.statut_synchro()["repairedCount"] == 1
        assert _clair_serveur(a, vps, "x")["data"]["title"] == "Fil", (
            "le serveur doit tenir de nouveau la copie de l'appareil"
        )
        poussees = len(_poussees(vps))
        assert a.cycle() == "upToDate"
        assert len(_poussees(vps)) == poussees, "la réparation ne boucle pas"
        assert a.statut_synchro()["repairedCount"] == 1

    def test_reset_pending_s_affiche_depuis_meta(self, poste, vps):
        """§3.6 : l'attente d'une réinitialisation se lit dans ``meta`` de
        chaque réponse, sur CHAQUE appareil connecté. Échec évité (A3) : une
        réinitialisation lancée par une boîte courriel compromise, que seul
        un courriel annonçait."""
        a, b = _deux_appareils(poste, vps)
        _une_heure_plus_tard(vps)
        avant = vps.nombre(EMAIL, "code_reinitialisation")
        b.service.reinit_demander(EMAIL)
        effectif = b.service.reinit_confirmer(
            EMAIL, vps.code(EMAIL, "code_reinitialisation", avant + 1)
        )["effectiveAt"]
        assert a.service.statut()["state"] == "unlocked", "A ne le sait pas encore"
        a.cycle()
        statut = a.service.statut()
        assert statut["state"] == "resetPending", "A l'apprend par meta"
        assert statut["pendingResetAt"] == effectif
        a.service.reinit_annuler()
        b.cycle()
        assert b.service.statut()["state"] == "unlocked", (
            "une annulation faite ailleurs efface l'attente au prochain tirage"
        )

    def test_une_restauration_logique_garde_les_planchers(self, poste, vps):
        """§3.10 et §6 bis : ``generation`` nouvelle, ``serverSeq`` qui
        recule — le curseur SEUL revient à 0, les planchers restent, et ce
        qui manque repart. Échec évité : une restauration lue comme un
        retour arrière de toute la machine, ou des écritures perdues."""
        a, b = _deux_appareils(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "v1", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        a.cycle()
        copie = _instantane(vps)
        a.magasin.upsert(
            conversation(
                "x", "Fil", [m1, message("m2", "user", "v2", t + 1)], t + 1, cree=t
            )
        )
        a.magasin.upsert(conversation("z", "Neuf", [message("z", "user", "z", t)], t))
        a.cycle()
        rev_max = _registre(a).connu("conversations", "x").rev_max
        assert rev_max == 2
        # ``diapason-comptes-admin restaurer`` : copie, sessions vidées,
        # generation nouvelle (§3.10).
        _restaurer(vps, copie)
        with vps.ctx.base.transaction() as conn:
            conn.execute("DELETE FROM sessions")
            conn.execute(
                "UPDATE meta SET valeur = 'restauree' WHERE cle = 'generation'"
            )
            ecriture(conn)
        assert a.cycle() == "sessionExpired"
        a.service.connecter(EMAIL, MDP, False)
        assert a.cycle() == "upToDate", "une restauration n'est PAS un retour arrière"
        assert _registre(a).connu("conversations", "x").rev_max >= rev_max, (
            "le plancher de révision ne descend pas sur une generation nouvelle"
        )
        assert b.cycle() == "sessionExpired", "les sessions ont été vidées"
        b.service.connecter(EMAIL, MDP, False)
        b.cycle()
        assert [m["id"] for m in b.vivantes()["x"]["messages"]] == ["m1", "m2"]
        assert "z" in b.vivantes(), "ce que la copie ne tenait pas a été repoussé"

    def test_un_retour_arriere_de_toute_la_machine(self, poste, vps):
        """§3.10 : même ``generation``, ``serverSeq`` sous le curseur —
        ``serverRolledBack``, rotation, puis tout repoussé. Échec évité : un
        appareil qui prend l'état d'avant pour l'état courant."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        m1 = message("m1", "user", "v1", t)
        a.magasin.upsert(conversation("x", "Fil", [m1], t))
        a.cycle()
        copie = _instantane(vps)
        a.magasin.upsert(
            conversation(
                "x", "Fil", [m1, message("m2", "user", "v2", t + 1)], t + 1, cree=t
            )
        )
        a.magasin.upsert(conversation("y", "Après", [message("y", "user", "y", t)], t))
        a.cycle()
        _restaurer(vps, copie)
        with vps.ctx.base.lecture() as conn:
            assert generation(conn) == a.service.etat.lire("generation"), (
                "une restauration de toute la machine ne change pas generation"
            )
        assert a.cycle() == "serverRolledBack"
        assert a.service.statut()["state"] == "serverRolledBack"
        assert a.moteur.actif() is False, "le moteur s'arrête jusqu'au geste"
        # Le parcours dit à l'utilisateur : se reconnecter, puis la rotation
        # (ici avec le même mot de passe, comme le demande le §3.10).
        a.service.connecter(EMAIL, MDP, False)
        # Se reconnecter NE SUFFIT PAS (24/09/2026 : ``_installer`` effaçait
        # ``etatCompte`` et le cycle suivant disait « Synchronisé » face au
        # serveur revenu en arrière, sans rotation).
        avant = len(_requetes_de_synchro(vps))
        assert a.cycle() == "serverRolledBack", "pas de synchronisation sans rotation"
        assert a.moteur.actif() is False, "le moteur reste arrêté"
        assert a.statut_synchro()["state"] == "serverRolledBack"
        assert len(_requetes_de_synchro(vps)) == avant, "aucune requête de synchro"
        _une_heure_plus_tard(vps)
        a.service.changer_mot_de_passe(MDP, MDP)
        assert a.moteur.actif() is True, "la rotation relance le moteur"
        assert a.cycle() == "upToDate"
        c = poste("c")
        c.service.connecter(EMAIL, MDP, False)
        assert c.cycle() == "upToDate"
        assert [m["id"] for m in c.vivantes()["x"]["messages"]] == ["m1", "m2"]
        assert "y" in c.vivantes(), "ce que le retour arrière avait perdu est revenu"


# ----------------------------------------------------------------------
# Un geste pendant un cycle : déconnexion, autre compte, verrouillage
# ----------------------------------------------------------------------


def _pendant_le_tirage(p: Poste, geste) -> None:
    """``geste`` joué une fois, juste après la première réponse que le
    cycle reçoit — le clic de la personne pendant que la requête vole."""
    vraie = p.moteur._requete  # noqa: SLF001
    fait: list[bool] = []

    def requete(registre, chemin, *, jeton):
        reponse = vraie(registre, chemin, jeton=jeton)
        if not fait:
            fait.append(True)
            geste()
        return reponse

    p.moteur._requete = requete  # noqa: SLF001


class TestGestePendantUnCycle:
    def test_une_deconnexion_en_plein_tirage_ne_recree_pas_etat_key(self, poste, vps):
        """§4.4 « une déconnexion vide tout ». Échec évité (contre-épreuve du
        24/09/2026) : le cycle, qui ne tient pas le verrou d'opération du
        service, RECRÉAIT ``etat.key`` à sa première écriture après la
        destruction — sans aucun compte, le magasin ne purgeait plus ses
        tombales à l'âge, chaque démarrage construisait le service et chaque
        fermeture de l'app attendait le serveur local."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        assert a.cycle() == "upToDate"
        a.magasin.upsert(conversation("y", "Autre", [message("n", "user", "y", t)], t))
        _pendant_le_tirage(a, lambda: a.service.deconnecter(False))
        assert a.cycle() == "disabled"
        assert not a.service.etat.existe(), "etat.key reste détruit"
        assert not a.magasin._compte_present(), (  # noqa: SLF001
            "sans compte, le magasin purge de nouveau ses tombales à l'âge"
        )

    def test_un_401_apres_la_deconnexion_ne_recree_pas_etat_key(self, poste, vps):
        """§3.7 : « Se déconnecter » ferme la session sur le VPS ; la requête
        suivante du cycle reçoit 401. Échec évité : le traitement du 401
        (``_session_perdue``) écrivait ``etatCompte`` dans un ``etat.key``
        qu'il recréait."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        assert a.cycle() == "upToDate"
        a.magasin.upsert(conversation("y", "Autre", [message("n", "user", "y", t)], t))
        fait: list[bool] = []

        def deconnecte_pendant_le_vol(requete, _reponse):
            # La requête du tirage est partie ; « Se déconnecter » ferme la
            # session sur le VPS et détruit etat.key avant qu'elle n'arrive :
            # le VPS la refuse.
            if fait or not requete.chemin.startswith("/api/v1/sync/changes"):
                return None
            fait.append(True)
            a.service.deconnecter(False)
            return reponse_json(401, {"error": {"code": "sessionRevoked"}})

        vps.falsifier = deconnecte_pendant_le_vol
        assert a.cycle() == "disabled"
        vps.falsifier = None
        assert fait, "le 401 a bien été servi après la déconnexion"
        assert not a.service.etat.existe(), "etat.key reste détruit"

    def test_un_autre_compte_n_herite_pas_du_server_seq_max(self, poste, vps):
        """§4.4 : « un autre compte vide tout ». Échec évité (contre-épreuve
        du 24/09/2026) : ``serverSeqMax`` et ``generation`` d'un compte
        précédent, laissés dans ``etat.key``, jugeaient le compte suivant —
        son ``seq`` plus petit sur le même VPS se lisait ``serverRolledBack``,
        une fausse alerte de sécurité jusqu'à une rotation."""
        a = _inscrit(poste, vps)
        premier = a.service.etat.lire("accountId")
        a.service.deconnecter(False)
        _une_heure_plus_tard(vps)
        inscrire(a.service, vps, email=EMAIL_2)
        a.service.consentir()
        with vps.ctx.base.lecture() as conn:
            generation_du_vps = generation(conn)
        a.service.etat.ecrire(
            synchroPortee=f"{premier}|1",
            generation=generation_du_vps,
            serverSeqMax=10**6,
        )
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        assert a.cycle() == "upToDate", "aucun retour arrière pour le compte neuf"
        assert int(a.service.etat.lire("serverSeqMax")) < 10**6

    def test_verrouiller_pendant_un_cycle_arrete_la_poussee(self, poste, vps):
        """§4.3 étape 2, et A7 : verrouillé, rien ne se scelle. Échec évité
        (contre-épreuve du 24/09/2026) : le cycle poussait jusqu'au bout avec
        l'ouverture prise au départ, pendant que le statut disait
        ``paused``."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        _pendant_le_tirage(a, a.service.verrouiller)
        assert a.cycle() == "paused"
        assert _poussees(vps) == [], "aucun lot ne part après le verrouillage"
        assert a.statut_synchro()["state"] == "paused"


class TestComptesFermes:
    """§6 bis : ``COMPTES_OUVERTS = False``. Le moteur ne touche au réseau
    que si le service a lu des comptes ouverts."""

    def test_comptes_fermes_le_moteur_ne_s_eveille_pas(self, poste, vps):
        """Échec évité (contre-épreuve du 24/09/2026) : ``actif()`` ne lisait
        que la serrure et ``etat.key`` — un compte mémorisé, ou hérité d'un
        banc, contactait le VPS alors que les comptes sont fermés."""
        a = _inscrit(poste, vps)
        assert a.moteur.actif() is True, "témoin : comptes ouverts, il s'éveille"
        a.service._ouverts = False  # noqa: SLF001 - le défaut réel
        assert a.moteur.actif() is False

    def test_comptes_fermes_le_serveur_local_ne_construit_aucun_moteur(
        self, tmp_path, monkeypatch
    ):
        """Échec évité : le premier sondage de ``/v1/account/status`` par une
        vue importait et construisait le moteur, comptes fermés compris —
        et un ``etat.key`` hérité faisait construire le service à chaque
        démarrage."""
        from types import SimpleNamespace

        from diapason.compte import service as module_service
        from diapason.server import app as module_app

        magasin = ConversationsStore(tmp_path / "conversations.db")
        try:
            veilleur = module_app._VeilleurSynchro(magasin)  # noqa: SLF001
            ferme = SimpleNamespace(comptes_ouverts=False, moteur=None)
            monkeypatch.setattr(module_app, "_service_compte", lambda *_a: ferme)
            service = module_app._service_synchronise(None, magasin, veilleur)  # noqa: SLF001
            assert service.moteur is None, "comptes fermés : aucun moteur"
            assert veilleur.service is None

            construits: list[bool] = []
            application = SimpleNamespace(
                state=SimpleNamespace(compte=lambda: construits.append(True))
            )
            monkeypatch.setattr(module_service, "COMPTES_OUVERTS", False)
            module_app._ouvrir_le_compte(application)  # noqa: SLF001
            assert construits == [], "un etat.key hérité ne construit rien"
            monkeypatch.setattr(module_service, "COMPTES_OUVERTS", True)
            module_app._ouvrir_le_compte(application)  # noqa: SLF001
            assert construits == [True], "témoin : comptes ouverts, il s'ouvre"
        finally:
            magasin.close()


class TestSynchroniserMaintenant:
    """P10 : ``POST /v1/account/sync-now``, de la route au VPS."""

    def _client(self, p: Poste):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from diapason.server.compte_routes import AccesCompte, create_compte_router

        app = FastAPI()
        app.include_router(create_compte_router(AccesCompte(lambda: p.service)))
        return TestClient(app)

    def test_sync_now_pousse_les_ecritures_en_attente(self, poste, vps):
        """Échec évité : une route qui rendrait 200 sans avoir rien poussé —
        la fermeture de l'app croirait ses modifications parties."""
        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        assert a.statut_synchro()["pendingCount"] == 1
        reponse = self._client(a).post("/v1/account/sync-now", json={})
        assert reponse.status_code == 200
        synchro = reponse.json()["status"]["sync"]
        assert synchro["state"] == "upToDate"
        assert synchro["pendingCount"] == 0
        assert len(_objets(vps)) == 1, "la conversation est sur le VPS"
        assert synchro["serverSeq"] == _seq_du_compte(vps), (
            "le serverSeq affiché est celui que le VPS a rendu à la poussée"
        )

    def test_sync_now_rend_syncing_si_un_cycle_tient_le_verrou(self, poste, vps):
        """§4.3 : les deux ne se chevauchent jamais, et l'attente est bornée
        (``ATTENTE_SYNCHRO_MAINTENANT_S``) : la fermeture n'a que 3 s. La
        réponse le DIT — ``syncing`` et ce qui reste en attente."""
        from diapason.compte.service import ATTENTE_SYNCHRO_MAINTENANT_S

        a = _inscrit(poste, vps)
        t = vps.horloge()
        a.magasin.upsert(conversation("x", "Fil", [message("m", "user", "x", t)], t))
        verrou = a.moteur._exclusif  # noqa: SLF001
        assert verrou.acquire()
        a.moteur.en_cours = True
        try:
            debut = time.monotonic()
            reponse = self._client(a).post("/v1/account/sync-now", json={})
            duree = time.monotonic() - debut
        finally:
            a.moteur.en_cours = False
            verrou.release()
        assert reponse.status_code == 200
        synchro = reponse.json()["status"]["sync"]
        assert synchro["state"] == "syncing", "la réponse dit que rien n'est confirmé"
        assert synchro["pendingCount"] == 1
        assert ATTENTE_SYNCHRO_MAINTENANT_S <= duree < 2.5, f"attente bornée : {duree}"
        assert _objets(vps) == []


# ----------------------------------------------------------------------
# Le moteur endormi (exigence du 24/09/2026)
# ----------------------------------------------------------------------


async def _attendre_pour_toujours(*_a: Any, **_k: Any) -> None:
    await asyncio.Event().wait()


class TestMoteurEndormi:
    def test_sans_compte_le_serveur_local_ne_fait_rien_et_se_ferme_aussitot(
        self, monkeypatch
    ):
        """Exigence de la session principale : sans compte déverrouillé,
        aucune requête, aucune tâche qui boucle, aucun service construit,
        et une fermeture qui n'attend pas. Échec évité : faire payer à
        chaque lancement et à chaque fermeture une synchronisation que
        personne n'a — les comptes sont fermés (``COMPTES_OUVERTS``)."""
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from diapason.compte import transport as module_transport
        from diapason.core.config import DiapasonConfig
        from diapason.mesh import discovery
        from diapason.server import app as module_app
        from diapason.server import prechauffage

        # Les AUTRES tâches du lifespan sont neutralisées : ce test ne
        # mesure que la synchronisation.
        monkeypatch.setattr(module_app, "_prewarm_local_model", _attendre_pour_toujours)
        monkeypatch.setattr(module_app, "_mesh_heartbeat", _attendre_pour_toujours)
        monkeypatch.setattr(discovery, "run_discovery", _attendre_pour_toujours)
        monkeypatch.setattr(
            prechauffage, "entretenir_le_prefixe", _attendre_pour_toujours
        )
        envois: list[str] = []
        monkeypatch.setattr(
            module_transport.Transport,
            "_envoyer",
            lambda _self, methode, chemin, **_k: envois.append(f"{methode} {chemin}"),
        )
        engine = MagicMock()
        engine.engine_id = "mock"
        cfg = DiapasonConfig()
        cfg.analytics.enabled = False
        cfg.traces.enabled = False
        app = module_app.create_app(engine, "test-model", config=cfg)
        veilleur = app.state.synchro_compte
        assert not veilleur.compte_sur_le_disque(), "le banc n'a aucun compte"
        # « Aucun fil qui tourne pour rien » se MESURE (24/09/2026 : une tâche
        # qui sondait le disque par ``asyncio.to_thread`` toutes les 20 ms
        # laissait ce test vert) : un seul regard sur le disque, et pas
        # d'exécuteur par défaut démarré sur la boucle du serveur.
        regards: list[bool] = []
        compte_sur_le_disque = module_app._VeilleurSynchro.compte_sur_le_disque

        def compter_les_regards(self_):
            regards.append(True)
            return compte_sur_le_disque(self_)

        monkeypatch.setattr(
            module_app._VeilleurSynchro, "compte_sur_le_disque", compter_les_regards
        )
        with TestClient(app):
            tache = app.state.tache_synchro
            boucle = veilleur._boucle  # noqa: SLF001
            time.sleep(0.2)
            assert not tache.done(), "la tâche existe et attend"
            assert veilleur.tours == 0, "elle n'a pas fait un seul tour"
            assert veilleur.reveils == 0, "rien ne l'a réveillée"
            assert veilleur.service is None, "aucun service de compte construit"
            assert app.state.compte._service is None  # noqa: SLF001
            assert regards == [True], f"un seul regard sur le disque : {regards}"
            assert boucle is not None
            assert boucle._default_executor is None, (  # noqa: SLF001
                "aucun fil démarré pour la synchronisation"
            )
            debut = time.monotonic()
        duree = time.monotonic() - debut
        assert tache.done(), "la fermeture termine la tâche"
        assert duree < 1.0, f"la fermeture ne doit pas attendre ({duree:.3f} s)"
        assert envois == [], f"aucune requête vers le serveur de comptes : {envois}"

    def test_la_tache_endormie_s_annule_sur_le_champ(self, tmp_path):
        """La tâche endormie n'est qu'un ``await`` sur un événement : son
        annulation la termine dans la même itération de boucle."""
        from types import SimpleNamespace

        from diapason.server.app import _synchroniser_le_compte, _VeilleurSynchro

        magasin = SimpleNamespace(chemin=str(tmp_path / "conversations.db"))
        application = SimpleNamespace(
            state=SimpleNamespace(synchro_compte=_VeilleurSynchro(magasin))
        )

        async def scenario() -> float:
            tache = asyncio.create_task(_synchroniser_le_compte(application))
            for _ in range(20):
                await asyncio.sleep(0)
            assert not tache.done()
            assert application.state.synchro_compte.tours == 0
            debut = time.monotonic()
            tache.cancel()
            with pytest.raises(asyncio.CancelledError):
                await tache
            return time.monotonic() - debut

        duree = asyncio.run(scenario())
        assert duree < 0.05, f"l'annulation doit être immédiate ({duree:.3f} s)"

    def test_une_ouverture_reveille_le_moteur_puis_il_se_rendort(self, tmp_path):
        """Le service réveille le moteur à l'ouverture (``sur_ouverture``) ;
        verrouillé, il se rendort sans délai — ni sondage ni cycle."""
        from types import SimpleNamespace

        from diapason.server.app import _synchroniser_le_compte, _VeilleurSynchro

        class FauxMoteur:
            def __init__(self) -> None:
                self.ouvert = True
                self.cycles = 0
                self.eveille = False
                self.derniere_ecriture = 0.0

            def actif(self) -> bool:
                return self.ouvert

            def brancher(self, *_a: Any) -> None:
                pass

            def cycle(self) -> str:
                self.cycles += 1
                self.ouvert = False  # verrouillé juste après
                return "upToDate"

            def purger_si_du(self) -> int:
                return 0

            def attente_avant_suite(self) -> float:
                return 0.0

            def repli_restant(self) -> float:
                return 0.0

            def _mono(self) -> float:
                return time.monotonic()

        magasin = SimpleNamespace(chemin=str(tmp_path / "conversations.db"))
        veilleur = _VeilleurSynchro(magasin)
        moteur = FauxMoteur()
        application = SimpleNamespace(state=SimpleNamespace(synchro_compte=veilleur))

        async def scenario() -> None:
            tache = asyncio.create_task(_synchroniser_le_compte(application))
            await asyncio.sleep(0.01)
            assert moteur.cycles == 0
            veilleur.service = SimpleNamespace(moteur=moteur)
            veilleur.reveiller()
            for _ in range(200):
                await asyncio.sleep(0.005)
                if moteur.cycles:
                    break
            await asyncio.sleep(0.05)
            assert moteur.cycles == 1, "un réveil, un cycle — puis plus rien"
            assert moteur.eveille is False, "verrouillé, le moteur se rendort"
            tache.cancel()
            with pytest.raises(asyncio.CancelledError):
                await tache

        asyncio.run(scenario())
