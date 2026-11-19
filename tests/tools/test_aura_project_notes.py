"""Project notes reach the model only when a NEW chat starts in that project; an existing chat's
prompt never changes. Real projects.db and the real startup-prompt composer; no model calls."""

import json
import time

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tools import aura_projects


class FakeSessionDB:
    def __init__(self, sessions):
        self.sessions = sessions

    def get_session(self, session_id):
        return self.sessions.get(session_id)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(json.dumps({"aura": {"enabled": True}}))
    token = set_hermes_home_override(str(tmp_path))
    try:
        yield tmp_path
    finally:
        reset_hermes_home_override(token)


def _project(name, notes):
    payload = aura_projects.create(name, notes)
    return next(p["id"] for p in payload["projects"] if p["name"] == name)


def _members(project_id):
    return next(p for p in aura_projects.list_all()["projects"] if p["id"] == project_id)["session_ids"]


def test_new_chat_in_a_project_gets_the_notes_once_and_is_filed(home):
    pid = _project("Launch", "Audience: founders. Tone: plain.")
    aura_projects.set_next_chat(pid)
    db = FakeSessionDB({"new-1": {"message_count": 1, "started_at": time.time()}})

    prompt = aura_projects.with_new_chat_project_context("BASE PROMPT", "new-1", db)

    assert prompt.startswith("BASE PROMPT")
    assert "Audience: founders. Tone: plain." in prompt and "Launch" in prompt
    assert _members(pid) == ["new-1"]
    # The choice is consumed: the next new chat outside the project gets nothing.
    db.sessions["new-2"] = {"message_count": 0, "started_at": time.time()}
    assert aura_projects.with_new_chat_project_context("BASE PROMPT", "new-2", db) == "BASE PROMPT"


def test_existing_chat_prompt_is_unchanged_even_when_notes_change(home):
    pid = _project("Launch", "First notes.")
    old = {"message_count": 12, "started_at": time.time() - 3600}
    db = FakeSessionDB({"old-chat": old})
    aura_projects.assign("old-chat", pid)

    aura_projects.set_next_chat(pid)
    aura_projects.update(pid, description="Edited notes.")
    assert aura_projects.with_new_chat_project_context("BASE PROMPT", "old-chat", db) == "BASE PROMPT"
    # An existing chat never consumes the pending choice either.
    db.sessions["fresh"] = {"message_count": 1, "started_at": time.time()}
    assert "Edited notes." in aura_projects.with_new_chat_project_context("BASE PROMPT", "fresh", db)


def test_stale_choice_and_missing_project_change_nothing(home, monkeypatch):
    pid = _project("Launch", "Notes.")
    aura_projects.set_next_chat(pid)
    monkeypatch.setattr(aura_projects, "NEXT_CHAT_TTL_S", -1)
    db = FakeSessionDB({"new": {"message_count": 0, "started_at": time.time()}})
    assert aura_projects.with_new_chat_project_context("BASE", "new", db) == "BASE"
    assert _members(pid) == []
    with pytest.raises(LookupError):
        aura_projects.set_next_chat("p_missing")


def test_real_startup_prompt_composer_adds_the_notes_for_a_new_project_chat(home, monkeypatch):
    # agent_factory's functions run against tui_gateway.server's namespace (method_ctx.bind_module),
    # so that is where production reads _get_db and where the composer is called.
    from tui_gateway import server as agent_factory

    pid = _project("Launch", "Audience: founders.")
    aura_projects.set_next_chat(pid)
    db = FakeSessionDB({"new-chat": {"message_count": 1, "started_at": time.time()},
                        "old-chat": {"message_count": 8, "started_at": time.time() - 7200}})
    monkeypatch.setattr(agent_factory, "_get_db", lambda: db, raising=False)
    monkeypatch.delenv("HERMES_TUI_SKILLS", raising=False)
    cfg = {"agent": {"system_prompt": "You are Aura."}}

    before = agent_factory._startup_system_prompt(cfg, "old-chat")
    assert "Audience: founders." not in before
    fresh = agent_factory._startup_system_prompt(cfg, "new-chat")
    assert "Audience: founders." in fresh
    assert agent_factory._startup_system_prompt(cfg, "old-chat") == before
