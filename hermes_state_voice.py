"""Played-only text in the existing SessionDB, scoped to one admitted voice turn.

The ordinary admission still owns auth, model routing, spend and tools. These
receipts only project acknowledged speech into that turn's assistant rows.
"""
from __future__ import annotations

import json
import re

PREFIX = "aura.voice.played.v1."
ACTIVE = "aura.voice.active.v1."


def validate_turn_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Invalid voice turn identity")
    return value


def _read(conn, turn_id):
    row = conn.execute("SELECT value FROM state_meta WHERE key=?", (PREFIX + turn_id,)).fetchone()
    return json.loads(row[0]) if row else None


def _put(conn, turn_id, value):
    conn.execute("INSERT INTO state_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (PREFIX + turn_id, json.dumps(value, ensure_ascii=True)))


def bind_voice_turn(db, turn_id, session_id, principal):
    validate_turn_id(turn_id)

    def write(conn):
        old = _read(conn, turn_id)
        if old and (old["session_id"], old["principal"]) != (session_id, principal):
            raise ValueError("Voice turn belongs to another conversation")
        if not old:
            _put(conn, turn_id, {"session_id": session_id, "principal": principal, "frozen": False, "messages": {}})
    db._execute_write(write)


def claim_voice_turn(conn, session_id, voice_turn_id):
    """Freeze the previous prefix before a new claim reads it into model context."""
    row = conn.execute("SELECT value FROM state_meta WHERE key=?", (ACTIVE + session_id,)).fetchone()
    previous = row[0] if row else None
    if previous and previous != voice_turn_id:
        old = _read(conn, previous)
        if old:
            old["frozen"] = True
            _put(conn, previous, old)
    if voice_turn_id:
        conn.execute("INSERT INTO state_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (ACTIVE + session_id, voice_turn_id))
    else:
        conn.execute("DELETE FROM state_meta WHERE key=?", (ACTIVE + session_id,))


def voice_row(db, turn_id, message_index, row):
    """Never write generated-but-unplayed text, including the first crash-safe flush."""
    receipt = None
    if db is not None:
        with db._read_ctx() as conn:
            receipt = _read(conn, turn_id)
    played = (receipt or {}).get("messages", {}).get(str(message_index), {})
    row["display_metadata"] = {**(row.get("display_metadata") or {}), "voice_turn_id": turn_id,
                               "voice_message_index": message_index,
                               "interrupted": bool(played.get("interrupted"))}
    row["content"] = played.get("text", "")
    row["api_content"] = None


def _sync_rows(conn, session_id, turn_id, receipt):
    rows = conn.execute("SELECT id,display_metadata FROM messages WHERE session_id=? AND role='assistant' "
                        "AND active=1 AND json_extract(display_metadata,'$.voice_turn_id')=? "
                        "AND json_type(display_metadata,'$.voice_message_index')='integer'",
                        (session_id, turn_id)).fetchall()
    for row_id, metadata in rows:
        metadata = json.loads(metadata)
        heard = receipt["messages"].get(str(metadata["voice_message_index"]), {})
        metadata["interrupted"] = bool(heard.get("interrupted"))
        conn.execute("UPDATE messages SET content=?,api_content=NULL,display_metadata=? WHERE id=? AND session_id=?",
                     (heard.get("text", ""), json.dumps(metadata), row_id, session_id))


def record_played(db, *, principal, session_id, turn_id, message_index, text, interrupted):
    validate_turn_id(turn_id)
    if type(message_index) is not int or not 0 <= message_index < 1000 or not isinstance(text, str) or len(text) > 64000:
        raise ValueError("Invalid played-text receipt")

    def write(conn):
        receipt = _read(conn, turn_id)
        if not receipt or (receipt["session_id"], receipt["principal"]) != (session_id, principal):
            raise ValueError("Voice turn is not owned by this caller")
        key = str(message_index)
        old = receipt["messages"].get(key, {"text": "", "interrupted": False})
        if receipt["frozen"] or old["interrupted"]:
            if interrupted and not old["interrupted"]:
                old = {**old, "interrupted": True}
                receipt["messages"][key] = old
                _put(conn, turn_id, receipt)
                _sync_rows(conn, session_id, turn_id, receipt)
            return old
        if not text.startswith(old["text"]):
            raise ValueError("Played-text receipts must extend the acknowledged prefix")
        heard = {"text": text, "interrupted": bool(interrupted)}
        receipt["messages"][key] = heard
        if interrupted:
            receipt["frozen"] = True
        _put(conn, turn_id, receipt)
        _sync_rows(conn, session_id, turn_id, receipt)
        return heard
    return db._execute_write(write)



def sync_appended_voice_rows(conn, session_id, messages):
    for turn_id in {m.get("display_metadata", {}).get("voice_turn_id") for m in messages
                    if isinstance(m.get("display_metadata"), dict)} - {None}:
        receipt = _read(conn, turn_id)
        if receipt and receipt["session_id"] == session_id:
            _sync_rows(conn, session_id, turn_id, receipt)


def compact_voice_result(conn, payload_json, result):
    """Stored terminal receipts must not retain an unheard response copy."""
    turn_id = (json.loads(payload_json).get('surface_v1') or {}).get('voice_recording_id')
    if not turn_id:
        return result
    from hermes_state_terminal import compact_result
    from agent.message_content import flatten_message_text
    result = compact_result(result, user_message=json.loads(payload_json).get('text'))
    if not isinstance(result.get('result'), dict):
        return result
    value = dict(result['result'])
    receipt = _read(conn, turn_id) or {'messages': {}}
    messages = []
    index = 0
    for message in value.get('messages') or []:
        if message.get('role') == 'assistant' and flatten_message_text(message.get('content')).strip():
            heard = receipt['messages'].get(str(index), {})
            message = {**message, 'content': heard.get('text', ''), 'api_content': None}
            index += 1
        messages.append(message)
    value['messages'] = messages
    value['final_response'] = ''  # The live chat stream delivered it; history owns played text.
    return {**result, 'result': value}
