"""Server-owned zero-price attestations. No price is inferred from a name/key.

Default allowlists are empty. A tool attestation binds its exact arguments;
open-world commands cannot acquire a blanket zero-price declaration.
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit

from tools.aura_dispatch_policy import _config

REFUSAL = "This would cost money, so I didn't run it."
MARKER = "AURA_FREE_ONLY_REFUSED"


class FreeOnlyRefused(PermissionError):
    def __init__(self):
        super().__init__(f"{MARKER}: {REFUSAL}")


def settings():
    try:
        value = _config().get("aura", {})
        if not isinstance(value, dict) or value.get("free_only", True) is not True:
            raise FreeOnlyRefused()
        return value
    except Exception as exc:
        raise FreeOnlyRefused() from exc


def enabled():
    settings()  # paid mode is unsupported until a separate spending-cap slice
    return True


def argument_hash(args):
    value = json.dumps(
        args, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _entries(config, key):
    entries = config.get(key, [])
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict) for entry in entries
    ):
        raise FreeOnlyRefused()
    return entries


def require_tool(name, args):
    config = settings()
    try:
        if _declared_paid_tool(name):
            raise FreeOnlyRefused()
        digest = argument_hash(args)
        entries = _entries(config, "free_tools")
        matches = [
            entry
            for entry in entries
            if entry.get("name") == name and entry.get("arguments_sha256") == digest
        ]
        _confirmed_zero(matches)
        return True
    except Exception as exc:
        raise FreeOnlyRefused() from exc


def _declared_paid_tool(name):
    if not name.startswith("mcp_"):
        return False
    from tools import mcp_tool
    from tools.mcp_tool_scope import _server_key
    from tools.mcp_tool_schema import mcp_prefixed_tool_name

    with mcp_tool._lock:
        server = mcp_tool._mcp_tool_server_names.get(name)
        policy = (
            mcp_tool._server_cost_policies.get(_server_key(server)) if server else None
        )
        costs = dict(policy.costs) if policy else {}
    return any(
        cost.high > 0 and mcp_prefixed_tool_name(server, raw) == name
        for raw, cost in costs.items()
    )


def _confirmed_zero(matches):
    if (
        len(matches) != 1
        or matches[0].get("confirmed_free") is not True
        or type(matches[0].get("cost_usd")) not in (int, float)
        or matches[0]["cost_usd"] != 0
    ):
        raise FreeOnlyRefused()


def _model_identity(provider, endpoint, request, api_mode):
    if not isinstance(provider, str) or not provider.strip():
        raise FreeOnlyRefused()
    model = request.get("model")
    if (
        api_mode != "chat_completions"
        or provider.lower() in {"moa", "auto"}
        or not isinstance(model, str)
        or not model.strip()
        or model != model.strip()
        or model in {"auto", "openrouter/free"}
    ):
        raise FreeOnlyRefused()
    endpoint = str(endpoint or "").rstrip("/")
    url = urlsplit(endpoint)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise FreeOnlyRefused()
    return model, endpoint


def _without_routing_overrides(provider, request):
    body = request.get("extra_body") or {}
    if not isinstance(body, dict) or any(
        key in body for key in ("model", "modelId", "models", "route")
    ):
        raise FreeOnlyRefused()
    if request.get("service_tier") not in (None, "default") or body.get(
        "service_tier"
    ) not in (None, "default"):
        raise FreeOnlyRefused()
    preferences = body.get("provider") or {}
    if not isinstance(preferences, dict):
        raise FreeOnlyRefused()
    if provider == "openrouter":
        preferences = {**preferences, "max_price": {"prompt": 0, "completion": 0}}
    return {
        **request,
        "extra_body": {**body, "provider": {**preferences, "allow_fallbacks": False}},
    }


def require_model(provider, endpoint, request, *, api_mode="chat_completions"):
    """Check the final SDK payload; return a copy with provider fallbacks disabled."""
    config = settings()
    try:
        model, endpoint = _model_identity(provider, endpoint, request, api_mode)
        matches = [
            entry
            for entry in _entries(config, "free_models")
            if entry.get("provider") == provider
            and entry.get("model") == model
            and str(entry.get("base_url", "")).rstrip("/") == endpoint
        ]
        _confirmed_zero(matches)
        return _without_routing_overrides(provider, request)
    except Exception as exc:
        raise FreeOnlyRefused() from exc


def require_agent_model(agent, request):
    return require_model(
        agent.provider, agent.base_url, request, api_mode=agent.api_mode
    )


def require_aux_model(client, request, provider=None, api_mode=None):
    from agent.auxiliary_client import _RELAY_AUX_CALL_CONTEXT, _runtime_main_value

    context = _RELAY_AUX_CALL_CONTEXT.get() or {}
    return require_model(
        provider or context.get("provider") or _runtime_main_value("provider"),
        getattr(client, "base_url", ""),
        request,
        api_mode=api_mode or context.get("api_mode") or "chat_completions",
    )


def guarded_aux_callback(client, callback, provider=None, api_mode=None):
    def execute(request):
        request = require_aux_model(client, request, provider, api_mode)
        seal_client(client)
        return callback(request)

    return execute


def seal_client(client):
    """The HTTP client may not redirect outside an attested route."""
    if enabled():
        import httpx

        transport = getattr(client, "_client", None)
        # Hermes's canonical Gemini facade owns an httpx transport under _http;
        # its auxiliary async facade holds that same client under _sync.
        from agent.gemini_native_adapter import GeminiNativeClient, AsyncGeminiNativeClient

        if isinstance(client, AsyncGeminiNativeClient):
            client = client._sync
        if type(client) is GeminiNativeClient:
            transport = client._http
        if not isinstance(transport, (httpx.Client, httpx.AsyncClient)):
            raise FreeOnlyRefused()
        transport.follow_redirects = False
    return client
