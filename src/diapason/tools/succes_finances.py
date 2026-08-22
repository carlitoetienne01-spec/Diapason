"""DIA tools for private Succès finances — read cashflow and log money."""

from __future__ import annotations

from typing import Any

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.succes.dates import resolve_date_expression
from diapason.succes.finances import SuccesFinancesStore
from diapason.succes.store import SuccesError
from diapason.succes.sync import SuccesSyncStore
from diapason.tools._stubs import BaseTool, ToolSpec


def _result(
    name: str, success: bool, content: str, metadata: dict[str, Any]
) -> ToolResult:
    return ToolResult(
        tool_name=name, success=success, content=content, metadata=metadata
    )


def _resolve_date(value: Any, *, optional: bool = True) -> str:
    raw = str(value or "").strip()
    if not raw and optional:
        return ""
    resolution = resolve_date_expression(raw)
    if resolution.status == "ambiguous":
        raise SuccesError(
            "Cette date est ambiguë. Demandez de choisir entre "
            + " et ".join(resolution.options)
            + "."
        )
    if resolution.status != "exact" or not resolution.value:
        raise SuccesError("Je n'ai pas reconnu cette date. Demandez une date précise.")
    return resolution.value


def _store() -> SuccesFinancesStore:
    return SuccesSyncStore()


@ToolRegistry.register("succes_finances")
class SuccesFinancesTool(BaseTool):
    """Inspect and record personal finances in the local Succès ledger."""

    tool_id = "succes_finances"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="succes_finances",
            description=(
                "Gère le budget personnel Succès (CAD $) : résumé revenus/dépenses, "
                "ajout d'une dépense ou d'un revenu, liste des abonnements et soldes. "
                "Utilise overview pour répondre « où va mon argent », "
                "add_transaction pour enregistrer une dépense/revenu dit à voix haute."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "overview",
                            "add_transaction",
                            "list_accounts",
                            "list_subscriptions",
                            "list_categories",
                        ],
                        "description": "Action à exécuter.",
                    },
                    "period": {
                        "type": "string",
                        "enum": ["day", "week", "month", "year"],
                        "description": "Période pour overview (défaut: month).",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["income", "expense"],
                        "description": "Type de transaction pour add_transaction.",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Montant en dollars CAD.",
                    },
                    "payee": {
                        "type": "string",
                        "description": "Bénéficiaire ou source.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Nom de catégorie (ex. Épicerie, Salaire).",
                    },
                    "account": {
                        "type": "string",
                        "description": "Nom du compte (défaut: premier compte).",
                    },
                    "date": {
                        "type": "string",
                        "description": "Date (aujourd'hui si vide).",
                    },
                    "notes": {"type": "string"},
                },
                "required": ["action"],
            },
            category="succes",
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip()
        try:
            store = _store()
            if action == "overview":
                period = str(kwargs.get("period") or "month")
                overview = store.finance_overview(period=period)
                top = overview["categoryBreakdown"][:5]
                lines = [
                    f"Période {overview['from']} → {overview['to']} (CAD $)",
                    f"Revenus : {overview['income']:.2f} $",
                    f"Dépenses : {overview['expense']:.2f} $",
                    f"Solde : {overview['net']:.2f} $",
                    f"Prévision fin de période : {overview['forecastRemaining']:.2f} $ "
                    "restants",
                ]
                if top:
                    lines.append("Top dépenses :")
                    for item in top:
                        lines.append(
                            f"  • {item['icon']} {item['name']} : {item['amount']:.2f} "
                            "$"
                        )
                return _result(
                    self.tool_id, True, "\n".join(lines), {"overview": overview}
                )

            if action == "list_accounts":
                accounts = store.list_accounts()
                lines = [
                    f"{a['icon']} {a['name']} — {a['balance']:.2f} $" for a in accounts
                ] or ["Aucun compte."]
                return _result(
                    self.tool_id, True, "\n".join(lines), {"accounts": accounts}
                )

            if action == "list_subscriptions":
                subs = store.list_subscriptions(active_only=True)
                lines = [
                    f"{s['name']} — {s['amount']:.2f} $ / {s['cadence']} (prochain : "
                    "{s['nextDueDate']})"
                    for s in subs
                ] or ["Aucun abonnement actif."]
                return _result(
                    self.tool_id, True, "\n".join(lines), {"subscriptions": subs}
                )

            if action == "list_categories":
                cats = store.list_categories()
                lines = [f"{c['icon']} {c['name']} ({c['kind']})" for c in cats]
                return _result(
                    self.tool_id, True, "\n".join(lines), {"categories": cats}
                )

            if action == "add_transaction":
                txn_type = str(kwargs.get("type") or "expense").strip()
                if txn_type not in {"income", "expense"}:
                    raise SuccesError("Le type doit être income ou expense.")
                amount = kwargs.get("amount")
                if amount is None:
                    raise SuccesError("Le montant est obligatoire.")
                accounts = store.list_accounts()
                if not accounts:
                    raise SuccesError("Aucun compte n'existe encore.")
                account_name = str(kwargs.get("account") or "").strip().casefold()
                account = (
                    next(
                        (a for a in accounts if a["name"].casefold() == account_name),
                        accounts[0],
                    )
                    if account_name
                    else accounts[0]
                )
                category_id = ""
                cat_name = str(kwargs.get("category") or "").strip()
                if cat_name:
                    kind = "income" if txn_type == "income" else "expense"
                    match = next(
                        (
                            c
                            for c in store.list_categories(kind=kind)
                            if c["name"].casefold() == cat_name.casefold()
                        ),
                        None,
                    )
                    if match:
                        category_id = match["id"]
                txn = store.create_transaction(
                    {
                        "accountId": account["id"],
                        "type": txn_type,
                        "amount": amount,
                        "date": _resolve_date(kwargs.get("date")),
                        "categoryId": category_id,
                        "payee": str(kwargs.get("payee") or "")[:160],
                        "notes": str(kwargs.get("notes") or "")[:2000],
                    }
                )
                label = "Revenu" if txn_type == "income" else "Dépense"
                return _result(
                    self.tool_id,
                    True,
                    f"{label} de {txn['amount']:.2f} $ enregistré(e) "
                    f"({txn['payee'] or 'sans libellé'}) sur {account['name']}.",
                    {"transaction": txn},
                )

            raise SuccesError(f"Action inconnue : {action}")
        except SuccesError as exc:
            return _result(self.tool_id, False, str(exc), {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            return _result(
                self.tool_id, False, f"Erreur finances : {exc}", {"error": str(exc)}
            )
