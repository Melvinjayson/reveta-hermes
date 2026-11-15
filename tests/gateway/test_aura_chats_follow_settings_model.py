"""Aura regression: a chat kept the model it started with after the owner picked another one in
Aura Settings (live: an old chat stayed on free Gemini while Settings said Anthropic Haiku, and
hung for minutes on Google's spent daily quota). With ``aura.enabled`` every chat, old or new,
runs the profile's current model; its history is untouched. Without Aura, chats stay frozen.

Real: SessionStore/SessionAuthority, ``stage_local_session``, ``session.resume`` (the refresh on
open) and ``_resolve_session_agent_runtime`` through the shared follow-profile fixtures.
"""
import json

import pytest

from tests.gateway.test_bot_chat_follows_profile import _frozen_bot_chat, _open, home  # noqa: F401
from tests.gateway.test_session_follow_profile_config import _owner, _route

_AURA = {'aura': {'enabled': True}}


def _profile(home, model, port, key, aura=True):
    (home / 'config.yaml').write_text(json.dumps({'model': {
        'provider': 'custom', 'base_url': f'http://127.0.0.1:{port}/v1', 'default': model, 'api_key': key},
        **(_AURA if aura else {})}))


def _history(authority, session_id):
    return [(m['role'], m['content']) for m in authority.db.get_messages(session_id)]


@pytest.mark.asyncio
async def test_new_aura_chat_follows_the_settings_model(home):  # noqa: F811
    _profile(home, 'gemini-model', 1, 'gemini-key')
    store, runner, authority, owner = _owner(home)
    runner._peek_session_state = lambda key: None
    try:
        ref, _ = _frozen_bot_chat(authority, owner.actor, home, title='Plan my launch')
        live = authority.sessions[ref.session_id]
        assert _route(runner, live) == ('gemini-model', 'http://127.0.0.1:1/v1', 'gemini-key')
        _profile(home, 'haiku-model', 2, 'haiku-key')
        assert _route(runner, live) == ('haiku-model', 'http://127.0.0.1:2/v1', 'haiku-key')
    finally:
        await owner.close()
        store.close_all_db_handles()


@pytest.mark.asyncio
async def test_existing_aura_chat_moves_to_the_settings_model_on_open_and_keeps_history(home):  # noqa: F811
    # An earlier build froze this chat on Gemini (created before aura.enabled marked new chats).
    _profile(home, 'gemini-model', 1, 'gemini-key', aura=False)
    store, runner, authority, owner = _owner(home)
    runner._peek_session_state = lambda key: None
    try:
        ref, _ = _frozen_bot_chat(authority, owner.actor, home, title='Old chat')
        live = authority.sessions[ref.session_id]
        authority.db.append_message(ref.session_id, 'user', 'hello')
        authority.db.append_message(ref.session_id, 'assistant', 'Hi, I am Aura.')
        before = _history(authority, ref.session_id)
        _profile(home, 'haiku-model', 2, 'haiku-key')
        assert _route(runner, live)[0] == 'gemini-model'  # still frozen until a client opens it
        await _open(authority, ref)
        assert _route(runner, live) == ('haiku-model', 'http://127.0.0.1:2/v1', 'haiku-key')
        assert _history(authority, ref.session_id) == before == [('user', 'hello'), ('assistant', 'Hi, I am Aura.')]
    finally:
        await owner.close()
        store.close_all_db_handles()


@pytest.mark.asyncio
async def test_without_aura_an_ordinary_chat_keeps_its_model(home):  # noqa: F811
    _profile(home, 'old-model', 1, 'old-key', aura=False)
    store, runner, authority, owner = _owner(home)
    runner._peek_session_state = lambda key: None
    try:
        ref, _ = _frozen_bot_chat(authority, owner.actor, home, title='Notes')
        live = authority.sessions[ref.session_id]
        _profile(home, 'new-model', 2, 'new-key', aura=False)
        await _open(authority, ref)
        assert _route(runner, live)[0] == 'old-model'
    finally:
        await owner.close()
        store.close_all_db_handles()


@pytest.mark.asyncio
async def test_an_explicit_frozen_choice_stays_frozen_under_aura(home):  # noqa: F811
    _profile(home, 'old-model', 1, 'old-key')
    store, runner, authority, owner = _owner(home)
    runner._peek_session_state = lambda key: None
    try:
        ref, _ = _frozen_bot_chat(authority, owner.actor, home, title='Pinned', follow_profile_config=False)
        live = authority.sessions[ref.session_id]
        _profile(home, 'new-model', 2, 'new-key')
        await _open(authority, ref)
        assert _route(runner, live)[0] == 'old-model'
    finally:
        await owner.close()
        store.close_all_db_handles()
