"""A restart re-runs ``aura_config.py --write``: what the owner set in the app must survive it."""

import sys

import pytest
from ruamel.yaml import YAML

from scripts.reveta import aura_config


def _boot(monkeypatch, home, env=None):
    """One boot as the start command runs it: ``aura_config.py --write $HERMES_HOME/config.yaml``."""
    for key in ("COMPOSIO_API_KEY", "AURA_PUBLIC_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(sys, "argv", ["aura_config.py", "--write", str(home / "config.yaml")])
    assert aura_config.main() == 0
    return YAML().load((home / "config.yaml").read_text(encoding="utf-8-sig"))


def _save(home, config):
    with (home / "config.yaml").open("w", encoding="utf-8") as handle:
        YAML().dump(config, handle)


def test_owner_settings_survive_a_restart_and_generated_policy_is_reapplied(tmp_path, monkeypatch):
    home = tmp_path / "home"
    key = {"COMPOSIO_API_KEY": "synthetic-composio"}
    config = _boot(monkeypatch, home, key)
    # What the app writes: Tools switches, owner aura.* settings, a connector switched off, an extra MCP server.
    for platform in ("cli", "api_server"):
        config["platform_toolsets"][platform] = ["aura", "todo", "memory", "clarify", "composio", "docs"]
    config["aura"]["clarify_without_approval"] = True
    config["aura"]["voice"] = {"full_duplex": True}
    config["aura"]["free_only"] = True  # a generated policy key: the boot must reset it
    config["approvals"]["mode"] = "off"  # likewise
    config["mcp_servers"]["composio"]["enabled"] = False
    config["mcp_servers"]["docs"] = {"url": "https://docs.example.invalid/mcp", "enabled": True}
    _save(home, config)

    after = _boot(monkeypatch, home, key)

    for platform in ("cli", "api_server"):
        assert after["platform_toolsets"][platform] == ["aura", "todo", "memory", "clarify", "composio", "docs"]
    assert after["aura"]["clarify_without_approval"] is True
    assert after["aura"]["voice"] == {"full_duplex": True}
    assert after["aura"]["free_only"] is False
    assert after["approvals"]["mode"] == "manual"
    assert after["mcp_servers"]["composio"]["enabled"] is False
    assert after["mcp_servers"]["composio"]["url"] == aura_config.COMPOSIO_MCP_URL
    assert after["mcp_servers"]["docs"]["url"] == "https://docs.example.invalid/mcp"
    assert "synthetic" not in (home / "config.yaml").read_text(encoding="utf-8")


def test_removing_the_composio_key_drops_it_but_keeps_owner_switches(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config = _boot(monkeypatch, home, {"COMPOSIO_API_KEY": "synthetic-composio"})
    config["platform_toolsets"]["cli"] = ["aura", "todo", "terminal", "browser", "composio"]
    _save(home, config)

    after = _boot(monkeypatch, home)

    assert after["platform_toolsets"]["cli"] == ["aura", "todo", "browser", "terminal"]
    assert "mcp_servers" not in after
    # A name Tools cannot switch on is not carried over by hand-editing the list.
    config = after
    config["platform_toolsets"]["cli"] = ["aura", "todo", "not_a_capability"]
    _save(home, config)
    assert _boot(monkeypatch, home)["platform_toolsets"]["cli"] == ["aura", "todo"]


def test_paid_route_survives_only_with_its_model(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config = _boot(monkeypatch, home)
    config["aura"]["paid_route"] = {"provider": "anthropic", "model": "m", "per_day_usd": 1, "per_chat_usd": 1}
    config["model"] = {"provider": "anthropic", "default": "m"}
    _save(home, config)
    after = _boot(monkeypatch, home)
    assert after["aura"]["paid_route"]["provider"] == "anthropic"
    assert after["model"]["provider"] == "anthropic"

    after["model"] = "not-a-mapping"
    _save(home, after)
    reset = _boot(monkeypatch, home)
    assert "paid_route" not in reset["aura"]
    assert reset["model"]["default"] == "aura-not-connected"


def test_public_address_and_origin_come_from_aura_public_url(tmp_path, monkeypatch):
    from gateway.webapp_listener import _public_url

    assert aura_config.aura_settings({})["webapp"]["public_url"] == "https://aura-zero.onrender.com"
    home = tmp_path / "home"
    config = _boot(monkeypatch, home, {"AURA_PUBLIC_URL": "https://aura.example.org:8443/"})
    assert config["webapp"]["public_url"] == "https://aura.example.org:8443"
    # The value the gateway's Origin check and sign-in callback read is accepted as-is.
    assert _public_url(config["webapp"]["public_url"]) == "https://aura.example.org:8443"


@pytest.mark.parametrize("bad", [
    "aura.example.org", "ftp://aura.example.org", "https://user:pw@aura.example.org",
    "https://aura.example.org/app", "https://aura.example.org?x=1", "https://aura.example.org:0",
    "https://aura.example.org:notaport", "https://",
])
def test_a_malformed_public_url_stops_the_boot(bad):
    with pytest.raises(ValueError, match="AURA_PUBLIC_URL"):
        aura_config.aura_settings({"AURA_PUBLIC_URL": bad})
