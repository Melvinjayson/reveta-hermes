"""/venus-value: human value inputs land as append-only amendment records for a run."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugins" / "venus-evidence"


@pytest.fixture(autouse=True)
def _hermes_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


@pytest.fixture
def plugin():
    name = "hermes_plugins.venus_evidence_value_under_test"
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


def _run(plugin):
    rec = plugin.get_recorder()
    rec.on_api_success({"session_id": "s1", "model": "m", "api_duration": 0.1, "usage": None})
    return rec.on_session_end({"session_id": "s1", "completed": True})["record_id"]


def _stored(home):
    files = sorted((home / "plugin-data" / "venus-evidence").glob("evidence-*.jsonl"))
    return [json.loads(line) for f in files for line in f.read_text().splitlines()]


def test_savings_unknown_until_both_minutes_set(plugin, _hermes_home):
    rid = _run(plugin)
    cmd = plugin._handle_value_command

    out = cmd(f"{rid} baseline_minutes=60")
    assert "savings_minutes=unknown" in out
    out = cmd(f"{rid} comparison_method=manual delivery_cost=12.50")
    assert "savings_minutes=unknown" in out
    out = cmd(f"{rid} human_review_minutes=15")
    assert "savings_minutes=45.0 (computed)" in out

    records = _stored(_hermes_home)
    run, *amendments = records
    assert run["value"]["savings_minutes"] == "unknown"  # the run record is never rewritten
    assert [a["value"]["savings_status"] for a in amendments] == ["unknown", "unknown", "computed"]
    last = amendments[-1]
    assert last["schema"] == "venus.evidence.amendment.v1" and last["amends_record_id"] == rid
    assert last["fields"] == {"human_review_minutes": "15"}
    assert last["provenance"]["source"] == "human_input"
    assert last["value"] | {"supplied_by": None} == {
        "baseline_minutes": 60.0, "human_review_minutes": 15.0, "delivery_cost": "12.50",
        "comparison_method": "manual", "savings_minutes": 45.0, "savings_status": "computed",
        "supplied_by": None}


def test_review_alone_stays_unknown_and_show_reports_it(plugin):
    rid = _run(plugin)
    plugin._handle_value_command(f"{rid} human_review_minutes=5")
    out = plugin._handle_value_command(rid)
    assert "baseline_minutes=unset" in out and "savings_minutes=unknown (unknown)" in out


@pytest.mark.parametrize("args, reason", [
    ("baseline_minutes=-1", "non-negative"),
    ("baseline_minutes=abc", "must be a number"),
    ("baseline_minutes=nan", "non-negative"),
    ("comparison_method=chatgpt", "comparison_method must be one of"),
    ("savings_minutes=99", "unknown field"),
])
def test_invalid_input_writes_nothing(plugin, _hermes_home, args, reason):
    rid = _run(plugin)
    out = plugin._handle_value_command(f"{rid} {args}")
    assert reason in out
    assert len(_stored(_hermes_home)) == 1


def test_unknown_run_and_bad_id_write_nothing(plugin, _hermes_home):
    _run(plugin)
    assert "no evidence record" in plugin._handle_value_command("0" * 32 + " baseline_minutes=5")
    assert plugin._handle_value_command("not-an-id baseline_minutes=5").startswith("usage:")
    assert len(_stored(_hermes_home)) == 1


def test_command_registered_through_real_discovery(_hermes_home):
    import hermes_yaml as yaml
    (_hermes_home / "config.yaml").write_text(yaml.safe_dump({"plugins": {"enabled": ["venus-evidence"]}}))
    from hermes_cli import plugins as pmod
    mgr = pmod.PluginManager()
    mgr.discover_and_load()
    assert "venus-value" in mgr._plugin_commands
    assert mgr._plugin_commands["venus-value"]["handler"]("").startswith("usage:")
