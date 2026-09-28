"""§5/§100 : les pouvoirs annoncés modifient le vrai magasin, jamais une copie."""

import json

import pytest

from diapason.core.types import ToolCall
from diapason.tools._stubs import ToolExecutor
from diapason.tools.diapason_app import (
    OPERATIONS,
    SUPPRESSIONS,
    DiapasonAppDeleteTool,
    DiapasonAppTool,
    decrire_operation,
)
from diapason.vie import routes
from diapason.vie.sync import VieSyncStore


@pytest.fixture
def magasin(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "configuration"))
    store = VieSyncStore(tmp_path / "vie.db")
    monkeypatch.setattr(routes, "_store", store)
    return store


def appel(operation, **params):
    outil = (
        DiapasonAppDeleteTool()
        if operation.startswith("delete_")
        else DiapasonAppTool()
    )
    resultat = outil.execute(operation=operation, params=params)
    assert resultat.success, resultat.content
    return json.loads(resultat.content)


class TestCatalogue:
    def test_le_telephone_ne_gagne_pas_les_pouvoirs_du_mac(self, magasin):
        """§5 : l'ajout local ne contourne pas le plafond du téléphone."""
        from diapason.core.origine_telephone import marquer_le_telephone

        with marquer_le_telephone():
            resultat = DiapasonAppTool().execute(
                operation="create_note", params={"body": {"title": "Interdite"}}
            )
        assert not resultat.success and magasin.list_notes() == [], (
            "aucune écriture hors portée"
        )

    def test_une_reprise_recoit_le_vrai_schema(self, magasin):
        """§5 : corriger les arguments sans deviner leur forme."""
        resultat = DiapasonAppTool().execute(
            operation="upsert_budget", params={"amount": 12}
        )
        assert not resultat.success and "expectedParameters" in resultat.content
        assert magasin.list_budgets() == [], "les arguments invalides n'écrivent rien"

    def test_une_periode_mal_placee_n_est_pas_ignoree(self, magasin):
        """§100 : le mois demandé ne doit pas devenir le mois par défaut."""
        resultat = DiapasonAppTool().execute(
            operation="list_budgets", yearMonth="2026-10"
        )
        assert not resultat.success, "un filtre mal placé n'est pas une lecture réussie"

    @pytest.mark.parametrize(
        "nom",
        [
            n
            for g in (OPERATIONS, SUPPRESSIONS)
            for ns in g.values()
            for n in ns.split()
        ],
    )
    def test_chaque_operation_a_un_schema_reel(self, nom):
        """§5 : aucun nom annoncé sans fonction derrière."""
        schema = decrire_operation(nom)
        assert schema["parameters"]["type"] == "object", "schéma exploitable"

    def test_erreurs_ne_modifient_rien(self, magasin):
        """§100 : un champ ignoré n'est pas une édition réussie."""
        outil = DiapasonAppTool()
        comptes_avant = magasin.list_accounts()
        for operation, params in [
            ("create_account", {"body": {"name": "Test", "montant": 40}}),
            ("create_account", {"body": {"name": ""}}),
            ("create_transaction", {"body": {"accountId": "absent", "amount": 4}}),
            ("delete_account", {"accountId": "absent"}),
            ("get_config", {}),
            ("../config", {}),
        ]:
            assert not outil.execute(operation=operation, params=params).success, (
                operation
            )
        assert magasin.list_accounts() == comptes_avant, "aucune écriture en échec"


_LE_MAC = [("navigate", {"page": "finances"}), ("current_view", {})]


@pytest.fixture
def mac_temoin(monkeypatch):
    """navigate et current_view remplacés par des témoins : un appel noté,
    c'est la fenêtre du Mac pilotée ou lue."""
    from diapason.server import contexte_routes
    from diapason.tools import diapason_app

    touches: list[str] = []

    def _naviguer(page):
        touches.append("navigate")
        return {"displayed": True, "page": page, "path": "/vie/finances"}

    def _lire_la_vue():
        touches.append("current_view")
        return {"tracked": True, "path": "/vie/finances"}

    monkeypatch.setattr(diapason_app, "naviguer", _naviguer)
    monkeypatch.setattr(contexte_routes, "lire_la_vue", _lire_la_vue)
    return touches


@pytest.fixture
def plafond_de_la_phase_6(monkeypatch):
    """La décision de la phase 6 simulée : les deux noms entrent au plafond."""
    from diapason.core import origine_telephone

    monkeypatch.setattr(
        origine_telephone,
        "OUTILS_DU_TELEPHONE",
        origine_telephone.OUTILS_DU_TELEPHONE | {"diapason_app", "diapason_app_delete"},
    )


def par_l_executeur(operation, params=None, **racine):
    """Le chemin de la Discussion et de la voix : ToolExecutor, cloche acceptée."""
    outil = (
        DiapasonAppDeleteTool()
        if operation.startswith("delete_")
        else DiapasonAppTool()
    )
    executeur = ToolExecutor(
        [outil],
        interactive=True,
        confirm_callback=lambda _: True,
        autoload_capability_policy=False,
    )
    return executeur.execute(
        ToolCall(
            id="essai",
            name=outil.tool_id,
            arguments=json.dumps(
                {"operation": operation, "params": params or {}, **racine}
            ),
        )
    )


class TestLeTelephone:
    """Revue de sécurité du 28/09/2026 : le plafond du téléphone se décide nom
    par nom, et diapason_app porte sous un seul nom les données de Diapason
    et deux actions sur la fenêtre du Mac."""

    @pytest.mark.parametrize(
        ("operation", "params"),
        [
            *_LE_MAC,
            ("catalogue", {}),
            ("create_note", {"body": {"title": "Interdite"}}),
            ("delete_note", {"noteId": "absente"}),
        ],
    )
    def test_aujourd_hui_les_deux_noms_sont_refuses_au_telephone(
        self, magasin, mac_temoin, operation, params
    ):
        """§5 : tant que la phase 6 n'a rien décidé, ni les données ni le Mac
        ne répondent au téléphone — par l'exécuteur comme en appel direct."""
        from diapason.core.origine_telephone import (
            OUTILS_DU_TELEPHONE,
            marquer_le_telephone,
        )

        assert not {"diapason_app", "diapason_app_delete"} & OUTILS_DU_TELEPHONE, (
            "la phase 6 a ouvert diapason_app : c'est une décision, mettre ce "
            "test à jour avec elle"
        )
        with marquer_le_telephone():
            rendus = [
                par_l_executeur(operation, params),
                DiapasonAppTool().execute(operation=operation, params=params),
                DiapasonAppDeleteTool().execute(operation=operation, params=params),
            ]
        for rendu in rendus:
            assert not rendu.success, f"{operation} a répondu au téléphone"
            assert "téléphone" in rendu.content, "le refus doit se dire"
        assert mac_temoin == [], "la fenêtre du Mac a été touchée depuis le téléphone"
        assert magasin.list_notes() == [], "aucune écriture depuis le téléphone"

    @pytest.mark.parametrize(("operation", "params"), _LE_MAC)
    def test_le_mac_reste_refuse_meme_si_le_plafond_ouvre_l_outil(
        self, magasin, mac_temoin, plafond_de_la_phase_6, operation, params
    ):
        """§5 : ouvrir diapason_app pour ses données n'ouvre pas, sans
        décision, le pilotage et la lecture de la fenêtre du Mac."""
        from diapason.core.origine_telephone import marquer_le_telephone

        with marquer_le_telephone():
            rendus = [
                par_l_executeur(operation, params),
                DiapasonAppTool().execute(operation=operation, params=params),
            ]
        for rendu in rendus:
            assert not rendu.success, f"{operation} a répondu au téléphone"
            assert "téléphone" in rendu.content and operation in rendu.content, (
                "le refus nomme l'opération et dit pourquoi, sans exception levée"
            )
        assert mac_temoin == [], f"{operation} a touché la fenêtre du Mac"

    @pytest.mark.parametrize("operation", ["ouvrir_fenetre", "", "screen"])
    def test_ce_que_la_liste_n_autorise_pas_est_refuse_au_telephone(
        self, magasin, mac_temoin, plafond_de_la_phase_6, operation
    ):
        """§5 : la garde est une liste d'AUTORISATION. Une opération du Mac
        ajoutée demain à _executer (ici un nom inventé, la chaîne vide,
        « screen ») doit tomber sur le refus du téléphone, pas sur l'erreur
        générique : une liste de refus qui ne nommerait que navigate et
        current_view laissait passer les 92 tests (revue du 28/09/2026)."""
        from diapason.core.origine_telephone import (
            MOTIF_OPERATION_REFUSEE,
            marquer_le_telephone,
        )

        with marquer_le_telephone():
            rendus = {
                "diapason_app": [
                    par_l_executeur(operation),
                    DiapasonAppTool().execute(operation=operation, params={}),
                ],
                "diapason_app_delete": [
                    DiapasonAppDeleteTool().execute(operation=operation, params={}),
                ],
            }
        for nom, rendus_de_l_outil in rendus.items():
            for rendu in rendus_de_l_outil:
                assert not rendu.success, f"« {operation} » a répondu au téléphone"
                assert rendu.content == MOTIF_OPERATION_REFUSEE.format(
                    operation=operation, nom=nom
                ), (
                    f"« {operation} » hors de la liste doit être refusée PARCE QUE "
                    f"le téléphone la demande, pas en erreur générique : "
                    f"{rendu.content!r}"
                )
        assert mac_temoin == [], "la fenêtre du Mac a été touchée depuis le téléphone"

    def test_les_donnees_restent_permises_si_le_plafond_ouvre_l_outil(
        self, magasin, mac_temoin, plafond_de_la_phase_6
    ):
        """§100 : le refus du Mac ne doit pas emporter les données — écrire,
        relire, décrire et supprimer répondent au téléphone."""
        from diapason.core.origine_telephone import marquer_le_telephone

        with marquer_le_telephone():
            creee = par_l_executeur("create_note", {"body": {"title": "Du téléphone"}})
            assert creee.success, creee.content
            note = json.loads(creee.content)["note"]
            relue = par_l_executeur("get_note", {"noteId": note["id"]})
            decrite = par_l_executeur("describe", name="create_note")
            catalogue = par_l_executeur("catalogue")
            assert relue.success and decrite.success and catalogue.success, (
                "lecture refusée au téléphone"
            )
            supprimee = par_l_executeur("delete_note", {"noteId": note["id"]})
        assert json.loads(relue.content)["note"]["title"] == "Du téléphone"
        assert json.loads(decrite.content)["operation"] == "create_note"
        assert "pages" not in json.loads(catalogue.content), (
            "le catalogue du téléphone n'offre pas les pages qu'il refuse d'ouvrir"
        )
        assert supprimee.success and magasin.list_notes() == [], "suppression réelle"
        assert mac_temoin == [], "aucune donnée ne passe par la fenêtre du Mac"

    def test_la_voix_du_telephone_suit_le_meme_refus(
        self, magasin, mac_temoin, plafond_de_la_phase_6, monkeypatch
    ):
        """La voix filtre ses schémas par NOM (outils_vocaux_du_telephone) :
        une fois diapason_app au plafond, seul l'outil peut refuser navigate."""
        from diapason.core.origine_telephone import marquer_le_telephone
        from diapason.speech.realtime import tools as voix

        monkeypatch.setattr(voix, "_executeurs", {})
        assert "diapason_app" in voix.outils_vocaux_du_telephone(None), (
            "le filtre vocal suit le plafond, nom par nom"
        )
        with marquer_le_telephone():
            navigation = voix.execute_voice_tool(
                "diapason_app",
                {"operation": "navigate", "params": {"page": "finances"}},
                ["diapason_app"],
            )
            ecriture = voix.execute_voice_tool(
                "diapason_app",
                {"operation": "create_note", "params": {"body": {"title": "Voix"}}},
                ["diapason_app"],
            )
        assert navigation["ok"] is False and "téléphone" in navigation["content"]
        assert mac_temoin == [], "la voix du téléphone a piloté la fenêtre du Mac"
        assert ecriture["ok"] is True, ecriture
        assert [n["title"] for n in magasin.list_notes()] == ["Voix"]

    def test_la_discussion_du_telephone_suit_le_meme_refus(
        self, magasin, mac_temoin, plafond_de_la_phase_6
    ):
        """La Discussion retire au téléphone les schémas par NOM
        (_trousse_de_l_origine) : diapason_app y passerait, navigate non."""
        from diapason.core.origine_telephone import marquer_le_telephone
        from diapason.server.routes import _trousse_de_l_origine

        outil = DiapasonAppTool()
        executeur = ToolExecutor([outil], autoload_capability_policy=False)
        with marquer_le_telephone():
            outils, executeur = _trousse_de_l_origine(([outil], executeur))
            rendu = executeur.execute(
                ToolCall(
                    id="essai",
                    name="diapason_app",
                    arguments=json.dumps({"operation": "current_view"}),
                )
            )
        assert outils == [outil], "le plafond simulé laisse passer le nom"
        assert not rendu.success and "téléphone" in rendu.content
        assert mac_temoin == [], "la Discussion du téléphone a lu la fenêtre du Mac"

    @pytest.mark.parametrize(("operation", "params"), _LE_MAC)
    def test_au_bureau_rien_ne_change(self, magasin, mac_temoin, operation, params):
        """§82 : le refus du téléphone n'ôte rien au bureau."""
        rendu = par_l_executeur(operation, params)
        assert rendu.success, rendu.content
        assert mac_temoin == [operation], f"{operation} n'a pas atteint la fenêtre"
        catalogue = par_l_executeur("catalogue")
        assert "finances" in json.loads(catalogue.content)["pages"], (
            "le bureau garde les pages que navigate ouvre"
        )


class TestActions:
    def test_note_creee_modifiee_relue_et_supprimee(self, magasin):
        """§100 : même note et même contenu dans l'écran et l'outil."""
        note = appel(
            "create_note", body={"title": "Essai", "content": "Texte initial"}
        )["note"]
        appel(
            "update_note",
            noteId=note["id"],
            body={"appendContent": "\nSuite", "category": "Travail"},
        )
        lue = appel("get_note", noteId=note["id"])["note"]
        assert "Suite" in lue["content"] and lue["category"] == "Travail", (
            "édition conservée"
        )
        assert magasin.get_note(note["id"]) == lue, "source unique"
        appel("delete_note", noteId=note["id"])
        assert magasin.list_notes() == [], "suppression effective"

    def test_finances_enregistrees_et_relues(self, magasin):
        """§100 : solde et budget sont calculés sur les écritures réelles."""
        comptes_avant = magasin.list_accounts()
        compte = appel(
            "create_account", body={"name": "Essai", "openingBalance": 1000}
        )["account"]
        categorie = appel("create_category", body={"name": "Courses"})["category"]
        txn = appel(
            "create_transaction",
            body={
                "accountId": compte["id"],
                "categoryId": categorie["id"],
                "amount": 40,
                "date": "2026-09-27",
            },
        )["transaction"]
        appel(
            "update_account", accountId=compte["id"], body={"name": "Compte quotidien"}
        )
        budget = appel(
            "upsert_budget",
            body={"scope": "global", "yearMonth": "2026-09", "limit": 500},
        )["budget"]
        appel(
            "upsert_budget",
            body={"scope": "global", "yearMonth": "2026-09", "limit": 600},
        )
        objectif = appel("create_goal", body={"name": "Épargne", "target": 2000})[
            "goal"
        ]
        appel("update_goal", goalId=objectif["id"], body={"current": 150})
        abonnement = appel(
            "create_subscription",
            body={"name": "Essai", "amount": 10, "nextDueDate": "2026-10-01"},
        )["subscription"]
        appel("update_subscription", subId=abonnement["id"], body={"active": False})
        assert (
            next(
                c for c in appel("list_accounts")["accounts"] if c["id"] == compte["id"]
            )["balance"]
            == 960
        ), "dépense déduite"
        assert (
            appel("list_budgets", yearMonth="2026-09")["budgets"][0]["limit"] == 600
        ), "budget modifié"
        assert appel("list_goals")["goals"][0]["current"] == 150, "épargne suivie"
        assert appel("list_subscriptions")["subscriptions"][0]["active"] is False, (
            "abonnement arrêté"
        )
        assert (
            len(
                appel("list_transactions", fromDate="2026-09-01", toDate="2026-09-30")[
                    "transactions"
                ]
            )
            == 1
        )
        assert (
            appel("list_transactions", fromDate="2027-01-01")["transactions"] == []
        ), "période filtrée"
        for op, cle, identifiant in [
            ("delete_transaction", "txnId", txn["id"]),
            ("delete_budget", "budgetId", budget["id"]),
            ("delete_goal", "goalId", objectif["id"]),
            ("delete_subscription", "subId", abonnement["id"]),
            ("delete_category", "categoryId", categorie["id"]),
            ("delete_account", "accountId", compte["id"]),
        ]:
            assert appel(op, **{cle: identifiant})["deleted"], op
        assert (
            magasin.list_accounts() == comptes_avant
            and magasin.list_transactions() == []
        ), "suppression réelle"

    def test_suppression_refusee_sans_approbation(self, magasin):
        """§100 : un refus de la cloche ne devient jamais un succès."""
        note = magasin.create_note({"title": "À conserver"})
        executeur = ToolExecutor(
            [DiapasonAppDeleteTool()], confirm_callback=lambda _: False
        )
        resultat = executeur.execute(
            ToolCall(
                id="essai",
                name="diapason_app_delete",
                arguments=json.dumps(
                    {"operation": "delete_note", "params": {"noteId": note["id"]}}
                ),
            )
        )
        assert not resultat.success, "suppression refusée"
        assert magasin.get_note(note["id"]), "note intacte"
