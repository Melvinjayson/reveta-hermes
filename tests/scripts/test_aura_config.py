"""Provider selection is explicit, free-first, and never persists key values."""

import json
import pytest

from scripts.reveta.aura_config import aura_settings


def test_gemini_precedes_router_and_is_exactly_allowlisted_without_copying_keys():
    config = aura_settings(
        {
            "OPENROUTER_API_KEY": "synthetic-router-key",
            "GEMINI_API_KEY": "synthetic-google-key",
        }
    )
    route = config["model"]
    entry, = config["aura"]["free_models"]
    assert route["provider"] == entry["provider"] == "gemini"
    assert route["default"] == entry["model"]
    assert route['default'] == 'gemini-3.8-flash'
    assert route["base_url"] == entry["base_url"]
    assert entry["cost_usd"] == 0 and entry["confirmed_free"] is True
    assert config["fallback_model"] == []
    assert "synthetic" not in json.dumps(config)
    assert config["approvals"]["mode"] == "manual"
    from hermes_cli.tools_config import _get_platform_tools
    for platform in ('cli', 'api_server'):
        assert 'aura' in _get_platform_tools(config, platform)


def test_gemini_only_and_no_key_are_explicit_and_anthropic_stays_disabled():
    assert (
        aura_settings({"GEMINI_API_KEY": "synthetic"})["model"]["provider"] == "gemini"
    )
    config = aura_settings({"ANTHROPIC_API_KEY": "synthetic-unused"})
    assert config["model"]["default"] == "aura-not-connected"
    assert config["fallback_model"] == []
    assert config["aura"]["anthropic"]["per_chat_usd"] == 0
    assert config["aura"]["anthropic"]["per_day_usd"] == 0


def test_google_alias_and_router_key_alone_cannot_select_an_automatic_route():
    assert aura_settings({"GOOGLE_API_KEY": "synthetic"})["model"]["provider"] == "gemini"
    assert aura_settings({"OPENROUTER_API_KEY": "synthetic"})["aura"]["free_models"] == []


def test_composio_mcp_only_with_key_and_key_value_never_serialized():
    assert 'mcp_servers' not in aura_settings({})
    assert aura_settings({})['platform_toolsets']['api_server'] == ['aura', 'todo']
    config = aura_settings({'COMPOSIO_API_KEY': 'ck_synthetic-consumer-key'})
    server = config['mcp_servers']['composio']
    assert server['url'] == 'https://connect.composio.dev/mcp'
    assert server['headers'] == {'x-consumer-api-key': '${COMPOSIO_API_KEY}'}
    assert set(server['tools']['exclude']) == {'COMPOSIO_REMOTE_WORKBENCH', 'COMPOSIO_REMOTE_BASH_TOOL'}
    assert 'synthetic' not in json.dumps(config)
    from hermes_cli.tools_config import _get_platform_tools
    for platform in ('cli', 'api_server'):
        assert config['platform_toolsets'][platform] == ['aura', 'todo', 'composio']
        assert 'composio' in _get_platform_tools(config, platform)


def test_browser_proxy_config_never_serializes_proxy_credentials():
    browser = aura_settings({'HTTPS_PROXY': 'http://proxy.example:8080'})['browser']
    assert browser['chromium_args'] == ['--proxy-server=http://proxy.example:8080']
    config = aura_settings({'HTTPS_PROXY': 'http://synthetic-user:synthetic-password@proxy.example:8080'})
    assert 'synthetic' not in json.dumps(config)


def test_override_only_attests_an_owner_confirmed_exact_free_model():
    env = {'GEMINI_API_KEY': 'synthetic', 'AURA_GEMINI_MODEL': 'gemini-3.9-flash'}
    assert aura_settings(env)['aura']['free_models'] == []
    config = aura_settings({**env, 'AURA_GEMINI_MODEL_CONFIRMED_FREE': 'true'})
    entry, = config['aura']['free_models']
    assert entry['model'] == config['model']['default'] == env['AURA_GEMINI_MODEL']
    assert entry['confirmed_free'] is True and entry['cost_usd'] == 0
    assert config['fallback_model'] == [] and config['aura']['free_only'] is False
    with pytest.raises(ValueError, match='exact Gemini model ID'):
        aura_settings({**env, 'AURA_GEMINI_MODEL': 'gemini-flash-latest'})


def test_write_creates_configured_workspace_in_fresh_home(tmp_path, monkeypatch, capsys):
    import sys

    from ruamel.yaml import YAML
    from scripts.reveta import aura_config

    home = tmp_path / 'fresh-home'
    config_path = home / 'config.yaml'
    workspace = home / 'aura-workspace'
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setattr(sys, 'argv', ['aura_config.py'])
    assert aura_config.main() == 0
    capsys.readouterr()
    assert not home.exists()

    monkeypatch.setattr(sys, 'argv', ['aura_config.py', '--write', str(config_path)])
    assert aura_config.main() == 0
    config = YAML().load(config_path.read_text(encoding='utf-8-sig'))
    assert config['terminal']['cwd'] == str(workspace)
    assert workspace.is_dir()

    brief = workspace / 'brief.md'
    brief.write_text('# Existing brief', encoding='utf-8')
    assert aura_config.main() == 0
    assert brief.read_text(encoding='utf-8-sig') == '# Existing brief'
    assert (home / 'SOUL.md').read_text(encoding='utf-8') == aura_config.AURA_SOUL


def test_soul_replaces_stock_hermes_identity_but_keeps_an_owner_soul(tmp_path):
    from hermes_cli.default_soul import DEFAULT_SOUL_MD
    from scripts.reveta.aura_config import AURA_SOUL, write_soul

    soul = tmp_path / 'SOUL.md'
    soul.write_text(DEFAULT_SOUL_MD, encoding='utf-8')  # what the image seeds on first boot
    assert write_soul(tmp_path) is True
    assert soul.read_text(encoding='utf-8') == AURA_SOUL
    assert write_soul(tmp_path) is True  # idempotent on every boot
    soul.write_text('You are Melvin\'s custom operator.', encoding='utf-8')
    assert write_soul(tmp_path) is False
    assert soul.read_text(encoding='utf-8') == 'You are Melvin\'s custom operator.'


def test_fresh_conversation_prompt_is_aura_with_reveta_context(tmp_path, monkeypatch):
    """Build the real system prompt for a brand-new agent the way a fresh chat does."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from agent import prompt_builder
    from agent.system_prompt import build_system_prompt
    from hermes_cli.default_soul import DEFAULT_SOUL_MD
    from scripts.reveta.aura_config import AURA_SYSTEM_PROMPT, write_soul

    home = tmp_path / 'data'
    home.mkdir()
    (home / 'SOUL.md').write_text(DEFAULT_SOUL_MD, encoding='utf-8')
    write_soul(home)
    monkeypatch.setenv('HERMES_HOME', str(home))
    prompt_builder.clear_skills_system_prompt_cache(clear_snapshot=False)
    agent = SimpleNamespace(
        load_soul_identity=True, skip_context_files=True, valid_tool_names=[], _task_completion_guidance=False,
        _tool_use_enforcement=False, _environment_probe=False, _kanban_worker_guidance='', _memory_store=None,
        _memory_manager=None, model='gemini-3.8-flash', provider='gemini', platform='', pass_session_id=False,
        session_id='', _session_db=SimpleNamespace(db_path=home / 'state.db'))
    with patch('agent.prompt_builder.build_environment_hints', return_value=''):
        prompt = build_system_prompt(agent, system_message=AURA_SYSTEM_PROMPT)

    assert prompt.startswith('You are Aura, the voice-first operator in Reveta')
    assert 'You are Hermes Agent' not in prompt
    for context in ('Reveta OS', 'Xhunt', 'Venus', 'founders'):
        assert context in prompt
    assert "Proposed goal: <one sentence outcome>" in prompt
    assert 'paid service' in prompt and 'Never show the user server paths' in prompt


def test_aura_skips_the_python_toolchain_probe_that_delays_the_first_turn():
    """Live: ~13 s before the first model call of a new chat. The probe's pip/python subprocesses
    take ~9 s even on an 8-core VM, and the first prompt build waits up to 10 s for them."""
    from scripts.reveta.aura_config import aura_settings

    assert aura_settings({'HERMES_HOME': '/tmp/aura'})['agent']['environment_probe'] is False
