"""Project only playback acknowledgements into a spoken turn's persisted rows."""
from hermes_state_voice import voice_row


def project_voice_rows(agent, messages, start, batch_messages, rows):
    turn_id = getattr(agent, "_voice_turn_recording_id", None)
    if not isinstance(turn_id, str) or not turn_id or type(start) is not int:
        return
    from agent.message_content import flatten_message_text
    spoken = [m for m in messages[start:] if isinstance(m, dict) and m.get("role") == "assistant"
              and flatten_message_text(m.get("content")).strip()]
    from agent.runtime_session_store import RuntimeSessionStore
    store = None if isinstance(agent._session_db, RuntimeSessionStore) else agent._session_db
    positions = {id(message): index for index, message in enumerate(spoken)}
    for message, row in zip(batch_messages, rows):
        if message.get("role") == "user":
            row["display_metadata"] = {**(row.get("display_metadata") or {}), "voice_turn_id": turn_id}
        if id(message) in positions:
            voice_row(store, turn_id, positions[id(message)], row)
            message["display_metadata"] = row["display_metadata"]

