"""Server-owned zero-price attestations. No price is inferred from a name/key.

Default allowlists are empty. A tool attestation binds its exact arguments;
open-world commands cannot acquire a blanket zero-price declaration.

``aura.free_only: false`` (the boolean, nothing else) turns the rule off: every
model and tool may run, the owner's capped paid route keeps its caps, and the
single-use approval gate in ``tools.aura_dispatch_policy`` still applies. Any other
value that is not ``true`` fails closed.
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit

from tools.aura_dispatch_policy import _config

REFUSAL = "This would cost money, so I didn't run it."
MARKER = "AURA_FREE_ONLY_REFUSED"


class FreeOnlyRefused(PermissionError):
    def __init__(self, user_message=REFUSAL):
        self.user_message = user_message
        super().__init__(f"{MARKER}: {user_message}")


def settings():
    try:
        value = _config().get("aura", {})
        # Only a real boolean is an owner decision; "false", 0 and None fail closed.
        if not isinstance(value, dict) or type(value.get("free_only", True)) is not bool:
            raise FreeOnlyRefused()
        return value
    except Exception as exc:
        raise FreeOnlyRefused() from exc


def enabled():
    """True while the free-only rule is on; False only for an explicit ``free_only: false``."""
    return settings().get("free_only", True) is True


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
    """True when the action is confirmed zero-price; False when the rule is off (price unverified)."""
    config = settings()
    if config.get("free_only", True) is False:
        return False
    try:
        if _declared_paid_tool(name):
            raise FreeOnlyRefused()
        from tools.aura_product import owned_tool
        if owned_tool(name):
            return True
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


def advertised_tool(name):
    return name in advertised_tools([name])


def advertised_tools(names):
    """The subset of *names* Aura may offer to the model at all (config is read once).

    Outside Aura (``aura.enabled`` not True) every tool is offered as before. Inside Aura,
    a tool the free-only gate can never run (not Aura-owned, no free_tools entry) is not
    offered: the model otherwise spends a turn on it and the user sees "This would cost
    money" for a renderer or catalog tool that costs nothing but is not attested. Dispatch
    still goes through require_tool; this only keeps refused-by-construction tools out.
    """
    from tools.aura_capabilities import unlockable_tools
    from tools.aura_product import available, owned_tool
    try:
        aura = available()
    except Exception:
        aura = False  # unreadable config is not Aura mode; dispatch still fails closed there
    if not aura:
        return set(names)
    try:
        config = settings()
        # With the rule off, the owner's configured MCP servers (e.g. Composio) are offered too;
        # the curated surface still hides the desktop/catalog GUI tools Aura's web app can't use.
        mcp = config.get("free_only", True) is False
        entries = config.get("free_tools", [])
        attested = {e.get("name") for e in entries if isinstance(e, dict)} if isinstance(entries, list) else set()
        # With the rule off, Hermes toolsets the owner switched on (tools/aura_capabilities.py)
        # are offered as well; enabled_toolsets already limited *names* to those toolsets.
        unlocked = unlockable_tools() if mcp else frozenset()
        return {name for name in names
                if owned_tool(name) or name in attested or (mcp and name.startswith("mcp_")) or name in unlocked}
    except Exception:
        return set()


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


def _paid_route_request(config, provider, endpoint, request, chat):
    """The owner's capped paid route (tools/aura_provider.py), or None when *request* is not it."""
    from tools.aura_provider import SpendCapReached, check, matches, route

    try:
        paid = route({"aura": config})
    except ValueError:
        return None
    if not matches(paid, provider, endpoint, request.get("model")):
        return None
    try:
        check(paid, chat)
    except SpendCapReached as exc:
        raise FreeOnlyRefused(str(exc)) from exc
    return {**request}


def require_model(provider, endpoint, request, *, api_mode="chat_completions", chat=None):
    """Check the final SDK payload; return a copy with provider fallbacks disabled."""
    config = settings()
    if isinstance(request, dict) and api_mode in {"chat_completions", "codex_responses", "anthropic_messages"}:
        paid = _paid_route_request(config, provider, endpoint, request, chat)
        if paid is not None:
            return paid
    if config.get("free_only", True) is False:
        return request
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
        agent.provider, agent.base_url, request, api_mode=agent.api_mode,
        chat=getattr(agent, "session_id", None),
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
