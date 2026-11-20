"""Aura model routing: deterministic policy and the per-request guard. Fixtures only; no model call."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tools import aura_model_routing as routing
from tools.aura_free_only import FreeOnlyRefused, require_model
from tools.aura_model_routing import REASONS, Route, RouteRefused

ROOT = Path(__file__).resolve().parents[2]
OR = "https://openrouter.ai/api/v1"


def _aura_config():
    spec = importlib.util.spec_from_file_location("aura_config_fixture", ROOT / "scripts" / "reveta" / "aura_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AURA_CONFIG = _aura_config()
TIERS = AURA_CONFIG.ROUTING_TIERS
TEST_MODEL = AURA_CONFIG.TEST_ROUTE_MODEL
LOCAL = {"AURA_PUBLIC_URL": "http://127.0.0.1:10000", "OPENROUTER_API_KEY": "sk-or-fixture"}


def _config(enabled=True, test=False, tiers=TIERS, free_only=False):
    return {"aura": {"free_only": free_only, "free_models": [],
                     "model_routing": {"enabled": enabled, "tiers": tiers,
                                       "test_route": {"enabled": test, "model": TEST_MODEL,
                                                      "capabilities": ["text", "tools"]}}}}


def _allow(log=None):
    def authorize(route):
        if log is not None:
            log.append(route.model)
        return True
    return authorize


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    token = set_hermes_home_override(str(tmp_path))

    def write(config):
        (tmp_path / "config.yaml").write_text(json.dumps(config), encoding="utf-8")

    try:
        yield write
    finally:
        reset_hermes_home_override(token)


# Configuration and authorization


def test_test_route_is_off_by_default_and_needs_flag_key_and_a_non_production_address():
    assert AURA_CONFIG.aura_settings({})["aura"]["model_routing"]["test_route"]["enabled"] is False
    assert AURA_CONFIG.test_route_enabled({**LOCAL, "AURA_TEST_MODEL_ROUTE": "1"}) is True
    assert AURA_CONFIG.test_route_enabled({**LOCAL, "AURA_TEST_MODEL_ROUTE": "true"}) is False
    assert AURA_CONFIG.test_route_enabled({"AURA_TEST_MODEL_ROUTE": "1", "OPENROUTER_API_KEY": "k"}) is False
    assert AURA_CONFIG.test_route_enabled({**LOCAL, "AURA_TEST_MODEL_ROUTE": "1", "OPENROUTER_API_KEY": ""}) is False
    generated = AURA_CONFIG.aura_settings({**LOCAL, "AURA_TEST_MODEL_ROUTE": "1"})["aura"]
    assert [m["model"] for m in generated["free_models"]] == [TEST_MODEL]
    assert generated["model_routing"]["enabled"] is False
    assert AURA_CONFIG.aura_settings({**LOCAL, "AURA_TEST_MODEL_ROUTE": "1"})["model"]["default"] != TEST_MODEL


@pytest.mark.parametrize("free_only", [False, True])
def test_test_route_requests_are_refused_while_the_flag_is_off(home, free_only):
    home(_config(test=False, free_only=free_only))
    with pytest.raises(FreeOnlyRefused, match="test model is switched off"):
        require_model("openrouter", OR, {"model": TEST_MODEL})


def test_enabled_test_route_is_pinned_to_zero_price_without_provider_fallbacks(home):
    config = _config(test=True, free_only=True)
    config["aura"]["free_models"] = [{"provider": "openrouter", "model": TEST_MODEL, "base_url": OR,
                                      "confirmed_free": True, "cost_usd": 0}]
    home(config)
    sent = require_model("openrouter", OR, {"model": TEST_MODEL})
    assert sent["extra_body"]["provider"]["allow_fallbacks"] is False
    assert sent["extra_body"]["provider"]["max_price"] == {"prompt": 0, "completion": 0}
    with pytest.raises(FreeOnlyRefused):  # another host is not the attested route
        require_model("openrouter", "https://example.test/api/v1", {"model": TEST_MODEL})


def test_unknown_selections_and_malformed_tier_ids_are_refused():
    with pytest.raises(RouteRefused) as unknown:
        routing.choose(_config(), selection="claude-opus", authorize=_allow())
    assert unknown.value.kind == "model_not_permitted"
    bad = {**TIERS, "default": {"model": " deepseek/x ", "paid": True}}
    with pytest.raises(RouteRefused, match="Model not permitted"):
        routing.choose(_config(tiers=bad), authorize=_allow())


@pytest.mark.parametrize("tier", ["default", "fallback", "reasoning"])
@pytest.mark.parametrize("free_only", [False, True])
def test_paid_tiers_are_never_sent_while_paid_models_are_off(home, tier, free_only):
    home(_config(enabled=True, free_only=free_only))
    with pytest.raises(FreeOnlyRefused, match="Paid models are switched off"):
        require_model("openrouter", OR, {"model": TIERS[tier]["model"]})


def test_paid_routes_cannot_bypass_authorization():
    with pytest.raises(RouteRefused) as missing:
        routing.choose(_config(), authorize=None)
    assert missing.value.kind == "budget_unavailable"
    with pytest.raises(RouteRefused) as refused:
        routing.choose(_config(), authorize=lambda route: False)
    assert refused.value.kind == "budget_reached"
    with pytest.raises(RouteRefused) as raising:
        routing.choose(_config(), authorize=lambda route: 1 / 0)
    assert raising.value.kind == "budget_reached"
    with pytest.raises(RouteRefused, match="budget"):
        routing.guard(_config(), "openrouter", OR, {"model": TIERS["default"]["model"]},
                      authorize=lambda route: False)


def test_routing_switched_off_refuses_even_with_an_authorizer():
    with pytest.raises(RouteRefused) as off:
        routing.choose(_config(enabled=False), authorize=_allow())
    assert off.value.kind == "routing_off"


# Routing


def test_routine_and_explicit_reasoning_choose_their_tiers():
    assert routing.choose(_config(), authorize=_allow()).model == TIERS["default"]["model"]
    reasoning = routing.choose(_config(), selection="reasoning", authorize=_allow())
    assert (reasoning.tier, reasoning.model) == ("reasoning", TIERS["reasoning"]["model"])
    assert reasoning.label == "Reasoning · moonshotai/kimi-k3.1-pro"


def test_voice_and_long_or_multi_step_work_never_escalate_by_themselves():
    route = routing.choose(_config(), voice=True, needs={"tools"}, authorize=_allow())
    assert route.tier == "default"


def test_default_to_fallback_on_a_transient_failure_is_authorized_again_and_labelled():
    log = []
    first = routing.choose(_config(), authorize=_allow(log))
    second = routing.fallback(_config(), first, "overloaded", attempt=0, authorize=_allow(log))
    assert second.model == TIERS["fallback"]["model"] and second.fallback_of == first.model
    assert second.label.startswith("Fallback · ")
    assert log == [first.model, second.model]


@pytest.mark.parametrize("failure", ["billing", "auth", "format_error", "model_not_found",
                                     "content_policy", "budget", "unknown"])
def test_non_transient_failures_and_budget_refusals_never_fall_back(failure):
    first = routing.choose(_config(), authorize=_allow())
    with pytest.raises(RouteRefused):
        routing.fallback(_config(), first, failure, attempt=0, authorize=_allow())


def test_a_budget_refusal_on_the_fallback_is_final():
    first = routing.choose(_config(), authorize=_allow())
    with pytest.raises(RouteRefused) as refused:
        routing.fallback(_config(), first, "timeout", attempt=0, authorize=lambda route: False)
    assert refused.value.kind == "budget_reached"


def test_free_routes_never_fall_back_to_paid():
    free = routing.test_route(_config(test=True))
    assert free.paid is False
    with pytest.raises(RouteRefused):
        routing.fallback(_config(test=True), free, "overloaded", attempt=0, authorize=_allow())


def test_fallback_never_leaves_the_configuration_or_picks_anthropic():
    no_fallback = {key: value for key, value in TIERS.items() if key != "fallback"}
    first = routing.choose(_config(tiers=no_fallback), authorize=_allow())
    with pytest.raises(RouteRefused) as refused:
        routing.fallback(_config(tiers=no_fallback), first, "overloaded", attempt=0, authorize=_allow())
    assert refused.value.user_message == REASONS["model_unavailable"]
    route = routing.fallback(_config(), routing.choose(_config(), authorize=_allow()), "server_error",
                             attempt=0, authorize=_allow())
    assert route.provider == "openrouter" and "anthropic" not in route.model and "claude" not in route.model


def test_fallback_from_fallback_or_reasoning_is_refused_and_attempts_are_bounded():
    first = routing.choose(_config(), authorize=_allow())
    second = routing.fallback(_config(), first, "timeout", attempt=0, authorize=_allow())
    for failed, attempt in ((second, 0), (first, routing.MAX_FALLBACKS)):
        with pytest.raises(RouteRefused):
            routing.fallback(_config(), failed, "timeout", attempt=attempt, authorize=_allow())
    reasoning = routing.choose(_config(), selection="reasoning", authorize=_allow())
    with pytest.raises(RouteRefused):
        routing.fallback(_config(), reasoning, "timeout", attempt=0, authorize=_allow())


def test_missing_capability_and_cancellation_stop_routing():
    with pytest.raises(RouteRefused, match="capability unavailable"):
        routing.choose(_config(), needs={"audio_output"}, authorize=_allow())
    calls = []
    with pytest.raises(RouteRefused, match="Stopped"):
        routing.choose(_config(), cancelled=True, authorize=_allow(calls))
    with pytest.raises(RouteRefused, match="Stopped"):
        routing.fallback(_config(), Route("default", "m", True), "timeout", attempt=0,
                         cancelled=True, authorize=_allow(calls))
    assert calls == []


# Agent-loop compatibility


def test_every_request_to_a_paid_tier_is_checked_on_its_own(home):
    from tools import aura_budget

    aura_budget.update_budget_limit(paid_enabled=True, actor="melvin")
    log = []
    for _ in range(3):  # a turn, a retry and a recovery cycle each send their own request
        routing.guard(_config(), "openrouter", OR, {"model": TIERS["default"]["model"]}, authorize=_allow(log))
    assert log == [TIERS["default"]["model"]] * 3
    assert len(aura_budget.get_budget_status()["history"]) == 3


def test_a_refused_request_never_builds_a_client_or_reaches_the_transport(home):
    from agent.chat_completion_helpers import _dispatch_nonstreaming_api_request

    home(_config(enabled=True))
    hits = []
    agent = SimpleNamespace(provider="openrouter", model=TIERS["default"]["model"], base_url=OR,
                            api_mode="chat_completions")
    with pytest.raises(FreeOnlyRefused, match="Paid models are switched off"):
        _dispatch_nonstreaming_api_request(agent, {"model": TIERS["default"]["model"]},
                                           make_client=lambda *a: hits.append("client"))
    assert hits == []


def test_a_committed_action_is_never_repeated_through_a_fallback():
    first = routing.choose(_config(), authorize=_allow())
    with pytest.raises(RouteRefused):
        routing.fallback(_config(), first, "timeout", attempt=0, committed_action=True, authorize=_allow())


def test_unrouted_models_keep_the_existing_gates(home):
    home(_config(enabled=True, free_only=False))
    request = {"model": "gemini-3.8-flash"}
    assert require_model("gemini", "https://generativelanguage.googleapis.com/v1beta", request) is request


def test_settings_status_shows_disabled_paid_tiers_and_no_secrets(home, monkeypatch):
    from tools import aura_provider

    home(_config(enabled=True))
    monkeypatch.setattr("hermes_cli.config.load_env", lambda: {"OPENROUTER_API_KEY": "sk-or-secret"})
    shown = aura_provider.status()
    assert [t["state"] for t in shown["routing"]["tiers"]] == ["disabled"] * 3
    assert shown["routing"]["test_route"]["experimental"] is True
    assert "sk-or-secret" not in json.dumps(shown)


def test_choosing_the_test_route_while_it_is_off_is_a_clear_error(home):
    from tools import aura_provider

    home(_config(test=False))
    with pytest.raises(ValueError, match="test model is switched off"):
        aura_provider.configure("openrouter_test")


# Catalog snapshot (tests/fixtures/aura/openrouter_candidates.json, scripts/reveta/openrouter_catalog.py)

SNAPSHOT = json.loads((ROOT / "tests" / "fixtures" / "aura" / "openrouter_candidates.json").read_text(encoding="utf-8-sig"))


def test_every_configured_id_is_listed_exactly_in_the_catalog_snapshot():
    configured = {**{tier: entry["model"] for tier, entry in TIERS.items()}, "test": TEST_MODEL}
    assert {tier: row["model"] for tier, row in SNAPSHOT["candidates"].items()} == configured
    assert all(row["listed"] for row in SNAPSHOT["candidates"].values())


def test_configured_capabilities_are_what_every_listed_endpoint_offers():
    for tier, entry in {**TIERS, "test": {"capabilities": ["text", "tools"]}}.items():
        row = SNAPSHOT["candidates"][tier]
        if "tools" in entry["capabilities"]:
            assert row["tools"] == "all"
        if "image" in entry["capabilities"]:
            assert "image" in row["input_modalities"]
    assert SNAPSHOT["candidates"]["test"]["prompt_usd_per_million"] == {"min": "0", "max": "0"}


def test_an_id_the_catalog_does_not_list_is_reported_not_substituted():
    script = importlib.util.spec_from_file_location("openrouter_catalog", ROOT / "scripts" / "reveta" / "openrouter_catalog.py")
    catalog = importlib.util.module_from_spec(script)
    script.loader.exec_module(catalog)
    similar = {"data": {"id": "z-ai/glm-5.3", "endpoints": []}}
    assert catalog.summarize("z-ai/glm-5.3-flash", similar, "fixture")["listed"] is False
    assert catalog.summarize("z-ai/glm-5.3-flash", {"error": {"code": 404}}, "fixture")["listed"] is False
