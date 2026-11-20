"""Settings → Model → Spending budget: owner-only routes over the real budget store."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

OWNER = SimpleNamespace(user_id="melvin", email="")
TESTER = SimpleNamespace(user_id="tester", email="tester@example.com")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "melvin")
    monkeypatch.delenv("AURA_COMPANION_ADMINS", raising=False)
    return tmp_path


def _client(session):
    from hermes_cli.web_routers import aura

    app = FastAPI()
    app.state.auth_required = True

    @app.middleware("http")
    async def fake_gate(request: Request, call_next):
        request.state.session = session
        return await call_next(request)

    app.include_router(aura.router)
    return TestClient(app)


def test_only_the_owner_reads_or_changes_the_budget(home):
    for who in (TESTER, SimpleNamespace(user_id="someone", email="")):
        client = _client(who)
        assert client.get("/api/aura/budget").status_code == 403
        assert client.put("/api/aura/budget", json={"limit_usd": 500}).status_code == 403
    assert _client(OWNER).get("/api/aura/budget").json()["limit_usd"] == 3.0


def test_owner_changes_are_validated_and_attributed(home):
    client = _client(OWNER)
    saved = client.put("/api/aura/budget", json={"limit_usd": 7.5, "paid_enabled": True})
    assert saved.status_code == 200
    body = saved.json()
    assert (body["limit_usd"], body["paid_enabled"], body["updated_by"]) == (7.5, True, "melvin")
    assert body["changes"][0]["previous_limit"] == 3.0 and body["changes"][0]["new_limit"] == 7.5
    for bad in (-1, 1_000_000, "lots"):
        assert client.put("/api/aura/budget", json={"limit_usd": bad}).status_code in (400, 422)
    assert client.get("/api/aura/budget").json()["limit_usd"] == 7.5
