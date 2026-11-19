"""Aura Companion: hand a task from the Aura chat to the browser, and its result back.

Off by default: it needs the companion gate (``AURA_COMPANION_SECRET`` plus the admin/tester lists,
see aura_companion.py) **and** the owner's ``aura.companion.handoff: true`` in config.yaml.

Flow:

1. In the signed-in Aura chat the person writes a task and taps *Send to browser*
   (``POST /api/aura/companion/handoff``). It waits for their browser.
2. The extension, holding its 12-hour key, picks it up (``POST /api/aura/companion/handoff/next``) and
   runs the ordinary take-over with the handoff id as its run id, so every step still goes through the
   server gate in aura_companion_actions.py and its audit log.
3. A consequential step (send, submit, buy, delete…) of a handoff run can be approved **only from the
   signed-in chat** (``…/handoff/approve``). The extension's key cannot approve it, so a compromised
   extension cannot approve its own step. The extension learns the decision from
   ``POST /api/aura/companion/action/status``.
4. The extension reports the outcome (``POST /api/aura/companion/handoff/result``). The summary is page
   content: it is redacted, clipped and shown in the chat as untrusted text. It reaches the model only if
   the person puts it in a message themselves.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, StringConstraints

router = APIRouter()

HANDOFF_PATH = "/api/aura/companion/handoff"
NEXT_PATH = HANDOFF_PATH + "/next"
RESULT_PATH = HANDOFF_PATH + "/result"
PUBLIC_PATHS = (NEXT_PATH, RESULT_PATH)
PENDING_TTL_SECONDS = 30 * 60
SUMMARY_LIMIT = 2000

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS companion_handoffs (
  id TEXT PRIMARY KEY, who TEXT NOT NULL, session_id TEXT NOT NULL, instruction TEXT NOT NULL,
  created REAL NOT NULL, updated REAL NOT NULL, state TEXT NOT NULL, ok INTEGER, summary TEXT NOT NULL DEFAULT '');
"""


class CreateBody(BaseModel):
    session_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    instruction: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class DecisionBody(BaseModel):
    approval_id: Id
    approve: bool


class CancelBody(BaseModel):
    id: Id


class ResultBody(BaseModel):
    id: Id
    ok: bool
    summary: Annotated[str, StringConstraints(max_length=SUMMARY_LIMIT * 2)] = ""


def enabled() -> bool:
    """The owner's switch. The companion gate is checked separately, per person."""
    from hermes_cli.config import load_config_readonly

    aura = load_config_readonly().get("aura")
    companion = aura.get("companion") if isinstance(aura, dict) else None
    return isinstance(companion, dict) and companion.get("handoff") is True


def _db():
    from hermes_cli.web_routers.aura_companion_actions import _db as actions_db

    db = actions_db()
    db.executescript(_SCHEMA)
    return db


def is_handoff_run(run_id: str) -> bool:
    db = _db()
    try:
        return db.execute("SELECT 1 FROM companion_handoffs WHERE id=?", (run_id,)).fetchone() is not None
    finally:
        db.close()


def run_allowed(who: str, run_id: str) -> bool:
    """A step of a handoff run is allowed only while that person's handoff is running (not cancelled or done).
    Runs that are not handoffs (started in the extension itself) are unaffected."""
    db = _db()
    try:
        row = db.execute("SELECT who, state FROM companion_handoffs WHERE id=?", (run_id,)).fetchone()
    finally:
        db.close()
    return row is None or (row[0] == who and row[1] == "started")


def create(who: str, session_id: str, instruction: str, now: Optional[float] = None) -> dict:
    """One open handoff per person: a new one cancels any that has not finished."""
    now = time.time() if now is None else now
    handoff_id = secrets.token_urlsafe(18)
    db = _db()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE companion_handoffs SET state='cancelled', updated=? WHERE who=? AND state IN ('pending','started')",
                   (now, who))
        db.execute("INSERT INTO companion_handoffs (id, who, session_id, instruction, created, updated, state)"
                   " VALUES (?,?,?,?,?,?,'pending')", (handoff_id, who, session_id, instruction, now, now))
        db.execute("COMMIT")
    finally:
        db.close()
    return {"id": handoff_id, "state": "pending"}


def take_next(who: str, now: Optional[float] = None) -> Optional[dict]:
    """The browser picks up this person's waiting handoff (once)."""
    now = time.time() if now is None else now
    db = _db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT id, instruction FROM companion_handoffs WHERE who=? AND state='pending' AND created>?"
                         " ORDER BY created DESC LIMIT 1", (who, now - PENDING_TTL_SECONDS)).fetchone()
        if row:
            db.execute("UPDATE companion_handoffs SET state='started', updated=? WHERE id=?", (now, row[0]))
        db.execute("COMMIT")
        return {"id": row[0], "instruction": row[1]} if row else None
    finally:
        db.close()


def record_result(who: str, handoff_id: str, ok: bool, summary: str) -> bool:
    from hermes_cli.web_routers.aura_companion import redact

    clean = " ".join(redact(summary).split())[:SUMMARY_LIMIT]
    db = _db()
    try:
        cursor = db.execute("UPDATE companion_handoffs SET state=?, ok=?, summary=?, updated=? WHERE id=? AND who=?"
                            " AND state='started'", ("done" if ok else "failed", int(ok), clean, time.time(), handoff_id, who))
        return cursor.rowcount == 1
    finally:
        db.close()


def cancel(who: str, handoff_id: str) -> bool:
    db = _db()
    try:
        cursor = db.execute("UPDATE companion_handoffs SET state='cancelled', updated=? WHERE id=? AND who=?"
                            " AND state IN ('pending','started')", (time.time(), handoff_id, who))
        return cursor.rowcount == 1
    finally:
        db.close()


def latest(who: str, session_id: str) -> Optional[dict]:
    """The chat's newest handoff, with the browser steps waiting for this person's approval."""
    db = _db()
    try:
        row = db.execute("SELECT id, instruction, state, ok, summary, created FROM companion_handoffs"
                         " WHERE who=? AND session_id=? ORDER BY created DESC LIMIT 1", (who, session_id)).fetchone()
        if row is None:
            return None
        handoff_id = row[0]
        pending = db.execute(
            "SELECT p.id, p.step, p.action, a.label, a.host FROM companion_approvals p"
            " JOIN companion_actions a ON a.detail = p.id AND a.status = 'approval_required'"
            " WHERE p.who=? AND p.run_id=? AND p.state='pending' ORDER BY p.created", (who, handoff_id)).fetchall()
        return {"id": handoff_id, "instruction": row[1], "state": row[2],
                "ok": None if row[3] is None else bool(row[3]), "summary": row[4],
                "approvals": [{"approval_id": p[0], "step": p[1], "action": p[2], "label": p[3], "host": p[4]}
                              for p in pending]}
    finally:
        db.close()


def decide_in_chat(who: str, approval_id: str, approve: bool) -> bool:
    """The chat-side tap. Only for a step that belongs to one of this person's handoffs."""
    from hermes_cli.web_routers.aura_companion_actions import decide

    db = _db()
    try:
        row = db.execute("SELECT run_id FROM companion_approvals WHERE id=? AND who=?", (approval_id, who)).fetchone()
    finally:
        db.close()
    return bool(row) and is_handoff_run(row[0]) and decide(who, approval_id, approve)


# ---- Routes -------------------------------------------------------------------------------------

_NO_STORE = {"Cache-Control": "no-store"}


def _signed_in(request: Request):
    """The Hermes session of an allow-listed person, while the owner has handoff switched on."""
    from hermes_cli.web_routers.aura_companion import _session, allowed

    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Sign in to Aura first.")
    if not allowed(session.user_id, session.email) or not enabled():
        raise HTTPException(status_code=403, detail="Browser handoff isn't switched on.")
    return session


@router.get(HANDOFF_PATH + "/status")
async def handoff_status(request: Request):
    from hermes_cli.web_routers.aura_companion import _session, allowed

    session = _session(request)
    on = bool(session) and allowed(session.user_id, session.email) and await asyncio.to_thread(enabled)
    return JSONResponse({"enabled": on}, headers=_NO_STORE)


@router.post(HANDOFF_PATH)
async def handoff_create(request: Request, body: CreateBody):
    session = _signed_in(request)
    return JSONResponse(await asyncio.to_thread(create, session.user_id, body.session_id, body.instruction),
                        headers=_NO_STORE)


@router.get(HANDOFF_PATH)
async def handoff_latest(request: Request, session_id: str):
    session = _signed_in(request)
    return JSONResponse({"handoff": await asyncio.to_thread(latest, session.user_id, session_id[:256])},
                        headers=_NO_STORE)


@router.post(HANDOFF_PATH + "/approve")
async def handoff_approve(request: Request, body: DecisionBody):
    session = _signed_in(request)
    if not await asyncio.to_thread(decide_in_chat, session.user_id, body.approval_id, body.approve):
        return JSONResponse({"error": "That step has expired or was already answered."}, status_code=409)
    return JSONResponse({"ok": True}, headers=_NO_STORE)


@router.post(HANDOFF_PATH + "/cancel")
async def handoff_cancel(request: Request, body: CancelBody):
    session = _signed_in(request)
    if not await asyncio.to_thread(cancel, session.user_id, body.id):
        return JSONResponse({"error": "That handoff already finished."}, status_code=409)
    return JSONResponse({"ok": True}, headers=_NO_STORE)


@router.post(NEXT_PATH)
async def handoff_next(request: Request):
    from hermes_cli.web_routers.aura_companion_actions import _caller

    who, _body, error = await _caller(request, _Empty)
    if error:
        return error
    if not await asyncio.to_thread(enabled):
        return Response(status_code=204)
    task = await asyncio.to_thread(take_next, who)
    return JSONResponse(task, headers=_NO_STORE) if task else Response(status_code=204)


@router.post(RESULT_PATH)
async def handoff_result(request: Request):
    from hermes_cli.web_routers.aura_companion_actions import _caller

    who, body, error = await _caller(request, ResultBody)
    if error:
        return error
    if not await asyncio.to_thread(record_result, who, body.id, body.ok, body.summary):
        return JSONResponse({"error": "That handoff isn't running."}, status_code=409)
    return JSONResponse({"ok": True}, headers=_NO_STORE)


class _Empty(BaseModel):
    kind: Literal["next"] = "next"
