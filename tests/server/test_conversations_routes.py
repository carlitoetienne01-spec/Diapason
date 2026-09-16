"""Tests de la persistance serveur des conversations du chat.

L'historique vivait dans le localStorage du frontend, cloisonné par
origine : la fenêtre principale et le mini-panneau portaient chacun le
leur. Le serveur devient la source de vérité — et une source de vérité qui
ment (une suppression qui ressuscite, un message perdu parce que deux vues
ont écrit le même fil, une poussée tardive que personne ne voit) est pire
que pas de source du tout.
"""

from __future__ import annotations

import json
import sqlite3
import time

import pytest

pytest.importorskip("fastapi", reason="diapason[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.server.auth_middleware import AuthMiddleware, RateLimitMiddleware
from diapason.server.conversations_routes import create_conversations_router
from diapason.server.conversations_store import (
    ConversationsStore,
    fusionner_conversations,
    fusionner_messages,
    sans_substituts,
)

_MS_PAR_JOUR = 24 * 3600 * 1000


def _msg(ident: str, role: str, content: str, ts: int, **extra) -> dict:
    message = {"id": ident, "role": role, "content": content, "timestamp": ts}
    message.update(extra)
    return message


def _conv(
    conv_id: str = "c1",
    *,
    title: str = "Première conversation",
    created: int = 500,
    updated: int = 1000,
    model: str = "qwen3",
    messages: list | None = None,
    **extra,
) -> dict:
    conv = {
        "id": conv_id,
        "title": title,
        "createdAt": created,
        "updatedAt": updated,
        "model": model,
        "messages": (
            messages if messages is not None else [_msg("m1", "user", "salut", 600)]
        ),
    }
    conv.update(extra)
    return conv


def _make_app(store: ConversationsStore) -> FastAPI:
    app = FastAPI()
    app.include_router(create_conversations_router(store))
    return app


@pytest.fixture
def db_path(tmp_path):
    # Jamais ~/.diapason : la base de test vit dans tmp_path.
    return tmp_path / "conversations.db"


@pytest.fixture
def store(db_path):
    return ConversationsStore(db_path)


@pytest.fixture
def client(store):
    return TestClient(_make_app(store))


class TestLesRoutesDesConversations:
    def test_un_upsert_puis_un_get_rend_la_conversation(self, client):
        """§5 — ne jamais faire semblant : ce que le PUT accepte, le GET
        doit le rendre tel quel, messages opaques compris — sinon la
        persistance est une promesse en attente."""
        corps = _conv()
        reponse = client.put("/v1/conversations/c1", json=corps)
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["conversation"]["updatedAt"] == 1000, (
            "le PUT doit rendre la conversation telle que stockée"
        )

        liste = client.get("/v1/conversations").json()
        assert liste["deleted"] == [], "rien n'a été supprimé"
        assert liste["seq"] == 1, "une écriture, un numéro"
        assert liste["conversations"] == [
            {
                "id": "c1",
                "title": "Première conversation",
                "createdAt": 500,
                "updatedAt": 1000,
                "model": "qwen3",
                "pinned": False,
                "messages": [_msg("m1", "user", "salut", 600)],
            }
        ], "la conversation doit ressortir en camelCase, messages tels quels"

    def test_le_since_est_un_numero_d_ecriture_pas_une_heure(self, client):
        """§100 — un premier jet filtrait sur l'heure du contenu : une
        conversation poussée EN RETARD avec un vieux updatedAt (vue rouverte
        après des jours, serveur relancé pendant la poussée) restait
        invisible à jamais aux vues dont le curseur avait dépassé cette
        heure. Le curseur suit l'ordre des écritures : ce qui arrive après
        est vu après, quelle que soit l'heure qu'il porte."""
        client.put("/v1/conversations/recente", json=_conv("recente", updated=9000))
        curseur = client.get("/v1/conversations").json()["seq"]

        # Une poussée tardive, datée bien AVANT tout ce que le curseur a vu.
        client.put("/v1/conversations/tardive", json=_conv("tardive", updated=100))

        depuis = client.get(f"/v1/conversations?since={curseur}").json()
        assert [c["id"] for c in depuis["conversations"]] == ["tardive"], (
            "la poussée tardive doit être rendue à qui demande « depuis mon "
            "curseur », même si son heure est plus vieille que le curseur"
        )
        assert depuis["seq"] == curseur + 1, "le curseur suivant est le nouveau numéro"

        rien = client.get(f"/v1/conversations?since={depuis['seq']}").json()
        assert rien["conversations"] == [] and rien["deleted"] == [], (
            "rien d'écrit après le dernier numéro : rien à rendre"
        )

    def test_le_since_filtre_aussi_les_tombales(self, client):
        """Un filtre qui ne porte que sur les vivantes ferait rater les
        suppressions, et une conversation effacée ailleurs resterait
        affichée ici (§100)."""
        client.put("/v1/conversations/c1", json=_conv())
        client.delete("/v1/conversations/supprimee-avant")
        curseur = client.get("/v1/conversations").json()["seq"]
        client.delete("/v1/conversations/supprimee-apres")

        depuis = client.get(f"/v1/conversations?since={curseur}").json()
        assert depuis["conversations"] == [], "c1 est antérieure au curseur"
        assert [t["id"] for t in depuis["deleted"]] == ["supprimee-apres"], (
            "seule la tombale postérieure au curseur doit repasser"
        )

    def test_une_fusion_sans_effet_n_ecrit_rien(self, client):
        """Re-pousser exactement ce que le serveur a ne doit consommer aucun
        numéro : sinon chaque tirage des autres vues re-recevrait la même
        conversation, à chaque tick, pour rien."""
        client.put("/v1/conversations/c1", json=_conv())
        avant = client.get("/v1/conversations").json()["seq"]
        client.put("/v1/conversations/c1", json=_conv())
        assert client.get("/v1/conversations").json()["seq"] == avant, (
            "une poussée identique ne doit pas avancer le compteur"
        )

    def test_deux_vues_qui_ecrivent_le_meme_fil_ne_perdent_aucun_message(self, client):
        """§100 — le défaut de revue du 16 sept. 2026 : un dernier-écrit-
        gagne au grain de la conversation entière effaçait la question ET la
        réponse de la vue A dès que la vue B envoyait la sienne dans la
        fenêtre de synchronisation. L'union des messages garde tout, et les
        métadonnées viennent de l'écriture la plus récente."""
        base = [
            _msg("q1", "user", "Bonjour", 100),
            _msg("r1", "assistant", "Salut", 101),
        ]
        client.put("/v1/conversations/c1", json=_conv(messages=base, updated=1000))

        # A envoie sa paire à T=2000 ; B, qui ne l'a pas encore, la sienne
        # à T=3000.
        de_a = base + [
            _msg("q2", "user", "A ?", 2000),
            _msg("r2", "assistant", "Ra", 2001),
        ]
        de_b = base + [
            _msg("q3", "user", "B ?", 3000),
            _msg("r3", "assistant", "Rb", 3001),
        ]
        client.put(
            "/v1/conversations/c1",
            json=_conv(messages=de_b, updated=3001, title="Titre de B"),
        )
        reponse = client.put(
            "/v1/conversations/c1",
            json=_conv(messages=de_a, updated=2001, title="Titre de A"),
        )

        fusion = reponse.json()["conversation"]
        ordre = [m["id"] for m in fusion["messages"]]
        assert ordre == ["q1", "r1", "q2", "r2", "q3", "r3"], (
            "les deux paires doivent survivre, dans l'ordre du temps"
        )
        assert fusion["title"] == "Titre de B", (
            "les métadonnées viennent de l'écriture la plus récente"
        )
        assert fusion["updatedAt"] == 3001, "updatedAt est le plus haut des deux"
        stocke = client.get("/v1/conversations").json()["conversations"][0]
        assert stocke == fusion, "ce que le PUT rend est ce que le GET rend"

    def test_une_copie_partielle_n_ecrase_jamais_la_reponse_complete(self, client):
        """Le mini-panneau pousse la réponse pendant qu'elle arrive, pour que
        l'autre vue la voie grandir. Si l'autre vue écrit la conversation
        APRÈS (un renommage, une épingle), sa copie porte encore la réponse
        tronquée : au grain du message, la plus complète gagne — quelle que
        soit la vue qui a écrit en dernier."""
        partielle = [_msg("q", "user", "?", 1), _msg("r", "assistant", "Bonj", 2)]
        complete = [
            _msg("q", "user", "?", 1),
            _msg("r", "assistant", "Bonjour !", 2, usage={"total_tokens": 4}),
        ]
        client.put("/v1/conversations/c1", json=_conv(messages=complete, updated=5000))
        reponse = client.put(
            "/v1/conversations/c1",
            json=_conv(messages=partielle, updated=6000, pinned=True),
        )

        fusion = reponse.json()["conversation"]
        assert fusion["messages"][1]["content"] == "Bonjour !", (
            "la copie partielle plus récente ne doit pas tronquer la réponse"
        )
        assert fusion["messages"][1]["usage"] == {"total_tokens": 4}, (
            "les champs de la copie complète doivent survivre"
        )
        assert fusion["pinned"] is True, "l'épingle, elle, vient de l'écriture récente"

    def test_une_suppression_pose_une_tombale_et_la_conversation_disparait(
        self, client
    ):
        """§100 — une conversation supprimée qui réapparaît dans la liste
        est un mensonge : elle doit passer dans deleted, et n'être plus
        jamais dans conversations."""
        client.put("/v1/conversations/c1", json=_conv())
        reponse = client.delete("/v1/conversations/c1")

        assert reponse.status_code == 200
        assert reponse.json()["deleted"] is True
        liste = client.get("/v1/conversations").json()
        assert liste["conversations"] == [], (
            "la conversation supprimée ne doit plus être listée vivante"
        )
        assert [t["id"] for t in liste["deleted"]] == ["c1"], (
            "la tombale doit être listée pour que les autres vues suppriment aussi"
        )

    def test_un_put_plus_vieux_qu_une_tombale_reste_supprime(self, client):
        """§100 — le pc-bureau rallumé pousse sa copie d'avant la
        suppression : la laisser ressusciter la conversation défait un choix
        que l'utilisateur a déjà fait. La réponse dit la suppression."""
        client.put("/v1/conversations/c1", json=_conv())
        tombale = client.delete("/v1/conversations/c1").json()

        reponse = client.put(
            "/v1/conversations/c1",
            json=_conv(updated=tombale["deletedAt"] - 1),
        )

        assert reponse.status_code == 200
        assert reponse.json() == {"deleted": True, "deletedAt": tombale["deletedAt"]}, (
            "la réponse doit dire la suppression, pas un faux succès"
        )
        assert client.get("/v1/conversations").json()["conversations"] == [], (
            "la vieille copie ne doit pas ressusciter la conversation"
        )

    def test_un_put_plus_recent_qu_une_tombale_ressuscite(self, client):
        """Une écriture POSTÉRIEURE à la suppression est un nouveau choix de
        l'utilisateur, et la refuser au nom de la tombale serait l'autre
        mensonge."""
        client.put("/v1/conversations/c1", json=_conv())
        tombale = client.delete("/v1/conversations/c1").json()

        ressuscitee = _conv(title="Revenue", updated=tombale["deletedAt"] + 1)
        reponse = client.put("/v1/conversations/c1", json=ressuscitee)

        assert reponse.status_code == 200
        assert reponse.json()["conversation"]["title"] == "Revenue"
        liste = client.get("/v1/conversations").json()
        assert [c["id"] for c in liste["conversations"]] == ["c1"], (
            "l'écriture plus récente doit rouvrir la conversation"
        )
        assert liste["deleted"] == [], (
            "la tombale effacée ne doit plus voyager — elle ferait resupprimer"
        )

    def test_la_suppression_est_idempotente_meme_sur_un_id_inconnu(self, client):
        """Deux vues suppriment la même conversation : la seconde ne doit
        pas échouer pour rien. Et supprimer un id que ce serveur n'a jamais
        vu doit quand même poser la tombale — la conversation existe
        peut-être dans un localStorage pas encore synchronisé."""
        premiere = client.delete("/v1/conversations/jamais-vu")
        seconde = client.delete("/v1/conversations/jamais-vu")

        assert premiere.status_code == 200 and seconde.status_code == 200
        assert seconde.json()["deleted"] is True
        assert seconde.json()["deletedAt"] >= premiere.json()["deletedAt"], (
            "re-supprimer ne doit jamais faire reculer la tombale"
        )
        assert [t["id"] for t in client.get("/v1/conversations").json()["deleted"]] == [
            "jamais-vu"
        ], "la tombale d'un id inconnu doit exister pour les autres vues"

    def test_une_tombale_vide_le_titre_et_les_messages(self, client, db_path):
        """§78 (l'esprit) — une suppression qui garde le texte n'est pas une
        suppression : la transcription doit quitter le disque, pas seulement
        la liste."""
        client.put("/v1/conversations/c1", json=_conv())
        client.delete("/v1/conversations/c1")

        db = sqlite3.connect(db_path)
        try:
            ligne = db.execute(
                "SELECT title, messages FROM conversations WHERE id = 'c1'"
            ).fetchone()
        finally:
            db.close()
        assert ligne == ("", "[]"), (
            "la tombale doit avoir vidé le titre et les messages sur disque"
        )

    def test_les_tombales_de_plus_de_30_jours_sont_purgees(self, db_path):
        """30 jours : assez pour qu'un appareil éteint des semaines apprenne
        la suppression avant la purge. Au-delà, garder la tombale ferait
        grossir la base pour rien — et la purge ne doit toucher QUE les
        tombales, jamais une vivante ancienne."""
        store = ConversationsStore(db_path)
        store.upsert(_conv("vivante-ancienne", updated=1000))
        store.delete("recemment-supprimee")
        store.delete("supprimee-il-y-a-longtemps")
        store.close()

        db = sqlite3.connect(db_path)
        db.execute(
            "UPDATE conversations SET deleted_at = ? "
            "WHERE id = 'supprimee-il-y-a-longtemps'",
            (int(time.time() * 1000) - 31 * _MS_PAR_JOUR,),
        )
        db.commit()
        db.close()

        rouvert = ConversationsStore(db_path)
        vivantes, tombales, _ = rouvert.list(None)
        assert [t["id"] for t in tombales] == ["recemment-supprimee"], (
            "la tombale de 31 jours doit être purgée, la récente gardée"
        )
        assert [c["id"] for c in vivantes] == ["vivante-ancienne"], (
            "la purge ne doit jamais emporter une conversation vivante"
        )

    def test_la_purge_ne_reutilise_jamais_un_numero_d_ecriture(self, db_path):
        """Un compteur calculé par MAX(seq) reculerait quand la purge emporte
        la ligne qui portait le plus grand numéro : la prochaine écriture le
        reprendrait, et un client dont le curseur vaut ce numéro ne la
        verrait jamais. Le compteur vit à part et ne recule pas."""
        store = ConversationsStore(db_path)
        store.delete("vieille-tombale")
        _, _, curseur = store.list(None)
        store.close()

        db = sqlite3.connect(db_path)
        db.execute(
            "UPDATE conversations SET deleted_at = ? WHERE id = 'vieille-tombale'",
            (int(time.time() * 1000) - 31 * _MS_PAR_JOUR,),
        )
        db.commit()
        db.close()

        rouvert = ConversationsStore(db_path)
        rouvert.upsert(_conv("nouvelle"))
        vivantes, _, _ = rouvert.list(curseur)
        assert [c["id"] for c in vivantes] == ["nouvelle"], (
            "l'écriture faite après la purge doit porter un numéro plus grand "
            "que tout ce qu'un client a pu voir"
        )

    def test_un_substitut_isole_ne_casse_pas_la_poussee(self, client):
        """Un demi-surrogat collé dans un message, échappé « \\ud800 » par
        JSON.stringify, faisait lever sqlite3 (UTF-8 refuse les substituts)
        : 500 sur chaque poussée, la conversation ne se synchronisait plus
        jamais. Il est remplacé par U+FFFD, et la poussée passe."""
        # Le texte JSON tel que JSON.stringify l'émet : l'échappement, pas le
        # caractère (le client HTTP de test refuse lui aussi de l'encoder).
        casse = json.dumps(_conv(messages=[_msg("m", "user", "abc?def", 1)]))
        casse = casse.replace("abc?def", "abc\\ud800def")
        reponse = client.put(
            "/v1/conversations/c1",
            content=casse,
            headers={"Content-Type": "application/json"},
        )
        assert reponse.status_code == 200, reponse.text
        contenu = reponse.json()["conversation"]["messages"][0]["content"]
        assert contenu == "abc�def", (
            "le substitut isolé doit devenir U+FFFD, pas un 500"
        )

    def test_un_corps_sans_updated_at_entier_est_rejete(self, client):
        """Sans updatedAt entier, le départage n'a plus d'ordre : mieux vaut
        un 422 franc qu'un stockage qui comparera des None."""
        sans = _conv()
        del sans["updatedAt"]
        assert client.put("/v1/conversations/c1", json=sans).status_code == 422, (
            "un corps sans updatedAt doit être refusé en 422"
        )

        faux_type = _conv()
        faux_type["updatedAt"] = "1000"
        assert client.put("/v1/conversations/c1", json=faux_type).status_code == 422, (
            "un updatedAt non entier doit être refusé en 422"
        )
        assert client.get("/v1/conversations").json()["conversations"] == [], (
            "rien ne doit avoir été stocké par un corps invalide"
        )

    def test_un_id_de_corps_divergent_est_refuse(self, client):
        """L'id de l'URL prime : deux ids qui divergent signalent un bug
        client, et écraser en silence stockerait un contenu sous un id que
        le client ne relira jamais (§100)."""
        reponse = client.put("/v1/conversations/c1", json=_conv("c2"))
        assert reponse.status_code == 400, (
            "un id de corps divergent doit être refusé en 400"
        )
        assert client.get("/v1/conversations").json()["conversations"] == [], (
            "rien ne doit avoir été stocké sous l'un ou l'autre id"
        )


class TestLaFusion:
    """La même règle vit dans convSync.ts ; ces tests en sont le miroir."""

    def test_la_fusion_est_commutative_et_idempotente(self):
        """Quel que soit l'ordre des poussées, toutes les vues doivent
        converger : fusionner(a, b) == fusionner(b, a), et re-fusionner le
        résultat avec une entrée ne change rien."""
        a = _conv(
            messages=[_msg("1", "user", "a", 1), _msg("2", "assistant", "ra", 2)],
            updated=10,
        )
        b = _conv(
            messages=[_msg("1", "user", "a", 1), _msg("3", "user", "b", 3)],
            updated=20,
            title="B",
        )

        ab = fusionner_conversations(a, b)
        ba = fusionner_conversations(b, a)
        assert ab == ba, "la fusion doit être commutative"
        assert fusionner_conversations(ab, a) == ab, "et idempotente"
        assert fusionner_conversations(ab, b) == ab, "dans les deux sens"
        assert [m["id"] for m in ab["messages"]] == ["1", "2", "3"]

    def test_deux_copies_a_la_meme_milliseconde_sont_departagees_pareil(self):
        """Deux vues écrivent à la même milliseconde : sans ordre total, le
        serveur gardait une copie et chaque client la sienne — trois
        versions « synchronisées ». L'ordre total ne dépend pas du côté."""
        a = _conv(title="Alpha", updated=1000, messages=[_msg("1", "user", "x", 1)])
        b = _conv(title="Beta", updated=1000, messages=[_msg("1", "user", "x", 1)])
        assert fusionner_conversations(a, b)["title"] == "Beta"
        assert fusionner_conversations(b, a)["title"] == "Beta", (
            "le départage doit désigner la même copie des deux côtés"
        )

    def test_les_messages_sans_identifiant_ne_se_dupliquent_pas(self):
        """Les historiques d'avant l'identifiant n'en portent pas : sans
        repli role@timestamp, chaque fusion aurait doublé chaque message."""
        ancien = [{"role": "user", "content": "salut", "timestamp": 5}]
        assert fusionner_messages(ancien, list(ancien)) == ancien, (
            "un message sans id fusionné avec lui-même doit rester unique"
        )

    def test_les_substituts_isoles_deviennent_u_fffd(self):
        assert sans_substituts("a\ud800b") == "a�b"
        assert sans_substituts("intact é 😀") == "intact é 😀", (
            "un texte bien formé doit traverser sans changement"
        )


class TestLAuthentificationDesConversations:
    def test_les_conversations_exigent_la_cle(self, tmp_path):
        """Des transcriptions privées derrière le mur de la clé : sans elle,
        401 — l'exemption du limiteur ne doit pas avoir ouvert la porte."""
        app = _make_app(ConversationsStore(tmp_path / "conversations.db"))
        app.add_middleware(RateLimitMiddleware)
        app.add_middleware(AuthMiddleware, api_key="oj_sk_test123")
        client = TestClient(app)

        assert client.get("/v1/conversations").status_code == 401, (
            "sans clé, la liste des conversations doit être refusée"
        )
        avec_cle = client.get(
            "/v1/conversations",
            headers={"Authorization": "Bearer oj_sk_test123"},
        )
        assert avec_cle.status_code == 200, "avec la clé, la liste doit passer"


class TestLeMagasinValideSonChemin:
    def test_un_chemin_qui_n_est_ni_str_ni_path_est_refuse(self):
        """Piège payé du dépôt : Path(MagicMock()) rend
        « MagicMock/<nom>/<id> » et 42 vraies bases SQLite ont dormi à la
        racine. Un code qui écrit doit valider son chemin AVANT d'écrire."""
        from unittest.mock import MagicMock

        with pytest.raises(TypeError):
            ConversationsStore(MagicMock())

    def test_create_app_n_ouvre_jamais_la_base_reelle_sous_pytest(
        self, tmp_path_factory
    ):
        """Le 16 sept. 2026, le premier lancement de la suite a créé
        ~/.diapason/conversations.db — la base de PRODUCTION — avant que
        l'app n'y ait écrit une ligne. La garde vit dans tests/conftest.py ;
        ce test vérifie qu'elle tient."""
        from unittest.mock import MagicMock

        from diapason.core.config import DiapasonConfig
        from diapason.server.app import create_app

        engine = MagicMock()
        engine.engine_id = "mock"
        engine.health.return_value = True
        engine.list_models.return_value = ["test-model"]
        cfg = DiapasonConfig()
        cfg.analytics.enabled = False
        cfg.traces.enabled = False

        app = create_app(engine, "test-model", config=cfg)
        chemin = app.state.conversations_store.chemin
        assert chemin.startswith(str(tmp_path_factory.getbasetemp())), (
            f"le magasin d'un create_app de test doit vivre dans le répertoire "
            f"jetable de pytest, pas en {chemin}"
        )
