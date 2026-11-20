"""Aura's paid-inference budget: the single authority every paid model request goes through.

The owner sets a USD limit in Settings → Model (initially $3; changeable, never a hard-coded
ceiling). Before a paid request is sent, ``authorize_or_reserve`` reserves an upper bound of its
cost; afterwards ``reconcile`` replaces the reservation with the cost OpenRouter reported, or keeps
the whole reservation when no cost was reported; ``release_reservation`` frees it only when the
provider refused the request before doing any work (an HTTP 4xx rejection).

What counts against the limit: reconciled actual costs, reservations still in flight, and
reservations settled without a reported cost. So the limit holds across concurrent requests,
retries, recovery cycles, fallbacks and auxiliary calls, because each is a separate request with
its own reservation. Reservations and the limit check share one SQLite ``BEGIN IMMEDIATE``
transaction, which serializes writers across threads and processes.

The store is ``$HERMES_HOME/aura-budget.db``, so each profile has its own budget. The ledger holds
request id, session id, model, tier, amounts, status and times — never prompts, keys or content.
Any store error raises ``BudgetRefused('unavailable')``: no store, no paid request.

The budget does not buy provider credit; it only limits what Aura lets itself spend.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import math
import sqlite3
from typing import Any, Iterator, Optional
import uuid

from hermes_constants import get_hermes_home

DEFAULT_LIMIT_USD = 3.0
MAX_LIMIT_USD = 1000.0
APPROACHING_SHARE = 0.8
# Provider rejected the request outright (bad request, auth, payment, not found, rate limit):
# no tokens were processed, so nothing was billed. Everything else keeps its reservation.
NOT_BILLED_STATUS = frozenset({400, 401, 402, 403, 404, 408, 409, 413, 422, 429})

REASONS = {
    "paid_off": "Paid models are switched off in Settings → Model.",
    "budget_reached": "Budget reached. Aura did not send this request.",
    "unavailable": "Aura couldn't check its budget, so it didn't send this paid request.",
    "invalid_estimate": "Aura couldn't bound this request's cost, so it didn't send it.",
}


class BudgetRefused(PermissionError):
    """A paid request the budget will not allow; ``user_message`` is safe to show."""

    def __init__(self, kind: str):
        self.kind = kind
        self.user_message = REASONS[kind]
        super().__init__(f"AURA_BUDGET_REFUSED[{kind}]: {self.user_message}")


@dataclass(frozen=True)
class Reservation:
    request_id: str
    amount_usd: float


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def _db(write: bool = False) -> Iterator[sqlite3.Connection]:
    try:
        db = sqlite3.connect(get_hermes_home() / "aura-budget.db", timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        db.executescript(
            "CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY CHECK (id = 1), limit_usd REAL NOT NULL,"
            " paid_enabled INTEGER NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS budget_changes (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,"
            " actor TEXT NOT NULL, previous_limit REAL, new_limit REAL NOT NULL, previous_enabled INTEGER,"
            " new_enabled INTEGER NOT NULL);"
            "CREATE TABLE IF NOT EXISTS ledger (request_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,"
            " model TEXT NOT NULL, tier TEXT NOT NULL, reserved_usd REAL NOT NULL, actual_usd REAL,"
            " status TEXT NOT NULL, cost_basis TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
        )
    except sqlite3.Error as exc:
        raise BudgetRefused("unavailable") from exc
    try:
        if write:
            db.execute("BEGIN IMMEDIATE")
        yield db
        if write:
            db.execute("COMMIT")
    except sqlite3.Error as exc:
        if write:
            db.execute("ROLLBACK")
        raise BudgetRefused("unavailable") from exc
    except BaseException:
        if write and db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def _settings(db: sqlite3.Connection) -> tuple[float, bool, str, str]:
    row = db.execute("SELECT limit_usd, paid_enabled, updated_at, updated_by FROM budget WHERE id = 1").fetchone()
    if row is None:
        return DEFAULT_LIMIT_USD, False, "", "default"
    return float(row[0]), bool(row[1]), row[2], row[3]


def _committed(db: sqlite3.Connection) -> tuple[float, float]:
    """(spent, in flight): actual costs plus cost-unknown reservations, and open reservations."""
    spent = db.execute(
        "SELECT COALESCE(SUM(CASE WHEN status = 'reconciled' THEN actual_usd"
        " WHEN status = 'usage_unknown' THEN reserved_usd ELSE 0 END), 0) FROM ledger").fetchone()[0]
    reserved = db.execute("SELECT COALESCE(SUM(reserved_usd), 0) FROM ledger WHERE status = 'reserved'").fetchone()[0]
    return float(spent), float(reserved)


def _amount(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise BudgetRefused("invalid_estimate")
    return float(value)


def authorize_or_reserve(*, session_id: str, model: str, tier: str, estimated_usd: float) -> Reservation:
    """Reserve *estimated_usd* for one paid request, or refuse. A refusal means: do not send it."""
    amount = _amount(estimated_usd)
    if amount == 0:
        raise BudgetRefused("invalid_estimate")
    with _db(write=True) as db:
        limit, enabled, _, _ = _settings(db)
        if not enabled:
            raise BudgetRefused("paid_off")
        spent, reserved = _committed(db)
        if spent + reserved + amount > limit + 1e-12:
            raise BudgetRefused("budget_reached")
        ident = uuid.uuid4().hex
        now = _now()
        db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,NULL,'reserved',NULL,?,?)",
                   (ident, session_id or "", model, tier, amount, now, now))
    return Reservation(ident, amount)


def reconcile(request_id: str, actual_usd: Optional[float], *, basis: str = "provider_reported") -> None:
    """Settle a reservation: the provider's reported cost, or (None) keep the whole reservation."""
    actual = None if actual_usd is None else _amount(actual_usd)
    with _db(write=True) as db:
        status = "usage_unknown" if actual is None else "reconciled"
        db.execute("UPDATE ledger SET actual_usd = ?, status = ?, cost_basis = ?, updated_at = ?"
                   " WHERE request_id = ? AND status = 'reserved'",
                   (actual, status, None if actual is None else basis, _now(), request_id))


def release_reservation(request_id: str, *, http_status: Optional[int] = None, not_sent: bool = False) -> bool:
    """Free a reservation only on evidence nothing was billed: the request was never sent, or the
    provider rejected it outright (HTTP 4xx). Otherwise it stays, settled as cost-unknown."""
    if not_sent or http_status in NOT_BILLED_STATUS:
        basis = "not sent" if not_sent else f"provider rejected (HTTP {http_status})"
        with _db(write=True) as db:
            db.execute("UPDATE ledger SET actual_usd = 0, status = 'released', cost_basis = ?, updated_at = ?"
                       " WHERE request_id = ? AND status = 'reserved'", (basis, _now(), request_id))
        return True
    reconcile(request_id, None)
    return False


def _limit(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or value > MAX_LIMIT_USD:
        raise ValueError(f"The budget must be between $0 and ${MAX_LIMIT_USD:,.0f}.")
    return round(float(value), 2)


def update_budget_limit(*, limit_usd: Any = None, paid_enabled: Any = None, actor: str) -> dict:
    """Owner-only (the web route checks). Spent amounts and history are never reset."""
    if paid_enabled is not None and type(paid_enabled) is not bool:
        raise ValueError("paid_enabled must be true or false.")
    with _db(write=True) as db:
        old_limit, old_enabled, _, _ = _settings(db)
        new_limit = old_limit if limit_usd is None else _limit(limit_usd)
        new_enabled = old_enabled if paid_enabled is None else paid_enabled
        now = _now()
        db.execute("INSERT INTO budget VALUES (1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET limit_usd = excluded.limit_usd,"
                   " paid_enabled = excluded.paid_enabled, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                   (new_limit, int(new_enabled), now, actor or "owner"))
        db.execute("INSERT INTO budget_changes (at, actor, previous_limit, new_limit, previous_enabled, new_enabled)"
                   " VALUES (?,?,?,?,?,?)", (now, actor or "owner", old_limit, new_limit,
                                             int(old_enabled), int(new_enabled)))
    return get_budget_status()


def _state(limit: float, used: float) -> str:
    if used >= limit:
        return "reached"
    return "approaching" if limit and used / limit >= APPROACHING_SHARE else "active"


def get_budget_status(history: int = 20) -> dict:
    """What Settings shows. Amounts in USD; no prompts or keys exist in the store to show."""
    with _db() as db:
        limit, enabled, updated_at, updated_by = _settings(db)
        spent, reserved = _committed(db)
        by_model = [{"model": m, "tier": t, "requests": n, "spent_usd": round(float(s), 6)} for m, t, n, s in db.execute(
            "SELECT model, tier, COUNT(*), COALESCE(SUM(CASE WHEN status = 'reconciled' THEN actual_usd"
            " WHEN status IN ('usage_unknown', 'reserved') THEN reserved_usd ELSE 0 END), 0)"
            " FROM ledger GROUP BY model, tier ORDER BY 4 DESC")]
        rows = db.execute("SELECT request_id, session_id, model, tier, reserved_usd, actual_usd, status, cost_basis,"
                          " created_at, updated_at FROM ledger ORDER BY created_at DESC, rowid DESC LIMIT ?",
                          (int(history),)).fetchall()
        changes = db.execute("SELECT at, actor, previous_limit, new_limit, previous_enabled, new_enabled"
                             " FROM budget_changes ORDER BY id DESC LIMIT 10").fetchall()
    used = spent + reserved
    return {
        "currency": "USD", "limit_usd": limit, "paid_enabled": enabled,
        "spent_usd": round(spent, 6), "reserved_usd": round(reserved, 6),
        "remaining_usd": round(max(limit - used, 0.0), 6),
        "percent_used": 100.0 if limit == 0 and used > 0 else round(100 * used / limit, 1) if limit else 0.0,
        "state": _state(limit, used), "updated_at": updated_at or None, "updated_by": updated_by,
        "by_model": by_model,
        "history": [dict(zip(("request_id", "session_id", "model", "tier", "reserved_usd", "actual_usd", "status",
                              "cost_basis", "created_at", "updated_at"), row)) for row in rows],
        "changes": [dict(zip(("at", "actor", "previous_limit", "new_limit", "previous_enabled", "new_enabled"), row))
                    for row in changes],
    }
