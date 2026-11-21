"""First-run welcome: shown once per profile, and honest about whether data survives restarts."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def _client():
    from hermes_cli.web_routers import aura

    app = FastAPI()
    app.state.auth_required = True

    @app.middleware("http")
    async def fake_gate(request: Request, call_next):
        request.state.session = SimpleNamespace(user_id="tester", email="")
        return await call_next(request)

    app.include_router(aura.router)
    return TestClient(app)


def test_welcome_is_pending_until_finished_then_stays_finished(home):
    client = _client()
    assert client.get("/api/aura/onboarding").json()["completed"] is False
    assert client.put("/api/aura/onboarding").json()["completed"] is True
    assert (home / "aura-onboarding.json").is_file()
    assert _client().get("/api/aura/onboarding").json()["completed"] is True


def test_storage_is_durable_only_on_a_mounted_home(home, monkeypatch):
    client = _client()
    monkeypatch.setattr(os.path, "ismount", lambda p: False)
    assert client.get("/api/aura/onboarding").json()["storage_durable"] is False
    monkeypatch.setattr(os.path, "ismount", lambda p: str(p) == str(home.parent.resolve()))
    assert client.get("/api/aura/onboarding").json()["storage_durable"] is True


def test_a_corrupt_state_file_shows_the_welcome_again(home):
    home.mkdir(parents=True)
    (home / "aura-onboarding.json").write_text("{not json", encoding="utf-8")
    assert _client().get("/api/aura/onboarding").json()["completed"] is False
