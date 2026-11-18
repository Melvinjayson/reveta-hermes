"""Aura Settings > Memory reads the built-in notes, capped; absent notes read as empty."""

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    token = set_hermes_home_override(str(tmp_path))
    try:
        yield tmp_path
    finally:
        reset_hermes_home_override(token)


def test_memory_notes_are_read_capped_and_empty_when_absent(home):
    from hermes_cli.web_routers.aura import _MEMORY_READ_CAP, _read_memory_notes

    assert _read_memory_notes() == {"memory": {"text": "", "truncated": False}, "user": {"text": "", "truncated": False}}
    (home / "memories").mkdir()
    (home / "memories" / "MEMORY.md").write_text("Prefers short answers.", encoding="utf-8")
    (home / "memories" / "USER.md").write_text("x" * (_MEMORY_READ_CAP + 5), encoding="utf-8")
    notes = _read_memory_notes()
    assert notes["memory"] == {"text": "Prefers short answers.", "truncated": False}
    assert notes["user"]["truncated"] is True and len(notes["user"]["text"]) == _MEMORY_READ_CAP
