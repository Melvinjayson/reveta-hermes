"""Owner-unlocked Hermes toolsets in Aura: saved for new conversations, offered only when on,
and never past the dispatch approval gate. Config fixtures only; no model calls."""

import json

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tools import aura_capabilities


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    token = set_hermes_home_override(str(tmp_path))

    def write(config):
        (tmp_path / "config.yaml").write_text(json.dumps(config))

    def read():
        from hermes_cli.config import load_config

        return load_config()

    try:
        yield write, read
    finally:
        reset_hermes_home_override(token)


def _all_ready(monkeypatch, missing=()):
    monkeypatch.setattr(aura_capabilities, "_availability", lambda: {
        name: {"available": name not in missing, "requires_env": ["SOME_KEY"] if name in missing else []}
        for name in aura_capabilities.CAPABILITIES})


def test_configure_writes_both_aura_surfaces_and_keeps_mcp_servers(home, monkeypatch):
    write, read = home
    _all_ready(monkeypatch)
    write({"aura": {"enabled": True}, "platform_toolsets": {
        "cli": ["aura", "todo", "composio"], "api_server": ["aura", "todo", "composio"]}})

    result = aura_capabilities.configure(["memory", "session_search"])

    toolsets = read()["platform_toolsets"]
    assert toolsets["cli"] == ["aura", "todo", "session_search", "memory", "composio"]
    assert toolsets["api_server"] == toolsets["cli"]
    assert result["applies_to"] == "new conversations"
    assert {c["id"] for c in result["capabilities"] if c["enabled"]} == {"memory", "session_search"}

    aura_capabilities.configure([])
    assert read()["platform_toolsets"]["cli"] == ["aura", "todo", "composio"]


def test_unknown_and_key_less_capabilities_are_refused(home, monkeypatch):
    write, read = home
    _all_ready(monkeypatch, missing={"web"})
    write({"aura": {"enabled": True}, "platform_toolsets": {"cli": ["aura", "todo"]}})

    with pytest.raises(ValueError, match="Unknown capability"):
        aura_capabilities.configure(["desktop_ui"])
    with pytest.raises(ValueError, match="Not available"):
        aura_capabilities.configure(["web"])
    assert read()["platform_toolsets"]["cli"] == ["aura", "todo"]

    web = next(c for c in aura_capabilities.status()["capabilities"] if c["id"] == "web")
    assert web["available"] is False and web["blocked"] and web["enabled"] is False


def test_modes_switch_only_available_toolsets(home, monkeypatch):
    write, read = home
    _all_ready(monkeypatch, missing={"web"})
    write({"aura": {"enabled": True}, "platform_toolsets": {"cli": ["aura", "todo"]}})

    result = aura_capabilities.set_mode("Research")
    assert result["mode"] == "Research"
    assert set(read()["platform_toolsets"]["cli"]) == {"aura", "todo", "session_search", "memory", "clarify"}
    assert aura_capabilities.set_mode("Focused")["mode"] == "Focused"
    with pytest.raises(ValueError):
        aura_capabilities.set_mode("Turbo")


def test_unlocked_tools_are_offered_only_with_the_rule_off(home):
    import model_tools

    write, _ = home
    selection = ["aura", "todo", "memory", "session_search", "desktop_ui", "project"]

    write({"aura": {"enabled": True, "free_only": False, "free_tools": []}})
    names = {t["function"]["name"] for t in model_tools._compute_tool_definitions(
        selection, quiet_mode=True, skip_tool_search_assembly=True)}
    assert {"memory", "session_search"} <= names
    assert not names & {"desktop_preview", "desktop_project", "set_theme"}

    write({"aura": {"enabled": True, "free_only": True, "free_tools": []}})
    names = {t["function"]["name"] for t in model_tools._compute_tool_definitions(
        selection, quiet_mode=True, skip_tool_search_assembly=True)}
    assert not names & {"memory", "session_search"}


def test_unlocked_consequential_tools_still_need_approval(home):
    from tools.aura_dispatch_policy import _classification

    write, _ = home
    write({"aura": {"enabled": True, "free_only": False}})
    for tool in ("memory", "delegate_task", "cronjob_manage", "browser_exec", "terminal", "write_file", "skill_manage"):
        assert _classification(tool, {}, {}) == "consequential", tool
    assert _classification("session_search", {}, {}) == "read"


def test_full_browser_needs_commands_because_hermes_only_offers_it_with_terminal(home, monkeypatch):
    write, read = home
    _all_ready(monkeypatch)
    write({"aura": {"enabled": True}, "platform_toolsets": {"cli": ["aura", "todo"]}})
    with pytest.raises(ValueError, match="needs Commands"):
        aura_capabilities.configure(["browser"])
    aura_capabilities.configure(["browser", "terminal"])
    assert {"browser", "terminal"} <= set(read()["platform_toolsets"]["cli"])
    assert aura_capabilities.set_mode("Agent")["mode"] == "Agent"

