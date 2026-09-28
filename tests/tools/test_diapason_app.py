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
