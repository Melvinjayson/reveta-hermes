"""Price and transport fixtures only. Never contacts a real model or app."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import json
from types import SimpleNamespace

import pytest

from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from tools import approval
from tools.approval_context import set_current_session_key, reset_current_session_key
from tools.aura_free_only import FreeOnlyRefused, REFUSAL, require_model
from tools.registry import ToolRegistry

URL = "http://127.0.0.1:9/v1"
MODEL = {
    "provider": "custom",
    "model": "fixture-model",
    "base_url": URL,
    "confirmed_free": True,
    "cost_usd": 0,
}


def _fixture_client():
    import httpx

    return SimpleNamespace(
        base_url=URL,
        _client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        ),
    )


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ht = set_hermes_home_override(str(tmp_path))
    st = set_current_session_key("free-fixture")

    def write(models=None):
        (tmp_path / "config.yaml").write_text(
            json.dumps({"aura": {"free_models": models if models is not None else []}})
        )

    write()
    try:
        yield tmp_path, write
    finally:
        approval.unregister_gateway_notify("free-fixture")
        reset_current_session_key(st)
        reset_hermes_home_override(ht)


def test_non_allowlisted_model_never_constructs_or_calls_transport(policy):
    from agent.chat_completion_helpers import _dispatch_nonstreaming_api_request

    hits = []
    agent = SimpleNamespace(
        provider="custom", model="unknown", base_url=URL, api_mode="chat_completions"
    )
    with pytest.raises(FreeOnlyRefused, match="This would cost money"):
        _dispatch_nonstreaming_api_request(
            agent, {"model": "unknown"}, make_client=lambda *a: hits.append("client")
        )
    assert hits == []


@pytest.mark.parametrize(
    "change",
    [
        {"cost_usd": 1},
        {"confirmed_free": False},
        {"cost_usd": None},
        {"base_url": URL + "/other"},
    ],
)
def test_paid_unknown_or_unconfirmed_price_is_refused(policy, change):
    _, write = policy
    write([{**MODEL, **change}])
    with pytest.raises(FreeOnlyRefused):
        require_model("custom", URL, {"model": "fixture-model"})


def test_allowlisted_fixture_model_runs_through_main_route(policy, monkeypatch):
    from agent import chat_completion_helpers as h

    _, write = policy
    write([MODEL])
    hits = []
    monkeypatch.setattr(
        h,
        "_chat_completion_capturing_headers",
        lambda agent, client, request: hits.append(request) or "fixture reply",
    )
    agent = SimpleNamespace(
        provider="custom",
        model="fixture-model",
        base_url=URL,
        api_mode="chat_completions",
    )
    original = {
        "model": "fixture-model",
        "extra_body": {"provider": {"allow_fallbacks": True}},
    }
    result = h._dispatch_nonstreaming_api_request(
        agent, original, make_client=lambda *a: _fixture_client()
    )
    assert result == "fixture reply" and len(hits) == 1
    assert hits[0]["extra_body"]["provider"]["allow_fallbacks"] is False
    assert original["extra_body"]["provider"]["allow_fallbacks"] is True


def test_free_quota_error_does_not_activate_paid_fallback(policy, monkeypatch):
    from agent import chat_completion_helpers as h
    from agent.error_classifier import FailoverReason

    _, write = policy
    write([MODEL])
    hits = []

    def exhausted(*args):
        hits.append("free attempt")
        raise RuntimeError("synthetic free quota exhausted")

    monkeypatch.setattr(h, "_chat_completion_capturing_headers", exhausted)
    agent = SimpleNamespace(
        provider="custom",
        model="fixture-model",
        base_url=URL,
        api_mode="chat_completions",
        _fallback_chain=[{"provider": "paid", "model": "paid-model"}],
        _fallback_index=0,
    )
    with pytest.raises(RuntimeError, match="synthetic free quota"):
        h._dispatch_nonstreaming_api_request(
            agent,
            {"model": "fixture-model"},
            make_client=lambda *a: _fixture_client(),
        )
    assert h.try_activate_fallback(agent, reason=FailoverReason.rate_limit) is False
    assert agent._fallback_index == 0 and agent.provider == "custom"
    assert hits == ["free attempt"]


@pytest.mark.parametrize(
    "payload",
    [
        {"model": "fixture-model", "extra_body": {"model": "paid"}},
        {"model": "fixture-model", "extra_body": {"models": ["paid"]}},
        {"model": "fixture-model", "service_tier": "priority"},
    ],
)
def test_wire_overrides_cannot_escape_allowlist(policy, payload):
    _, write = policy
    write([MODEL])
    with pytest.raises(FreeOnlyRefused):
        require_model("custom", URL, payload)


@pytest.mark.parametrize("name", ["read_file", "paid_addon", "unknown_app"])
def test_unknown_tool_price_refuses_before_approval_and_side_effect(policy, name):
    hits, prompts = [], []
    registry = ToolRegistry()
    registry.register(
        name=name,
        toolset="fixture",
        schema={"name": name},
        handler=lambda args: hits.append("effect") or '{"success":true}',
    )

    def approve(data):
        prompts.append(data)
        approval.resolve_gateway_approval(
            "free-fixture", "once", request_id=data["request_id"]
        )

    approval.register_gateway_notify("free-fixture", approve)
    result = json.loads(registry.dispatch(name, {}))
    assert result["status"] == "refused" and result["error"] == REFUSAL
    assert not hits and not prompts


def test_positive_tool_price_cannot_be_marked_confirmed_free(policy):
    from tests.fakes.aura_price_policy import attest_tool

    home, _ = policy
    attest_tool(home, "paid_addon", {})
    from ruamel.yaml import YAML

    yaml = YAML()
    config = yaml.load((home / "config.yaml").read_text())
    config["aura"]["free_tools"][0]["cost_usd"] = 1
    with (home / "config.yaml").open("w") as output:
        yaml.dump(config, output)
    hits = []
    registry = ToolRegistry()
    registry.register(
        name="paid_addon",
        toolset="fixture",
        schema={"name": "paid_addon"},
        handler=lambda args: hits.append(1),
    )
    assert json.loads(registry.dispatch("paid_addon", {}))["error"] == REFUSAL
    assert hits == []


def test_revoked_zero_price_while_approval_pending_prevents_execution(policy):
    from tests.fakes.aura_price_policy import attest_tool

    home, write = policy
    attest_tool(home, "fixture_write", {})
    hits = []
    registry = ToolRegistry()
    registry.register(
        name="fixture_write",
        toolset="fixture",
        schema={"name": "fixture_write"},
        handler=lambda args: hits.append(1),
    )

    def notify(data):
        write()  # founder-owned price attestation withdrawn while user is deciding
        assert (
            approval.resolve_gateway_approval(
                "free-fixture", "once", request_id=data["request_id"]
            )
            == 1
        )

    approval.register_gateway_notify("free-fixture", notify)
    assert json.loads(registry.dispatch("fixture_write", {}))["error"] == REFUSAL
    assert hits == []


def test_auxiliary_sync_async_and_stream_routes_cannot_call_unknown_model(policy):
    from agent.auxiliary_client import (
        _relay_sync_completion,
        _relay_async_completion,
        _relay_sync_stream,
    )

    hits = []
    client = SimpleNamespace(
        base_url=URL,
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: hits.append(1))
        ),
    )
    with pytest.raises(FreeOnlyRefused):
        _relay_sync_completion(
            client,
            {"model": "unknown"},
            provider="custom",
            create=lambda request: hits.append(1),
        )

    async def create(request):
        hits.append(1)

    with pytest.raises(FreeOnlyRefused):
        asyncio.run(
            _relay_async_completion(
                client, {"model": "unknown"}, provider="custom", create=create
            )
        )
    with pytest.raises(FreeOnlyRefused):
        _relay_sync_stream(client, {"model": "unknown"}, provider="custom")
    assert hits == []


@pytest.mark.parametrize(
    "kind", ["browser submit fixture", "connected-app write fixture"]
)
def test_browser_and_connected_app_fixture_use_same_single_use_gate(
    policy, monkeypatch, kind
):
    from tests.fakes.aura_price_policy import attest_tool

    home, _ = policy
    hits, requests = [], []
    args = {"action": "submit", "body": "synthetic"}
    if kind == "browser submit fixture":
        registry = ToolRegistry()
        registry.register(
            name="browser_exec",
            toolset="fixture",
            schema={"name": "browser_exec"},
            handler=lambda args: hits.append(kind) or '{"success":true}',
        )
        name = "browser_exec"
        dispatch = lambda: registry.dispatch(name, args)
    else:
        from tools.connectors import dispatch as bridge

        name = "connectors__fixture__send"
        monkeypatch.setattr(
            bridge,
            "_dispatch_connector_call",
            lambda *a: hits.append(kind) or '{"success":true}',
        )
        dispatch = lambda: bridge.dispatch_connector_call(name, args, "synthetic-call")
    attest_tool(home, name, args)
    choice = "deny"

    def notify(data):
        assert hits == []
        requests.append(data)
        assert (
            approval.resolve_gateway_approval(
                "free-fixture", choice, request_id=data["request_id"]
            )
            == 1
        )

    approval.register_gateway_notify("free-fixture", notify)
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert (
            json.loads(pool.submit(copy_context().run, dispatch).result(timeout=5))[
                "status"
            ]
            == "refused"
        )
        assert hits == []
        choice = "once"
        assert json.loads(pool.submit(copy_context().run, dispatch).result(timeout=5))[
            "success"
        ]
    assert hits == [kind]
    assert (
        approval.resolve_gateway_approval(
            "free-fixture", "once", request_id=requests[-1]["request_id"]
        )
        == 0
    )
    assert hits == [kind]


def test_declared_mcp_charge_overrides_zero_attestation_before_approval(
    policy, monkeypatch
):
    from tools import mcp_tool
    from tools.mcp_tool_costs import CostPolicy, ToolCost
    from tools.mcp_tool_scope import _server_key
    from tools.mcp_tool_schema import mcp_prefixed_tool_name
    from tests.fakes.aura_price_policy import attest_tool

    home, _ = policy
    name = mcp_prefixed_tool_name("fixture", "paid")
    attest_tool(home, name, {})
    monkeypatch.setitem(mcp_tool._mcp_tool_server_names, name, "fixture")
    monkeypatch.setitem(
        mcp_tool._server_cost_policies,
        _server_key("fixture"),
        CostPolicy({"paid": ToolCost(1, 1)}, 0, "credits"),
    )
    registry, hits, prompts = ToolRegistry(), [], []
    registry.register(
        name=name,
        toolset="fixture",
        schema={"name": name},
        handler=lambda args: hits.append(1),
    )
    approval.register_gateway_notify("free-fixture", lambda data: prompts.append(data))
    assert json.loads(registry.dispatch(name, {}))["error"] == REFUSAL
    assert hits == prompts == []


def test_redirect_cannot_escape_confirmed_endpoint(policy):
    import httpx
    import openai
    from agent.chat_completion_helpers import _dispatch_nonstreaming_api_request

    _, write = policy
    write([MODEL])
    urls = []

    def respond(request):
        urls.append(str(request.url))
        return httpx.Response(307, headers={"Location": "http://127.0.0.1:10/paid"})

    with httpx.Client(
        transport=httpx.MockTransport(respond), follow_redirects=True
    ) as transport:
        with openai.OpenAI(
            api_key="synthetic", base_url=URL, http_client=transport, max_retries=0
        ) as client:
            agent = SimpleNamespace(
                provider="custom",
                model="fixture-model",
                base_url=URL,
                api_mode="chat_completions",
            )
            with pytest.raises(openai.APIStatusError):
                _dispatch_nonstreaming_api_request(
                    agent,
                    {
                        "model": "fixture-model",
                        "messages": [{"role": "user", "content": "synthetic"}],
                    },
                    make_client=lambda *a: client,
                )
    assert urls == [URL + "/chat/completions"]


@pytest.mark.parametrize("flag", [False, "false", 0, None])
def test_disabling_or_malformed_mode_cannot_enable_paid_calls(policy, flag):
    home, _ = policy
    (home / "config.yaml").write_text(
        json.dumps({"aura": {"free_only": flag, "free_models": [MODEL]}})
    )
    with pytest.raises(FreeOnlyRefused):
        require_model("custom", URL, {"model": "fixture-model"})


def test_auxiliary_quota_stops_before_any_recovery_route(policy, monkeypatch):
    from agent import auxiliary_client as aux

    monkeypatch.setattr(
        aux, "_LadderRoute", lambda *a: pytest.fail("recovery route constructed")
    )
    ladder = aux._aux_recovery_ladder(
        RuntimeError("synthetic quota"),
        client=None,
        kwargs={},
        task="fixture",
        async_mode=False,
        base_info=URL,
        resolved_provider="custom",
        resolved_model="fixture-model",
        resolved_base_url=URL,
        resolved_api_key="synthetic",
        resolved_api_mode="chat_completions",
        final_model="fixture-model",
        max_tokens=10,
        main_runtime=None,
        route_info=None,
    )
    with pytest.raises(RuntimeError, match="synthetic quota"):
        next(ladder)
