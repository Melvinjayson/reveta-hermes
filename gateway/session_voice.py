"""Playback receipts for an admitted turn; the chat authority remains the sole writer."""
from hermes_state_runtime import RuntimeStoreError
from hermes_state_voice import record_played


async def record(connection, ref, params):
    authority, actor = connection.authority, connection.actor
    authority.authorize(actor, ref, 'session:control')
    if set(params) - {'session_id', 'turn_id', 'message_index', 'text', 'interrupted'}:
        raise RuntimeStoreError('invalid_params')
    try:
        heard = record_played(authority.db, principal=actor.subject, session_id=ref.session_id,
                              turn_id=params['turn_id'], message_index=params['message_index'],
                              text=params['text'], interrupted=params.get('interrupted', False))
    except (ValueError, KeyError) as exc:
        raise RuntimeStoreError('invalid_params') from exc
    live = authority.sessions.get(ref.session_id)
    if live:
        live.event_stream.publish(ref.session_id, {**heard, 'turn_id': params['turn_id'],
            'message_index': params['message_index']}, event_type='message.voice_played')
    return heard
