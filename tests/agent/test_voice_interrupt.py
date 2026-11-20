"""Voice barge-in owns generation, while a started tool owns its real result."""
import threading
from unittest.mock import patch

import pytest

from agent.interrupt_compat import request_voice_interrupt
from tests.agent import test_run_agent as _base
from tests.agent.test_run_agent import _mock_assistant_msg, _mock_tool_call

agent = _base.agent
_mock_plugin_discovery = _base._mock_plugin_discovery


@pytest.fixture(autouse=True)
def isolated_voice_home(tmp_path, monkeypatch):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    token = set_hermes_home_override(str(tmp_path))
    try:
        yield
    finally:
        reset_hermes_home_override(token)


@pytest.mark.parametrize("concurrent", [False, True])
def test_voice_interrupt_keeps_started_tool_result_once(agent, concurrent):
    started, release = threading.Event(), threading.Event()
    observed = []
    errors = []
    messages = []

    def tool(*args, **kwargs):
        from tools.interrupt import is_interrupted
        started.set()
        assert release.wait(5)
        observed.append(is_interrupted())
        return '{"success": true, "output": "actual tool result"}'

    call = _mock_tool_call(name="web_search", arguments='{"q":"synthetic"}', call_id="voice-tool")
    response = _mock_assistant_msg(content="", tool_calls=[call])
    run = agent._execute_tool_calls_concurrent if concurrent else agent._execute_tool_calls_sequential

    def execute():
        try:
            run(response, messages, "voice-task")
        except BaseException as exc:
            errors.append(exc)

    with patch("model_tools.handle_function_call", side_effect=tool) as dispatch:
        thread = threading.Thread(target=execute)
        thread.start()
        try:
            assert started.wait(5)
            assert request_voice_interrupt(agent)
            assert agent._interrupt_requested
        finally:
            release.set()
            thread.join(5)
        assert not thread.is_alive()
        assert not errors
        assert dispatch.call_count == 1
    assert observed == [False]
    results = [message for message in messages if message.get("tool_call_id") == "voice-tool"]
    assert len(results) == 1
    assert "actual tool result" in results[0]["content"]


def test_voice_never_falls_back_to_a_legacy_hard_stop():
    calls = []

    class Legacy:
        def interrupt(self):
            calls.append("interrupted tool")

    assert request_voice_interrupt(Legacy()) is False
    assert calls == []


def test_voice_does_not_interrupt_active_children(agent):
    calls = []

    class Child:
        def interrupt(self, *args, **kwargs):
            calls.append("child tool cancelled")

    agent._active_children = [Child()]
    with patch("agent.interrupt_control._set_interrupt") as signal:
        assert request_voice_interrupt(agent)
    assert calls == []
    signal.assert_not_called()
    agent.clear_interrupt()
    assert agent._preserve_running_tools_on_interrupt is False
