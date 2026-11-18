"""Aura Companion take-over: server-side approval and an audit log for every browser action.

The extension proposes each step; this server decides. Every step is recorded before it runs:

* ``POST /api/aura/companion/action``: the extension describes the step it is about to perform. The
  server classifies it with its own rule (``CONSEQUENTIAL``, the same words as the extension's
  ``lib/policy.js``) and the extension's claim can only make it stricter. A step that is not
  consequential gets a single-use grant. A consequential one (send, submit, post, buy, pay, delete…)
  gets a grant only after the person approved exactly that run, step, action, element and value.
* ``POST /api/aura/companion/action/approve`` and ``/deny``: the person's tap, recorded here.
* ``POST /api/aura/companion/action/result``: spends the grant once and records the outcome.
* ``GET /api/aura/companion/audit``: the signed-in person's own trail (Hermes sign-in, not the key).

Nothing typed is stored: only a SHA-256 of the value. Element labels are page content: they are
redacted, clipped and kept as data, never interpreted. The log lives in
``$HERMES_HOME/aura-companion.db`` beside the daily limit. Every route is behind the companion's
own gate (``AURA_COMPANION_SECRET`` plus the admin/tester lists), so all of this is off by default.

Limit, stated plainly: the person taps Approve in the extension, which also holds the key. This
makes every approval explicit, server-checked, single-use and auditable, and lets the server refuse
a step the extension under-classified; it does not defend against a compromised extension.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import sqlite3
import time
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints, ValidationError

router = APIRouter()

ACTION_PATH = "/api/aura/companion/action"
APPROVE_PATH = ACTION_PATH + "/approve"
DENY_PATH = ACTION_PATH + "/deny"
RESULT_PATH = ACTION_PATH + "/result"
AUDIT_PATH = "/api/aura/companion/audit"
PUBLIC_PATHS = (ACTION_PATH, APPROVE_PATH, DENY_PATH, RESULT_PATH)

# Mirrors CONSEQUENTIAL in apps/aura-companion/lib/policy.js; a test keeps the two identical.
CONSEQUENTIAL = re.compile(
    r"\b(send|submit|post|publish|share|tweet|reply|comment|buy|purchase|order|checkout|check out|pay|"
    r"payment|donate|tip|delete|remove|erase|discard|archive|transfer|withdraw|confirm|book|reserve|"
    r"subscribe|unsubscribe|sign up|register|apply|accept|invite|upload|save changes|place)\b",
    re.IGNORECASE,
)
APPROVAL_TTL_SECONDS = 10 * 60

Short = Annotated[str, StringConstraints(max_length=200)]
Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class Element(BaseModel):
    label: Short = ""
    name: Short = ""
    domId: Short = ""
    type: Short = ""
    tag: Short = ""
    inForm: bool = False


class ActionBody(BaseModel):
    run_id: Id
    index: int = Field(ge=0, lt=8)
    action: Literal["click", "type", "select", "scroll"]
    target: Annotated[str, StringConstraints(max_length=64)] = ""
    host: Annotated[str, StringConstraints(max_length=253)] = ""
    value_sha256: Annotated[str, StringConstraints(pattern=r"^([0-9a-f]{64})?$")] = ""
    element: Element = Element()
    consequential: bool = False


class DecisionBody(BaseModel):
    approval_id: Id


class ResultBody(BaseModel):
    grant: Id
    ok: bool
    error: Short = ""


def is_consequential(body: ActionBody) -> bool:
    """The server's own reading; the extension's claim can only add to it."""
    if body.consequential:
        return True
    if body.action != "click":
        return False
    element = body.element
    kind = element.type.lower()
    if kind in {"submit", "image"} or (element.tag == "button" and element.inForm and kind in {"", "submit"}):
        return True
    return bool(CONSEQUENTIAL.search(" ".join(filter(None, (element.label, element.name, element.domId)))))


# ---- Store ----------------------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS companion_actions (
  id INTEGER PRIMARY KEY, at REAL NOT NULL, who TEXT NOT NULL, run_id TEXT NOT NULL, step INTEGER NOT NULL,
  action TEXT NOT NULL, target TEXT NOT NULL, host TEXT NOT NULL, label TEXT NOT NULL,
  value_sha256 TEXT NOT NULL, consequential INTEGER NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS companion_approvals (
  id TEXT PRIMARY KEY, who TEXT NOT NULL, run_id TEXT NOT NULL, step INTEGER NOT NULL, action TEXT NOT NULL,
  target TEXT NOT NULL, value_sha256 TEXT NOT NULL, created REAL NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS companion_grants (
  id TEXT PRIMARY KEY, who TEXT NOT NULL, action_row INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
"""


def _db() -> sqlite3.Connection:
    from hermes_constants import get_hermes_home

    db = sqlite3.connect(get_hermes_home() / "aura-companion.db", timeout=10, isolation_level=None)
    db.executescript(_SCHEMA)
    return db


def _log(db, who: str, body: ActionBody, consequential: bool, status: str, detail: str = "") -> int:
    from hermes_cli.web_routers.aura_companion import redact

    label = redact(body.element.label or body.element.tag or "")[:80]
    cursor = db.execute(
        "INSERT INTO companion_actions (at, who, run_id, step, action, target, host, label, value_sha256,"
        " consequential, status, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (time.time(), who, body.run_id, body.index, body.action, body.target, body.host.lower(), label,
         body.value_sha256, int(consequential), status, detail))
    return int(cursor.lastrowid)


def _grant(db, who: str, row: int) -> str:
    grant = secrets.token_urlsafe(18)
    db.execute("INSERT INTO companion_grants (id, who, action_row) VALUES (?,?,?)", (grant, who, row))
    return grant


def request_action(who: str, body: ActionBody, now: Optional[float] = None) -> dict:
    """Record the step; return a grant, or the approval the person has to give first."""
    now = time.time() if now is None else now
    consequential = is_consequential(body)
    db = _db()
    try:
        db.execute("BEGIN IMMEDIATE")
        key = (who, body.run_id, body.index, body.action, body.target, body.value_sha256)
        approval = None
        if consequential:
            approval = db.execute(
                "SELECT id FROM companion_approvals WHERE who=? AND run_id=? AND step=? AND action=? AND target=?"
                " AND value_sha256=? AND state='approved' AND created>?", (*key, now - APPROVAL_TTL_SECONDS)).fetchone()
        if consequential and approval is None:
            approval_id = secrets.token_urlsafe(18)
            db.execute("INSERT INTO companion_approvals VALUES (?,?,?,?,?,?,?,?,'pending')", (approval_id, *key, now))
            _log(db, who, body, True, "approval_required", approval_id)
            db.execute("COMMIT")
            return {"status": "approval_required", "approval_id": approval_id, "consequential": True}
        if approval is not None:
            db.execute("UPDATE companion_approvals SET state='used' WHERE id=?", (approval[0],))
        row = _log(db, who, body, consequential, "granted", approval[0] if approval else "")
        grant = _grant(db, who, row)
        db.execute("COMMIT")
        return {"status": "granted", "grant": grant, "consequential": consequential}
    finally:
        db.close()


def decide(who: str, approval_id: str, approve: bool, now: Optional[float] = None) -> bool:
    """The person's tap for one pending approval. Single-use; expires after ten minutes."""
    now = time.time() if now is None else now
    db = _db()
    try:
        cursor = db.execute(
            "UPDATE companion_approvals SET state=?, created=? WHERE id=? AND who=? AND state='pending' AND created>?",
            ("approved" if approve else "denied", now, approval_id, who, now - APPROVAL_TTL_SECONDS))
        if cursor.rowcount != 1:
            return False
        run = db.execute("SELECT run_id, step, action, target FROM companion_approvals WHERE id=?", (approval_id,)).fetchone()
        db.execute(
            "INSERT INTO companion_actions (at, who, run_id, step, action, target, host, label, value_sha256,"
            " consequential, status, detail) VALUES (?,?,?,?,?,?,'','','',1,?,?)",
            (now, who, *run, "approved" if approve else "denied", approval_id))
        return True
    finally:
        db.close()


def record_result(who: str, grant: str, ok: bool, error: str = "") -> bool:
    """Spend a grant once and record what happened. A second use is refused."""
    from hermes_cli.web_routers.aura_companion import redact

    db = _db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT action_row FROM companion_grants WHERE id=? AND who=? AND used=0", (grant, who)).fetchone()
        if row is None:
            db.execute("ROLLBACK")
            return False
        db.execute("UPDATE companion_grants SET used=1 WHERE id=?", (grant,))
        db.execute("UPDATE companion_actions SET status=?, detail=? WHERE id=?",
                   ("done" if ok else "failed", redact(error)[:200], row[0]))
        db.execute("COMMIT")
        return True
    finally:
        db.close()


def audit(who: str, limit: int = 200) -> list[dict]:
    db = _db()
    try:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT at, run_id, step, action, host, label, consequential, status FROM companion_actions"
                          " WHERE who=? ORDER BY id DESC LIMIT ?", (who, limit)).fetchall()
        return [{**dict(row), "consequential": bool(row["consequential"])} for row in rows]
    finally:
        db.close()


# ---- Routes -------------------------------------------------------------------------------------

async def _caller(request: Request, model: type[BaseModel]):
    """The companion key's subject and the parsed body, or the JSON error to return."""
    from hermes_cli.web_routers.aura_companion import _EXTENSION_ORIGIN, _TOKEN_RE, verify_token

    origin = request.headers.get("origin")
    if origin is not None and not _EXTENSION_ORIGIN.match(origin):
        raise HTTPException(status_code=403, detail="Not allowed from this origin.")
    match = _TOKEN_RE.match(request.headers.get("authorization", "").strip())
    who = verify_token(match.group(1)) if match else None
    if who is None:
        return None, None, JSONResponse({"error": "Your connection expired. Connect to Aura again."}, status_code=401)
    try:
        return who["sub"], model.model_validate(await request.json()), None
    except (ValueError, ValidationError):
        return None, None, JSONResponse({"error": "That request wasn't in the companion's format."}, status_code=422)


_NO_STORE = {"Cache-Control": "no-store"}


@router.post(ACTION_PATH)
async def companion_action(request: Request):
    who, body, error = await _caller(request, ActionBody)
    if error:
        return error
    return JSONResponse(await asyncio.to_thread(request_action, who, body), headers=_NO_STORE)


async def _decision(request: Request, approve: bool):
    who, body, error = await _caller(request, DecisionBody)
    if error:
        return error
    if not await asyncio.to_thread(decide, who, body.approval_id, approve):
        return JSONResponse({"error": "That approval has expired or was already used."}, status_code=409)
    return JSONResponse({"ok": True}, headers=_NO_STORE)


@router.post(APPROVE_PATH)
async def companion_action_approve(request: Request):
    return await _decision(request, True)


@router.post(DENY_PATH)
async def companion_action_deny(request: Request):
    return await _decision(request, False)


@router.post(RESULT_PATH)
async def companion_action_result(request: Request):
    who, body, error = await _caller(request, ResultBody)
    if error:
        return error
    if not await asyncio.to_thread(record_result, who, body.grant, body.ok, body.error):
        return JSONResponse({"error": "That step was not granted, or was already reported."}, status_code=409)
    return JSONResponse({"ok": True}, headers=_NO_STORE)


@router.get(AUDIT_PATH)
async def companion_audit(request: Request):
    """Behind Hermes sign-in: the person's own browser actions, newest first."""
    from hermes_cli.web_routers.aura_companion import _session, allowed

    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Sign in to Aura first.")
    if not allowed(session.user_id, session.email):
        raise HTTPException(status_code=403, detail="The companion isn't switched on for this account.")
    return JSONResponse({"actions": await asyncio.to_thread(audit, session.user_id)}, headers=_NO_STORE)
