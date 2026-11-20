"""Owner-chosen paid chat model for Aura, bounded by daily and per-chat USD caps.

Set from Aura Settings (``/api/aura/provider``), so no deploy-environment edit is needed.
The key goes to Hermes's ``.env`` through the standard credential lifecycle; the choice and
caps go to ``config.yaml`` under ``aura.paid_route``. Spend is recorded per API call from the
provider's token usage at Hermes's bundled price snapshot and checked before every call.
Without a paid route, the free Gemini default and the free-only guard are unchanged.

Shortcut: the cap check reads spend recorded *after* each call, so one call can overshoot a
cap by its own cost. Auxiliary calls (titles, compression) are checked but not recorded.
"""
from __future__ import annotations

import math
import sqlite3
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urlsplit

from hermes_constants import get_hermes_home

PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {"label": "OpenAI", "env": "OPENAI_API_KEY", "host": "api.openai.com",
               "base_url": "https://api.openai.com/v1", "runtime": {"openai", "custom"},
               "models": ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-4.1-mini"]},
    "anthropic": {"label": "Anthropic", "env": "ANTHROPIC_API_KEY", "host": "api.anthropic.com",
                  "base_url": "https://api.anthropic.com", "runtime": {"anthropic"},
                  "models": ["claude-sonnet-5", "claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-5"]},
}
MAX_CAP_USD = 500.0


class SpendCapReached(PermissionError):
    """A paid call would exceed an owner-set cap; the message is safe to show."""


def price(provider: str, model: str):
    from agent.usage_pricing import BillingRoute, _lookup_official_docs_pricing

    entry = _lookup_official_docs_pricing(BillingRoute(provider=provider, model=model, base_url="",
                                                       billing_mode="official_docs_snapshot"))
    if entry is None or entry.input_cost_per_million is None or entry.output_cost_per_million is None:
        raise ValueError(f"{model} has no bundled price, so its spend cannot be capped")
    return entry


def _cap(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0 or value > MAX_CAP_USD:
        raise ValueError(f"caps must be between 0 and {MAX_CAP_USD:g} USD")
    return float(value)


def route(config: Optional[dict] = None) -> Optional[dict]:
    """The validated paid route, or None when Aura stays on the free default."""
    if config is None:
        from tools.aura_dispatch_policy import _config
        config = _config()
    value = (config.get("aura") or {}).get("paid_route")
    if not isinstance(value, dict) or value.get("provider") not in PROVIDERS:
        return None
    spec = PROVIDERS[value["provider"]]
    if value.get("model") not in spec["models"]:
        return None
    return {"provider": value["provider"], "model": value["model"],
            "per_day_usd": _cap(value.get("per_day_usd")), "per_chat_usd": _cap(value.get("per_chat_usd"))}


def matches(paid: Optional[dict], runtime_provider: str, endpoint: str, model: str) -> bool:
    if not paid:
        return False
    spec = PROVIDERS[paid["provider"]]
    url = urlsplit(str(endpoint or spec["base_url"]))
    return (str(runtime_provider or "").lower() in spec["runtime"] and model == paid["model"]
            and url.scheme == "https" and url.hostname == spec["host"] and not url.username)


def ledger():
    db = sqlite3.connect(get_hermes_home() / "aura-spend.db", timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS chat_spend (id TEXT PRIMARY KEY, chat TEXT, day TEXT, "
               "provider TEXT, model TEXT, usd REAL)")
    return db


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def totals(chat: Optional[str] = None) -> tuple[float, float]:
    with ledger() as db:
        day = db.execute("SELECT COALESCE(SUM(usd),0) FROM chat_spend WHERE day=?", (_today(),)).fetchone()[0]
        per_chat = db.execute("SELECT COALESCE(SUM(usd),0) FROM chat_spend WHERE chat=?",
                              (chat,)).fetchone()[0] if chat else 0.0
    return float(day), float(per_chat)


def check(paid: dict, chat: Optional[str] = None) -> None:
    day, per_chat = totals(chat)
    if day >= paid["per_day_usd"]:
        raise SpendCapReached(f"Aura reached today's ${paid['per_day_usd']:.2f} limit for "
                              f"{paid['model']}. Raise it in Aura Settings or try again tomorrow (UTC).")
    if chat and per_chat >= paid["per_chat_usd"]:
        raise SpendCapReached(f"This chat reached its ${paid['per_chat_usd']:.2f} limit. Start a new chat "
                              "or raise the per-chat limit in Aura Settings.")


def charge(chat: str, provider: str, model: str, usd: float) -> None:
    with ledger() as db:
        db.execute("INSERT INTO chat_spend VALUES (?,?,?,?,?,?)",
                   (uuid.uuid4().hex, chat or "", _today(), provider, model, float(usd)))


def record(agent, usage) -> None:
    """Add one main-model call's cost to the ledger when it ran on the paid route."""
    paid = route()
    if not matches(paid, agent.provider, agent.base_url, agent.model):
        return
    tokens = {name: int(getattr(usage, name, 0) or 0) for name in
              ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")}
    charge(agent.session_id or "", paid["provider"], paid["model"], usd_for(paid, **tokens))


def usd_for(paid: dict, input_tokens: int = 0, output_tokens: int = 0, cache_read_tokens: int = 0,
            cache_write_tokens: int = 0) -> float:
    """Cost of one call on the paid route at the bundled price snapshot."""
    entry = price(paid["provider"], paid["model"])
    read_rate = entry.cache_read_cost_per_million or entry.input_cost_per_million
    write_rate = entry.cache_write_cost_per_million or entry.input_cost_per_million
    usd = (Decimal(input_tokens) * entry.input_cost_per_million
           + Decimal(output_tokens) * entry.output_cost_per_million
           + Decimal(cache_read_tokens) * read_rate + Decimal(cache_write_tokens) * write_rate) / 1_000_000
    return float(usd)


def options() -> list[dict]:
    rows = []
    for key, spec in PROVIDERS.items():
        for model in spec["models"]:
            entry = price(key, model)
            rows.append({"provider": key, "label": spec["label"], "model": model,
                         "input_per_million_usd": float(entry.input_cost_per_million),
                         "output_per_million_usd": float(entry.output_cost_per_million)})
    return rows


def status() -> dict:
    """What Settings shows: never a key, only whether one is stored."""
    from hermes_cli.config import load_env
    from tools.aura_dispatch_policy import _config

    config, env = _config(), load_env()
    paid = route(config)
    day, _ = totals()
    model = config.get("model") or {}
    from tools.aura_model_routing import status as routing_status

    return {"paid_route": paid, "active_model": {"provider": model.get("provider"), "model": model.get("default")},
            "routing": routing_status(config),
            "spent_today_usd": round(day, 4),
            "keys": {key: bool((env.get(spec["env"]) or "").strip()) for key, spec in PROVIDERS.items()},
            "gemini_key": bool((env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY") or "").strip()),
            "options": options()}


def configure(provider: str, model: str = "", per_day_usd: Any = None, per_chat_usd: Any = None,
              api_key: str = "") -> dict:
    """Switch Aura's main model. ``provider='gemini'`` returns to the free default."""
    import os

    import importlib.util
    from pathlib import Path

    from hermes_cli.config import load_config, load_env, save_config

    generator = importlib.util.spec_from_file_location(
        "aura_config", Path(__file__).resolve().parents[1] / "scripts" / "reveta" / "aura_config.py")
    aura_config = importlib.util.module_from_spec(generator)
    generator.loader.exec_module(aura_config)
    aura_settings = aura_config.aura_settings

    config = load_config()
    aura = dict(config.get("aura") or {})
    if provider == "gemini":
        aura.pop("paid_route", None)
        config["model"] = aura_settings({**load_env(), **os.environ})["model"]
    elif provider == "openrouter_test":
        # Explicit choice only; the next boot returns to the free default (aura_config.merge_owner_settings).
        from tools.aura_model_routing import OPENROUTER_BASE_URL, RouteRefused, test_route

        try:
            route = test_route(config)
        except RouteRefused as exc:
            raise ValueError(exc.user_message) from exc
        if not (load_env().get("OPENROUTER_API_KEY") or "").strip():
            raise ValueError("add OPENROUTER_API_KEY to the deployment first")
        aura.pop("paid_route", None)
        config["model"] = {"provider": "openrouter", "default": route.model, "base_url": OPENROUTER_BASE_URL}
    else:
        spec = PROVIDERS.get(provider)
        if spec is None or model not in spec["models"]:
            raise ValueError("choose one of the listed providers and models")
        price(provider, model)
        paid = {"provider": provider, "model": model, "per_day_usd": _cap(per_day_usd),
                "per_chat_usd": _cap(per_chat_usd)}
        if api_key.strip():
            from hermes_cli.credential_lifecycle import save_provider_env_credential
            save_provider_env_credential(spec["env"], api_key.strip())
            config = load_config()  # the credential lifecycle may reconcile config mirrors
            aura = dict(config.get("aura") or {})
        elif not (load_env().get(spec["env"]) or "").strip():
            raise ValueError(f"add your {spec['label']} API key first")
        aura["paid_route"] = paid
        config["model"] = {"provider": provider, "default": model, "base_url": spec["base_url"]}
    config["aura"] = aura
    config["fallback_model"] = []
    save_config(config)
    return status()
