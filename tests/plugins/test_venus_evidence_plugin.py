"""venus-evidence: metadata-only run evidence through the observer hooks.

Behaviour contracts: what a record says about a run (tool outcomes, cost, value, outcome) and
what it must never contain (prompts, arguments, results, secrets); plus the plugin's observer
guarantees (opt-in, no return values, no actions) through the real discovery path.
"""

import importlib.util
import json
import sys
import types
from decimal import Decimal
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugins" / "venus-evidence"
SECRET_PROMPT = "PLEASE-SUMMARISE-MY-PRIVATE-MERGER-MEMO"
SECRET_ARG = "sk-live-THIS-IS-A-SECRET-TOKEN-123"
SECRET_RESULT = "RAW-TOOL-OUTPUT-WITH-CUSTOMER-PII"


@pytest.fixture(autouse=True)
def _hermes_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def _load():
    name = "hermes_plugins.venus_evidence_under_test"
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / "__init__.py",
                                                  submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class ListSink:
    def __init__(self, fail=False):
        self.records, self.fail = [], fail

    def write(self, record):
        if self.fail:
            raise OSError("disk full")
        self.records.append(json.loads(json.dumps(record)))


def _no_price(model, provider, base_url, tokens):
    return None, "unknown", "none"


def _recorder(mod, sink=None, estimator=_no_price):
    return mod.EvidenceRecorder(sink=sink or ListSink(), estimator=estimator)


def _api_ok(rec, sid="s1", usage=None, **kw):
    rec.on_api_success({"session_id": sid, "model": "m-1", "provider": "custom", "base_url": "",
                        "api_duration": 0.25, "usage": usage, "platform": "cli",
                        "response": {"assistant_message": {"content": SECRET_RESULT}},
                        "request": {"body": {"messages": [{"content": SECRET_PROMPT}]}}, **kw})


def _tool(rec, name, status, result="{}", sid="s1"):
    rec.on_tool({"session_id": sid, "tool_name": name, "status": status, "duration_ms": 12,
                 "args": {"command": f"echo {SECRET_ARG}"}, "result": result,
                 "error_message": f"failed with {SECRET_ARG}"})


def _end(rec, sid="s1", **kw):
    kw.setdefault("completed", True)
    return rec.on_session_end({"session_id": sid, "model": "m-1", **kw})


USAGE = {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 5, "cache_write_tokens": 0,
         "reasoning_tokens": 3, "request_count": 1, "prompt_tokens": 105, "total_tokens": 125}


def _strings(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, str):
        yield value


class TestToolOutcomes:
    def test_failed_denied_and_blocked_tools_are_never_success(self):
        mod = _load()
        sink = ListSink()
        rec = _recorder(mod, sink)
        _tool(rec, "read_file", "ok", '{"content": "x"}')
        _tool(rec, "terminal", "error", '{"error": "exit 1", "exit_code": 1}')
        _tool(rec, "terminal", "error", json.dumps({"error": "BLOCKED: User denied this command.",
                                                     "status": "blocked", "user_summary": "You denied it"}))
        _tool(rec, "write_file", "blocked")
        _tool(rec, "web_search", "cancelled")
        _tool(rec, "mystery", "something-new")
        tools = _end(rec)["tools"]
        assert tools["success"] == 1
        assert tools["error"] == 3
        assert tools["denied"] == 1
        assert tools["blocked"] == 1
        assert [c["outcome"] for c in tools["calls"]] == [
            "success", "error", "denied", "blocked", "error", "error"]
        assert tools["calls"][0] == {"name": "read_file", "outcome": "success", "duration_ms": 12}

    def test_human_denied_approval_marks_the_failing_tool_denied(self):
        mod = _load()
        rec = _recorder(mod)
        rec.on_human_request({"request_id": "r1", "kind": "approval", "session_id": "s1",
                              "prompt": f"rm -rf / {SECRET_ARG}"})
        rec.on_human_resolved({"request_id": "r1", "kind": "approval", "session_id": "s1", "outcome": "deny",
                               "prompt": f"rm -rf / {SECRET_ARG}"})
        _tool(rec, "terminal", "error", '{"error": "BLOCKED", "status": "blocked"}')
        record = _end(rec)
        assert record["tools"]["denied"] == 1 and record["tools"]["success"] == 0
        event = record["approvals"]["events"][0]
        assert event["kind"] == "approval" and event["outcome"] == "denied"
        assert isinstance(event["wait_ms"], int) and event["wait_ms"] >= 0


class TestUnknownIsNotZero:
    def test_unpriced_cost_is_null_unknown(self):
        mod = _load()
        rec = _recorder(mod)
        _api_ok(rec, usage=USAGE)
        cost = _end(rec)["cost"]
        assert cost["amount_usd"] is None and cost["status"] == "unknown"

    def test_missing_usage_makes_cost_unknown_even_when_priced(self):
        mod = _load()
        rec = _recorder(mod, estimator=lambda *a: (Decimal("0.5"), "estimated", "official_docs_snapshot"))
        _api_ok(rec, usage=USAGE)
        _api_ok(rec, usage=None)
        record = _end(rec)
        assert record["cost"] == {"amount_usd": None, "status": "unknown", "source": "missing_usage"}
        assert record["tokens"]["complete"] is False and record["tokens"]["calls_without_usage"] == 1

    def test_no_api_calls_cost_unknown(self):
        mod = _load()
        rec = _recorder(mod)
        _tool(rec, "read_file", "ok")
        assert _end(rec)["cost"]["amount_usd"] is None

    def test_provider_reported_cost_wins(self):
        mod = _load()
        rec = _recorder(mod, estimator=lambda *a: pytest.fail("estimator must not run"))
        _api_ok(rec, usage={**USAGE, "cost_usd": 0.0123})
        cost = _end(rec)["cost"]
        assert cost == {"amount_usd": "0.0123", "status": "reported", "source": "provider_reported"}

    def test_estimate_through_usage_pricing_snapshot(self):
        mod = _load()
        rec = mod.EvidenceRecorder(sink=ListSink())  # real agent.usage_pricing estimator
        rec.on_api_success({"session_id": "s1", "model": "claude-opus-4-8", "provider": "anthropic",
                            "base_url": "https://api.anthropic.com", "api_duration": 1.0,
                            "usage": {"input_tokens": 1_000_000, "output_tokens": 0}})
        cost = _end(rec)["cost"]
        assert cost["status"] == "estimated" and Decimal(cost["amount_usd"]) == 5

    def test_missing_baseline_leaves_value_unknown(self):
        mod = _load()
        rec = _recorder(mod)
        _api_ok(rec, usage=USAGE)
        rec.set_value_inputs("s1", human_review_minutes=5)
        value = _end(rec)["value"]
        assert value["baseline_minutes"] is None
        assert value["delivery_cost"] is None and value["comparison_method"] is None
        assert value["savings_minutes"] == "unknown" and value["savings_status"] == "unknown"

    def test_savings_only_with_baseline_and_review(self):
        mod = _load()
        rec = _recorder(mod)
        _api_ok(rec, usage=USAGE)
        rec.set_value_inputs("s1", baseline_minutes=60, human_review_minutes=10,
                             comparison_method="manual", delivery_cost="12.50")
        value = _end(rec)["value"]
        assert value["savings_minutes"] == 50.0 and value["savings_status"] == "computed"
        assert value["comparison_method"] == "manual" and value["supplied_by"] == "human"


class TestRunOutcome:
    @pytest.mark.parametrize("end, api, expected", [
        ({"completed": True}, "ok", "completed"),
        ({"completed": False, "interrupted": True}, "ok", "partial"),
        ({"completed": False, "failed": True}, "ok", "failed"),
        ({"completed": False}, "error", "failed"),
        ({"completed": False}, "ok", "partial"),
        ({"completed": None}, "ok", "unknown"),
    ])
    def test_outcome(self, end, api, expected):
        mod = _load()
        rec = _recorder(mod)
        if api == "ok":
            _api_ok(rec, usage=USAGE)
        else:
            rec.on_api_error({"session_id": "s1", "api_duration": 0.1, "retryable": True,
                              "error": {"type": "RateLimit", "message": SECRET_PROMPT}})
        assert _end(rec, **end)["outcome"]["status"] == expected

    def test_api_counts_retries_and_latency(self):
        mod = _load()
        rec = _recorder(mod)
        rec.on_api_error({"session_id": "s1", "api_duration": 0.5, "retryable": True})
        rec.on_api_error({"session_id": "s1", "api_duration": 0.1, "retryable": False})
        _api_ok(rec, usage=USAGE)
        api = _end(rec)["api"]
        assert api == {"attempts": 3, "succeeded": 1, "errors": 2, "retries": 1,
                       "latency_ms_total": 850, "latency_ms_max": 500}


class TestRedaction:
    def test_record_holds_no_prompt_args_results_or_secrets(self):
        mod = _load()
        sink = ListSink()
        rec = _recorder(mod, sink)
        _api_ok(rec, usage=USAGE)
        rec.on_api_error({"session_id": "s1", "api_duration": 0.1, "retryable": True,
                          "error": {"type": "AuthError", "message": f"bad key {SECRET_ARG}"},
                          "request": {"body": {"messages": [{"content": SECRET_PROMPT}]}}})
        _tool(rec, "terminal", "ok", json.dumps({"output": SECRET_RESULT}))
        _tool(rec, "terminal", "error", json.dumps({"error": SECRET_ARG}))
        rec.on_human_request({"request_id": "r", "kind": "clarify", "session_id": "s1", "prompt": SECRET_PROMPT})
        rec.on_human_resolved({"request_id": "r", "kind": "clarify", "session_id": "s1",
                               "outcome": "answered", "prompt": SECRET_PROMPT})
        _end(rec, turn_exit_reason="completed")
        dumped = json.dumps(sink.records)
        for secret in (SECRET_PROMPT, SECRET_ARG, SECRET_RESULT, "echo", "messages"):
            assert secret not in dumped
        assert not any(len(s) > 300 for s in _strings(sink.records))

    def test_hostile_tool_name_and_outcome_are_bounded(self):
        mod = _load()
        rec = _recorder(mod)
        _tool(rec, "x" * 5000 + "\x00\x1b[31m", "ok")
        rec.on_human_resolved({"request_id": "r", "kind": "sudo", "session_id": "s1",
                               "outcome": "provided " + SECRET_ARG})
        record = _end(rec)
        name = record["tools"]["calls"][0]["name"]
        assert len(name) <= 128 and "\x00" not in name and "\x1b" not in name
        assert len(record["approvals"]["events"][0]["outcome"]) <= 32


class TestBuffers:
    def test_tool_event_overflow_is_counted_not_lost(self):
        mod = _load()
        rec = _recorder(mod)
        limit = mod.ev.MAX_TOOL_EVENTS
        for _ in range(limit + 7):
            _tool(rec, "read_file", "ok")
        record = _end(rec)
        assert len(record["tools"]["calls"]) == limit
        assert record["tools"]["dropped"] == 7 and record["buffer"]["dropped_events"] == 7
        assert record["tools"]["success"] == limit + 7  # counts stay exact

    def test_failed_writes_buffer_then_flush_and_count_drops(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod, "MAX_PENDING_WRITES", 2)
        sink = ListSink(fail=True)
        rec = _recorder(mod, sink)
        for sid in ("a", "b", "c"):
            _api_ok(rec, sid=sid, usage=USAGE)
            _end(rec, sid=sid)
        sink.fail = False
        _api_ok(rec, sid="d", usage=USAGE)
        last = _end(rec, sid="d")
        assert [r["session_id"] for r in sink.records] == ["a", "b", "d"]
        assert last["buffer"]["dropped_records"] == 1

    def test_open_run_overflow_evicts_oldest_and_counts(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod, "MAX_OPEN_RUNS", 2)
        rec = _recorder(mod)
        for sid in ("a", "b", "c"):
            _api_ok(rec, sid=sid, usage=USAGE)
        assert _end(rec, sid="a") is None
        assert _end(rec, sid="c")["buffer"]["dropped_records"] == 1


class TestProvisionalRoute:
    def test_route_suggestion_logs_only_and_takes_no_action(self, monkeypatch):
        import model_tools
        from hermes_cli import plugins as pmod
        mod = _load()
        sink = ListSink()
        monkeypatch.setattr(mod, "_recorder", _recorder(mod, sink))

        def forbidden(*a, **k):
            raise AssertionError("route suggestion must not act")
        monkeypatch.setattr(model_tools, "handle_function_call", forbidden)
        monkeypatch.setattr(pmod, "invoke_hook", forbidden)

        _api_ok(mod._recorder, usage=USAGE)
        assert mod.record_route_suggestion("tool", 0.62, "heuristic", session_id="s1") is None
        record = _end(mod._recorder)
        assert record["route_suggestions"]["items"][0] | {"at": None} == {
            "route": "tool", "confidence": 0.62, "source": "heuristic", "provisional": True, "at": None}
        assert record["tools"]["total"] == 0 and record["api"]["attempts"] == 1
        assert len(sink.records) == 1

    def test_invalid_route_rejected(self):
        mod = _load()
        with pytest.raises(ValueError):
            mod.record_route_suggestion("create_goal", 0.9, "x")


def test_fixture_demo_flow_is_marked_fixture(_hermes_home):
    mod = _load()
    rec = mod.EvidenceRecorder(estimator=lambda *a: (Decimal("0.002"), "estimated", "official_docs_snapshot"))
    rec.begin_run("demo", source="fixture")
    rec.on_api_success({"session_id": "demo", "model": "demo-model", "provider": "demo",
                        "api_duration": 0.4, "usage": USAGE})
    rec.on_tool({"session_id": "demo", "tool_name": "read_file", "status": "ok", "duration_ms": 3})
    record = rec.on_session_end({"session_id": "demo", "completed": True})
    assert record["provenance"]["source"] == "fixture"
    assert record["provenance"]["plugin_version"] == "0.1.0"
    lines = list((_hermes_home / "plugin-data" / "venus-evidence").glob("evidence-*.jsonl"))
    assert len(lines) == 1
    stored = [json.loads(l) for l in lines[0].read_text().splitlines()]
    assert stored[0]["provenance"]["source"] == "fixture" and stored[0]["cost"]["amount_usd"] == "0.002"


class TestThroughRealDiscovery:
    HOOKS = ("post_api_request", "api_request_error", "post_tool_call",
             "on_human_input_request", "on_human_input_resolved", "on_session_end")

    def _manager(self, home, enabled):
        import hermes_yaml as yaml
        if enabled:
            (home / "config.yaml").write_text(yaml.safe_dump({"plugins": {"enabled": ["venus-evidence"]}}))
        from hermes_cli import plugins as pmod
        mgr = pmod.PluginManager()
        mgr.discover_and_load()
        return mgr

    def _drive(self, mgr):
        results = [
            mgr.invoke_hook("post_api_request", session_id="e2e", model="m", provider="custom",
                            api_duration=0.2, usage=USAGE, response={"x": SECRET_RESULT}),
            mgr.invoke_hook("post_tool_call", session_id="e2e", tool_name="terminal", status="ok",
                            args={"command": SECRET_ARG}, result=SECRET_RESULT, duration_ms=5),
            mgr.invoke_hook("on_human_input_request", request_id="q", kind="approval", session_id="e2e",
                            prompt=SECRET_PROMPT),
            mgr.invoke_hook("on_human_input_resolved", request_id="q", kind="approval", session_id="e2e",
                            outcome="once", prompt=SECRET_PROMPT),
            mgr.invoke_hook("api_request_error", session_id="e2e", api_duration=0.1, retryable=True,
                            error={"type": "X", "message": SECRET_PROMPT}),
            mgr.invoke_hook("on_session_end", session_id="e2e", completed=True, model="m"),
        ]
        return results

    def test_disabled_by_default_registers_nothing_and_writes_nothing(self, _hermes_home):
        mgr = self._manager(_hermes_home, enabled=False)
        loaded = mgr._plugins["venus-evidence"]
        assert loaded.manifest.source == "bundled" and not loaded.enabled
        assert all(r == [] for r in self._drive(mgr))
        assert not (_hermes_home / "plugin-data" / "venus-evidence").exists()

    def test_enabled_hooks_return_nothing_and_write_one_record(self, _hermes_home):
        mgr = self._manager(_hermes_home, enabled=True)
        assert mgr._plugins["venus-evidence"].enabled
        assert all(r == [] for r in self._drive(mgr))
        files = list((_hermes_home / "plugin-data" / "venus-evidence").glob("evidence-*.jsonl"))
        assert len(files) == 1
        text = files[0].read_text()
        (record,) = [json.loads(line) for line in text.splitlines()]
        assert record["provenance"]["source"] == "measured_runtime"
        assert record["tools"]["success"] == 1 and record["approvals"]["events"][0]["outcome"] == "approved"
        assert record["api"]["retries"] == 1 and record["outcome"]["status"] == "completed"
        for secret in (SECRET_PROMPT, SECRET_ARG, SECRET_RESULT):
            assert secret not in text
