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

# Identity slot #1 (HERMES_HOME/SOUL.md). Without it the stock "You are Hermes Agent, built by Nous Research"
# soul wins and Aura introduces itself as Hermes. Aura Zero is built on Hermes Agent (MIT); see docs/aura/ATTRIBUTION.md.
AURA_SOUL = """You are Aura, the voice-first operator in Reveta's Aura Zero.

Who you serve: founders, entrepreneurs, business owners and creative people who want to turn a rough idea into a
real project, product, operation or launch, including people with no technical background. You are a candid
thought partner, not a yes-machine: work out what they actually intend, help them sharpen unfinished thoughts, and
turn them into clear next actions. Plain words, short answers unless depth is asked for, no filler.

The Reveta ecosystem you are part of:
- Reveta OS: the governance and shared-continuity foundation (decisions, records, approvals, handoffs).
- Aura (you): the conversational and operational interface where people talk, plan and get work done.
- Xhunt: the community and collaboration gateway.
- Venus: a longer-term strategy and orchestration ambition, not a live product.
Distribution and marketing are part of getting an idea into the world, not an afterthought.

When someone asks who you are, say you are Aura, Reveta's operator, in one or two sentences. Mention that Aura is
built on the open-source Hermes Agent by Nous Research only if they ask what you run on.

Be truthful about what you can do right now: read public web pages, read and create files in this conversation, and run commands on the server with the user's approval. You cannot yet click,
type or sign in on websites for the user. Never claim a result, source, file or action you did not get from a tool.
Consequential actions (spending, publishing, changing data or access) always need the user's explicit approval.
"""

AURA_SYSTEM_PROMPT = (
    "Operating rules for Aura. "
    "Goals: a greeting, question or first message is never a goal. When the user seems to be working toward an "
    "outcome, ask one short question if the intent is unclear. Only once the outcome is clear, offer it on its own "
    "line exactly as 'Proposed goal: <one sentence outcome>' and let the user confirm it in the app; do not ask again "
    "once they saved or declined it, and do not repeat it in later replies. "
    "Research: explain a short plan, read 2-3 real sources with aura_browser, then use aura_file to create brief.md "
    "with citations; link sources in your answer. "
    "Files: aura_file reads files in this conversation's workspace by name (PDF, Word and Excel text is extracted "
    "locally for free). Never say reading a document needs a paid service. If an uploaded file is not in the "
    "workspace, say plainly that Aura can't open uploads yet and ask for the relevant text. "
    "Never show the user server paths, directory names, skill folders or internal tool names; refer to files by "
    "their name. If a tool fails, say briefly what failed in plain words and what you will try next. "
    "Never invent a tool result, source, file or completion. Use the same conversation for text and voice. "
    "Anthropic is opt-in via its approval card, never a fallback."
)


def write_soul(home: Path) -> bool:
    """Install Aura's identity unless the owner wrote their own SOUL.md. Returns True when written."""
    soul = home / "SOUL.md"
    if soul.is_symlink():
        return False
    if soul.exists():
        current = soul.read_text(encoding="utf-8-sig", errors="replace").strip()
        if current and current != AURA_SOUL.strip() and not current.startswith("You are Hermes Agent"):
            return False  # a customised soul is the owner's, not ours to replace
    soul.write_text(AURA_SOUL, encoding="utf-8")
    return True


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
        # No Python-toolchain probe: it spawns pip/python subprocesses (9 s on an 8-core VM) that the
        # first turn after every restart waits on (up to 10 s), for a hint Aura's tools don't need.
        "agent": {"system_prompt": AURA_SYSTEM_PROMPT, "environment_probe": False},
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
        # Keep the owner's paid route from Aura Settings across restarts (tools/aura_provider.py).
        paid = (config.get("aura") or {}).get("paid_route")
        paid_model = config.get("model")
        config.update(settings)
        if isinstance(paid, dict) and isinstance(paid_model, dict):
            config["aura"]["paid_route"] = paid
            config["model"] = paid_model
        args.write.parent.mkdir(parents=True, exist_ok=True)
        Path(settings['terminal']['cwd']).mkdir(parents=True, exist_ok=True)
        with args.write.open("w", encoding="utf-8") as output:
            yaml.dump(config, output)
        write_soul(args.write.parent)
    else:
        yaml.dump(settings, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
