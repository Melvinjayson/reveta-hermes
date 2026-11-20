"""Owner-only preview switches (Settings -> Preview): companion, handoff and the evidence plugin.

Real config.yaml in a temp HERMES_HOME, the real Aura router and the real plugin enable path.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from ruamel.yaml import YAML
from starlette.testclient import TestClient

OWNER = SimpleNamespace(user_id="melvin", email="")
TESTER = SimpleNamespace(user_id="tester", email="tester@example.com")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "melvin")
    for var in ("AURA_COMPANION_SECRET", "AURA_COMPANION_ADMINS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AURA_COMPANION_TESTERS", "tester@example.com")
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


def test_everyone_but_the_owner_is_refused(home):
    for who in (TESTER, SimpleNamespace(user_id="someone", email="")):
        client = _client(who)
        assert client.get("/api/aura/preview").status_code == 403
        assert client.put("/api/aura/preview", json={"companion": True}).status_code == 403
    assert not (home / "config.yaml").exists()


def test_owner_switches_companion_and_handoff_and_the_gates_follow(home):
    from hermes_cli.web_routers import aura_companion as ac
    from hermes_cli.web_routers import aura_companion_handoff as handoff

    client = _client(OWNER)
    assert client.get("/api/aura/preview").json()["companion"] is False
    assert ac.issue_token("melvin", "") is None and not handoff.enabled()
    r = client.put("/api/aura/preview", json={"companion": True, "handoff": True})
    assert r.status_code == 200 and r.json()["companion"] is True and r.json()["handoff"] is True
    assert ac.issue_token("melvin", "") and handoff.enabled()
    # A tester still needs the deploy secret; the owner's switch is for the owner only.
    assert ac.issue_token("tester", "tester@example.com") is None
    assert client.put("/api/aura/preview", json={"companion": False}).json()["handoff"] is True
    assert ac.issue_token("melvin", "") is None


def test_owner_switches_the_evidence_plugin_on_and_it_loads(home):
    from hermes_cli import plugins as pmod

    r = _client(OWNER).put("/api/aura/preview", json={"venus_evidence": True})
    assert r.status_code == 200, r.text
    assert r.json()["venus_evidence"] is True
    saved = YAML().load((home / "config.yaml").read_text())
    assert "venus-evidence" in saved["plugins"]["enabled"]
    mgr = pmod.PluginManager()
    mgr.discover_and_load()
    assert mgr._plugins["venus-evidence"].enabled and "venus-value" in mgr._plugin_commands
    off = _client(OWNER).put("/api/aura/preview", json={"venus_evidence": False}).json()
    assert off["venus_evidence"] is False and off["restart_required"] is True


def test_switches_survive_the_boot_time_config_rewrite(home, monkeypatch):
    from scripts.reveta import aura_config

    _client(OWNER).put("/api/aura/preview", json={"companion": True, "handoff": True, "venus_evidence": True})
    for key in ("COMPOSIO_API_KEY", "AURA_PUBLIC_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, "argv", ["aura_config.py", "--write", str(home / "config.yaml")])
    assert aura_config.main() == 0
    status = _client(OWNER).get("/api/aura/preview").json()
    assert status["companion"] is True and status["handoff"] is True and status["venus_evidence"] is True
