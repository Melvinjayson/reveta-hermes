#!/usr/bin/env python3
"""Verify Aura's routing candidates against OpenRouter's public model catalog. No inference.

    python scripts/reveta/openrouter_catalog.py --write tests/fixtures/aura/openrouter_candidates.json
    python scripts/reveta/openrouter_catalog.py --from-raw DIR --retrieved-at 2026-11-20T17:00:00Z --write ...

Reads ``GET https://openrouter.ai/api/v1/models/<id>/endpoints`` (public, no key) for each ID in
``scripts/reveta/aura_config.py`` and records, per candidate: exact ID, name, modalities, every serving
endpoint (provider, tag, quantization, service tier, prompt/completion USD per token, context, tool and
structured-output support) and the retrieval time and URL. ``--from-raw`` rebuilds the snapshot from
saved responses (``{"source_url", "status", "body"}`` per file) when this host cannot reach openrouter.ai.

An ID the catalog does not list exactly is reported and the script exits 1. It never substitutes a
similar name. The output is a labelled snapshot for tests and review; nothing bills from it, because the
price of a request depends on the endpoint OpenRouter picks.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

CATALOG = "https://openrouter.ai/api/v1/models/{model}/endpoints"


def candidates() -> dict[str, str]:
    from scripts.reveta import aura_config

    ids = {tier: entry["model"] for tier, entry in aura_config.ROUTING_TIERS.items()}
    return {**ids, "test": aura_config.TEST_ROUTE_MODEL}


def _per_million(value: str) -> str:
    return format((Decimal(value) * 1_000_000).normalize(), "f")


def summarize(model: str, response: dict, source_url: str) -> dict:
    """One candidate's verified facts, or ``{"listed": False}`` when the exact ID is absent."""
    data = (response or {}).get("data")
    if not isinstance(data, dict) or data.get("id") != model:
        return {"model": model, "listed": False, "source_url": source_url}
    endpoints = []
    for e in data.get("endpoints") or []:
        params = set(e.get("supported_parameters") or [])
        endpoints.append({
            "provider": e.get("provider_name"), "tag": e.get("tag"), "quantization": e.get("quantization"),
            "service_tier": e.get("service_tier"), "context_length": e.get("context_length"),
            "max_completion_tokens": e.get("max_completion_tokens"),
            "prompt_usd_per_million": _per_million(e["pricing"]["prompt"]),
            "completion_usd_per_million": _per_million(e["pricing"]["completion"]),
            "tools": "tools" in params, "structured_outputs": "structured_outputs" in params,
        })
    prompt = sorted(Decimal(e["prompt_usd_per_million"]) for e in endpoints)
    completion = sorted(Decimal(e["completion_usd_per_million"]) for e in endpoints)
    arch = data.get("architecture") or {}

    def share(key: str) -> str:
        n = sum(1 for e in endpoints if e[key])
        return "all" if endpoints and n == len(endpoints) else "none" if n == 0 else f"{n}/{len(endpoints)}"

    return {
        "model": model, "listed": True, "name": data.get("name"), "source_url": source_url,
        "input_modalities": arch.get("input_modalities"), "output_modalities": arch.get("output_modalities"),
        "endpoint_count": len(endpoints),
        "prompt_usd_per_million": {"min": format(prompt[0], "f"), "max": format(prompt[-1], "f")} if prompt else None,
        "completion_usd_per_million": {"min": format(completion[0], "f"), "max": format(completion[-1], "f")} if completion else None,
        "context_length": {"min": min(e["context_length"] for e in endpoints),
                           "max": max(e["context_length"] for e in endpoints)} if endpoints else None,
        "tools": share("tools"), "structured_outputs": share("structured_outputs"),
        "endpoints": endpoints,
    }


def fetch(model: str) -> tuple[dict, str]:
    url = CATALOG.format(model=model)
    with urlopen(Request(url, headers={"Accept": "application/json", "User-Agent": "aura-catalog-check"}), timeout=30) as r:
        return json.load(r), url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", type=Path)
    parser.add_argument("--from-raw", type=Path, help="directory of saved catalog responses")
    parser.add_argument("--retrieved-at", help="ISO time the saved responses were fetched")
    args = parser.parse_args()
    rows = {}
    for tier, model in candidates().items():
        if args.from_raw:
            saved = json.loads((args.from_raw / (model.replace("/", "__").replace(":", "_") + ".json")).read_text(encoding="utf-8-sig"))
            response, url = saved["body"], saved["source_url"]
        else:
            response, url = fetch(model)
        rows[tier] = summarize(model, response, url)
    snapshot = {"label": "OpenRouter catalog snapshot — review data, not a billing price list",
                "retrieved_at": args.retrieved_at or datetime.now(UTC).isoformat(timespec="seconds"),
                "candidates": rows}
    text = json.dumps(snapshot, indent=2) + "\n"
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    missing = [row["model"] for row in rows.values() if not row["listed"]]
    for model in missing:
        print(f"not listed in the OpenRouter catalog: {model}", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
