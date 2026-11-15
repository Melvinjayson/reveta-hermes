"""Aura only offers the model tools its free-only gate can run (live: desktop_preview was offered,
then refused with "This would cost money"). Outside Aura nothing changes. Config fixtures only."""

import json

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tools.aura_free_only import advertised_tool


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    token = set_hermes_home_override(str(tmp_path))

    def write(config):
        (tmp_path / "config.yaml").write_text(json.dumps(config))

    try:
        yield write
    finally:
        reset_hermes_home_override(token)


def test_aura_hides_tools_the_free_only_gate_always_refuses(home):
    home({"aura": {"enabled": True, "free_only": True, "free_tools": []}})
    for owned in ("aura_browser", "aura_file", "aura_computer", "todo_list"):
        assert advertised_tool(owned)
    for refused in ("desktop_preview", "manage_catalog", "desktop_project", "terminal", "tool_call"):
        assert not advertised_tool(refused)


def test_attested_free_tool_stays_offered(home):
    home({"aura": {"enabled": True, "free_only": True, "free_tools": [
        {"name": "focus_pane", "arguments_sha256": "x", "confirmed_free": True, "cost_usd": 0}]}})
    assert advertised_tool("focus_pane")


def test_outside_aura_every_tool_is_offered(home):
    home({})
    assert advertised_tool("desktop_preview") and advertised_tool("terminal")
    home({"aura": {"enabled": False}})
    assert advertised_tool("desktop_preview")


def test_model_tool_definitions_apply_the_filter(home):
    import model_tools

    home({"aura": {"enabled": True, "free_only": True, "free_tools": []}})
    names = {t["function"]["name"] for t in model_tools._compute_tool_definitions(
        ["aura", "todo", "desktop_ui", "catalog", "project"], quiet_mode=True, skip_tool_search_assembly=True)}
    assert "todo_list" in names
    assert not names & {"desktop_preview", "manage_catalog", "desktop_project", "set_theme"}


def test_aura_prompt_keeps_exploration_in_conversation_and_ignores_its_own_echo():
    from scripts.reveta.aura_config import AURA_SYSTEM_PROMPT as prompt

    assert "thinking aloud" in prompt and "run no tools for it" in prompt
    assert "drop the old reading completely" in prompt
    assert "done now with your tools, without asking first" in prompt
    assert "approval cards still cover consequential actions" in prompt
    assert "repeats or paraphrases your own recent reply is not a request" in prompt
    assert "status of work only when asked" in prompt
    assert "Never state how the user feels as fact" in prompt
