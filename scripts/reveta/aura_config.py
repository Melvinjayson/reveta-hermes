#!/usr/bin/env python3
"""Prepare an Aura configuration without reading key files or calling providers.

Writes only when --write is supplied. The founder runs this during a separately
approved cutover; generating configuration does not start or deploy anything.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def aura_settings(env: dict[str, str]) -> dict:
    gemini = {"provider": "gemini", "model": "gemini-2.5-flash"}
    if env.get("OPENROUTER_API_KEY", "").strip():
        model = {"provider": "openrouter", "default": "openrouter/free"}
        fallback = [gemini] if env.get("GEMINI_API_KEY", "").strip() else []
    elif env.get("GEMINI_API_KEY", "").strip():
        model = {"provider": "gemini", "default": gemini["model"]}
        fallback = []
    else:
        # An explicit closed loopback endpoint prevents ambient paid-provider
        # credentials from becoming an auto-selected default.
        model = {
            "provider": "custom",
            "default": "aura-not-connected",
            "base_url": "http://127.0.0.1:9/v1",
        }
        fallback = []
    return {
        "model": model,
        "fallback_model": fallback,
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
            yaml.load(args.write.read_text(encoding="utf-8"))
            if args.write.exists()
            else {}
        )
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise ValueError("Existing configuration must be a mapping")
        config.update(settings)
        args.write.parent.mkdir(parents=True, exist_ok=True)
        with args.write.open("w", encoding="utf-8") as output:
            yaml.dump(config, output)
    else:
        yaml.dump(settings, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
