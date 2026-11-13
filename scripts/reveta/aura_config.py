#!/usr/bin/env python3
"""Prepare an Aura configuration without reading key files or calling providers.

Writes only when --write is supplied. The founder runs this during a separately
approved cutover; generating configuration does not start or deploy anything.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys

DEFAULT_FREE_GEMINI_MODEL = "gemini-3.8-flash"


def aura_settings(env: dict[str, str]) -> dict:
    # Exact native ID/endpoint: website/docs/guides/google-gemini.md.
    # Use an AI Studio FREE-TIER project; a billing-enabled key can incur charges.
    endpoint = "https://generativelanguage.googleapis.com/v1beta"
    model_id = env.get("AURA_GEMINI_MODEL", "").strip() or DEFAULT_FREE_GEMINI_MODEL
    if not re.fullmatch(r"gemini-[a-z0-9][a-z0-9.-]*", model_id) or model_id.endswith('-latest'):
        raise ValueError('AURA_GEMINI_MODEL must be an exact Gemini model ID, not a route or alias')
    confirmed_free = model_id == DEFAULT_FREE_GEMINI_MODEL or env.get(
        'AURA_GEMINI_MODEL_CONFIRMED_FREE', '').strip().lower() == 'true'
    free_models = []
    if any(env.get(key, "").strip() for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY")):
        model = {"provider": "gemini", "default": model_id, "base_url": endpoint}
        free_models = [{"provider": "gemini", "model": model["default"], "base_url": endpoint,
                        "confirmed_free": True, "cost_usd": 0}] if confirmed_free else []
    else:
        # An explicit closed loopback endpoint prevents ambient paid-provider
        # credentials from becoming an auto-selected default.
        model = {
            "provider": "custom",
            "default": "aura-not-connected",
            "base_url": "http://127.0.0.1:9/v1",
        }
    return {
        "model": model,
        "fallback_model": [],
        "aura": {
            "enabled": True,
            "free_only": True,
            "free_models": free_models,
            "free_tools": [],
            "anthropic": {
                "model": env.get("AURA_ANTHROPIC_MODEL", "claude-sonnet-4-5"),
                "per_chat_usd": _cap(env.get("AURA_ANTHROPIC_PER_CHAT_USD", "0")),
                "per_day_usd": _cap(env.get("AURA_ANTHROPIC_PER_DAY_USD", "0")),
            },
        },
        "terminal": {"backend": "local", "cwd": str(Path(env.get("HERMES_HOME", ".")) / "aura-workspace")},
        "platform_toolsets": {"cli": ["aura", "todo"], "api_server": ["aura", "todo"]},
        # This compact surface needs no deferred catalog/bridge calls.
        "tools": {"tool_search": {"enabled": "off"}},
        "browser": browser_settings(env),
        "agent": {"system_prompt": "You are Aura. For research, explain a short plan, read 2-3 real sources with aura_browser, then use aura_file to create brief.md with citations. Never invent a tool result, source, file or completion. Link sources in your answer. Use the same conversation for text and voice. Anthropic is opt-in via its approval card, never a fallback."},
        "approvals": {
            "mode": "manual",
            "cron_mode": "deny",
            "unattended_mode": "deny",
            "single_query_mode": "deny",
        },
        "webapp": {
            "enabled": True,
            "host": "0.0.0.0",
            "port": 10000,
            "public_url": "https://aura-zero.onrender.com",
        },
    }


def browser_settings(env: dict[str, str]) -> dict:
    from urllib.parse import urlsplit

    browser = {"cloud_provider": "local", "engine": "auto", "headless": True,
               "harness_home": str(Path(env.get("HERMES_HOME", ".")) / "cache" / "browser-harness")}
    proxy = urlsplit(env.get("HTTPS_PROXY") or env.get("https_proxy") or "")
    if proxy.hostname and proxy.port and not (proxy.username or proxy.password):
        browser["chromium_args"] = [f"--proxy-server={proxy.scheme}://{proxy.hostname}:{proxy.port}"]
    return browser


def _cap(value: str) -> float:
    import math

    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else 0
    except (ValueError, TypeError):
        return 0


def main() -> int:
    from ruamel.yaml import YAML

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", type=Path, help="explicit destination config.yaml; omit to preview"
    )
    args = parser.parse_args()
    yaml = YAML()
    settings = aura_settings(dict(os.environ))
    if args.write:
        config = (
            yaml.load(args.write.read_text(encoding="utf-8-sig"))
            if args.write.exists()
            else {}
        )
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise ValueError("Existing configuration must be a mapping")
        config.update(settings)
        args.write.parent.mkdir(parents=True, exist_ok=True)
        Path(settings['terminal']['cwd']).mkdir(parents=True, exist_ok=True)
        with args.write.open("w", encoding="utf-8") as output:
            yaml.dump(config, output)
    else:
        yaml.dump(settings, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
