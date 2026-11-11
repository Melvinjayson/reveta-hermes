"""Aura routes and concrete adapter contracts; no live model requests."""
import json
from types import SimpleNamespace

import httpx
import pytest

from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from tools import approval, aura_product
from tools.approval_context import set_current_session_key, reset_current_session_key
from tools.registry import registry


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    ht = set_hermes_home_override(str(tmp_path))
    st = set_current_session_key('aura-product-chat')
    cfg = {'aura': {'enabled': True, 'free_only': True}, 'terminal': {'backend': 'local'},
           'browser': {'cloud_provider': 'local'}, 'approvals': {'mode': 'manual'}}
    def write():
        (tmp_path / 'config.yaml').write_text(json.dumps(cfg))
    write()
    try:
        yield tmp_path, cfg, write
    finally:
        approval.unregister_gateway_notify('aura-product-chat')
        reset_current_session_key(st)
        reset_hermes_home_override(ht)


def dispatch(name, args):
    value = registry.dispatch(name, args)
    return json.loads(value) if isinstance(value, str) else value


def test_files_use_real_hermes_adapters_and_refuse_escapes(home):
    root, _, _ = home
    result = dispatch('aura_file', {'name': 'brief.md', 'action': 'write', 'content': '# Brief\n\n[Source](https://example.com)'})
    path = aura_product.file_path('brief.md')
    assert result['success'] and result['file']['path'] == str(path)
    assert path.read_text().startswith('# Brief')
    assert path.is_relative_to(root / 'aura-workspace')
    read = dispatch('aura_file', {'name': 'brief.md', 'action': 'read'})
    assert '# Brief' in json.dumps(read)
    refused = dispatch('aura_file', {'name': '../outside', 'action': 'write', 'content': 'no'})
    assert refused.get('error') and not (root / 'outside').exists()
    # Overwrite is consequential and cannot execute without a bound approval bridge.
    refused = dispatch('aura_file', {'name': 'brief.md', 'action': 'write', 'content': 'no'})
    assert refused['status'] == 'refused' and path.read_text().startswith('# Brief')


def test_computer_uses_existing_single_use_approval(home):
    cards = []
    args = {'command': 'printf aura-test'}
    denied = dispatch('aura_computer', args)
    assert denied['status'] == 'refused'
    def approve(card):
        cards.append(card)
        approval.resolve_gateway_approval('aura-product-chat', 'once', request_id=card['request_id'])
    approval.register_gateway_notify('aura-product-chat', approve)
    result = dispatch('aura_computer', args)
    assert result['exit_code'] == 0 and 'aura-test' in result['output']
    assert len(cards) == 1 and cards[0]['single_use'] is True
    assert result['aura_display']['command'] == args['command']
    replay = approval.resolve_gateway_approval('aura-product-chat', 'once', request_id=cards[0]['request_id'])
    assert not replay


def test_gemini_native_route_and_async_sealing(home):
    from scripts.reveta.aura_config import aura_settings
    from tools.aura_free_only import require_model, seal_client, FreeOnlyRefused
    from agent.gemini_native_adapter import GeminiNativeClient, AsyncGeminiNativeClient
    root, cfg, write = home
    settings = aura_settings({'GOOGLE_API_KEY': 'synthetic'})
    cfg['aura'].update(settings['aura'])
    write()
    route = settings['model']
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': 'Native fixture reply'}]}, 'finishReason': 'STOP'}]})
    with GeminiNativeClient(api_key='synthetic', http_client=httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)) as client:
        request = require_model('gemini', client.base_url, {'model': route['default'], 'messages': [{'role': 'user', 'content': 'hello'}]})
        seal_client(AsyncGeminiNativeClient(client))
        result = client.chat.completions.create(**request)
        assert result.choices[0].message.content == 'Native fixture reply'
        assert requests[0].url.path.endswith('/models/' + route['default'] + ':generateContent')
        assert client._http.follow_redirects is False
        with pytest.raises(FreeOnlyRefused):
            require_model('gemini', client.base_url, {'model': 'unapproved'})
    assert not (root / 'aura-spend.db').exists()


def test_anthropic_is_disabled_until_caps_and_card_approve_and_accounts_usage(home, monkeypatch):
    from tools import aura_spend
    from agent import secret_scope, anthropic_adapter
    _, cfg, write = home
    calls, cards = [], []
    monkeypatch.setattr(secret_scope, 'get_secret', lambda name: 'synthetic')
    monkeypatch.setattr(anthropic_adapter, 'build_anthropic_client', lambda *a, **kw: calls.append('called'))
    args = {'task': 'Explicitly requested Anthropic planning', 'max_output_tokens': 16}
    assert dispatch('aura_complex', args).get('error') and calls == []
    cfg['aura']['anthropic'] = {'model': 'claude-sonnet-4-5', 'per_chat_usd': 0.2, 'per_day_usd': 0.2}
    write()
    assert dispatch('aura_complex', args)['status'] == 'refused' and calls == []
    class Client:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def with_options(self, **kw):
            assert kw == {'max_retries': 0}
            return self
        @property
        def messages(self): return self
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=8, output_tokens=4),
                                   content=[SimpleNamespace(type='text', text='Fixture plan')])
    monkeypatch.setattr(anthropic_adapter, 'build_anthropic_client', lambda *a, **kw: Client())
    def approve(card):
        cards.append(card)
        approval.resolve_gateway_approval('aura-product-chat', 'once', request_id=card['request_id'])
    approval.register_gateway_notify('aura-product-chat', approve)
    result = dispatch('aura_complex', args)
    assert len(calls) == len(cards) == 1 and 'Estimated maximum $' in cards[0]['description']
    assert float(result['cost_usd']) > 0 and result['input_tokens'] == 8
    with aura_spend.ledger() as db:
        assert db.execute("SELECT COUNT(*) FROM spend WHERE status='completed' AND actual > 0").fetchone()[0] == 1
    cfg['aura']['anthropic']['per_chat_usd'] = 0.000001
    write()
    assert dispatch('aura_complex', args).get('error') and len(calls) == 1
