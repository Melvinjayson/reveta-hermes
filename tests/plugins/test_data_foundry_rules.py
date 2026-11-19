"""Data Foundry rules over venus-evidence records: provenance, labels, grades, sign-off, /evidence."""

import importlib.util
import json
import sys
import types
from decimal import Decimal
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugins" / "venus-evidence"
SECRET_PROMPT = "PLEASE-SUMMARISE-MY-PRIVATE-MERGER-MEMO"
SECRET_NOTE = "reviewer-note-with-client-name-ACME"
USAGE = {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 0, "cache_write_tokens": 0,
         "reasoning_tokens": 0}
ENV_VARS = ("VENUS_EVIDENCE_ENV", "IS_PULL_REQUEST", "RENDER", "RENDER_GIT_COMMIT")


@pytest.fixture(autouse=True)
def _hermes_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return home


@pytest.fixture
def plugin():
    name = "hermes_plugins.venus_evidence_foundry_under_test"
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / "__init__.py",
                                                  submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    mod.foundry = importlib.import_module(f"{name}.foundry")
    mod.ev = importlib.import_module(f"{name}.evidence")
    return mod


def _priced(model, provider, base_url, tokens):
    return Decimal("0.01"), "estimated", "official_docs_snapshot"


def _run(plugin, *, usage=USAGE, completed=True, estimator=_priced, sid="s1"):
    """Drive one run through the real recorder and its JSONL sink; returns the stored record."""
    rec = plugin.EvidenceRecorder(sink=plugin._recorder.sink, estimator=estimator)
    rec.on_api_success({"session_id": sid, "model": "m-1", "provider": "custom", "api_duration": 0.2,
                        "usage": usage, "request": {"messages": [{"content": SECRET_PROMPT}]}})
    rec.on_tool({"session_id": sid, "tool_name": "read_file", "status": "ok", "duration_ms": 3})
    return rec.on_session_end({"session_id": sid, "completed": completed})


def _stored(home):
    files = sorted((home / "plugin-data" / "venus-evidence").glob("evidence-*.jsonl"))
    return [json.loads(line) for f in files for line in f.read_text().splitlines()]


def _grade_all(plugin, home):
    return {run["record_id"]: plugin.foundry.assess(run, am, so)
            for run, am, so in plugin.foundry.index(_stored(home))}


class TestRecordShape:
    def test_envelope_producer_and_facets(self, plugin, monkeypatch):
        monkeypatch.setenv("RENDER", "true")
        monkeypatch.setenv("RENDER_GIT_COMMIT", "abcdef1234567890")
        record = _run(plugin)
        assert record["eventType"] == "COMPLETE" and record["schema_version"] == "venus.run_event.v1"
        assert record["producer"] == "venus-evidence/0.1.0+abcdef1"
        assert record["run"]["runId"] == record["record_id"] and record["job"]["name"]
        prov = record["run"]["facets"]["provenance"]
        assert prov["environment"] == "live" and prov["decided_by"] == "RENDER"
        metrics = record["run"]["facets"]["evidence"]["metrics"]
        assert metrics["tool_calls"] == {"value": 1, "label": "measured", "source": "observer_hooks"}
        assert metrics["cost_usd"]["label"] == "estimated" and metrics["cost_usd"]["status"] == "estimated"
        assert metrics["baseline_minutes"] == {"value": None, "label": "unknown", "source": "none"}

    @pytest.mark.parametrize("env, expected", [
        ({}, ("local", "default")),
        ({"RENDER": "1"}, ("live", "RENDER")),
        ({"RENDER": "1", "IS_PULL_REQUEST": "true"}, ("preview", "IS_PULL_REQUEST")),
        ({"RENDER": "1", "IS_PULL_REQUEST": "true", "VENUS_EVIDENCE_ENV": "live"}, ("live", "VENUS_EVIDENCE_ENV")),
        ({"RENDER": "1", "VENUS_EVIDENCE_ENV": "LIVEE"}, ("local", "VENUS_EVIDENCE_ENV")),
    ])
    def test_environment_resolution(self, plugin, monkeypatch, env, expected):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        prov = _run(plugin)["run"]["facets"]["provenance"]
        assert (prov["environment"], prov["decided_by"]) == expected

    def test_fixture_source_is_fixture_even_on_live_host(self, plugin, monkeypatch):
        monkeypatch.setenv("RENDER", "1")
        rec = plugin.EvidenceRecorder(sink=plugin._recorder.sink, estimator=_priced)
        rec.begin_run("demo", source="fixture")
        rec.on_api_success({"session_id": "demo", "model": "m", "usage": USAGE})
        record = rec.on_session_end({"session_id": "demo", "completed": True})
        assert record["run"]["facets"]["provenance"]["environment"] == "fixture"
        assert plugin.foundry.assess(record)["grade"] == "not_evidence"

    def test_no_commit_gives_unknown_producer(self, plugin):
        assert _run(plugin)["producer"] == "venus-evidence/0.1.0+unknown"


class TestCost:
    def test_included_route_without_usage_stays_included(self, plugin):
        included = lambda *a: (Decimal(0), "included", "none")
        record = _run(plugin, usage=None, estimator=included)
        assert record["cost"] == {"amount_usd": "0", "status": "included", "source": "none"}
        metric = record["run"]["facets"]["evidence"]["metrics"]["cost_usd"]
        assert metric["status"] == "included" and metric["value"] == "0" and metric["label"] != "unknown"

    def test_priced_route_without_usage_is_still_unknown(self, plugin):
        record = _run(plugin, usage=None)
        assert record["cost"]["status"] == "unknown" and record["cost"]["amount_usd"] is None

    def test_real_subscription_route_through_usage_pricing(self, plugin):
        rec = plugin.EvidenceRecorder(sink=plugin._recorder.sink)
        rec.on_api_success({"session_id": "c", "model": "gpt-5-codex", "provider": "openai-codex", "usage": None})
        assert rec.on_session_end({"session_id": "c", "completed": True})["cost"]["status"] == "included"

    def test_reported_plus_included_is_actual_not_estimated(self, plugin):
        rec = plugin.EvidenceRecorder(sink=plugin._recorder.sink, estimator=lambda *a: (Decimal(0), "included", "none"))
        rec.on_api_success({"session_id": "r", "model": "a", "usage": {**USAGE, "cost_usd": "0.02"}})
        rec.on_api_success({"session_id": "r", "model": "b", "usage": USAGE})
        record = rec.on_session_end({"session_id": "r", "completed": True})
        assert record["cost"]["status"] == "reported"
        assert record["run"]["facets"]["evidence"]["metrics"]["cost_usd"]["status"] == "actual"


def _value_ready(plugin, monkeypatch, home):
    monkeypatch.setenv("RENDER", "1")
    rid = _run(plugin)["record_id"]
    plugin._handle_value_command(f"{rid} baseline_minutes=60")
    plugin._handle_value_command(f"{rid} human_review_minutes=15")
    return rid


class TestGrades:
    @pytest.mark.parametrize("env", [{"VENUS_EVIDENCE_ENV": "preview"}, {"VENUS_EVIDENCE_ENV": "local"}, {}])
    def test_preview_and_local_never_count(self, plugin, monkeypatch, _hermes_home, env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        rid = _run(plugin)["record_id"]
        plugin._handle_value_command(f"{rid} baseline_minutes=60 human_review_minutes=10")
        plugin._handle_evidence_command(f"signoff {rid} accept")
        graded = _grade_all(plugin, _hermes_home)[rid]
        assert graded["grade"] == "not_evidence" and not graded["time_saved_minutes"].scored
        assert "live runs: 0" in plugin._handle_evidence_command("")

    def test_live_complete_runtime_is_runtime_evidence(self, plugin, monkeypatch, _hermes_home):
        monkeypatch.setenv("RENDER", "1")
        rid = _run(plugin)["record_id"]
        graded = _grade_all(plugin, _hermes_home)[rid]
        assert graded["grade"] == "runtime_evidence"
        assert {"no_baseline", "no_review_minutes"} <= set(graded["capture_gaps"])
        assert graded["time_saved_minutes"] == plugin.foundry.Score.unscored("grade is runtime_evidence")

    def test_live_with_missing_tokens_is_not_evidence(self, plugin, monkeypatch, _hermes_home):
        monkeypatch.setenv("RENDER", "1")
        rid = _run(plugin, usage=None)["record_id"]
        graded = _grade_all(plugin, _hermes_home)[rid]
        assert graded["grade"] == "not_evidence" and "cost_unknown" in graded["capture_gaps"]
        assert graded["metrics"]["tokens_total"]["label"] == "unknown"

    def test_value_claim_ready_needs_baseline_review_and_accept(self, plugin, monkeypatch, _hermes_home):
        rid = _value_ready(plugin, monkeypatch, _hermes_home)
        assert _grade_all(plugin, _hermes_home)[rid]["grade"] == "runtime_evidence"  # no sign-off yet
        plugin._handle_evidence_command(f"signoff {rid[:8]} needs_more")
        assert _grade_all(plugin, _hermes_home)[rid]["grade"] == "runtime_evidence"
        out = plugin._handle_evidence_command(f"signoff {rid[:8]} accept 7 looks right")
        assert "grade=value_claim_ready" in out
        graded = _grade_all(plugin, _hermes_home)[rid]
        assert graded["grade"] == "value_claim_ready" and graded["capture_gaps"] == []
        assert graded["time_saved_minutes"] == plugin.foundry.Score.of(45)
        assert graded["metrics"]["baseline_minutes"]["label"] == "user_reported"  # amendments stay human input

    def test_signoff_minutes_count_as_review_minutes(self, plugin, monkeypatch, _hermes_home):
        monkeypatch.setenv("RENDER", "1")
        rid = _run(plugin)["record_id"]
        plugin._handle_value_command(f"{rid} baseline_minutes=30")
        plugin._handle_evidence_command(f"signoff {rid} accept 10")
        graded = _grade_all(plugin, _hermes_home)[rid]
        assert graded["grade"] == "value_claim_ready" and graded["time_saved_minutes"].value == 20
        assert graded["metrics"]["human_review_minutes"]["source"] == "signoff"

    def test_failed_run_is_runtime_evidence_never_value_claim(self, plugin, monkeypatch, _hermes_home):
        monkeypatch.setenv("RENDER", "1")
        rec = plugin.EvidenceRecorder(sink=plugin._recorder.sink, estimator=_priced)
        rec.on_api_success({"session_id": "f", "model": "m", "usage": USAGE})
        rid = rec.on_session_end({"session_id": "f", "failed": True})["record_id"]
        plugin._handle_value_command(f"{rid} baseline_minutes=60 human_review_minutes=5")
        plugin._handle_evidence_command(f"signoff {rid} accept")
        graded = _grade_all(plugin, _hermes_home)[rid]
        assert graded["event_type"] == "FAIL" and graded["grade"] == "runtime_evidence"

    def test_run_without_complete_or_fail_is_not_evidence(self, plugin, monkeypatch, _hermes_home):
        monkeypatch.setenv("RENDER", "1")
        rid = _run(plugin, completed=None, sid="u")["record_id"]
        graded = _grade_all(plugin, _hermes_home)[rid]
        assert graded["event_type"] == "ABORT" and "no_terminal_event" in graded["capture_gaps"]
        assert graded["grade"] == "not_evidence"


class TestUnscored:
    def test_unknown_is_skipped_not_zero(self, plugin):
        score = plugin.foundry
        totals = score.total([score.Score.of(30), score.Score.unscored("x"), score.Score.of(10)])
        assert totals == {"sum": 40, "count": 2, "skipped": 1, "mean": 20}
        assert score.total([score.Score.unscored("x")]) == {"sum": None, "count": 0, "skipped": 1, "mean": None}

    def test_listing_totals_skip_unscored_runs(self, plugin, monkeypatch, _hermes_home):
        rid = _value_ready(plugin, monkeypatch, _hermes_home)
        plugin._handle_evidence_command(f"signoff {rid} accept")
        _run(plugin, sid="s2")  # live, runtime evidence only: unscored
        out = plugin._handle_evidence_command("")
        assert "time saved: 45 min over 1 (skipped 1 unscored)" in out
        assert "cost: $0.0200 over 2 (skipped 0 unknown)" in out


class TestSignoffIntegrity:
    def test_edit_after_signoff_is_hash_mismatch(self, plugin, monkeypatch, _hermes_home):
        rid = _value_ready(plugin, monkeypatch, _hermes_home)
        plugin._handle_evidence_command(f"signoff {rid} accept")
        path = next((_hermes_home / "plugin-data" / "venus-evidence").glob("evidence-*.jsonl"))
        lines = path.read_text().splitlines()
        run = json.loads(lines[0])
        run["tools"]["total"] = 99  # someone edits the record after sign-off
        lines[0] = json.dumps(run)
        path.write_text("\n".join(lines) + "\n")
        graded = _grade_all(plugin, _hermes_home)[rid]
        assert "signoff_hash_mismatch" in graded["capture_gaps"] and graded["grade"] == "runtime_evidence"
        assert graded["signoff"] == {"verdict": "accept", "matches": False}

    def test_new_amendment_after_signoff_is_hash_mismatch(self, plugin, monkeypatch, _hermes_home):
        rid = _value_ready(plugin, monkeypatch, _hermes_home)
        plugin._handle_evidence_command(f"signoff {rid} accept")
        plugin._handle_value_command(f"{rid} baseline_minutes=600")  # inflating the baseline later
        graded = _grade_all(plugin, _hermes_home)[rid]
        assert "signoff_hash_mismatch" in graded["capture_gaps"] and not graded["time_saved_minutes"].scored

    def test_signoff_is_a_separate_statement_never_a_flag(self, plugin, monkeypatch, _hermes_home):
        rid = _value_ready(plugin, monkeypatch, _hermes_home)
        before = _stored(_hermes_home)[0]
        plugin._handle_evidence_command(f"signoff {rid} reject 3 {SECRET_NOTE}")
        stored = _stored(_hermes_home)
        assert stored[0] == before
        statement = stored[-1]
        assert statement["_type"] == "https://in-toto.io/Statement/v1"
        assert statement["predicateType"] == "reveta.dev/venus-signoff/v1"
        assert statement["subject"][0] == {"name": f"venus-run/{rid}",
                                           "digest": {"sha256": plugin.foundry.canonical_sha256(before)}}
        assert statement["predicate"] | {"signed_at": None} == {
            "verdict": "reject", "reviewer": "unknown", "minutes": "3", "note": SECRET_NOTE, "signed_at": None}

    def test_reviewer_comes_from_the_messaging_source(self, plugin, monkeypatch, _hermes_home):
        rid = _value_ready(plugin, monkeypatch, _hermes_home)
        source = types.SimpleNamespace(user_id="u42", platform=types.SimpleNamespace(value="telegram"))
        plugin._handle_evidence_command(f"signoff {rid} accept", source=source, platform="telegram")
        assert _stored(_hermes_home)[-1]["predicate"]["reviewer"] == "telegram:u42"


class TestOldAndMalformed:
    V1 = {"schema": "venus.evidence.v1", "record_id": "a" * 32, "session_id": "old",
          "provenance": {"source": "measured_runtime", "plugin": "venus-evidence", "plugin_version": "0.1.0"},
          "outcome": {"status": "completed", "duration_ms": 900},
          "api": {"attempts": 1, "errors": 0}, "tokens": {"total": 120, "complete": True},
          "cost": {"amount_usd": "0.01", "status": "reported", "source": "provider_reported"},
          "tools": {"total": 2}, "approvals": {"total": 0, "wait_ms_total": 0},
          "value": {"baseline_minutes": None}, "buffer": {"dropped_records": 0}}

    def test_old_v1_record_is_readable_but_has_no_provenance(self, plugin):
        graded = plugin.foundry.assess(self.V1)
        assert graded["grade"] == "not_evidence" and "no_provenance" in graded["capture_gaps"]
        assert graded["event_type"] == "COMPLETE"
        assert graded["metrics"]["cost_usd"]["status"] == "actual"
        assert graded["metrics"]["tokens_total"] == {"value": 120, "label": "measured", "source": "observer_hooks"}
        assert graded["completeness_pct"] == 82  # 9 of 11: baseline and review unknown

    @pytest.mark.parametrize("record", [
        None, "text", [], {}, {"schema": "venus.evidence.v1"},
        {"schema": "venus.evidence.v1", "record_id": "b" * 32, "run": "x", "outcome": [1], "tools": "many"},
        {"schema_version": "venus.run_event.v1", "run": {"runId": "c" * 32, "facets": {
            "provenance": {"environment": "live"},
            "evidence": {"metrics": {"baseline_minutes": {"label": "user_reported", "value": "n/a"}}}}}},
    ])
    def test_malformed_never_raises(self, plugin, record):
        graded = plugin.foundry.assess(record, amendments="junk", signoffs=[{"_type": 1}])
        assert graded["grade"] == "not_evidence"
        assert not graded["time_saved_minutes"].scored

    def test_malformed_lines_in_the_store_are_skipped(self, plugin, monkeypatch, _hermes_home):
        monkeypatch.setenv("RENDER", "1")
        _run(plugin)
        path = next((_hermes_home / "plugin-data" / "venus-evidence").glob("evidence-*.jsonl"))
        with path.open("a") as fh:
            fh.write('{"torn": \n[1,2]\n"str"\n' + json.dumps(self.V1) + "\n")
        out = plugin._handle_evidence_command("")
        assert "latest 2 run(s)" in out and "runtime_evidence" in out and "aaaaaaaa  none" in out


class TestEvidenceCommand:
    def test_list_line_shape_and_no_content(self, plugin, monkeypatch, _hermes_home):
        monkeypatch.setenv("RENDER", "1")
        rid = _run(plugin)["record_id"]
        out = plugin._handle_evidence_command("")
        line = next(l for l in out.splitlines() if l.startswith(rid[:8]))
        assert "live" in line and "runtime_evidence" in line and "%" in line
        assert "measured=" in line and "gaps=no_baseline,no_review_minutes" in line
        assert "time_saved=unknown" in line
        assert SECRET_PROMPT not in out

    def test_default_limit_is_five_and_n_is_honoured(self, plugin):
        for i in range(7):
            _run(plugin, sid=f"s{i}")
        assert "latest 5 run(s)" in plugin._handle_evidence_command("")
        assert "latest 2 run(s)" in plugin._handle_evidence_command("2")

    def test_note_is_never_listed(self, plugin, monkeypatch, _hermes_home):
        rid = _value_ready(plugin, monkeypatch, _hermes_home)
        plugin._handle_evidence_command(f"signoff {rid} accept 5 {SECRET_NOTE}")
        assert SECRET_NOTE not in plugin._handle_evidence_command("")

    @pytest.mark.parametrize("args, reason", [
        ("signoff", "usage"), ("signoff abc accept", "at least 8"),
        ("signoff deadbeef accept", "no run matching"), ("signoff {rid} maybe", "verdict must be"),
        ("signoff {rid} accept -3", "non-negative"), ("five", "usage"), ("signoff 'unterminated", "evidence:"),
    ])
    def test_bad_input_is_explained_and_writes_nothing(self, plugin, _hermes_home, args, reason):
        rid = _run(plugin)["record_id"]
        before = len(_stored(_hermes_home))
        assert reason in plugin._handle_evidence_command(args.format(rid=rid))
        assert len(_stored(_hermes_home)) == before

    def test_empty_store(self, plugin):
        assert plugin._handle_evidence_command("") == "evidence: no runs recorded yet"

    def test_registered_like_venus_value(self, plugin):
        names = []
        ctx = types.SimpleNamespace(register_hook=lambda *a: None,
                                    register_command=lambda name, **kw: names.append(name))
        plugin.register(ctx)
        assert names == ["venus-value", "evidence"]
