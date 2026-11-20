"""Owner-set paid route: allowed only on the exact route and only under its caps. No network."""

import json
from types import SimpleNamespace

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tools import aura_provider
from tools.aura_free_only import FreeOnlyRefused, require_agent_model, require_model

PAID = {"provider": "anthropic", "model": "claude-haiku-4-5", "per_day_usd": 1.0, "per_chat_usd": 0.5}
ANTHROPIC = "https://api.anthropic.com"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    token = set_hermes_home_override(str(tmp_path))

    def write(paid=PAID):
        aura = {"free_models": []}
        if paid:
            aura["paid_route"] = paid
        (tmp_path / "config.yaml").write_text(json.dumps({"aura": aura}))

    write()
    # The route's per-day/per-chat caps are what these tests check; the Aura budget
    # (tools/aura_budget.py, tested in test_aura_budget.py) is switched on and out of the way.
    from tools.aura_budget import update_budget_limit
    update_budget_limit(limit_usd=1000, paid_enabled=True, actor="test")
    try:
        yield write
    finally:
        reset_hermes_home_override(token)


def _agent(**over):
    return SimpleNamespace(**{"provider": "anthropic", "base_url": ANTHROPIC, "model": PAID["model"],
                              "api_mode": "anthropic_messages", "session_id": "chat-1", **over})


def _usage(inp, out):
    return SimpleNamespace(input_tokens=inp, output_tokens=out, cache_read_tokens=0, cache_write_tokens=0)


def test_exact_paid_route_runs_under_caps(home):
    request = {"model": PAID["model"], "messages": []}
    # The budget bounds the route's cost: output is capped so the reservation is a ceiling.
    assert require_agent_model(_agent(), request) == {**request, "max_tokens": 4096}


@pytest.mark.parametrize("change", [
    {"model": "claude-opus-5"},
    {"base_url": "https://evil.example/v1"},
    {"base_url": "http://api.anthropic.com"},
    {"provider": "openrouter"},
])
def test_anything_but_the_exact_route_stays_refused(home, change):
    agent = _agent(**change)
    with pytest.raises(FreeOnlyRefused):
        require_agent_model(agent, {"model": agent.model, "messages": []})


def test_no_paid_route_keeps_free_only(home):
    home(paid=None)
    with pytest.raises(FreeOnlyRefused):
        require_agent_model(_agent(), {"model": PAID["model"], "messages": []})


def test_recorded_spend_stops_the_chat_then_the_day(home):
    agent = _agent()
    request = {"model": PAID["model"], "messages": []}
    # haiku-4-5 at $1/$5 per million: 100k out = $0.50, the per-chat cap
    aura_provider.record(agent, _usage(0, 100_000))
    with pytest.raises(FreeOnlyRefused, match="This chat reached"):
        require_agent_model(agent, request)
    other = _agent(session_id="chat-2")
    assert require_agent_model(other, request) == {**request, "max_tokens": 4096}
    aura_provider.record(other, _usage(0, 100_000))
    with pytest.raises(FreeOnlyRefused, match="today"):
        require_agent_model(_agent(session_id="chat-3"), request)
    # the day check also guards calls that carry no chat id (aux, client re-validation)
    with pytest.raises(FreeOnlyRefused):
        require_model("anthropic", ANTHROPIC, request, api_mode="anthropic_messages")


def test_other_routes_are_never_recorded(home):
    aura_provider.record(_agent(model="gemini-3.8-flash", provider="gemini"), _usage(10**7, 10**7))
    assert aura_provider.totals("chat-1") == (0.0, 0.0)


@pytest.mark.parametrize("caps", [(0, 1), (1, -1), (float("inf"), 1), (1, 501), ("1", 1), (True, 1)])
def test_invalid_caps_are_rejected(home, caps):
    with pytest.raises(ValueError):
        aura_provider.configure("anthropic", PAID["model"], *caps, api_key="sk-ant-fixture")


def test_configure_stores_key_route_and_model_then_returns_to_free(home, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-fixture")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API key"):
        aura_provider.configure("openai", "gpt-5.6-luna", 2, 0.5)
    status = aura_provider.configure("openai", "gpt-5.6-luna", 2, 0.5, api_key="sk-fixture")
    assert status["keys"]["openai"] is True and "sk-fixture" not in json.dumps(status)
    assert status["paid_route"]["model"] == "gpt-5.6-luna"
    assert status["active_model"] == {"provider": "openai", "model": "gpt-5.6-luna"}
    status = aura_provider.configure("gemini")
    assert status["paid_route"] is None and status["active_model"]["provider"] == "gemini"


def test_unlisted_model_is_rejected(home):
    with pytest.raises(ValueError):
        aura_provider.configure("openai", "gpt-4o", 1, 1, api_key="sk-fixture")
