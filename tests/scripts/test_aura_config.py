"""Provider selection is explicit, free-first, and never persists key values."""

import json

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
