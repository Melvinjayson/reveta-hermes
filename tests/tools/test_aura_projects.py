"""Aura Projects: projects persist in the profile's projects.db with conversation membership.
Real sqlite under a temporary HERMES_HOME; no network."""

import sqlite3

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tools import aura_projects


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    token = set_hermes_home_override(str(tmp_path))
    try:
        yield tmp_path
    finally:
        reset_hermes_home_override(token)


def _project(payload, name):
    return next(p for p in payload["projects"] if p["name"] == name)


def test_projects_persist_in_projects_db_and_desktop_sees_them(home):
    aura_projects.create("  Launch   plan ", "Ship the pricing page")
    reopened = aura_projects.list_all()
    project = _project(reopened, "Launch plan")
    assert project["description"] == "Ship the pricing page" and project["session_ids"] == []

    from hermes_cli.projects_db import connect, list_projects

    conn = connect(home / "projects.db")
    assert [p.name for p in list_projects(conn)] == ["Launch plan"]
    conn.close()


def test_a_conversation_belongs_to_one_project_and_can_leave(home):
    a = _project(aura_projects.create("A"), "A")["id"]
    b = _project(aura_projects.create("B"), "B")["id"]

    aura_projects.assign("chat-1", a)
    moved = aura_projects.assign("chat-1", b)
    assert _project(moved, "A")["session_ids"] == [] and _project(moved, "B")["session_ids"] == ["chat-1"]

    out = aura_projects.assign("chat-1", None)
    assert all(not p["session_ids"] for p in out["projects"])
    with pytest.raises(LookupError):
        aura_projects.assign("chat-1", "p_missing")


def test_rename_clear_description_and_delete_keep_conversations(home):
    pid = _project(aura_projects.create("Old", "note"), "Old")["id"]
    aura_projects.assign("chat-9", pid)
    renamed = aura_projects.update(pid, name="New", description="")
    assert _project(renamed, "New")["description"] == ""

    assert aura_projects.remove(pid)["projects"] == []
    conn = sqlite3.connect(home / "projects.db")
    assert conn.execute("SELECT COUNT(*) FROM aura_project_sessions").fetchone()[0] == 0
    conn.close()
    assert (home / "state.db").exists() is False  # deleting a project never touched conversation storage


def test_invalid_names_are_refused(home):
    with pytest.raises(ValueError):
        aura_projects.create("   ")
    with pytest.raises(ValueError):
        aura_projects.create("x" * 81)
    with pytest.raises(LookupError):
        aura_projects.update("p_missing", name="X")

