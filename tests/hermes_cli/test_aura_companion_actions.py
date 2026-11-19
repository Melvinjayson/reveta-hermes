"""Companion take-over: every browser action is logged, and consequential ones need a server-checked approval."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from hermes_cli.web_routers import aura_companion as ac
from hermes_cli.web_routers import aura_companion_actions as actions

SECRET = "x" * 40
EXT = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
SHA = hashlib.sha256(b"hello").hexdigest()


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for var in ("AURA_COMPANION_TOKENS_NOT_BEFORE", "AURA_COMPANION_DAILY_LIMIT", "AURA_COMPANION_TESTERS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("AURA_COMPANION_SECRET", SECRET)
    monkeypatch.setenv("AURA_COMPANION_ADMINS", "melvin@example.com")


@pytest.fixture
def client():
    from hermes_cli import web_server

    return TestClient(web_server.app, follow_redirects=False)


def _headers(who="u1", email="melvin@example.com"):
    return {"Authorization": f"Bearer {ac.issue_token(who, email)['token']}", "Origin": EXT}


def _step(**over):
    body = {"run_id": "run1", "index": 0, "action": "click", "target": "e3", "host": "shop.example",
            "element": {"label": "Next page", "tag": "a"}}
    return {**body, **over}


def test_a_plain_step_is_granted_once_and_logged(client):
    granted = client.post(actions.ACTION_PATH, json=_step(), headers=_headers()).json()
    assert granted["status"] == "granted" and granted["consequential"] is False
    result = {"grant": granted["grant"], "ok": True}
    assert client.post(actions.RESULT_PATH, json=result, headers=_headers()).status_code == 200
    assert client.post(actions.RESULT_PATH, json=result, headers=_headers()).status_code == 409  # single use
    rows = actions.audit("u1")
    assert [(r["action"], r["status"], r["label"]) for r in rows] == [("click", "done", "Next page")]


@pytest.mark.parametrize("element, claim", [
    ({"label": "Send message", "tag": "button"}, False),
    ({"label": "Place order", "tag": "button"}, False),
    ({"label": "Delete account", "tag": "a"}, False),
    ({"label": "Go", "tag": "button", "inForm": True}, False),   # a form's button submits
    ({"label": "Continue", "tag": "input", "type": "submit"}, False),
    ({"label": "Next", "tag": "a"}, True),                        # the extension's claim can only add
])
def test_consequential_steps_wait_for_an_approval_the_server_checks(client, element, claim):
    step = _step(element=element, consequential=claim)
    first = client.post(actions.ACTION_PATH, json=step, headers=_headers()).json()
    assert first["status"] == "approval_required" and "grant" not in first
    # Approval is bound to the person: another allow-listed account cannot approve it.
    other = _headers("u2", "melvin@example.com")
    assert client.post(actions.APPROVE_PATH, json={"approval_id": first["approval_id"]}, headers=other).status_code == 409
    assert client.post(actions.APPROVE_PATH, json={"approval_id": first["approval_id"]}, headers=_headers()).status_code == 200
    # ...and to the exact step: a different value or element is not covered.
    assert client.post(actions.ACTION_PATH, json={**step, "target": "e9"}, headers=_headers()).json()["status"] == "approval_required"
    assert client.post(actions.ACTION_PATH, json={**step, "value_sha256": SHA}, headers=_headers()).json()["status"] == "approval_required"
    granted = client.post(actions.ACTION_PATH, json=step, headers=_headers()).json()
    assert granted["status"] == "granted" and granted["consequential"] is True
    # The approval was spent: the same step needs a new one.
    assert client.post(actions.ACTION_PATH, json=step, headers=_headers()).json()["status"] == "approval_required"


def test_a_denied_or_expired_approval_grants_nothing(client, monkeypatch):
    step = _step(element={"label": "Submit", "tag": "button"})
    pending = client.post(actions.ACTION_PATH, json=step, headers=_headers()).json()
    assert client.post(actions.DENY_PATH, json={"approval_id": pending["approval_id"]}, headers=_headers()).status_code == 200
    assert client.post(actions.APPROVE_PATH, json={"approval_id": pending["approval_id"]}, headers=_headers()).status_code == 409
    assert client.post(actions.ACTION_PATH, json=step, headers=_headers()).json()["status"] == "approval_required"

    late = actions.request_action("u1", actions.ActionBody(**step), now=1000.0)
    assert actions.decide("u1", late["approval_id"], True, now=1000.0 + actions.APPROVAL_TTL_SECONDS + 1) is False
    statuses = {r["status"] for r in actions.audit("u1")}
    assert {"approval_required", "denied"} <= statuses and "granted" not in statuses


def test_no_key_no_extension_origin_or_gate_off_means_nothing_runs(client, monkeypatch):
    assert client.post(actions.ACTION_PATH, json=_step()).status_code == 401
    assert client.post(actions.ACTION_PATH, json=_step(), headers={**_headers(), "Origin": "https://evil.example"}).status_code == 403
    headers = _headers()
    monkeypatch.delenv("AURA_COMPANION_SECRET")  # companion switched off: existing keys stop working
    assert client.post(actions.ACTION_PATH, json=_step(), headers=headers).status_code == 401
    assert actions.audit("u1") == []


def test_audit_stores_no_typed_value_and_redacts_labels(client):
    step = _step(action="type", value_sha256=SHA, element={"label": "Notes sk-ant-abcdefghijklmnopqrstuvwx", "tag": "textarea"})
    assert client.post(actions.ACTION_PATH, json=step, headers=_headers()).json()["status"] == "granted"
    db_bytes = (Path(actions._db().execute("PRAGMA database_list").fetchone()[2])).read_bytes()
    assert b"sk-ant-abcdefghijklmnopqrstuvwx" not in db_bytes
    assert actions.audit("u1")[0]["label"].startswith("Notes [redacted]")


def test_audit_page_needs_sign_in_and_only_shows_the_callers_rows(client):
    from hermes_cli import web_server

    state = web_server.app.state
    saved = {k: getattr(state, k, None) for k in ("auth_required", "bound_host")}
    state.auth_required, state.bound_host = True, None
    try:
        assert client.get(actions.AUDIT_PATH).status_code == 401
    finally:
        for k, v in saved.items():
            if v is None:
                if hasattr(state, k):
                    delattr(state, k)
            else:
                setattr(state, k, v)
    actions.request_action("u2", actions.ActionBody(**_step()))
    assert actions.audit("u1") == [] and len(actions.audit("u2")) == 1


LABELS = ["Send", "Submit form", "Post reply", "Buy now", "Check out", "Pay", "Delete", "Save changes", "Sign up",
          "Place order", "Next page", "Read more", "Show details", "Open menu", "Search", "Subscribe", "Sent items"]


def test_server_and_extension_classify_clicks_the_same_way():
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    policy = Path(__file__).resolve().parents[2] / "apps/aura-companion/lib/policy.js"
    script = ("const P = require(process.argv[1]); const labels = JSON.parse(process.argv[2]);"
              "console.log(JSON.stringify(labels.map(l => P.isConsequential({action: 'click'}, {label: l, tag: 'a'}))));")
    out = subprocess.run([node, "-e", script, str(policy), json.dumps(LABELS)], capture_output=True, text=True,
                         check=True, timeout=30)
    extension = json.loads(out.stdout)
    server = [actions.is_consequential(actions.ActionBody(**_step(element={"label": l, "tag": "a"}))) for l in LABELS]
    assert server == extension
    assert server[:10] == [True] * 10 and server[10:15] == [False] * 5
