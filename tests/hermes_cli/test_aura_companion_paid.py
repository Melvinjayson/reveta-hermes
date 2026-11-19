"""Companion planning on the owner's capped paid route, and the owner-only preview switches.

Real config.yaml, real spend ledger and real gate in a temp HERMES_HOME; only the provider call
(``agent.auxiliary_client.call_llm``) is replaced.
"""
from __future__ import annotations

import os
import stat
from types import SimpleNamespace

import pytest
import hermes_yaml as yaml
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from hermes_cli.web_routers import aura_companion as ac

OWNER = "melvin"
PAID = {"provider": "openai", "model": "gpt-5.6-luna", "per_day_usd": 1.0, "per_chat_usd": 0.5}
PAGE = {"intent": "takeover", "url": "https://example.com/a", "title": "A", "excerpt": "Hello"}
MESSAGES = [{"role": "user", "content": "Plan this page"}]


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for var in ("AURA_COMPANION_SECRET", "AURA_COMPANION_ADMINS", "AURA_COMPANION_TESTERS",
                "AURA_COMPANION_TOKENS_NOT_BEFORE", "AURA_COMPANION_DAILY_LIMIT", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", OWNER)
    return tmp_path


def _config(home, aura=None, **extra):
    (home / "config.yaml").write_text(yaml.safe_dump({"aura": {"free_only": False, **(aura or {})}, **extra}))


def _key(home):
    (home / ".env").write_text("OPENAI_API_KEY=sk-test-not-real-0000000000000000\n")


@pytest.fixture
def provider(monkeypatch):
    calls = []

    def call_llm(**kwargs):
        calls.append(kwargs)
        usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=200)
        return SimpleNamespace(usage=usage, choices=[SimpleNamespace(message=SimpleNamespace(content='{"steps": []}'))])

    import agent.auxiliary_client as aux
    monkeypatch.setattr(aux, "call_llm", call_llm)
    return calls


def _spent():
    from tools.aura_provider import totals
    return totals()[0]


def test_owner_with_key_and_caps_plans_on_the_paid_route_and_is_charged(home, provider):
    _config(home, {"paid_route": PAID})
    _key(home)
    out = ac._call_model(MESSAGES, "takeover", {"sub": OWNER, "email": ""})
    assert out == '{"steps": []}'
    (call,) = provider
    assert (call["provider"], call["model"], call["base_url"]) == ("openai", "gpt-5.6-luna", "https://api.openai.com/v1")
    assert call["max_tokens"] == 700
    from tools.aura_provider import usd_for
    assert _spent() == pytest.approx(usd_for(PAID, input_tokens=1000, output_tokens=200)) and _spent() > 0


@pytest.mark.parametrize("who", [{"sub": "tester", "email": "tester@example.com"}, {"sub": "", "email": ""}, {}])
def test_everyone_but_the_owner_is_refused_before_any_call(home, provider, monkeypatch, who):
    monkeypatch.setenv("AURA_COMPANION_TESTERS", "tester@example.com")
    _config(home, {"paid_route": PAID})
    _key(home)
    with pytest.raises(PermissionError):
        ac._call_model(MESSAGES, "ask", who)
    assert provider == [] and _spent() == 0


def test_listed_admin_counts_as_owner(home, provider, monkeypatch):
    monkeypatch.setenv("AURA_COMPANION_ADMINS", "Admin@Example.com")
    _config(home, {"paid_route": PAID})
    _key(home)
    ac._call_model(MESSAGES, "ask", {"sub": "u9", "email": "admin@example.com"})
    assert len(provider) == 1


def test_owner_without_paid_route_or_key_is_refused(home, provider):
    _config(home)
    with pytest.raises(PermissionError, match="paid model"):
        ac._call_model(MESSAGES, "ask", {"sub": OWNER})
    _config(home, {"paid_route": PAID})
    with pytest.raises(PermissionError, match="API key"):
        ac._call_model(MESSAGES, "ask", {"sub": OWNER})
    assert provider == []


def test_daily_cap_from_settings_stops_planning_and_is_not_raised(home, provider):
    from tools.aura_provider import SpendCapReached, charge

    _config(home, {"paid_route": PAID})
    _key(home)
    charge("some-chat", "openai", "gpt-5.6-luna", 1.0)  # chat already spent today's $1.00
    with pytest.raises(SpendCapReached):
        ac._call_model(MESSAGES, "ask", {"sub": OWNER})
    assert provider == []
    saved = yaml.safe_load((home / "config.yaml").read_text())
    assert saved["aura"]["paid_route"] == PAID  # the cap itself is untouched


def test_missing_usage_is_charged_as_the_worst_case_not_zero(home, monkeypatch):
    import agent.auxiliary_client as aux
    from tools.aura_provider import usd_for

    monkeypatch.setattr(aux, "call_llm", lambda **kw: SimpleNamespace(
        usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]))
    _config(home, {"paid_route": PAID})
    _key(home)
    ac._call_model(MESSAGES, "ask", {"sub": OWNER})
    assert _spent() >= usd_for(PAID, output_tokens=900)


def test_free_only_on_keeps_the_free_path(home, monkeypatch):
    import agent.auxiliary_client as aux

    seen = []
    monkeypatch.setattr(aux, "call_llm", lambda **kw: seen.append(kw) or SimpleNamespace(
        usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content="free"))]))
    (home / "config.yaml").write_text(yaml.safe_dump({"aura": {"free_only": True, "paid_route": PAID}}))
    assert ac._call_model(MESSAGES, "ask", {"sub": "tester"}) == "free"
    assert "provider" not in seen[0] and _spent() == 0


# ---- The ask route on the owner's Settings switch (no deploy secret) -----------------------------

def _app(session=None):
    app = FastAPI()

    @app.middleware("http")
    async def fake_gate(request: Request, call_next):
        request.state.session = session
        return await call_next(request)

    app.include_router(ac.router)
    return TestClient(app)


def test_settings_switch_turns_the_companion_on_for_the_owner_only(home, provider):
    _config(home, {"paid_route": PAID})
    _key(home)
    assert ac.issue_token(OWNER, "") is None  # off until the owner switches it on
    _config(home, {"paid_route": PAID, "companion": {"enabled": True}})
    assert ac.issue_token("someone", "someone@example.com") is None
    token = ac.issue_token(OWNER, "")["token"]
    secret = home / "aura-companion.secret"
    assert stat.S_IMODE(os.stat(secret).st_mode) == 0o600 and len(secret.read_text()) >= 32
    body = {"messages": MESSAGES, "page": PAGE}
    ok = _app().post(ac.ASK_PATH, json=body, headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200 and len(provider) == 1
    _config(home, {"paid_route": PAID, "companion": {"enabled": False}})
    assert _app().post(ac.ASK_PATH, json=body, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_ask_route_reports_the_cap_as_429(home, provider):
    from tools.aura_provider import charge

    _config(home, {"paid_route": PAID, "companion": {"enabled": True}})
    _key(home)
    charge("chat", "openai", "gpt-5.6-luna", 5.0)
    token = ac.issue_token(OWNER, "")["token"]
    r = _app().post(ac.ASK_PATH, json={"messages": MESSAGES, "page": PAGE},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 429 and "limit" in r.json()["error"] and provider == []
