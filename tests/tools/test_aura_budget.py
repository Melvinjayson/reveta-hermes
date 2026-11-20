"""Aura's spending budget and the paid-request boundary. Mocked providers only; no inference."""

import importlib.util
import json
from pathlib import Path
from threading import Barrier, Thread
from types import SimpleNamespace

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tools import aura_budget as budget
from tools import aura_paid_requests as paid
from tools.aura_budget import BudgetRefused
from tools.aura_free_only import FreeOnlyRefused, guarded_aux_callback, require_agent_model, require_model

ROOT = Path(__file__).resolve().parents[2]
OR = "https://openrouter.ai/api/v1"


def _tiers():
    spec = importlib.util.spec_from_file_location("aura_config_budget", ROOT / "scripts" / "reveta" / "aura_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ROUTING_TIERS


TIERS = _tiers()
ROUTINE = TIERS["default"]["model"]
FALLBACK = TIERS["fallback"]["model"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    token = set_hermes_home_override(str(tmp_path))

    def write(routing=True, paid_route=None):
        aura = {"free_only": False, "free_models": [],
                "model_routing": {"enabled": routing, "tiers": TIERS, "test_route": {"enabled": False}}}
        if paid_route:
            aura["paid_route"] = paid_route
        (tmp_path / "config.yaml").write_text(json.dumps({"aura": aura}), encoding="utf-8")

    write()
    try:
        yield write
    finally:
        reset_hermes_home_override(token)


def _on(limit=3.0):
    return budget.update_budget_limit(limit_usd=limit, paid_enabled=True, actor="melvin")


def _reserve(amount, model=ROUTINE, tier="default", session="chat-1"):
    return budget.authorize_or_reserve(session_id=session, model=model, tier=tier, estimated_usd=amount)


def _agent(model=ROUTINE, session="chat-1"):
    return SimpleNamespace(provider="openrouter", base_url=OR, model=model, api_mode="chat_completions",
                           session_id=session)


def _request(text="AURA READY?", max_tokens=None):
    request = {"model": ROUTINE, "messages": [{"role": "user", "content": text}]}
    if max_tokens:
        request["max_tokens"] = max_tokens
    return request


# Budget settings


def test_default_budget_is_three_dollars_with_paid_models_off(home):
    status = budget.get_budget_status()
    assert (status["limit_usd"], status["paid_enabled"], status["spent_usd"], status["state"]) == (3.0, False, 0, "active")
    with pytest.raises(BudgetRefused) as off:
        _reserve(0.01)
    assert off.value.kind == "paid_off"


def test_raising_and_lowering_the_limit_is_logged_with_actor_and_never_resets_spend(home):
    _on(3.0)
    r = _reserve(1.0)
    budget.reconcile(r.request_id, 1.25)
    raised = budget.update_budget_limit(limit_usd=10, actor="melvin")
    lowered = budget.update_budget_limit(limit_usd=0.5, actor="melvin")
    assert raised["limit_usd"] == 10 and lowered["limit_usd"] == 0.5
    assert lowered["spent_usd"] == 1.25 and lowered["state"] == "reached" and lowered["remaining_usd"] == 0
    changes = lowered["changes"]
    assert [(c["previous_limit"], c["new_limit"], c["actor"]) for c in changes[:2]] == [(10, 0.5, "melvin"), (3.0, 10, "melvin")]
    with pytest.raises(BudgetRefused) as reached:
        _reserve(0.0001)
    assert reached.value.kind == "budget_reached"
    assert budget.get_budget_status()["history"][0]["actual_usd"] == 1.25


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), 1_000_001, "3", True, None])
def test_invalid_limits_are_rejected_server_side(home, bad):
    if bad is None:
        assert budget.update_budget_limit(actor="melvin")["limit_usd"] == 3.0  # nothing to change
        return
    with pytest.raises(ValueError):
        budget.update_budget_limit(limit_usd=bad, actor="melvin")
    assert budget.get_budget_status()["limit_usd"] == 3.0


def test_disabling_paid_inference_refuses_new_paid_requests(home):
    _on()
    budget.update_budget_limit(paid_enabled=False, actor="melvin")
    with pytest.raises(BudgetRefused, match="switched off"):
        _reserve(0.01)


# Reservations and reconciliation


def test_concurrent_reservations_never_exceed_the_limit(home):
    _on(3.0)
    workers, barrier, won, lost = 24, Barrier(24), [], []

    def one():
        barrier.wait()
        try:
            won.append(_reserve(0.2))
        except BudgetRefused:
            lost.append(1)

    threads = [Thread(target=one) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 15 and len(lost) == 9
    status = budget.get_budget_status()
    assert status["reserved_usd"] == pytest.approx(3.0) and status["remaining_usd"] == 0


def test_reconciling_to_the_reported_cost_frees_the_rest_of_the_reservation(home):
    _on(1.0)
    r = _reserve(0.5)
    assert budget.get_budget_status()["reserved_usd"] == 0.5
    budget.reconcile(r.request_id, 0.012)
    status = budget.get_budget_status()
    assert (status["spent_usd"], status["reserved_usd"], status["remaining_usd"]) == (0.012, 0, 0.988)
    assert status["by_model"][0] == {"model": ROUTINE, "tier": "default", "requests": 1, "spent_usd": 0.012}


def test_missing_cost_keeps_the_whole_reservation_and_rejections_release_it(home):
    _on(1.0)
    unknown, rejected, server = _reserve(0.3), _reserve(0.3), _reserve(0.3)
    budget.reconcile(unknown.request_id, None)
    assert budget.release_reservation(rejected.request_id, http_status=429) is True
    assert budget.release_reservation(server.request_id, http_status=500) is False
    status = budget.get_budget_status()
    assert status["spent_usd"] == pytest.approx(0.6) and status["reserved_usd"] == 0
    assert {row["status"] for row in status["history"]} == {"usage_unknown", "released"}


def test_the_ledger_holds_no_prompt_text(home):
    _on()
    home()
    require_model("openrouter", OR, _request("my private plan for Venus"), chat="chat-1")
    raw = (Path(budget.get_hermes_home()) / "aura-budget.db").read_bytes()
    assert b"private plan" not in raw and b"Venus" not in raw


def test_budget_survives_a_restart(home, tmp_path):
    import subprocess
    import sys

    _on(5.0)
    budget.reconcile(_reserve(1.0).request_id, 0.75)
    code = ("import json; from tools.aura_budget import get_budget_status as s; d = s();"
            "print(json.dumps([d['limit_usd'], d['spent_usd'], d['paid_enabled']]))")
    fresh = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True,
                           env={"HERMES_HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT)})
    assert json.loads(fresh.stdout.strip().splitlines()[-1]) == [5.0, 0.75, True]


def test_each_profile_has_its_own_budget(home, tmp_path):
    _on(9.0)
    other = tmp_path / "other-profile"
    other.mkdir()
    token = set_hermes_home_override(str(other))
    try:
        assert budget.get_budget_status()["limit_usd"] == 3.0 and budget.get_budget_status()["paid_enabled"] is False
    finally:
        reset_hermes_home_override(token)
    assert budget.get_budget_status()["limit_usd"] == 9.0


def test_an_unusable_store_fails_closed(home, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    token = set_hermes_home_override(str(blocker))
    try:
        with pytest.raises(BudgetRefused) as down:
            _reserve(0.01)
        assert down.value.kind == "unavailable"
    finally:
        reset_hermes_home_override(token)


# The paid-request boundary


def test_a_routed_paid_request_is_bounded_pinned_and_reserved_before_dispatch(home):
    _on(3.0)
    sent = require_model("openrouter", OR, _request(max_tokens=100_000), chat="chat-1")
    assert sent["max_tokens"] == TIERS["default"]["max_output_tokens"]
    ceiling = TIERS["default"]["price_ceiling"]
    assert sent["extra_body"]["provider"]["max_price"] == {"prompt": ceiling["prompt_per_million"],
                                                           "completion": ceiling["completion_per_million"]}
    row = budget.get_budget_status()["history"][0]
    assert (row["model"], row["tier"], row["status"], row["session_id"]) == (ROUTINE, "default", "reserved", "chat-1")
    bound = (paid.input_token_bound(_request()) * ceiling["prompt_per_million"]
             + 4096 * ceiling["completion_per_million"]) / 1_000_000
    assert row["reserved_usd"] == pytest.approx(bound)


def test_an_exhausted_budget_stops_the_request_before_any_client_exists(home):
    from agent.chat_completion_helpers import _dispatch_nonstreaming_api_request

    _on(0.001)
    hits = []
    with pytest.raises(FreeOnlyRefused, match="Budget reached"):
        _dispatch_nonstreaming_api_request(_agent(), _request(), make_client=lambda *a: hits.append("client"))
    assert hits == [] and budget.get_budget_status()["history"] == []


def test_paid_routing_switched_off_refuses_even_with_budget(home):
    _on()
    home(routing=False)
    with pytest.raises(FreeOnlyRefused, match="isn't switched on"):
        require_model("openrouter", OR, _request())


def test_retries_and_the_fallback_each_reserve_their_own_request(home):
    _on(3.0)
    agent = _agent()
    for _ in range(3):  # first attempt and two retries
        require_agent_model(agent, _request())
        paid.settle_failed(agent, SimpleNamespace(status_code=503))
    agent.model = FALLBACK
    require_agent_model(agent, {**_request(), "model": FALLBACK})
    paid.settle_agent_call(agent, SimpleNamespace(cost=0.0004))
    rows = budget.get_budget_status()["history"]
    assert [(r["tier"], r["status"]) for r in reversed(rows)] == [
        ("default", "usage_unknown"), ("default", "usage_unknown"), ("default", "usage_unknown"), ("fallback", "reconciled")]


def test_a_cancelled_call_without_usage_keeps_its_reservation(home):
    _on()
    agent = _agent()
    require_agent_model(agent, _request())
    paid.settle_agent_call(agent, None)
    assert budget.get_budget_status()["history"][0]["status"] == "usage_unknown"


def test_an_unsettled_reservation_is_closed_when_the_next_request_starts(home):
    _on()
    agent = _agent()
    require_agent_model(agent, _request())
    require_agent_model(agent, _request())
    assert [r["status"] for r in budget.get_budget_status()["history"]] == ["reserved", "usage_unknown"]


def test_background_title_generation_on_a_paid_model_is_reserved_and_reconciled(home):
    _on()
    client = SimpleNamespace(base_url=OR, _client=__import__("httpx").Client())
    call = guarded_aux_callback(client, lambda request: SimpleNamespace(usage=SimpleNamespace(cost=0.0001)),
                                provider="openrouter", api_mode="chat_completions")
    call(_request("title this chat"))
    row = budget.get_budget_status()["history"][0]
    assert (row["status"], row["actual_usd"]) == ("reconciled", 0.0001)


def test_free_model_requests_never_touch_the_budget(home):
    request = {"model": "gemini-3.8-flash", "messages": []}
    assert require_model("gemini", "https://generativelanguage.googleapis.com/v1beta", request) is request
    assert budget.get_budget_status()["history"] == []


def test_the_owner_route_spends_from_the_same_budget(home):
    route = {"provider": "anthropic", "model": "claude-haiku-4-5", "per_day_usd": 5.0, "per_chat_usd": 5.0}
    home(paid_route=route)
    request = {"model": "claude-haiku-4-5", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 50}
    with pytest.raises(FreeOnlyRefused, match="switched off"):
        require_model("anthropic", "https://api.anthropic.com", request, api_mode="anthropic_messages", chat="c")
    _on()
    sent = require_model("anthropic", "https://api.anthropic.com", request, api_mode="anthropic_messages", chat="c")
    assert sent["max_tokens"] == 50 and "extra_body" not in sent
    assert budget.get_budget_status()["history"][0]["tier"] == "owner_route"


def test_reported_cost_reads_openrouter_usage_shapes():
    assert paid.reported_cost(SimpleNamespace(cost=0.002)) == 0.002
    assert paid.reported_cost(SimpleNamespace(model_extra={"cost": "0.003"})) == 0.003
    assert paid.reported_cost({"cost": -1}) is None and paid.reported_cost(None) is None
