"""Voice finals use ordinary durable admission; interruption withdraws stale approvals."""
import asyncio
from unittest.mock import patch

import pytest

from gateway.session_surface import admit_surface, surface_note, surface_turn_scope, arm_surface_turn
from hermes_state_runtime import list_session_admissions
from tests.gateway.test_prompt_queued_controls import _call, _connection
from tests.gateway.test_session_authority_cancel_settlement import _authority, REF


@pytest.mark.asyncio
async def test_reconnected_final_uses_one_existing_chat_admission(tmp_path, monkeypatch):
    db, authority = _authority(tmp_path, monkeypatch)
    monkeypatch.setattr(authority, '_schedule', lambda ref: None)
    connection = _connection(authority)
    params = dict(text='changed request', submission_id='a' * 32, voice_recording_id='a' * 32)
    with db:
        first = await _call(connection, 'prompt.submit', **params)
        second = await _call(connection, 'prompt.submit', **params)
        assert 'error' not in first, first
        assert 'error' not in second, second
        assert len(list_session_admissions(db, session_id='s', pending_only=False)) == 1
        receipt = await _call(connection, 'session.voice.record', turn_id='a' * 32,
                              message_index=0, text='Heard.', interrupted=True)
        assert receipt['result'] == {'text': 'Heard.', 'interrupted': True}


def test_voice_recording_does_not_change_model_route_or_add_model_context():
    from types import SimpleNamespace
    committed = admit_surface({'voice_recording_id': 'a' * 32})['surface_v1']
    assert surface_note(committed) == ''
    agent = SimpleNamespace()
    with surface_turn_scope(committed):
        arm_surface_turn(agent)
    assert agent._voice_turn_pending is False  # no auxiliary.voice_chat model
    assert agent._voice_turn_recording_id == 'a' * 32
    with surface_turn_scope(None):
        arm_surface_turn(agent)
    assert agent._voice_turn_recording_id is None


@pytest.mark.asyncio
async def test_changed_voice_request_withdraws_old_approval(tmp_path, monkeypatch):
    from gateway.session_server_requests import _ask, resolve
    db, authority = _authority(tmp_path, monkeypatch)
    events = authority.sessions['s'].event_stream
    announced, received = asyncio.Event(), []
    loop = asyncio.get_running_loop()

    class Transport:
        def write(self, frame):
            received.append(frame)
            loop.call_soon_threadsafe(announced.set)
            return True
    transport = Transport()
    events.fanout.attach(transport)
    asking = asyncio.create_task(asyncio.to_thread(_ask, events, 's', 'approval', {'command': 'old words'},
                                                   cancelled=lambda: False, timeout=5))
    with db:
        await asyncio.wait_for(announced.wait(), 5)
        with patch('gateway.session_server_requests.withdraw', wraps=__import__(
                'gateway.session_server_requests', fromlist=['withdraw']).withdraw) as withdraw:
            generation = authority._handle(REF).execution_generation
            connection = _connection(authority)
            response = await _call(connection, 'session.interrupt', execution_generation=generation,
                                   preserve_running_tools=True)
            assert 'error' not in response, response
            withdraw.assert_called_once_with(events, 's', 'approval')
        await asyncio.wait_for(asking, 5)
        assert not resolve({'id': received[0]['id'], 'result': {'approved': True}})
