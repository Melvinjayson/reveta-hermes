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
    assert config['fallback_model'] == [] and config['aura']['free_only'] is True
    with pytest.raises(ValueError, match='exact Gemini model ID'):
        aura_settings({**env, 'AURA_GEMINI_MODEL': 'gemini-flash-latest'})
