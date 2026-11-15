"""Aura regression: Google's per-day quota (free tier) is spent, so retrying
only hangs the turn for minutes (live: 191-220 s, then an empty reply).
A daily-quota 429 must end the turn on the first call; a per-minute 429 from
the same API stays a retryable throttle.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from agent.error_classifier import FailoverReason, classify_api_error
from agent.gemini_native_adapter import gemini_http_error

_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"


def _gemini_429(quota_id: str, delay: str) -> Exception:
    body = {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED",
        "message": ("You exceeded your current quota, please check your plan and billing details. "
                    "Quota exceeded for metric: generativelanguage.googleapis.com/"
                    f"generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash\n"
                    f"Please retry in {delay}."),
        "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
                "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                "quotaId": quota_id, "quotaValue": "20"}]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay},
        ],
    }}
    return gemini_http_error(httpx.Response(429, json=body, request=httpx.Request("POST", _URL)))


def _daily():
    return _gemini_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier", "30366s")


def _per_minute():
    return _gemini_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "23s")


def test_daily_quota_is_terminal_per_minute_stays_retryable():
    daily = classify_api_error(_daily(), provider="gemini", model="gemini-3.8-flash")
    assert daily.reason == FailoverReason.billing and not daily.retryable
    minute = classify_api_error(_per_minute(), provider="gemini", model="gemini-3.8-flash")
    assert minute.reason == FailoverReason.rate_limit and minute.retryable


def _agent():
    from run_agent import AIAgent
    with (
        patch("model_tools.get_tool_definitions", return_value=[]),
        patch("model_tools.check_toolset_requirements", return_value={}),
        patch("agent.process_bootstrap.OpenAI", return_value=MagicMock()),
    ):
        agent = AIAgent(
            api_key="AIza-test-key-000000", base_url="https://generativelanguage.googleapis.com/v1beta",
            provider="gemini", model="gemini-3.8-flash", quiet_mode=True,
            skip_context_files=True, skip_memory=True, fallback_model=[],
        )
    agent.client = MagicMock()
    agent._api_max_retries = 3
    return agent


def _run(make_error):
    agent, calls = _agent(), []

    def fake_call(_kwargs):
        calls.append(1)
        raise make_error()

    with (
        patch.object(agent, "_interruptible_api_call", side_effect=fake_call),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
        patch("agent.agent_runtime_helpers.time.sleep"),
        patch("time.sleep"),
    ):
        result = agent.run_conversation("hello")
    return result, len(calls)


def test_daily_quota_ends_turn_on_first_call():
    result, calls = _run(_daily)
    assert calls == 1
    assert result.get("failed") or not result.get("completed", True)


def test_per_minute_throttle_is_still_retried():
    _, calls = _run(_per_minute)
    assert calls > 1
