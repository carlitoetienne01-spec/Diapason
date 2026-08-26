"""HTTP routes for the Succès Finances module."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from diapason.succes.corps import DeleteBody
from diapason.succes.finances import SuccesFinancesStore
from diapason.succes.store import SuccesError

# Models live at module scope. Nested classes plus `from __future__ import
# annotations` make FastAPI treat `body` as a required query param (422).


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["checking", "savings", "cash", "credit", "other"] = "checking"
    openingBalance: float = 0
    color: str = Field(default="#6366f1", max_length=7)
    icon: str = Field(default="🏦", max_length=16)
    opId: str | None = None


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: Literal["checking", "savings", "cash", "credit", "other"] | None = None
    openingBalance: float | None = None
    color: str | None = Field(default=None, max_length=7)
    icon: str | None = Field(default=None, max_length=16)
    archived: bool | None = None
    opId: str | None = None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["income", "expense"] = "expense"
    color: str = Field(default="#6366f1", max_length=7)
    icon: str = Field(default="📦", max_length=16)
    opId: str | None = None


class TransactionCreate(BaseModel):
    accountId: str = Field(min_length=1, max_length=80)
    type: Literal["income", "expense", "transfer"] = "expense"
    amount: float = Field(gt=0)
    date: str = ""
    categoryId: str = ""
    payee: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=2000)
    transferAccountId: str = ""
    subscriptionId: str = ""
    opId: str | None = None


class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0)
    cadence: Literal["weekly", "monthly", "yearly"] = "monthly"
    nextDueDate: str = ""
    accountId: str = ""
    categoryId: str = ""
    reminderDays: int = Field(default=3, ge=0, le=30)
    notes: str = Field(default="", max_length=2000)
    opId: str | None = None


class SubscriptionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    amount: float | None = Field(default=None, gt=0)
    cadence: Literal["weekly", "monthly", "yearly"] | None = None
    nextDueDate: str | None = None
    accountId: str | None = None
    categoryId: str | None = None
    active: bool | None = None
    reminderDays: int | None = Field(default=None, ge=0, le=30)
    notes: str | None = Field(default=None, max_length=2000)
    opId: str | None = None


class BudgetUpsert(BaseModel):
    scope: Literal["global", "category"] = "global"
    categoryId: str = ""
    yearMonth: str = ""
    limit: float = Field(gt=0)
    opId: str | None = None


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target: float = Field(gt=0)
    current: float = Field(default=0, ge=0)
    accountId: str = ""
    deadline: str = ""
    color: str = Field(default="#6366f1", max_length=7)
    icon: str = Field(default="🎯", max_length=16)
    opId: str | None = None


class GoalPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target: float | None = Field(default=None, gt=0)
    current: float | None = Field(default=None, ge=0)
    accountId: str | None = None
    deadline: str | None = None
    color: str | None = Field(default=None, max_length=7)
    icon: str | None = Field(default=None, max_length=16)
    opId: str | None = None


class CsvImportBody(BaseModel):
    csvText: str = Field(min_length=1, max_length=2_000_000)
    accountId: str = Field(min_length=1, max_length=80)
    mapping: dict[str, str] | None = None


def register_finances_routes(
    router: APIRouter,
    *,
    get_store,
    domain_error,
    resolved_date,
) -> None:
    """Poser les routes des Finances sur un routeur existant.

    `DeleteBody` n'est PLUS un paramètre : il arrive par l'import du module,
    ci-dessus. Passé en argument, il n'existait que dans les variables locales
    de cette fonction — et FastAPI résout les annotations différées contre les
    GLOBALES du module, jamais contre elles. `/openapi.json` rendait donc 500
    pour tout le dépôt (constaté le 26 août 2026).
    """

    def _finances() -> SuccesFinancesStore:
        store = get_store()
        if not isinstance(store, SuccesFinancesStore):
            raise HTTPException(
                status_code=503,
                detail="Le module Finances n'est pas disponible.",
            )
        return store

    # ── Accounts ──────────────────────────────────────────────────────

    @router.get("/finances/accounts")
    async def list_accounts(includeArchived: bool = False) -> dict[str, Any]:
        accounts = _finances().list_accounts(include_archived=includeArchived)
        return {"accounts": accounts, "count": len(accounts)}

    @router.post("/finances/accounts", status_code=201)
    async def create_account(body: AccountCreate) -> dict[str, Any]:
        try:
            account = _finances().create_account(
                body.model_dump(exclude={"opId"}), op_id=body.opId
            )
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"account": account, "persistence": "local"}

    @router.patch("/finances/accounts/{account_id}")
    async def update_account(account_id: str, body: AccountPatch) -> dict[str, Any]:
        data = body.model_dump(exclude_none=True, exclude={"opId"})
        try:
            account = _finances().update_account(account_id, data, op_id=body.opId)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"account": account, "persistence": "local"}

    @router.delete("/finances/accounts/{account_id}")
    async def delete_account(account_id: str, body: DeleteBody) -> dict[str, Any]:
        if not body.confirmed:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "confirmation_required",
                    "message": "Confirmez la suppression de ce compte.",
                },
            )
        try:
            _finances().delete_account(account_id, op_id=body.opId)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"deleted": True}

    # ── Categories ────────────────────────────────────────────────────

    @router.get("/finances/categories")
    async def list_categories(kind: str | None = None) -> dict[str, Any]:
        try:
            categories = _finances().list_categories(kind=kind)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"categories": categories, "count": len(categories)}

    @router.post("/finances/categories", status_code=201)
    async def create_category(body: CategoryCreate) -> dict[str, Any]:
        try:
            category = _finances().create_category(
                body.model_dump(exclude={"opId"}), op_id=body.opId
            )
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"category": category, "persistence": "local"}

    @router.delete("/finances/categories/{category_id}")
    async def delete_category(category_id: str, body: DeleteBody) -> dict[str, Any]:
        if not body.confirmed:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "confirmation_required",
                    "message": "Confirmez la suppression de cette catégorie.",
                },
            )
        try:
            _finances().delete_category(category_id, op_id=body.opId)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"deleted": True}

    # ── Transactions ──────────────────────────────────────────────────

    @router.get("/finances/transactions")
    async def list_transactions(
        from_date: str | None = None,
        to_date: str | None = None,
        accountId: str | None = None,
        categoryId: str | None = None,
        type: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        try:
            txns = _finances().list_transactions(
                from_date=resolved_date(from_date) if from_date else None,
                to_date=resolved_date(to_date) if to_date else None,
                account_id=accountId,
                category_id=categoryId,
                txn_type=type,
                limit=limit,
            )
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"transactions": txns, "count": len(txns)}

    @router.post("/finances/transactions", status_code=201)
    async def create_transaction(body: TransactionCreate) -> dict[str, Any]:
        data = body.model_dump(exclude={"opId"})
        if data.get("date"):
            data["date"] = resolved_date(data["date"])
        try:
            txn = _finances().create_transaction(data, op_id=body.opId)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"transaction": txn, "persistence": "local"}

    @router.delete("/finances/transactions/{txn_id}")
    async def delete_transaction(txn_id: str, body: DeleteBody) -> dict[str, Any]:
        if not body.confirmed:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "confirmation_required",
                    "message": "Confirmez la suppression de cette transaction.",
                },
            )
        try:
            _finances().delete_transaction(txn_id, op_id=body.opId)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"deleted": True}

    # ── Subscriptions ─────────────────────────────────────────────────

    @router.get("/finances/subscriptions")
    async def list_subscriptions(activeOnly: bool = False) -> dict[str, Any]:
        subs = _finances().list_subscriptions(active_only=activeOnly)
        return {"subscriptions": subs, "count": len(subs)}

    @router.post("/finances/subscriptions", status_code=201)
    async def create_subscription(body: SubscriptionCreate) -> dict[str, Any]:
        data = body.model_dump(exclude={"opId"})
        if data.get("nextDueDate"):
            data["nextDueDate"] = resolved_date(data["nextDueDate"])
        try:
            sub = _finances().create_subscription(data, op_id=body.opId)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"subscription": sub, "persistence": "local"}

    @router.patch("/finances/subscriptions/{sub_id}")
    async def update_subscription(
        sub_id: str, body: SubscriptionPatch
    ) -> dict[str, Any]:
        data = body.model_dump(exclude_none=True, exclude={"opId"})
        if data.get("nextDueDate"):
            data["nextDueDate"] = resolved_date(str(data["nextDueDate"]))
        try:
            sub = _finances().update_subscription(sub_id, data, op_id=body.opId)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"subscription": sub, "persistence": "local"}

    @router.delete("/finances/subscriptions/{sub_id}")
    async def delete_subscription(sub_id: str, body: DeleteBody) -> dict[str, Any]:
        if not body.confirmed:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "confirmation_required",
                    "message": "Confirmez la suppression de cet abonnement.",
                },
            )
        try:
            _finances().delete_subscription(sub_id, op_id=body.opId)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"deleted": True}

    @router.post("/finances/subscriptions/materialize")
    async def materialize_subscriptions(onDate: str | None = None) -> dict[str, Any]:
        try:
            result = _finances().materialize_due_subscriptions(
                on_date=resolved_date(onDate) if onDate else None
            )
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {**result, "persistence": "local"}

    # ── Budgets ───────────────────────────────────────────────────────

    @router.get("/finances/budgets")
    async def list_budgets(yearMonth: str | None = None) -> dict[str, Any]:
        budgets = _finances().list_budgets(year_month=yearMonth)
        return {"budgets": budgets, "count": len(budgets)}

    @router.post("/finances/budgets", status_code=201)
    async def upsert_budget(body: BudgetUpsert) -> dict[str, Any]:
        try:
            budget = _finances().upsert_budget(
                body.model_dump(exclude={"opId"}), op_id=body.opId
            )
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"budget": budget, "persistence": "local"}

    @router.delete("/finances/budgets/{budget_id}")
    async def delete_budget(budget_id: str, body: DeleteBody) -> dict[str, Any]:
        if not body.confirmed:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "confirmation_required",
                    "message": "Confirmez la suppression de ce budget.",
                },
            )
        try:
            _finances().delete_budget(budget_id, op_id=body.opId)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"deleted": True}

    # ── Goals ─────────────────────────────────────────────────────────

    @router.get("/finances/goals")
    async def list_goals() -> dict[str, Any]:
        goals = _finances().list_goals()
        return {"goals": goals, "count": len(goals)}

    @router.post("/finances/goals", status_code=201)
    async def create_goal(body: GoalCreate) -> dict[str, Any]:
        data = body.model_dump(exclude={"opId"})
        if data.get("deadline"):
            data["deadline"] = resolved_date(data["deadline"])
        try:
            goal = _finances().create_goal(data, op_id=body.opId)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"goal": goal, "persistence": "local"}

    @router.patch("/finances/goals/{goal_id}")
    async def update_goal(goal_id: str, body: GoalPatch) -> dict[str, Any]:
        data = body.model_dump(exclude_none=True, exclude={"opId"})
        if "deadline" in data and data["deadline"]:
            data["deadline"] = resolved_date(str(data["deadline"]))
        try:
            goal = _finances().update_goal(goal_id, data, op_id=body.opId)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"goal": goal, "persistence": "local"}

    @router.delete("/finances/goals/{goal_id}")
    async def delete_goal(goal_id: str, body: DeleteBody) -> dict[str, Any]:
        if not body.confirmed:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "confirmation_required",
                    "message": "Confirmez la suppression de cet objectif.",
                },
            )
        try:
            _finances().delete_goal(goal_id, op_id=body.opId)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"deleted": True}

    # ── Overview + CSV ────────────────────────────────────────────────

    @router.get("/finances/overview")
    async def finance_overview(
        period: Literal["day", "week", "month", "year"] = "month",
        anchor: str | None = None,
    ) -> dict[str, Any]:
        try:
            return _finances().finance_overview(
                period=period,
                anchor=resolved_date(anchor) if anchor else None,
            )
        except SuccesError as exc:
            raise domain_error(exc) from exc

    @router.post("/finances/import/csv")
    async def import_csv(body: CsvImportBody) -> dict[str, Any]:
        try:
            summary = _finances().import_csv(
                body.csvText, account_id=body.accountId, mapping=body.mapping
            )
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"summary": summary, "persistence": "local"}
