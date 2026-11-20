"""Aura follows the user out of the current task: topic shifts, meta feedback and corrections."""

from __future__ import annotations

import pytest

from tools import aura_conversation as conv
from tests.fakes.fake_llm_provider import FakeLLMServer, Text

AURA = {"aura": {"enabled": True}}


@pytest.mark.parametrize("text, kind", [
    ("You're not listening to me", "meta"),
    ("no, you keep giving me lists", "meta"),
    ("Stop asking me questions and just answer", "meta"),
    ("that's not what I asked", "meta"),
    ("Let's step back for a second", "meta"),
    ("Forget that. What's the capital of Peru?", "shift"),
    ("Actually, let's talk about pricing instead", "shift"),
    ("New question: how do I export the data?", "shift"),
    ("never mind, something else", "shift"),
    ("No, I meant the mobile app, not the website", "correction"),
    ("I mean the second option", "correction"),
])
def test_cues_at_the_start_of_a_message_are_recognised(text, kind):
    assert conv.classify(text) == kind


@pytest.mark.parametrize("text", [
    "Research HTTP client libraries and give me a brief",
    "Can you stop the background job that is running?",       # a request about a job, not about the chat
    "Write a post about why founders should step back from daily ops",
    "Summarise what you keep in memory about me",
    "Actually",
    "",
])
def test_ordinary_requests_and_cues_buried_in_a_request_are_not_shifts(text):
    assert conv.classify(text) is None


def test_the_topic_follows_the_user_across_turns():
    session: dict = {}
    assert conv.turn_note(session, "Research HTTP client libraries and give me a brief", AURA) == ""
    assert session[conv.TOPIC_KEY] == "Research HTTP client libraries and give me a brief"

    meta = conv.turn_note(session, "You're not listening to me", AURA)
    assert "commenting on how this conversation is going" in meta
    assert 'earlier topic was: "Research HTTP client libraries and give me a brief"' in meta
    assert "Do not resume the task" in meta
    assert session[conv.TOPIC_KEY].startswith("Research HTTP")  # paused, not replaced

    shift = conv.turn_note(session, "Forget that, help me name my company", AURA)
    assert "changing the subject" in shift and "Research HTTP" in shift
    assert session[conv.TOPIC_KEY] == "Forget that, help me name my company"

    assert conv.turn_note(session, "ok", AURA) == ""  # too short to become the topic
    assert session[conv.TOPIC_KEY] == "Forget that, help me name my company"

    long = "x " * 200
    conv.turn_note(session, long, AURA)
    assert len(session[conv.TOPIC_KEY]) == conv.TOPIC_LIMIT and "\n" not in session[conv.TOPIC_KEY]


@pytest.mark.parametrize("config", [
    {}, {"aura": {"enabled": False}}, {"aura": {"enabled": True, "conversation_notes": False}},
])
def test_no_note_outside_aura_or_when_the_owner_switches_it_off(config):
    session: dict = {conv.TOPIC_KEY: "earlier"}
    assert conv.turn_note(session, "You're not listening", config) == ""
    assert session == {conv.TOPIC_KEY: "earlier"}


def test_the_model_gets_the_note_in_this_turn_only_and_never_in_the_system_prompt(monkeypatch):
    """Fake model, real agent: the note rides on the user message through the same seam prompt_turn uses."""
    from hermes_constants import get_hermes_home
    from run_agent import AIAgent
    from tui_gateway.session_notifications import _prepend_note

    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    # The owner's live setting (15 Nov): free-only off, so the fake model may be called.
    (home / "config.yaml").write_text("aura:\n  enabled: true\n  free_only: false\n", encoding="utf-8")
    session: dict = {}
    with FakeLLMServer([Text("Here is the plan."), Text("Sorry. What would help most right now?")]) as fake:
        agent = AIAgent(model="fake-model", api_key="sk-fake", base_url=fake.base_url, provider="custom",
                        quiet_mode=True, skip_context_files=True, skip_memory=True, enabled_toolsets=["todo"])
        history = []
        for text in ("Research HTTP client libraries and give me a brief", "You're not listening to me"):
            message = _prepend_note(text, conv.turn_note(session, text, AURA))
            result = agent.run_conversation(message, conversation_history=history)
            history = result["messages"]

        first, second = fake.main_requests()
        system = [m for m in second["messages"] if m["role"] == "system"]
        users = [m for m in second["messages"] if m["role"] == "user"]
        assert first["messages"][0] == system[0]  # byte-identical system prompt: the cached prefix survives
        assert all("[Aura context]" not in str(m["content"]) for m in system)
        assert "[Aura context]" not in str(users[0]["content"])
        assert str(users[-1]["content"]).startswith("[Aura context] The user is commenting")
        assert str(users[-1]["content"]).endswith("You're not listening to me")
