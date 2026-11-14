"""Played prefixes share chat storage and freeze before the next model reads history."""
import pytest

from hermes_state import SessionDB
from hermes_state_voice import bind_voice_turn, claim_voice_turn, record_played, voice_row


@pytest.fixture
def voice_db(tmp_path):
    with SessionDB(db_path=tmp_path / 'state.db') as db:
        db.create_session('chat', 'cli')
        bind_voice_turn(db, 'a' * 32, 'chat', 'human')
        yield db


def heard(db, text, interrupted=False, principal='human'):
    return record_played(db, principal=principal, session_id='chat', turn_id='a' * 32,
                         message_index=0, text=text, interrupted=interrupted)


def test_barge_in_keeps_only_acknowledged_prefix_and_tool_result(voice_db):
    row = {'role': 'assistant', 'content': 'Heard. Never played.', 'tool_calls': [
        {'id': 'one', 'type': 'function', 'function': {'name': 'test', 'arguments': '{}'}}]}
    voice_row(voice_db, 'a' * 32, 0, row)
    assert row['content'] == ''
    voice_db.append_messages_batch('chat', [row, {'role': 'tool', 'tool_call_id': 'one', 'content': 'real result'}])
    heard(voice_db, 'Heard.')
    heard(voice_db, 'Heard.', True)
    assert heard(voice_db, 'Heard. Never played.') == {'text': 'Heard.', 'interrupted': True}
    rows = voice_db.get_messages('chat')
    assert rows[0]['content'] == 'Heard.'
    assert rows[0]['display_metadata']['interrupted'] is True
    assert rows[1]['content'] == 'real result'


def test_ack_before_initial_flush_is_not_lost_including_managed_projection(voice_db):
    heard(voice_db, 'Already played.')
    row = {'role': 'assistant', 'content': 'Generated.'}
    voice_row(None, 'a' * 32, 0, row)
    assert row['content'] == ''
    voice_db.append_messages_batch('chat', [row])
    assert voice_db.get_messages('chat')[0]['content'] == 'Already played.'


def test_replayed_receipts_are_idempotent_and_cannot_rewrite_or_cross_auth(voice_db):
    assert heard(voice_db, 'Hello.') == heard(voice_db, 'Hello.')
    with pytest.raises(ValueError):
        heard(voice_db, 'Changed words.')
    with pytest.raises(ValueError):
        heard(voice_db, 'Hello.', principal='somebody-else')
    with pytest.raises(ValueError):
        bind_voice_turn(voice_db, 'a' * 32, 'other-chat', 'human')


def test_next_turn_freezes_previous_cache_prefix(voice_db):
    voice_db._execute_write(lambda conn: claim_voice_turn(conn, 'chat', 'a' * 32))
    heard(voice_db, 'Heard.')
    voice_db._execute_write(lambda conn: claim_voice_turn(conn, 'chat', None))
    assert heard(voice_db, 'Heard. Too late.')['text'] == 'Heard.'


def test_terminal_result_never_retains_unflushed_unheard_copy(voice_db):
    import json
    from hermes_state_voice import compact_voice_result
    payload = json.dumps({'text': 'request', 'surface_v1': {'voice_recording_id': 'a' * 32}})
    raw = {'result': {'final_response': 'Never heard.', 'current_turn_user_idx': 0, 'messages': [
        {'role': 'user', 'content': 'request'}, {'role': 'assistant', 'content': 'Never heard.'}]}}
    with voice_db._read_ctx() as conn:
        stored = compact_voice_result(conn, payload, raw)
    assert stored['result']['final_response'] == ''
    assert stored['result']['messages'][0]['content'] == ''
    assert raw['result']['messages'][-1]['content'] == 'Never heard.'  # no live-stream mutation
