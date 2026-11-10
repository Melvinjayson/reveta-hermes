"""Provider selection is explicit, free-first, and never persists key values."""

import json

from scripts.reveta.aura_config import aura_settings


def test_openrouter_precedes_gemini_without_copying_keys():
    config = aura_settings(
        {
            "OPENROUTER_API_KEY": "synthetic-router-key",
            "GEMINI_API_KEY": "synthetic-google-key",
        }
    )
    assert config["model"] == {"provider": "openrouter", "default": "openrouter/free"}
    assert config["fallback_model"][0]["provider"] == "gemini"
    assert "synthetic" not in json.dumps(config)
    assert config["approvals"]["mode"] == "manual"


def test_gemini_only_and_no_key_are_explicit_and_anthropic_stays_disabled():
    assert (
        aura_settings({"GEMINI_API_KEY": "synthetic"})["model"]["provider"] == "gemini"
    )
    config = aura_settings({"ANTHROPIC_API_KEY": "synthetic-unused"})
    assert config["model"]["default"] == "aura-not-connected"
    assert config["fallback_model"] == []
    assert "anthropic" not in json.dumps(config)
