"""Le magasin des conversations face à plusieurs horloges.

compte-chiffre.md §6, étape 2. Jusqu'au 24/09/2026, ``ConversationsStore``
supposait une seule horloge : toutes les vues tournaient sur la même
machine. Le moteur de synchronisation y fera entrer des copies datées par
d'autres appareils, et trois défauts attendaient ce jour-là :

- ``delete`` datait sa tombale « maintenant » : une copie venue d'un
  appareil en avance gagnait contre la suppression qui l'avait effacée ;
- aucune voie n'appliquait une suppression distante avec la règle d'upsert ;
- la purge effaçait toute tombale de plus de 30 jours, confirmée ou non :
  un appareil éteint 40 jours ressuscitait la conversation supprimée.

Les contre-épreuves du même jour en ont trouvé cinq de plus : un
``peut_purger`` posé après l'ouverture n'était jamais consulté, une tombale
distante était « vieille » dès son arrivée, une date à la borne d'int64
rendait ``delete`` impossible, et deux gardes (id vide, date de la tombale
à la purge) n'étaient exercées par rien. Une sixième — une suppression
datée par une horloge en avance efface des messages écrits après elle —
est figée ici telle qu'elle est, en attendant l'étape 10.

Sans compte, les deux crochets valent None et rien ne doit bouger : les
tests de ``test_conversations_routes.py`` passent tels quels, et ceux d'ici
qui portent « sans compte » le redisent au niveau du magasin.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Dict, List, Set, Tuple

import pytest

from diapason.server.conversations_store import ConversationsStore

_MS_PAR_JOUR = 24 * 3600 * 1000


def _maintenant_ms() -> int:
    return int(time.time() * 1000)


def _conv(conv_id: str = "c1", *, updated: int = 1000, title: str = "Fil") -> dict:
    return {
        "id": conv_id,
        "title": title,
        "createdAt": 500,
        "updatedAt": updated,
        "model": "qwen3",
        "pinned": False,
        "messages": [
            {"id": "m1", "role": "user", "content": "salut", "timestamp": 600}
        ],
    }


def _vieillir(db_path, conv_id: str, jours: int) -> int:
    """Recule la tombale de ``conv_id`` de ``jours`` jours ; rend sa date."""
    date = _maintenant_ms() - jours * _MS_PAR_JOUR
    db = sqlite3.connect(db_path)
    try:
        db.execute(
            "UPDATE conversations SET deleted_at = ? WHERE id = ?", (date, conv_id)
        )
        db.commit()
    finally:
        db.close()
    return date


class _EtatDuMoteur:
    """Les trois tables que §4.6 consulte avant de purger, en mémoire.

    Le moteur réel (étape 10) les lira dans ``compte/etat.key`` ; ici on ne
    teste que le contrat que le magasin lui offre.
    """

    def __init__(self) -> None:
        self.sortants: Set[str] = set()
        self.confirmees: Dict[str, int] = {}  # connus.empreinte == H(tombale)
        self.planchers: Dict[str, int] = {}
        self.questions: List[Tuple[str, int]] = []

    def exporter(self, conv_id: str, deleted_at: int) -> None:
        self.sortants.add(conv_id)
        self.planchers[conv_id] = deleted_at

    def confirmer(self, conv_id: str, deleted_at: int) -> None:
        self.sortants.discard(conv_id)
        self.confirmees[conv_id] = deleted_at

    def peut_purger(self, conv_id: str, deleted_at: int) -> bool:
        self.questions.append((conv_id, deleted_at))
        return (
            conv_id not in self.sortants
            and self.confirmees.get(conv_id) == deleted_at
            and conv_id in self.planchers
        )


@pytest.fixture
def db_path(tmp_path):
    # Jamais ~/.diapason : la base de test vit dans tmp_path.
    return tmp_path / "conversations.db"


@pytest.fixture
def compte(db_path):
    """Un compte existe : ``compte/etat.key`` à côté de la base (§2.10)."""
    etat = db_path.parent / "compte" / "etat.key"
    etat.parent.mkdir()
    etat.write_bytes(b"")
    return etat


def _vieillir_la_pose(db_path, conv_id: str, jours: int) -> None:
    """Recule l'heure LOCALE de pose d'une tombale distante."""
    db = sqlite3.connect(db_path)
    try:
        db.execute(
            "UPDATE tombales_posees SET posee_le_ms = ? WHERE id = ?",
            (_maintenant_ms() - jours * _MS_PAR_JOUR, conv_id),
        )
        db.commit()
    finally:
        db.close()


@pytest.fixture
def store(db_path):
    magasin = ConversationsStore(db_path)
    yield magasin
    magasin.close()


class TestLaDatationDeLaSuppression:
    def test_une_tombale_gagne_contre_une_copie_datee_dans_le_futur(self, store):
        """§4.6 (datation), §100 — pc-bureau, en avance d'un jour, pousse sa
        copie ; l'utilisateur la supprime ici. Datée « maintenant », la
        tombale perdait contre la copie même qu'elle effaçait, et la
        poussée suivante de cette copie ressuscitait la conversation."""
        futur = _maintenant_ms() + _MS_PAR_JOUR
        store.upsert(_conv(updated=futur))

        deleted_at = store.delete("c1")
        reponse = store.upsert(_conv(updated=futur))

        assert deleted_at > futur, (
            "la tombale doit être datée au-dessus de la copie qu'elle a vue"
        )
        assert reponse == {"deleted": True, "deletedAt": deleted_at}, (
            "la copie en avance déjà vue ne doit pas ressusciter la conversation"
        )
        vivantes, tombales, _ = store.list(None)
        assert vivantes == [], "aucune conversation vivante ne doit rester"
        assert tombales == [{"id": "c1", "deletedAt": deleted_at}], (
            "la tombale doit voyager avec sa date au-dessus de la copie"
        )

    def test_sans_compte_une_suppression_ordinaire_reste_datee_maintenant(self, store):
        """§6 étape 2 (comportement inchangé) — sur une seule horloge, la
        copie stockée est dans le passé : la tombale doit porter l'heure de
        la suppression, comme avant, et non ``updatedAt + 1``."""
        store.upsert(_conv(updated=1000))

        avant = _maintenant_ms()
        deleted_at = store.delete("c1")
        apres = _maintenant_ms()

        assert avant <= deleted_at <= apres, (
            "une suppression sur une seule horloge doit rester datée maintenant"
        )

    def test_resupprimer_ne_fait_jamais_reculer_la_tombale(self, store):
        """§4.6 — la tombale distante datée dans le futur puis re-supprimée
        ici ne doit pas redescendre à « maintenant » : les vues qui l'ont
        déjà vue garderaient une date que le serveur contredit."""
        futur = _maintenant_ms() + _MS_PAR_JOUR
        store.appliquer_tombale("c1", futur)

        assert store.delete("c1") == futur, (
            "re-supprimer doit garder la plus haute des dates"
        )

    def test_une_copie_datee_a_la_borne_d_int64_reste_supprimable(self, store):
        """Contre-épreuve du 24/09/2026 — la route stocke ``updatedAt =
        2**63 - 1`` ; ``delete`` calculait ``updatedAt + 1`` et levait
        OverflowError : 500, conversation impossible à supprimer."""
        borne = 2**63 - 1
        store.upsert(_conv(updated=borne))

        deleted_at = store.delete("c1")
        reponse = store.upsert(_conv(updated=borne))

        assert deleted_at == borne, "à la borne, la tombale prend updatedAt même"
        assert reponse == {"deleted": True, "deletedAt": borne}, (
            "à égalité la tombale gagne : la copie effacée ne revient pas"
        )

    def test_une_ecriture_qui_echoue_ne_laisse_aucun_numero_consomme(self, store):
        """Contre-épreuve du 24/09/2026 — une écriture qui levait après
        ``_prochain_seq`` laissait la transaction ouverte : ``list`` rendait
        déjà le numéro, que l'écriture suivante commitait sans ligne."""
        store.upsert(_conv("a"))
        _, _, seq_avant = store.list(None)
        trop_grande = _conv("b")
        trop_grande["createdAt"] = 2**63

        with pytest.raises(OverflowError):
            store.upsert(trop_grande)
        _, _, seq_apres = store.list(None)

        assert seq_apres == seq_avant, "l'écriture ratée ne doit consommer aucun seq"


class TestLaTombaleDistante:
    def test_une_tombale_distante_ancienne_perd_contre_une_modification_posterieure(
        self, store
    ):
        """§4.6 — l'autre appareil a supprimé une version que celle-ci a
        déjà dépassée. Effacer une modification que la suppression n'avait
        pas vue défait un choix postérieur de l'utilisateur."""
        store.upsert(_conv(updated=5000, title="Modifiée après"))
        _, _, seq_avant = store.list(None)

        reponse = store.appliquer_tombale("c1", 4000)

        assert reponse["conversation"]["title"] == "Modifiée après", (
            "la réponse doit rendre la copie qui a gagné, pas un faux succès"
        )
        vivantes, tombales, seq_apres = store.list(None)
        assert [c["id"] for c in vivantes] == ["c1"], (
            "la conversation modifiée après la suppression doit rester vivante"
        )
        assert tombales == [], "la tombale perdante ne doit pas être posée"
        assert seq_apres == seq_avant, (
            "une tombale qui perd n'écrit rien et ne consomme pas de numéro"
        )

    def test_une_tombale_distante_recente_supprime_et_vide_le_texte(
        self, store, db_path
    ):
        """§4.6, règle d'upsert à la lettre : ``deletedAt >= updatedAt``
        gagne, égalité comprise. Et la tombale garde la date de l'appareil
        qui a supprimé — une date par appareil empêcherait les copies de
        converger."""
        store.upsert(_conv(updated=5000))

        reponse = store.appliquer_tombale("c1", 5000)

        assert reponse == {"deleted": True, "deletedAt": 5000}, (
            "à égalité la tombale gagne, datée par l'appareil qui a supprimé"
        )
        db = sqlite3.connect(db_path)
        try:
            ligne = db.execute(
                "SELECT title, messages, deleted_at FROM conversations WHERE id = 'c1'"
            ).fetchone()
        finally:
            db.close()
        assert ligne == ("", "[]", 5000), (
            "la tombale distante doit vider le titre et les messages sur disque"
        )

    def test_une_tombale_distante_d_un_id_inconnu_est_posee(self, store):
        """§4.6 — la conversation existe peut-être encore dans le
        localStorage d'une vue : sans tombale ici, sa prochaine poussée la
        recréerait."""
        reponse = store.appliquer_tombale("jamais-vue", 7000)
        vieille = store.upsert(_conv("jamais-vue", updated=6999))

        assert reponse == {"deleted": True, "deletedAt": 7000}
        assert vieille == {"deleted": True, "deletedAt": 7000}, (
            "une copie plus vieille que la tombale distante doit rester supprimée"
        )

    def test_une_tombale_distante_ne_recule_jamais_une_tombale_locale(self, store):
        """La même suppression revenue avec une date plus basse ne change
        rien et n'écrit rien ; une date plus haute l'emporte et s'écrit,
        pour que toutes les copies convergent vers le maximum."""
        store.appliquer_tombale("c1", 9000)
        _, _, seq = store.list(None)

        plus_basse = store.appliquer_tombale("c1", 8000)
        _, _, seq_bas = store.list(None)
        plus_haute = store.appliquer_tombale("c1", 9500)
        _, tombales, seq_haut = store.list(None)

        assert plus_basse == {"deleted": True, "deletedAt": 9000}
        assert seq_bas == seq, "une tombale déjà dépassée ne doit rien écrire"
        assert plus_haute == {"deleted": True, "deletedAt": 9500}
        assert tombales == [{"id": "c1", "deletedAt": 9500}]
        assert seq_haut == seq + 1, "la date plus haute doit être écrite"

    @pytest.mark.parametrize("date", [1.5, True, "9000", None])
    def test_une_date_qui_n_est_pas_un_entier_est_refusee(self, store, date):
        """CLAUDE.md §4, règle 1 — une date flottante finirait dans une
        enveloppe signée que Python et Dart n'écrivent pas pareil ; True
        vaudrait 1 ms."""
        with pytest.raises(TypeError):
            store.appliquer_tombale("c1", date)

    @pytest.mark.parametrize("ident", ["", None, 42], ids=["vide", "none", "entier"])
    def test_un_id_qui_n_est_pas_une_chaine_non_vide_est_refuse(self, store, ident):
        """§4.6 — SQLite accepte NULL dans une clé primaire TEXT et range 42
        en « 42 » : sans ce refus, une tombale sans conversation se posait
        et voyageait jusqu'aux vues (contre-épreuve du 24/09/2026)."""
        with pytest.raises(TypeError):
            store.appliquer_tombale(ident, 1000)
        _, tombales, seq = store.list(None)
        assert tombales == [] and seq == 0, "un id refusé ne doit rien écrire"

    @pytest.mark.parametrize("date", [-1, 2**63], ids=["negative", "int64+1"])
    def test_une_date_hors_de_la_plage_sqlite_est_refusee_sans_rien_ecrire(
        self, store, date
    ):
        """Contre-épreuve du 24/09/2026 — ``appliquer_tombale('V', 2**63)``
        levait OverflowError au milieu de l'écriture, après avoir déjà
        incrémenté le compteur dans une transaction laissée ouverte."""
        with pytest.raises(ValueError):
            store.appliquer_tombale("v", date)
        _, tombales, seq = store.list(None)
        assert tombales == [] and seq == 0, "une date refusée ne doit rien écrire"

    @pytest.mark.parametrize("date", [0, 2**63 - 1], ids=["zero", "int64"])
    def test_les_bornes_de_la_plage_sont_acceptees(self, store, date):
        """Les deux bornes se stockent : refuser ``2**63 - 1`` rendrait
        inapplicable la tombale que :meth:`delete` pose à cette borne."""
        assert store.appliquer_tombale("v", date) == {
            "deleted": True,
            "deletedAt": date,
        }, "une date aux bornes d'int64 doit être posée telle quelle"


class TestLaPurgeBorneeParLaConfirmation:
    def test_une_tombale_de_40_jours_exportee_mais_non_confirmee_survit(self, db_path):
        """§4.6, revue protocole — l'appareil était éteint 40 jours : la
        suppression est partie dans ``sortants`` mais le serveur de compte
        ne l'a jamais confirmée. La purger à l'âge seul la rendait à la
        première copie distante tirée."""
        etat = _EtatDuMoteur()
        magasin = ConversationsStore(db_path)
        magasin.upsert(_conv(updated=1000))
        magasin.delete("c1")
        magasin.close()
        date = _vieillir(db_path, "c1", 40)
        etat.exporter("c1", date)

        rouvert = ConversationsStore(db_path, peut_purger=etat.peut_purger)
        try:
            _, tombales, _ = rouvert.list(None)
        finally:
            rouvert.close()

        assert tombales == [{"id": "c1", "deletedAt": date}], (
            "une tombale non confirmée ne doit jamais être purgée, même à 40 jours"
        )
        assert etat.questions == [("c1", date)], (
            "le moteur doit être consulté avec l'id et la date de la tombale"
        )

    def test_une_fois_confirmee_la_tombale_de_40_jours_est_purgee(self, db_path):
        """§4.6 — confirmée par le serveur et gardée par son plancher, la
        tombale n'a plus rien à défendre localement : la garder ferait
        grossir la base pour rien."""
        etat = _EtatDuMoteur()
        magasin = ConversationsStore(db_path)
        magasin.delete("c1")
        magasin.close()
        date = _vieillir(db_path, "c1", 40)
        etat.exporter("c1", date)
        etat.confirmer("c1", date)

        rouvert = ConversationsStore(db_path, peut_purger=etat.peut_purger)
        try:
            _, tombales, _ = rouvert.list(None)
        finally:
            rouvert.close()

        assert tombales == [], "la tombale confirmée et vieille doit être purgée"

    def test_le_moteur_n_est_consulte_que_pour_les_tombales_de_plus_de_30_jours(
        self, db_path
    ):
        """L'âge reste nécessaire : une tombale récente ou une conversation
        vivante ne sont jamais proposées à la purge, même si le moteur
        répondrait oui."""
        magasin = ConversationsStore(db_path)
        magasin.upsert(_conv("vivante-ancienne", updated=1000))
        magasin.delete("recente")
        magasin.close()
        questions: List[Tuple[str, int]] = []

        def toujours_oui(conv_id: str, deleted_at: int) -> bool:
            questions.append((conv_id, deleted_at))
            return True

        rouvert = ConversationsStore(db_path, peut_purger=toujours_oui)
        try:
            vivantes, tombales, _ = rouvert.list(None)
        finally:
            rouvert.close()

        assert questions == [], "rien de récent ni de vivant ne doit être proposé"
        assert [c["id"] for c in vivantes] == ["vivante-ancienne"]
        assert [t["id"] for t in tombales] == ["recente"]

    @pytest.mark.parametrize(
        "reponse",
        [1, "oui", object()],
        ids=["un", "chaine", "objet"],
    )
    def test_seul_un_vrai_booleen_autorise_la_purge(self, db_path, reponse):
        """§5 — un rappel qui rend autre chose que True (un MagicMock, un
        entier) ne vaut pas confirmation. Garder coûte 60 octets ; purger à
        tort ressuscite une conversation."""
        magasin = ConversationsStore(db_path)
        magasin.delete("c1")
        magasin.close()
        _vieillir(db_path, "c1", 40)

        rouvert = ConversationsStore(db_path, peut_purger=lambda _i, _d: reponse)
        try:
            _, tombales, _ = rouvert.list(None)
        finally:
            rouvert.close()

        assert [t["id"] for t in tombales] == ["c1"], (
            "une réponse non booléenne doit garder la tombale"
        )

    def test_un_moteur_qui_leve_garde_la_tombale_et_n_empeche_pas_l_ouverture(
        self, db_path
    ):
        """Le magasin s'ouvre au démarrage du serveur : un rappel qui lève
        ne doit ni tuer le serveur ni purger à l'aveugle."""
        magasin = ConversationsStore(db_path)
        magasin.delete("c1")
        magasin.close()
        _vieillir(db_path, "c1", 40)

        def en_panne(_conv_id: str, _deleted_at: int) -> bool:
            raise RuntimeError("etat.key illisible")

        rouvert = ConversationsStore(db_path, peut_purger=en_panne)
        try:
            _, tombales, _ = rouvert.list(None)
        finally:
            rouvert.close()

        assert [t["id"] for t in tombales] == ["c1"], (
            "une panne du moteur doit garder la tombale"
        )

    def test_un_crochet_pose_apres_l_ouverture_est_consulte(self, db_path, compte):
        """§4.6, §6 étape 2 — ``create_app`` ouvre le magasin SANS crochet, et
        le moteur le pose ensuite. La purge ne vivait que dans le
        constructeur : le crochet posé après coup n'était jamais consulté,
        et chaque redémarrage purgeait à l'âge seul la tombale non confirmée
        (contre-épreuve du 24/09/2026)."""
        etat = _EtatDuMoteur()
        magasin = ConversationsStore(db_path)
        magasin.delete("c1")
        magasin.close()
        date = _vieillir(db_path, "c1", 40)
        etat.exporter("c1", date)

        rouvert = ConversationsStore(db_path)  # comme create_app
        try:
            _, a_l_ouverture, _ = rouvert.list(None)
            rouvert.peut_purger = etat.peut_purger
            non_confirmee = rouvert.purger_tombales()
            _, apres_le_crochet, _ = rouvert.list(None)
            etat.confirmer("c1", date)
            confirmee = rouvert.purger_tombales()
            _, apres_confirmation, _ = rouvert.list(None)
        finally:
            rouvert.close()

        assert a_l_ouverture == [{"id": "c1", "deletedAt": date}], (
            "avec un compte, l'ouverture sans crochet ne doit rien purger"
        )
        assert non_confirmee == 0 and apres_le_crochet == a_l_ouverture, (
            "la tombale non confirmée doit survivre au crochet posé après coup"
        )
        assert etat.questions[0] == ("c1", date), "le crochet doit être consulté"
        assert confirmee == 1 and apres_confirmation == [], (
            "une fois confirmée, la purge relancée doit l'emporter"
        )

    def test_une_tombale_distante_deja_vieille_a_30_jours_pour_atteindre_les_vues(
        self, db_path
    ):
        """§4.6 — pc-bureau supprime hors ligne et sa tombale arrive 40 jours
        plus tard. Mesurée sur ``deleted_at``, elle était purgée au
        redémarrage suivant : une vue fermée entre-temps ne l'apprenait
        jamais, et sa première retouche recréait la conversation partout
        (contre-épreuve du 24/09/2026)."""
        magasin = ConversationsStore(db_path)
        magasin.upsert(_conv("y"))
        _, _, curseur_de_la_vue = magasin.list(None)
        distante = _maintenant_ms() - 40 * _MS_PAR_JOUR
        magasin.appliquer_tombale("y", distante)
        magasin.close()

        rouvert = ConversationsStore(db_path, peut_purger=lambda _i, _d: True)
        try:
            _, tombales, _ = rouvert.list(curseur_de_la_vue)
        finally:
            rouvert.close()
        _vieillir_la_pose(db_path, "y", 31)
        plus_tard = ConversationsStore(db_path, peut_purger=lambda _i, _d: True)
        try:
            _, apres_31_jours, _ = plus_tard.list(None)
        finally:
            plus_tard.close()

        assert tombales == [{"id": "y", "deletedAt": distante}], (
            "la vue qui se rouvre doit encore apprendre la suppression"
        )
        assert apres_31_jours == [], (
            "31 jours après sa POSE ici, la tombale confirmée doit partir"
        )

    def test_une_conversation_ressuscitee_pendant_la_purge_n_est_pas_emportee(
        self, db_path, compte
    ):
        """§100 — ``peut_purger`` tourne hors du verrou ; une poussée peut
        ressusciter la conversation pendant ce temps. Sans la garde sur
        ``deleted_at``, la purge effaçait la conversation VIVANTE."""
        magasin = ConversationsStore(db_path)
        magasin.delete("c1")
        magasin.close()
        _vieillir(db_path, "c1", 40)
        rouvert = ConversationsStore(db_path)

        def ressuscite_puis_accepte(conv_id: str, _deleted_at: int) -> bool:
            rouvert.upsert(_conv(conv_id, updated=_maintenant_ms()))
            return True

        rouvert.peut_purger = ressuscite_puis_accepte
        try:
            rouvert.purger_tombales()
            vivantes, _, _ = rouvert.list(None)
        finally:
            rouvert.close()

        assert [c["id"] for c in vivantes] == ["c1"], (
            "la conversation ressuscitée pendant la purge doit survivre"
        )

    def test_une_tombale_redatee_pendant_la_purge_n_est_pas_emportee(
        self, db_path, compte
    ):
        """L'accord portait sur la tombale telle que lue : une suppression
        plus récente arrivée pendant la question est un autre état, que le
        moteur n'a pas encore confirmé."""
        magasin = ConversationsStore(db_path)
        magasin.delete("c1")
        magasin.close()
        _vieillir(db_path, "c1", 40)
        rouvert = ConversationsStore(db_path)
        recente = _maintenant_ms()

        def redate_puis_accepte(conv_id: str, _deleted_at: int) -> bool:
            rouvert.appliquer_tombale(conv_id, recente)
            return True

        rouvert.peut_purger = redate_puis_accepte
        try:
            purgees = rouvert.purger_tombales()
            _, tombales, _ = rouvert.list(None)
        finally:
            rouvert.close()

        assert purgees == 0, "rien de ce que le moteur a confirmé n'existe encore"
        assert tombales == [{"id": "c1", "deletedAt": recente}], (
            "la tombale redatée pendant la purge doit survivre"
        )

    def test_sans_compte_la_purge_reste_celle_d_avant(self, db_path):
        """§6 étape 2 (comportement inchangé) — sans ``peut_purger``, la
        tombale de 31 jours part comme avant le 24/09/2026."""
        magasin = ConversationsStore(db_path)
        magasin.delete("c1")
        magasin.close()
        _vieillir(db_path, "c1", 31)

        rouvert = ConversationsStore(db_path)
        try:
            _, tombales, _ = rouvert.list(None)
            assert rouvert.peut_purger is None and rouvert.sur_ecriture is None, (
                "sans compte, aucun crochet ne doit être posé"
            )
        finally:
            rouvert.close()

        assert tombales == [], "sans compte la tombale de 31 jours doit partir"


class TestLeCrochetSurEcriture:
    def test_chaque_ecriture_appelle_le_crochet_avec_son_numero(self, store):
        """§4.3 — le moteur se réveille sur ce crochet : une écriture qui ne
        l'appelle pas attend le prochain tirage (jusqu'à 300 s) pour partir.
        Le numéro passé est celui que ``list`` rend juste après."""
        vus: List[int] = []
        store.sur_ecriture = vus.append

        store.upsert(_conv("a"))
        store.upsert(_conv("a", updated=2000, title="Renommée"))
        store.delete("a")
        store.appliquer_tombale("b", 3000)
        _, _, seq = store.list(None)

        assert vus == [1, 2, 3, 4], "chaque écriture doit signaler son numéro"
        assert vus[-1] == seq, "le dernier numéro signalé doit être le courant"

    def test_une_ecriture_sans_effet_ne_reveille_personne(self, store):
        """Une fusion sans effet ou une tombale perdante n'écrivent rien :
        réveiller le moteur pour rien le ferait exporter à vide."""
        store.upsert(_conv(updated=5000))
        vus: List[int] = []
        store.sur_ecriture = vus.append

        store.upsert(_conv(updated=5000))
        store.appliquer_tombale("c1", 4000)

        assert vus == [], "rien n'a été écrit, rien ne doit être signalé"

    def test_le_crochet_voit_l_ecriture_commitee_et_peut_relire_le_magasin(
        self, store, db_path
    ):
        """§4.3 — appelé après le commit, le crochet voit l'écriture depuis
        une AUTRE connexion (la même connexion voit aussi le non-commité, et
        la première version de ce test ne prouvait rien : contre-épreuve du
        24/09/2026). Appelé hors du verrou, il peut relire le magasin ; la
        relecture tourne dans un fil borné pour qu'un interblocage échoue
        au lieu de pendre la suite (pytest-timeout n'est pas installé)."""
        vus_ailleurs: List[list] = []
        relus: List[list] = []
        fils_finis: List[bool] = []

        def crochet(_seq: int) -> None:
            autre = sqlite3.connect(db_path)
            try:
                vus_ailleurs.append(
                    autre.execute("SELECT title FROM conversations").fetchall()
                )
            finally:
                autre.close()
            fil = threading.Thread(target=lambda: relus.append(store.list(None)[0]))
            fil.start()
            fil.join(timeout=5)
            fils_finis.append(not fil.is_alive())

        store.sur_ecriture = crochet
        store.upsert(_conv(title="Vue par le crochet"))

        assert vus_ailleurs == [[("Vue par le crochet",)]], (
            "une autre connexion doit voir l'écriture : elle est commitée"
        )
        assert fils_finis == [True], "relire depuis le crochet ne doit pas bloquer"
        assert [c["title"] for c in relus[0]] == ["Vue par le crochet"]

    def test_un_crochet_qui_leve_ne_fait_pas_echouer_l_ecriture(self, store):
        """§100 — l'écriture est commitée : faire échouer l'appel dirait au
        client « non enregistré » alors que ça l'est."""

        def en_panne(_seq: int) -> None:
            raise RuntimeError("boucle fermée")

        store.sur_ecriture = en_panne

        reponse = store.upsert(_conv(title="Gardée"))
        deleted_at = store.delete("autre")

        assert reponse["conversation"]["title"] == "Gardée"
        assert isinstance(deleted_at, int)
        vivantes, tombales, _ = store.list(None)
        assert [c["id"] for c in vivantes] == ["c1"], (
            "l'écriture doit être là malgré la panne du crochet"
        )
        assert [t["id"] for t in tombales] == ["autre"]

    def test_le_crochet_passe_au_constructeur_est_appele(self, db_path):
        """Le moteur peut aussi brancher le crochet à l'ouverture."""
        vus: List[int] = []
        magasin = ConversationsStore(db_path, sur_ecriture=vus.append)
        try:
            magasin.upsert(_conv())
        finally:
            magasin.close()

        assert vus == [1], "le crochet du constructeur doit être appelé"


class TestLeDecalageDHorloge:
    def test_une_suppression_datee_par_une_horloge_en_avance_emporte_les_messages_ecrits_apres_elle(  # noqa: E501
        self, store
    ):
        """§4.6 contre §4.9, limite CONNUE et figée ici (contre-épreuve du
        24/09/2026). L'appareil A, en avance de 3 h, supprime à l'heure
        réelle T : ``deletedAt = T + 3 h``. Une heure plus tard, B, à
        l'heure et sans avoir vu la suppression, ajoute une question
        (``updatedAt = T + 1 h``). La tombale gagne et la question écrite
        APRÈS la suppression disparaît : le décalage ne touche pas que les
        métadonnées, contrairement à ce que dit §4.9. L'étape 10 doit
        trancher ; si ce test rougit, c'est qu'elle l'a fait — réécrire
        alors la docstring de ``ConversationsStore``."""
        heure = 3600 * 1000
        t = 1_800_000_000_000
        conv = _conv("z", updated=t + heure)
        conv["messages"].append(
            {"id": "m2", "role": "user", "content": "écrite après", "timestamp": t}
        )
        store.upsert(conv)

        reponse = store.appliquer_tombale("z", t + 3 * heure)

        vivantes, _, _ = store.list(None)
        assert reponse == {"deleted": True, "deletedAt": t + 3 * heure}, (
            "aujourd'hui la tombale datée par l'horloge en avance gagne"
        )
        assert vivantes == [], (
            "aujourd'hui les messages écrits pendant le décalage sont perdus"
        )
