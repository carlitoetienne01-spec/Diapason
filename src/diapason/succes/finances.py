"""Personal finances for the native Succès domain — local-first CAD budgeting.

Accounts, categories, transactions, subscriptions, budgets and savings goals
live beside habits/notes in succes.db. Money is stored as integer cents.
Remote sync is wired later; mutations still go through the operation log.
"""

from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

from diapason.succes.continuity import SuccesContinuityStore
from diapason.succes.store import (
    SuccesError,
    SuccesNotFound,
    _clean_text,
    _validate_iso_date,
    now_ms,
)
from diapason.succes.workspace import _color

ACCOUNT_TYPES = frozenset({"checking", "savings", "cash", "credit", "other"})
CATEGORY_KINDS = frozenset({"income", "expense"})
TXN_TYPES = frozenset({"income", "expense", "transfer"})
SUB_CADENCES = frozenset({"weekly", "monthly", "yearly"})
BUDGET_SCOPES = frozenset({"global", "category"})
PERIODS = frozenset({"day", "week", "month", "year"})

DEFAULT_EXPENSE_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("Épicerie", "🛒", "#22c55e"),
    ("Loyer / Hypothèque", "🏠", "#6366f1"),
    ("Services publics", "💡", "#f59e0b"),
    ("Transport", "🚗", "#3b82f6"),
    ("Abonnements", "🔁", "#a855f7"),
    ("Restauration", "🍽️", "#ef4444"),
    ("Santé", "💊", "#14b8a6"),
    ("Loisirs", "🎮", "#ec4899"),
    ("Shopping", "🛍️", "#f97316"),
    ("Éducation", "📚", "#0ea5e9"),
    ("Assurances", "🛡️", "#64748b"),
    ("Impôts & frais", "🧾", "#78716c"),
    ("Autre dépense", "📦", "#94a3b8"),
)

DEFAULT_INCOME_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("Salaire", "💼", "#16a34a"),
    ("Freelance", "💻", "#2563eb"),
    ("Aides", "🤝", "#ca8a04"),
    ("Investissements", "📈", "#7c3aed"),
    ("Cadeaux", "🎁", "#db2777"),
    ("Autre revenu", "💰", "#059669"),
)

_FINANCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS succes_accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL DEFAULT 'checking',
    currency TEXT NOT NULL DEFAULT 'CAD',
    opening_balance_cents INTEGER NOT NULL DEFAULT 0,
    color TEXT NOT NULL DEFAULT '#6366f1',
    icon TEXT NOT NULL DEFAULT '🏦',
    archived INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS succes_finance_categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'expense',
    color TEXT NOT NULL DEFAULT '#6366f1',
    icon TEXT NOT NULL DEFAULT '📦',
    system INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS succes_transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    category_id TEXT NOT NULL DEFAULT '',
    txn_type TEXT NOT NULL DEFAULT 'expense',
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CAD',
    txn_date TEXT NOT NULL,
    payee TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    transfer_account_id TEXT NOT NULL DEFAULT '',
    subscription_id TEXT NOT NULL DEFAULT '',
    import_hash TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_succes_txn_date
    ON succes_transactions(txn_date);
CREATE INDEX IF NOT EXISTS idx_succes_txn_account
    ON succes_transactions(account_id, txn_date);
CREATE INDEX IF NOT EXISTS idx_succes_txn_category
    ON succes_transactions(category_id, txn_date);

CREATE TABLE IF NOT EXISTS succes_subscriptions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CAD',
    cadence TEXT NOT NULL DEFAULT 'monthly',
    next_due_date TEXT NOT NULL,
    account_id TEXT NOT NULL DEFAULT '',
    category_id TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    reminder_days INTEGER NOT NULL DEFAULT 3,
    notes TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS succes_budgets (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'global',
    category_id TEXT NOT NULL DEFAULT '',
    year_month TEXT NOT NULL,
    limit_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CAD',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS succes_savings_goals (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    target_cents INTEGER NOT NULL,
    current_cents INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'CAD',
    account_id TEXT NOT NULL DEFAULT '',
    deadline TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#6366f1',
    icon TEXT NOT NULL DEFAULT '🎯',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);

PRAGMA user_version = 5;
"""


def _to_cents(value: Any) -> int:
    if value is None or value == "":
        raise SuccesError("Le montant est obligatoire.")
    try:
        amount = float(
            str(value).replace(",", ".").replace("$", "").replace(" ", "").strip()
        )
    except (TypeError, ValueError) as exc:
        raise SuccesError("Montant invalide.") from exc
    if amount < 0:
        raise SuccesError("Le montant doit être positif.")
    return int(round(amount * 100))


def _from_cents(cents: int) -> float:
    return round(cents / 100.0, 2)


def _year_month(value: str | None = None) -> str:
    if value:
        text = value.strip()
        if len(text) == 7 and text[4] == "-":
            return text
        return _validate_iso_date(text)[:7]
    return date.today().isoformat()[:7]


def _period_bounds(period: str, anchor: str | None = None) -> tuple[str, str]:
    day = date.fromisoformat(
        _validate_iso_date(anchor) if anchor else date.today().isoformat()
    )
    if period == "day":
        return day.isoformat(), day.isoformat()
    if period == "week":
        start = day - timedelta(days=day.weekday())  # Monday
        end = start + timedelta(days=6)
        return start.isoformat(), end.isoformat()
    if period == "year":
        return f"{day.year}-01-01", f"{day.year}-12-31"
    # month
    start = day.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _advance_due(due: str, cadence: str) -> str:
    current = date.fromisoformat(_validate_iso_date(due))
    if cadence == "weekly":
        return (current + timedelta(days=7)).isoformat()
    if cadence == "yearly":
        try:
            return current.replace(year=current.year + 1).isoformat()
        except ValueError:
            return current.replace(year=current.year + 1, day=28).isoformat()
    # monthly
    month = current.month + 1
    year = current.year
    if month > 12:
        month = 1
        year += 1
    day = min(current.day, 28)
    for candidate in (current.day, day, 28, 27, 26):
        try:
            return date(year, month, candidate).isoformat()
        except ValueError:
            continue
    return date(year, month, 1).isoformat()


class SuccesFinancesStore(SuccesContinuityStore):
    """Accounts, cashflow, subscriptions, budgets and savings goals."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__(db_path)
        with self._connect() as conn:
            conn.executescript(_FINANCES_SCHEMA)
            self._seed_defaults(conn)
            conn.commit()

    def _seed_defaults(self, conn: sqlite3.Connection) -> None:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM succes_finance_categories WHERE deleted_at_ms "
            "IS NULL"
        ).fetchone()["n"]
        if count:
            return
        stamp = now_ms()
        for name, icon, color in DEFAULT_EXPENSE_CATEGORIES:
            conn.execute(
                """INSERT INTO succes_finance_categories
                   (id, name, kind, color, icon, system, updated_at_ms)
                   VALUES (?, ?, 'expense', ?, ?, 1, ?)""",
                (str(uuid.uuid4()), name, color, icon, stamp),
            )
        for name, icon, color in DEFAULT_INCOME_CATEGORIES:
            conn.execute(
                """INSERT INTO succes_finance_categories
                   (id, name, kind, color, icon, system, updated_at_ms)
                   VALUES (?, ?, 'income', ?, ?, 1, ?)""",
                (str(uuid.uuid4()), name, color, icon, stamp),
            )
        # Default checking account if none.
        accounts = conn.execute(
            "SELECT COUNT(*) AS n FROM succes_accounts WHERE deleted_at_ms IS NULL"
        ).fetchone()["n"]
        if not accounts:
            conn.execute(
                """INSERT INTO succes_accounts
                   (id, name, account_type, currency, opening_balance_cents,
                    color, icon, archived, updated_at_ms)
                   VALUES (?, 'Compte chèque', 'checking', 'CAD', 0,
                           '#6366f1', '🏦', 0, ?)""",
                (str(uuid.uuid4()), stamp),
            )

    # ── dict helpers ──────────────────────────────────────────────────

    @staticmethod
    def _account_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "type": row["account_type"],
            "currency": row["currency"],
            "openingBalance": _from_cents(int(row["opening_balance_cents"])),
            "color": row["color"],
            "icon": row["icon"],
            "archived": bool(row["archived"]),
            "updatedAtMs": int(row["updated_at_ms"]),
        }

    @staticmethod
    def _category_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "kind": row["kind"],
            "color": row["color"],
            "icon": row["icon"],
            "system": bool(row["system"]),
            "updatedAtMs": int(row["updated_at_ms"]),
        }

    @staticmethod
    def _txn_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "accountId": row["account_id"],
            "categoryId": row["category_id"] or "",
            "type": row["txn_type"],
            "amount": _from_cents(int(row["amount_cents"])),
            "currency": row["currency"],
            "date": row["txn_date"],
            "payee": row["payee"],
            "notes": row["notes"],
            "transferAccountId": row["transfer_account_id"] or "",
            "subscriptionId": row["subscription_id"] or "",
            "updatedAtMs": int(row["updated_at_ms"]),
        }

    @staticmethod
    def _subscription_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "amount": _from_cents(int(row["amount_cents"])),
            "currency": row["currency"],
            "cadence": row["cadence"],
            "nextDueDate": row["next_due_date"],
            "accountId": row["account_id"] or "",
            "categoryId": row["category_id"] or "",
            "active": bool(row["active"]),
            "reminderDays": int(row["reminder_days"]),
            "notes": row["notes"],
            "updatedAtMs": int(row["updated_at_ms"]),
        }

    @staticmethod
    def _budget_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "scope": row["scope"],
            "categoryId": row["category_id"] or "",
            "yearMonth": row["year_month"],
            "limit": _from_cents(int(row["limit_cents"])),
            "currency": row["currency"],
            "updatedAtMs": int(row["updated_at_ms"]),
        }

    @staticmethod
    def _goal_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "target": _from_cents(int(row["target_cents"])),
            "current": _from_cents(int(row["current_cents"])),
            "currency": row["currency"],
            "accountId": row["account_id"] or "",
            "deadline": row["deadline"] or "",
            "color": row["color"],
            "icon": row["icon"],
            "updatedAtMs": int(row["updated_at_ms"]),
        }

    def _load_account(
        self, conn: sqlite3.Connection, entity_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_accounts WHERE id=? AND deleted_at_ms IS NULL",
            (entity_id,),
        ).fetchone()
        return self._account_dict(row) if row else None

    def _load_category(
        self, conn: sqlite3.Connection, entity_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_finance_categories WHERE id=? AND deleted_at_ms IS "
            "NULL",
            (entity_id,),
        ).fetchone()
        return self._category_dict(row) if row else None

    def _load_txn(
        self, conn: sqlite3.Connection, entity_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_transactions WHERE id=? AND deleted_at_ms IS NULL",
            (entity_id,),
        ).fetchone()
        return self._txn_dict(row) if row else None

    def _load_subscription(
        self, conn: sqlite3.Connection, entity_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_subscriptions WHERE id=? AND deleted_at_ms IS NULL",
            (entity_id,),
        ).fetchone()
        return self._subscription_dict(row) if row else None

    def _load_budget(
        self, conn: sqlite3.Connection, entity_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_budgets WHERE id=? AND deleted_at_ms IS NULL",
            (entity_id,),
        ).fetchone()
        return self._budget_dict(row) if row else None

    def _load_goal(
        self, conn: sqlite3.Connection, entity_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_savings_goals WHERE id=? AND deleted_at_ms IS NULL",
            (entity_id,),
        ).fetchone()
        return self._goal_dict(row) if row else None

    # ── Accounts ──────────────────────────────────────────────────────

    def list_accounts(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        clause = "deleted_at_ms IS NULL"
        if not include_archived:
            clause += " AND archived=0"
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM succes_accounts WHERE {clause} ORDER BY name COLLATE "
                "NOCASE"
            ).fetchall()
            accounts = [self._account_dict(row) for row in rows]
            for account in accounts:
                account["balance"] = self._account_balance(
                    conn, account["id"], account["openingBalance"]
                )
        return accounts

    def _account_balance(
        self, conn: sqlite3.Connection, account_id: str, opening: float
    ) -> float:
        rows = conn.execute(
            """SELECT account_id, txn_type, amount_cents, transfer_account_id
               FROM succes_transactions
               WHERE deleted_at_ms IS NULL
                 AND (account_id=? OR transfer_account_id=?)""",
            (account_id, account_id),
        ).fetchall()
        cents = int(round(opening * 100))
        for row in rows:
            amount = int(row["amount_cents"])
            kind = row["txn_type"]
            if kind == "income" and row["account_id"] == account_id:
                cents += amount
            elif kind == "expense" and row["account_id"] == account_id:
                cents -= amount
            elif kind == "transfer":
                if row["account_id"] == account_id:
                    cents -= amount
                if row["transfer_account_id"] == account_id:
                    cents += amount
        return _from_cents(cents)

    def create_account(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        name = _clean_text(
            data.get("name"), field="Nom du compte", maximum=120, required=True
        )
        account_type = str(data.get("type") or "checking").strip()
        if account_type not in ACCOUNT_TYPES:
            raise SuccesError("Type de compte invalide.")
        opening = _to_cents(data.get("openingBalance", 0))
        color = _color(data.get("color") or "#6366f1")
        icon = (
            _clean_text(
                data.get("icon") or "🏦", field="Icône", maximum=16, required=True
            )
            or "🏦"
        )
        request = {
            "action": "create_account",
            "name": name,
            "type": account_type,
            "openingBalance": opening,
            "color": color,
            "icon": icon,
        }
        account_id = str(uuid.uuid4())
        stamp = now_ms()
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_account)
            if replay is not None:
                return replay
            conn.execute(
                """INSERT INTO succes_accounts
                   (id, name, account_type, currency, opening_balance_cents,
                    color, icon, archived, updated_at_ms)
                   VALUES (?, ?, ?, 'CAD', ?, ?, ?, 0, ?)""",
                (account_id, name, account_type, opening, color, icon, stamp),
            )
            payload = self._load_account(conn, account_id)
            assert payload is not None
            self._record_op(
                conn,
                entity="accounts",
                entity_id=account_id,
                kind="upsert",
                payload=payload,
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )
            payload["balance"] = self._account_balance(
                conn, account_id, payload["openingBalance"]
            )
            return payload

    def update_account(
        self, account_id: str, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        stamp = now_ms()
        request = {"action": "update_account", "id": account_id, **dict(data)}
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_account)
            if replay is not None:
                return replay
            existing = self._load_account(conn, account_id)
            if existing is None:
                raise SuccesNotFound("Ce compte n'existe pas.")
            name = (
                _clean_text(
                    data["name"], field="Nom du compte", maximum=120, required=True
                )
                if "name" in data
                else existing["name"]
            )
            account_type = str(data.get("type") or existing["type"])
            if account_type not in ACCOUNT_TYPES:
                raise SuccesError("Type de compte invalide.")
            opening = (
                _to_cents(data["openingBalance"])
                if "openingBalance" in data
                else int(round(existing["openingBalance"] * 100))
            )
            color = _color(data.get("color") or existing["color"])
            icon = (
                _clean_text(
                    data.get("icon") or existing["icon"],
                    field="Icône",
                    maximum=16,
                    required=True,
                )
                or existing["icon"]
            )
            archived = (
                int(bool(data["archived"]))
                if "archived" in data
                else int(existing["archived"])
            )
            conn.execute(
                """UPDATE succes_accounts SET name=?, account_type=?, opening_balance_cents=?,
                   color=?, icon=?, archived=?, updated_at_ms=?
                   WHERE id=? AND deleted_at_ms IS NULL""",
                (name, account_type, opening, color, icon, archived, stamp, account_id),
            )
            payload = self._load_account(conn, account_id)
            assert payload is not None
            self._record_op(
                conn,
                entity="accounts",
                entity_id=account_id,
                kind="upsert",
                payload=payload,
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )
            payload["balance"] = self._account_balance(
                conn, account_id, payload["openingBalance"]
            )
            return payload

    def delete_account(self, account_id: str, *, op_id: str | None = None) -> None:
        stamp = now_ms()
        request = {"action": "delete_account", "id": account_id}
        with self._transaction() as conn:
            if (
                self._replayed_entity(conn, op_id, request, self._load_account)
                is not None
            ):
                return
            existing = self._load_account(conn, account_id)
            if existing is None:
                raise SuccesNotFound("Ce compte n'existe pas.")
            conn.execute(
                "UPDATE succes_accounts SET deleted_at_ms=?, updated_at_ms=? WHERE "
                "id=?",
                (stamp, stamp, account_id),
            )
            self._record_op(
                conn,
                entity="accounts",
                entity_id=account_id,
                kind="delete",
                payload={"id": account_id},
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )

    # ── Categories ────────────────────────────────────────────────────

    def list_categories(self, *, kind: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM succes_finance_categories WHERE deleted_at_ms IS NULL"
        params: list[Any] = []
        if kind:
            if kind not in CATEGORY_KINDS:
                raise SuccesError("Type de catégorie invalide.")
            query += " AND kind=?"
            params.append(kind)
        query += " ORDER BY kind, name COLLATE NOCASE"
        with self._connect() as conn:
            return [
                self._category_dict(row)
                for row in conn.execute(query, params).fetchall()
            ]

    def create_category(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        name = _clean_text(
            data.get("name"), field="Nom de la catégorie", maximum=80, required=True
        )
        kind = str(data.get("kind") or "expense").strip()
        if kind not in CATEGORY_KINDS:
            raise SuccesError("Type de catégorie invalide.")
        color = _color(data.get("color") or "#6366f1")
        icon = (
            _clean_text(
                data.get("icon") or "📦", field="Icône", maximum=16, required=True
            )
            or "📦"
        )
        request = {
            "action": "create_finance_category",
            "name": name,
            "kind": kind,
            "color": color,
            "icon": icon,
        }
        category_id = str(uuid.uuid4())
        stamp = now_ms()
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_category)
            if replay is not None:
                return replay
            conn.execute(
                """INSERT INTO succes_finance_categories
                   (id, name, kind, color, icon, system, updated_at_ms)
                   VALUES (?, ?, ?, ?, ?, 0, ?)""",
                (category_id, name, kind, color, icon, stamp),
            )
            payload = self._load_category(conn, category_id)
            assert payload is not None
            self._record_op(
                conn,
                entity="finance_categories",
                entity_id=category_id,
                kind="upsert",
                payload=payload,
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )
            return payload

    def delete_category(self, category_id: str, *, op_id: str | None = None) -> None:
        stamp = now_ms()
        request = {"action": "delete_finance_category", "id": category_id}
        with self._transaction() as conn:
            if (
                self._replayed_entity(conn, op_id, request, self._load_category)
                is not None
            ):
                return
            existing = self._load_category(conn, category_id)
            if existing is None:
                raise SuccesNotFound("Cette catégorie n'existe pas.")
            if existing["system"]:
                raise SuccesError("Impossible de supprimer une catégorie système.")
            conn.execute(
                "UPDATE succes_finance_categories SET deleted_at_ms=?, updated_at_ms=? "
                "WHERE id=?",
                (stamp, stamp, category_id),
            )
            self._record_op(
                conn,
                entity="finance_categories",
                entity_id=category_id,
                kind="delete",
                payload={"id": category_id},
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )

    # ── Transactions ──────────────────────────────────────────────────

    def list_transactions(
        self,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        account_id: str | None = None,
        category_id: str | None = None,
        txn_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM succes_transactions WHERE deleted_at_ms IS NULL"
        params: list[Any] = []
        if from_date:
            query += " AND txn_date>=?"
            params.append(_validate_iso_date(from_date))
        if to_date:
            query += " AND txn_date<=?"
            params.append(_validate_iso_date(to_date))
        if account_id:
            query += " AND (account_id=? OR transfer_account_id=?)"
            params.extend([account_id, account_id])
        if category_id:
            query += " AND category_id=?"
            params.append(category_id)
        if txn_type:
            if txn_type not in TXN_TYPES:
                raise SuccesError("Type de transaction invalide.")
            query += " AND txn_type=?"
            params.append(txn_type)
        query += " ORDER BY txn_date DESC, updated_at_ms DESC LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        with self._connect() as conn:
            return [
                self._txn_dict(row) for row in conn.execute(query, params).fetchall()
            ]

    def create_transaction(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        account_id = _clean_text(
            data.get("accountId"), field="Compte", maximum=80, required=True
        )
        txn_type = str(data.get("type") or "expense").strip()
        if txn_type not in TXN_TYPES:
            raise SuccesError("Type de transaction invalide.")
        amount = _to_cents(data.get("amount"))
        txn_date = _validate_iso_date(str(data.get("date") or date.today().isoformat()))
        category_id = _clean_text(
            data.get("categoryId") or "", field="Catégorie", maximum=80
        )
        payee = _clean_text(data.get("payee") or "", field="Bénéficiaire", maximum=160)
        notes = _clean_text(data.get("notes") or "", field="Notes", maximum=2000)
        transfer_account_id = _clean_text(
            data.get("transferAccountId") or "", field="Compte destination", maximum=80
        )
        subscription_id = _clean_text(
            data.get("subscriptionId") or "", field="Abonnement", maximum=80
        )
        if txn_type == "transfer":
            if not transfer_account_id:
                raise SuccesError("Un transfert nécessite un compte destination.")
            if transfer_account_id == account_id:
                raise SuccesError("Les comptes source et destination doivent différer.")
            category_id = ""
        request = {
            "action": "create_transaction",
            "accountId": account_id,
            "type": txn_type,
            "amount": amount,
            "date": txn_date,
            "categoryId": category_id,
            "payee": payee,
            "notes": notes,
            "transferAccountId": transfer_account_id,
            "subscriptionId": subscription_id,
        }
        txn_id = str(uuid.uuid4())
        stamp = now_ms()
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_txn)
            if replay is not None:
                return replay
            if self._load_account(conn, account_id) is None:
                raise SuccesNotFound("Ce compte n'existe pas.")
            if (
                transfer_account_id
                and self._load_account(conn, transfer_account_id) is None
            ):
                raise SuccesNotFound("Le compte destination n'existe pas.")
            if category_id and self._load_category(conn, category_id) is None:
                raise SuccesNotFound("Cette catégorie n'existe pas.")
            conn.execute(
                """INSERT INTO succes_transactions
                   (id, account_id, category_id, txn_type, amount_cents, currency,
                    txn_date, payee, notes, transfer_account_id, subscription_id,
                    import_hash, updated_at_ms)
                   VALUES (?, ?, ?, ?, ?, 'CAD', ?, ?, ?, ?, ?, '', ?)""",
                (
                    txn_id,
                    account_id,
                    category_id,
                    txn_type,
                    amount,
                    txn_date,
                    payee,
                    notes,
                    transfer_account_id,
                    subscription_id,
                    stamp,
                ),
            )
            payload = self._load_txn(conn, txn_id)
            assert payload is not None
            self._record_op(
                conn,
                entity="transactions",
                entity_id=txn_id,
                kind="upsert",
                payload=payload,
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )
            return payload

    def delete_transaction(self, txn_id: str, *, op_id: str | None = None) -> None:
        stamp = now_ms()
        request = {"action": "delete_transaction", "id": txn_id}
        with self._transaction() as conn:
            if self._replayed_entity(conn, op_id, request, self._load_txn) is not None:
                return
            if self._load_txn(conn, txn_id) is None:
                raise SuccesNotFound("Cette transaction n'existe pas.")
            conn.execute(
                "UPDATE succes_transactions SET deleted_at_ms=?, updated_at_ms=? WHERE "
                "id=?",
                (stamp, stamp, txn_id),
            )
            self._record_op(
                conn,
                entity="transactions",
                entity_id=txn_id,
                kind="delete",
                payload={"id": txn_id},
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )

    # ── Subscriptions ─────────────────────────────────────────────────

    def list_subscriptions(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM succes_subscriptions WHERE deleted_at_ms IS NULL"
        if active_only:
            query += " AND active=1"
        query += " ORDER BY next_due_date ASC, name COLLATE NOCASE"
        with self._connect() as conn:
            return [
                self._subscription_dict(row) for row in conn.execute(query).fetchall()
            ]

    def create_subscription(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        name = _clean_text(
            data.get("name"), field="Nom de l'abonnement", maximum=120, required=True
        )
        amount = _to_cents(data.get("amount"))
        cadence = str(data.get("cadence") or "monthly").strip()
        if cadence not in SUB_CADENCES:
            raise SuccesError("Fréquence d'abonnement invalide.")
        next_due = _validate_iso_date(
            str(data.get("nextDueDate") or date.today().isoformat())
        )
        account_id = _clean_text(
            data.get("accountId") or "", field="Compte", maximum=80
        )
        category_id = _clean_text(
            data.get("categoryId") or "", field="Catégorie", maximum=80
        )
        reminder = max(0, min(30, int(data.get("reminderDays") or 3)))
        notes = _clean_text(data.get("notes") or "", field="Notes", maximum=2000)
        request = {
            "action": "create_subscription",
            "name": name,
            "amount": amount,
            "cadence": cadence,
            "nextDueDate": next_due,
            "accountId": account_id,
            "categoryId": category_id,
            "reminderDays": reminder,
            "notes": notes,
        }
        sub_id = str(uuid.uuid4())
        stamp = now_ms()
        with self._transaction() as conn:
            replay = self._replayed_entity(
                conn, op_id, request, self._load_subscription
            )
            if replay is not None:
                return replay
            conn.execute(
                """INSERT INTO succes_subscriptions
                   (id, name, amount_cents, currency, cadence, next_due_date,
                    account_id, category_id, active, reminder_days, notes, updated_at_ms)
                   VALUES (?, ?, ?, 'CAD', ?, ?, ?, ?, 1, ?, ?, ?)""",
                (
                    sub_id,
                    name,
                    amount,
                    cadence,
                    next_due,
                    account_id,
                    category_id,
                    reminder,
                    notes,
                    stamp,
                ),
            )
            payload = self._load_subscription(conn, sub_id)
            assert payload is not None
            self._record_op(
                conn,
                entity="subscriptions",
                entity_id=sub_id,
                kind="upsert",
                payload=payload,
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )
            return payload

    def update_subscription(
        self, sub_id: str, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        stamp = now_ms()
        request = {"action": "update_subscription", "id": sub_id, **dict(data)}
        with self._transaction() as conn:
            replay = self._replayed_entity(
                conn, op_id, request, self._load_subscription
            )
            if replay is not None:
                return replay
            existing = self._load_subscription(conn, sub_id)
            if existing is None:
                raise SuccesNotFound("Cet abonnement n'existe pas.")
            name = (
                _clean_text(data["name"], field="Nom", maximum=120, required=True)
                if "name" in data
                else existing["name"]
            )
            amount = (
                _to_cents(data["amount"])
                if "amount" in data
                else int(round(existing["amount"] * 100))
            )
            cadence = str(data.get("cadence") or existing["cadence"])
            if cadence not in SUB_CADENCES:
                raise SuccesError("Fréquence d'abonnement invalide.")
            next_due = (
                _validate_iso_date(str(data["nextDueDate"]))
                if "nextDueDate" in data
                else existing["nextDueDate"]
            )
            account_id = data.get("accountId", existing["accountId"]) or ""
            category_id = data.get("categoryId", existing["categoryId"]) or ""
            active = (
                int(bool(data["active"]))
                if "active" in data
                else int(existing["active"])
            )
            reminder = (
                max(0, min(30, int(data["reminderDays"])))
                if "reminderDays" in data
                else existing["reminderDays"]
            )
            notes = data.get("notes", existing["notes"]) or ""
            conn.execute(
                """UPDATE succes_subscriptions SET name=?, amount_cents=?, cadence=?,
                   next_due_date=?, account_id=?, category_id=?, active=?,
                   reminder_days=?, notes=?, updated_at_ms=?
                   WHERE id=? AND deleted_at_ms IS NULL""",
                (
                    name,
                    amount,
                    cadence,
                    next_due,
                    account_id,
                    category_id,
                    active,
                    reminder,
                    notes,
                    stamp,
                    sub_id,
                ),
            )
            payload = self._load_subscription(conn, sub_id)
            assert payload is not None
            self._record_op(
                conn,
                entity="subscriptions",
                entity_id=sub_id,
                kind="upsert",
                payload=payload,
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )
            return payload

    def delete_subscription(self, sub_id: str, *, op_id: str | None = None) -> None:
        stamp = now_ms()
        request = {"action": "delete_subscription", "id": sub_id}
        with self._transaction() as conn:
            if (
                self._replayed_entity(conn, op_id, request, self._load_subscription)
                is not None
            ):
                return
            if self._load_subscription(conn, sub_id) is None:
                raise SuccesNotFound("Cet abonnement n'existe pas.")
            conn.execute(
                "UPDATE succes_subscriptions SET deleted_at_ms=?, updated_at_ms=? "
                "WHERE id=?",
                (stamp, stamp, sub_id),
            )
            self._record_op(
                conn,
                entity="subscriptions",
                entity_id=sub_id,
                kind="delete",
                payload={"id": sub_id},
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )

    def materialize_due_subscriptions(
        self, *, on_date: str | None = None
    ) -> dict[str, Any]:
        """Create expense transactions for subscriptions due on or before on_date."""
        today = _validate_iso_date(on_date) if on_date else date.today().isoformat()
        created: list[dict[str, Any]] = []
        with self._transaction() as conn:
            rows = conn.execute(
                """SELECT * FROM succes_subscriptions
                   WHERE deleted_at_ms IS NULL AND active=1 AND next_due_date<=?
                   ORDER BY next_due_date""",
                (today,),
            ).fetchall()
            for row in rows:
                sub = self._subscription_dict(row)
                account_id = sub["accountId"]
                if not account_id:
                    # Use first non-archived account.
                    acct = conn.execute(
                        """SELECT id FROM succes_accounts
                           WHERE deleted_at_ms IS NULL AND archived=0
                           ORDER BY name LIMIT 1"""
                    ).fetchone()
                    if acct is None:
                        continue
                    account_id = acct["id"]
                txn_id = str(uuid.uuid4())
                stamp = now_ms()
                conn.execute(
                    """INSERT INTO succes_transactions
                       (id, account_id, category_id, txn_type, amount_cents, currency,
                        txn_date, payee, notes, transfer_account_id, subscription_id,
                        import_hash, updated_at_ms)
                       VALUES (?, ?, ?, 'expense', ?, 'CAD', ?, ?, ?, '', ?, '', ?)""",
                    (
                        txn_id,
                        account_id,
                        sub["categoryId"],
                        int(round(sub["amount"] * 100)),
                        sub["nextDueDate"],
                        sub["name"],
                        f"Abonnement ({sub['cadence']})",
                        sub["id"],
                        stamp,
                    ),
                )
                next_due = sub["nextDueDate"]
                # Advance until after today (catch up missed periods).
                guard = 0
                while next_due <= today and guard < 36:
                    next_due = _advance_due(next_due, sub["cadence"])
                    guard += 1
                conn.execute(
                    "UPDATE succes_subscriptions SET next_due_date=?, updated_at_ms=? "
                    "WHERE id=?",
                    (next_due, stamp, sub["id"]),
                )
                created.append(self._load_txn(conn, txn_id) or {})
        return {"created": created, "count": len(created)}

    # ── Budgets ───────────────────────────────────────────────────────

    def list_budgets(self, *, year_month: str | None = None) -> list[dict[str, Any]]:
        ym = _year_month(year_month)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM succes_budgets
                   WHERE deleted_at_ms IS NULL AND year_month=?
                   ORDER BY scope, category_id""",
                (ym,),
            ).fetchall()
            return [self._budget_dict(row) for row in rows]

    def upsert_budget(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        scope = str(data.get("scope") or "global").strip()
        if scope not in BUDGET_SCOPES:
            raise SuccesError("Portée de budget invalide.")
        category_id = _clean_text(
            data.get("categoryId") or "", field="Catégorie", maximum=80
        )
        if scope == "global":
            category_id = ""
        elif not category_id:
            raise SuccesError("Un budget de catégorie nécessite une catégorie.")
        year_month = _year_month(str(data.get("yearMonth") or ""))
        limit = _to_cents(data.get("limit"))
        request = {
            "action": "upsert_budget",
            "scope": scope,
            "categoryId": category_id,
            "yearMonth": year_month,
            "limit": limit,
        }
        stamp = now_ms()
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_budget)
            if replay is not None:
                return replay
            existing = conn.execute(
                """SELECT id FROM succes_budgets
                   WHERE deleted_at_ms IS NULL AND scope=? AND category_id=? AND year_month=?""",
                (scope, category_id, year_month),
            ).fetchone()
            budget_id = existing["id"] if existing else str(uuid.uuid4())
            if existing:
                conn.execute(
                    """UPDATE succes_budgets SET limit_cents=?, updated_at_ms=?
                       WHERE id=?""",
                    (limit, stamp, budget_id),
                )
            else:
                conn.execute(
                    """INSERT INTO succes_budgets
                       (id, scope, category_id, year_month, limit_cents, currency, updated_at_ms)
                       VALUES (?, ?, ?, ?, ?, 'CAD', ?)""",
                    (budget_id, scope, category_id, year_month, limit, stamp),
                )
            payload = self._load_budget(conn, budget_id)
            assert payload is not None
            self._record_op(
                conn,
                entity="budgets",
                entity_id=budget_id,
                kind="upsert",
                payload=payload,
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )
            return payload

    def delete_budget(self, budget_id: str, *, op_id: str | None = None) -> None:
        stamp = now_ms()
        request = {"action": "delete_budget", "id": budget_id}
        with self._transaction() as conn:
            if (
                self._replayed_entity(conn, op_id, request, self._load_budget)
                is not None
            ):
                return
            if self._load_budget(conn, budget_id) is None:
                raise SuccesNotFound("Ce budget n'existe pas.")
            conn.execute(
                "UPDATE succes_budgets SET deleted_at_ms=?, updated_at_ms=? WHERE id=?",
                (stamp, stamp, budget_id),
            )
            self._record_op(
                conn,
                entity="budgets",
                entity_id=budget_id,
                kind="delete",
                payload={"id": budget_id},
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )

    # ── Savings goals ─────────────────────────────────────────────────

    def list_goals(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM succes_savings_goals
                   WHERE deleted_at_ms IS NULL
                   ORDER BY name COLLATE NOCASE"""
            ).fetchall()
            return [self._goal_dict(row) for row in rows]

    def create_goal(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        name = _clean_text(
            data.get("name"), field="Nom de l'objectif", maximum=120, required=True
        )
        target = _to_cents(data.get("target"))
        current = _to_cents(data.get("current", 0))
        account_id = _clean_text(
            data.get("accountId") or "", field="Compte", maximum=80
        )
        deadline = ""
        if data.get("deadline"):
            deadline = _validate_iso_date(str(data["deadline"]))
        color = _color(data.get("color") or "#6366f1")
        icon = (
            _clean_text(
                data.get("icon") or "🎯", field="Icône", maximum=16, required=True
            )
            or "🎯"
        )
        request = {
            "action": "create_goal",
            "name": name,
            "target": target,
            "current": current,
            "accountId": account_id,
            "deadline": deadline,
            "color": color,
            "icon": icon,
        }
        goal_id = str(uuid.uuid4())
        stamp = now_ms()
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_goal)
            if replay is not None:
                return replay
            conn.execute(
                """INSERT INTO succes_savings_goals
                   (id, name, target_cents, current_cents, currency, account_id,
                    deadline, color, icon, updated_at_ms)
                   VALUES (?, ?, ?, ?, 'CAD', ?, ?, ?, ?, ?)""",
                (
                    goal_id,
                    name,
                    target,
                    current,
                    account_id,
                    deadline,
                    color,
                    icon,
                    stamp,
                ),
            )
            payload = self._load_goal(conn, goal_id)
            assert payload is not None
            self._record_op(
                conn,
                entity="savings_goals",
                entity_id=goal_id,
                kind="upsert",
                payload=payload,
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )
            return payload

    def update_goal(
        self, goal_id: str, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        stamp = now_ms()
        request = {"action": "update_goal", "id": goal_id, **dict(data)}
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_goal)
            if replay is not None:
                return replay
            existing = self._load_goal(conn, goal_id)
            if existing is None:
                raise SuccesNotFound("Cet objectif n'existe pas.")
            name = (
                _clean_text(data["name"], field="Nom", maximum=120, required=True)
                if "name" in data
                else existing["name"]
            )
            target = (
                _to_cents(data["target"])
                if "target" in data
                else int(round(existing["target"] * 100))
            )
            current = (
                _to_cents(data["current"])
                if "current" in data
                else int(round(existing["current"] * 100))
            )
            account_id = data.get("accountId", existing["accountId"]) or ""
            deadline = existing["deadline"]
            if "deadline" in data:
                deadline = (
                    _validate_iso_date(str(data["deadline"]))
                    if data["deadline"]
                    else ""
                )
            color = _color(data.get("color") or existing["color"])
            icon = (
                _clean_text(
                    data.get("icon") or existing["icon"],
                    field="Icône",
                    maximum=16,
                    required=True,
                )
                or existing["icon"]
            )
            conn.execute(
                """UPDATE succes_savings_goals SET name=?, target_cents=?, current_cents=?,
                   account_id=?, deadline=?, color=?, icon=?, updated_at_ms=?
                   WHERE id=? AND deleted_at_ms IS NULL""",
                (
                    name,
                    target,
                    current,
                    account_id,
                    deadline,
                    color,
                    icon,
                    stamp,
                    goal_id,
                ),
            )
            payload = self._load_goal(conn, goal_id)
            assert payload is not None
            self._record_op(
                conn,
                entity="savings_goals",
                entity_id=goal_id,
                kind="upsert",
                payload=payload,
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )
            return payload

    def delete_goal(self, goal_id: str, *, op_id: str | None = None) -> None:
        stamp = now_ms()
        request = {"action": "delete_goal", "id": goal_id}
        with self._transaction() as conn:
            if self._replayed_entity(conn, op_id, request, self._load_goal) is not None:
                return
            if self._load_goal(conn, goal_id) is None:
                raise SuccesNotFound("Cet objectif n'existe pas.")
            conn.execute(
                "UPDATE succes_savings_goals SET deleted_at_ms=?, updated_at_ms=? "
                "WHERE id=?",
                (stamp, stamp, goal_id),
            )
            self._record_op(
                conn,
                entity="savings_goals",
                entity_id=goal_id,
                kind="delete",
                payload={"id": goal_id},
                request=request,
                timestamp_ms=stamp,
                op_id=op_id,
            )

    # ── Dashboard / analytics ─────────────────────────────────────────

    def finance_overview(
        self, *, period: str = "month", anchor: str | None = None
    ) -> dict[str, Any]:
        if period not in PERIODS:
            raise SuccesError("Période invalide.")
        start, end = _period_bounds(period, anchor)
        # Previous period of same length for comparison.
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
        span = (end_d - start_d).days + 1
        prev_end = start_d - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span - 1)

        with self._connect() as conn:
            txns = [
                self._txn_dict(row)
                for row in conn.execute(
                    """SELECT * FROM succes_transactions
                       WHERE deleted_at_ms IS NULL AND txn_date>=? AND txn_date<=?""",
                    (start, end),
                ).fetchall()
            ]
            prev = [
                self._txn_dict(row)
                for row in conn.execute(
                    """SELECT * FROM succes_transactions
                       WHERE deleted_at_ms IS NULL AND txn_date>=? AND txn_date<=?""",
                    (prev_start.isoformat(), prev_end.isoformat()),
                ).fetchall()
            ]
            categories = {
                row["id"]: self._category_dict(row)
                for row in conn.execute(
                    "SELECT * FROM succes_finance_categories WHERE deleted_at_ms IS "
                    "NULL"
                ).fetchall()
            }

        income = sum(t["amount"] for t in txns if t["type"] == "income")
        expense = sum(t["amount"] for t in txns if t["type"] == "expense")
        prev_income = sum(t["amount"] for t in prev if t["type"] == "income")
        prev_expense = sum(t["amount"] for t in prev if t["type"] == "expense")

        by_category: dict[str, float] = {}
        for t in txns:
            if t["type"] != "expense":
                continue
            key = t["categoryId"] or "__none__"
            by_category[key] = by_category.get(key, 0.0) + t["amount"]

        category_breakdown = []
        for cat_id, total in sorted(by_category.items(), key=lambda item: -item[1]):
            cat = categories.get(cat_id)
            category_breakdown.append(
                {
                    "categoryId": "" if cat_id == "__none__" else cat_id,
                    "name": cat["name"] if cat else "Sans catégorie",
                    "icon": cat["icon"] if cat else "📦",
                    "color": cat["color"] if cat else "#94a3b8",
                    "amount": round(total, 2),
                }
            )

        # Daily series for charts.
        series_map: dict[str, dict[str, float]] = {}
        cursor = start_d
        while cursor <= end_d:
            key = cursor.isoformat()
            series_map[key] = {"date": key, "income": 0.0, "expense": 0.0}  # type: ignore[assignment]
            cursor += timedelta(days=1)
        for t in txns:
            bucket = series_map.get(t["date"])
            if not bucket:
                continue
            if t["type"] == "income":
                bucket["income"] = round(bucket["income"] + t["amount"], 2)
            elif t["type"] == "expense":
                bucket["expense"] = round(bucket["expense"] + t["amount"], 2)
        series = list(series_map.values())

        # Forecast: remaining days in month * average daily expense so far.
        today = date.today()
        days_elapsed = max(1, (min(today, end_d) - start_d).days + 1)
        avg_daily_expense = expense / days_elapsed
        days_left = max(0, (end_d - today).days)
        forecast_expense = round(expense + avg_daily_expense * days_left, 2)
        forecast_remaining = round(income - forecast_expense, 2)

        year_month = start[:7]
        budgets = self.list_budgets(year_month=year_month)
        budget_status = []
        for budget in budgets:
            if budget["scope"] == "global":
                spent = expense
            else:
                spent = by_category.get(budget["categoryId"], 0.0)
            limit = budget["limit"]
            budget_status.append(
                {
                    **budget,
                    "spent": round(spent, 2),
                    "remaining": round(limit - spent, 2),
                    "pct": round((spent / limit) * 100, 1) if limit else 0,
                    "over": spent > limit,
                }
            )

        accounts = self.list_accounts()
        subscriptions = self.list_subscriptions(active_only=True)
        upcoming = [
            s
            for s in subscriptions
            if s["nextDueDate"] <= (today + timedelta(days=14)).isoformat()
        ]
        goals = self.list_goals()

        return {
            "period": period,
            "from": start,
            "to": end,
            "currency": "CAD",
            "income": round(income, 2),
            "expense": round(expense, 2),
            "net": round(income - expense, 2),
            "prevIncome": round(prev_income, 2),
            "prevExpense": round(prev_expense, 2),
            "prevNet": round(prev_income - prev_expense, 2),
            "categoryBreakdown": category_breakdown,
            "series": series,
            "forecastExpense": forecast_expense,
            "forecastRemaining": forecast_remaining,
            "budgets": budget_status,
            "accounts": accounts,
            "upcomingSubscriptions": upcoming,
            "goals": goals,
            "transactionCount": len(txns),
        }

    # ── CSV import ────────────────────────────────────────────────────

    def import_csv(
        self,
        csv_text: str,
        *,
        account_id: str,
        mapping: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Import bank CSV. mapping keys: date, amount, payee, notes, type, category."""
        with self._connect() as conn:
            if self._load_account(conn, account_id) is None:
                raise SuccesNotFound("Ce compte n'existe pas.")
            categories = {
                row["name"].casefold(): self._category_dict(row)
                for row in conn.execute(
                    "SELECT * FROM succes_finance_categories WHERE deleted_at_ms IS "
                    "NULL"
                ).fetchall()
            }

        map_keys = {
            "date": (mapping or {}).get("date") or "date",
            "amount": (mapping or {}).get("amount") or "amount",
            "payee": (mapping or {}).get("payee") or "description",
            "notes": (mapping or {}).get("notes") or "notes",
            "type": (mapping or {}).get("type") or "type",
            "category": (mapping or {}).get("category") or "category",
        }

        reader = csv.DictReader(io.StringIO(csv_text))
        if not reader.fieldnames:
            raise SuccesError("Le fichier CSV est vide ou sans en-têtes.")

        created = 0
        skipped = 0
        errors: list[str] = []

        with self._transaction() as conn:
            for index, row in enumerate(reader, start=2):
                try:
                    raw_date = str(row.get(map_keys["date"]) or "").strip()
                    raw_amount = str(row.get(map_keys["amount"]) or "").strip()
                    if not raw_date or not raw_amount:
                        skipped += 1
                        continue
                    # Accept YYYY-MM-DD or DD/MM/YYYY
                    if "/" in raw_date:
                        parts = raw_date.split("/")
                        if len(parts) == 3:
                            raw_date = (
                                f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                            )
                    txn_date = _validate_iso_date(raw_date)
                    signed = float(
                        raw_amount.replace(",", ".").replace("$", "").replace(" ", "")
                    )
                    txn_type = str(row.get(map_keys["type"]) or "").strip().lower()
                    if txn_type not in TXN_TYPES:
                        txn_type = "expense" if signed < 0 else "income"
                    amount_cents = int(round(abs(signed) * 100))
                    payee = str(row.get(map_keys["payee"]) or "").strip()[:160]
                    notes = str(row.get(map_keys["notes"]) or "").strip()[:2000]
                    cat_name = str(row.get(map_keys["category"]) or "").strip()
                    category_id = ""
                    if cat_name:
                        match = categories.get(cat_name.casefold())
                        if match:
                            category_id = match["id"]

                    digest = hashlib.sha256(
                        f"{account_id}|{txn_date}|{amount_cents}|{payee}|{txn_type}".encode()
                    ).hexdigest()
                    exists = conn.execute(
                        """SELECT id FROM succes_transactions
                           WHERE import_hash=? AND deleted_at_ms IS NULL""",
                        (digest,),
                    ).fetchone()
                    if exists:
                        skipped += 1
                        continue

                    txn_id = str(uuid.uuid4())
                    stamp = now_ms()
                    conn.execute(
                        """INSERT INTO succes_transactions
                           (id, account_id, category_id, txn_type, amount_cents, currency,
                            txn_date, payee, notes, transfer_account_id, subscription_id,
                            import_hash, updated_at_ms)
                           VALUES (?, ?, ?, ?, ?, 'CAD', ?, ?, ?, '', '', ?, ?)""",
                        (
                            txn_id,
                            account_id,
                            category_id,
                            txn_type,
                            amount_cents,
                            txn_date,
                            payee,
                            notes,
                            digest,
                            stamp,
                        ),
                    )
                    created += 1
                except Exception as exc:  # noqa: BLE001 — collect row errors
                    errors.append(f"Ligne {index}: {exc}")
                    if len(errors) >= 20:
                        break

        return {"created": created, "skipped": skipped, "errors": errors}


__all__ = [
    "ACCOUNT_TYPES",
    "BUDGET_SCOPES",
    "CATEGORY_KINDS",
    "PERIODS",
    "SUB_CADENCES",
    "SuccesFinancesStore",
    "TXN_TYPES",
]
