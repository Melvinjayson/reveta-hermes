"""The paid-request boundary: bound a request's cost, reserve it, then settle it.

``tools.aura_model_routing`` decides *which* model may serve a request; ``tools.aura_budget`` decides
*whether* Aura may pay for it. This module joins them at the one place every provider request
passes (``tools.aura_free_only.require_model``):

1. ``bound`` caps the request so its cost has a ceiling: ``max_tokens`` at most the tier's
   ``max_output_tokens``, and (OpenRouter) ``provider.max_price`` at the tier's price ceiling — if no
   endpoint is that cheap, OpenRouter fails the request instead of charging more.
2. The ceiling cost is reserved through ``aura_budget.authorize_or_reserve``; a refusal stops the
   request before any client is built.
3. After the call, ``settle_agent_call`` / the auxiliary wrapper reconcile with the cost OpenRouter
   reported (``usage.cost``), or the bundled-rate estimate for the legacy OpenAI/Anthropic route; with
   no cost they keep the whole reservation. ``settle_failed`` releases only on a provider 4xx refusal.

Input tokens are bounded by the UTF-8 byte length of messages and tools plus a fixed overhead (a
token is at least one byte for these tokenizers), output by ``max_tokens`` (reasoning tokens bill as
output and count inside it). The reservation is therefore an upper bound on the request's cost.
"""
from __future__ import annotations

from contextvars import ContextVar
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROTOCOL_OVERHEAD_TOKENS = 1024
DEFAULT_MAX_OUTPUT_TOKENS = 4096
# The reservation made by the request guard on this call stack; the caller takes it at once.
_PENDING: ContextVar[Optional[str]] = ContextVar("aura_paid_pending", default=None)


def input_token_bound(request: dict) -> int:
    payload = {key: request.get(key) for key in ("messages", "tools", "system", "input", "instructions")}
    return len(json.dumps(payload, ensure_ascii=False, default=str).encode()) + PROTOCOL_OVERHEAD_TOKENS


def _output_cap(request: dict, cap: int) -> int:
    asked = request.get("max_tokens") or request.get("max_completion_tokens")
    return min(asked, cap) if type(asked) is int and asked > 0 else cap


def bound(request: dict, *, prompt_per_million: float, completion_per_million: float,
          max_output_tokens: int, openrouter: bool) -> tuple[dict, float]:
    """A copy of *request* whose cost cannot exceed the returned USD estimate."""
    output = _output_cap(request, max_output_tokens)
    # Keep the caller's key: some OpenAI models accept only max_completion_tokens.
    key = "max_completion_tokens" if "max_completion_tokens" in request else "max_tokens"
    pinned = {**request, key: output}
    if openrouter:
        body = dict(request.get("extra_body") or {})
        preferences = body.get("provider") if isinstance(body.get("provider"), dict) else {}
        body["provider"] = {**preferences, "max_price": {"prompt": prompt_per_million,
                                                         "completion": completion_per_million}}
        body["usage"] = {"include": True}  # ask OpenRouter to report the request's cost
        pinned["extra_body"] = body
    estimate = (input_token_bound(request) * prompt_per_million + output * completion_per_million) / 1_000_000
    return pinned, estimate


def reserve(request: dict, *, session_id: str, model: str, tier: str, prompt_per_million: float,
            completion_per_million: float, max_output_tokens: int, openrouter: bool) -> dict:
    """Bound, then reserve; raises ``aura_budget.BudgetRefused`` (the request must not be sent)."""
    from tools.aura_budget import authorize_or_reserve

    pinned, estimate = bound(request, prompt_per_million=prompt_per_million,
                             completion_per_million=completion_per_million,
                             max_output_tokens=max_output_tokens, openrouter=openrouter)
    reservation = authorize_or_reserve(session_id=session_id, model=model, tier=tier, estimated_usd=estimate)
    _PENDING.set(reservation.request_id)
    return pinned


def take_pending() -> Optional[str]:
    """The reservation the guard just made on this call stack (once)."""
    ident = _PENDING.get()
    _PENDING.set(None)
    return ident


def reported_cost(usage: Any) -> Optional[float]:
    """OpenRouter's reported USD cost for one response, when it sent one."""
    if usage is None:
        return None
    value = getattr(usage, "cost", None)
    if value is None:
        extra = getattr(usage, "model_extra", None) or (usage if isinstance(usage, dict) else {})
        value = extra.get("cost") if isinstance(extra, dict) else None
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return None
    return cost if cost >= 0 else None


def adopt(agent: Any) -> None:
    """Attach the reservation just made to *agent*; an older unsettled one keeps its full amount."""
    ident = take_pending()
    previous = getattr(agent, "_aura_reservation", None)
    if previous and previous != ident:
        _settle(previous, None)
    agent._aura_reservation = ident


def _settle(ident: str, cost: Optional[float], basis: str = "provider_reported") -> None:
    from tools.aura_budget import reconcile

    try:
        reconcile(ident, cost, basis=basis)
    except Exception:
        logger.exception("Aura budget reservation %s was not reconciled; it keeps its full amount", ident)


def settle_agent_call(agent: Any, raw_usage: Any, legacy_usd: Optional[float] = None) -> None:
    """After a main-agent response: reported cost, else the legacy route's estimate, else the reservation."""
    ident = getattr(agent, "_aura_reservation", None)
    if not ident:
        return
    agent._aura_reservation = None
    cost = reported_cost(raw_usage)
    if cost is not None:
        _settle(ident, cost)
    elif legacy_usd is not None:
        _settle(ident, legacy_usd, basis="bundled_rate_snapshot")
    else:
        _settle(ident, None)


def settle_failed(agent: Any, error: Any) -> None:
    """After a failed main-agent request: release on a provider 4xx refusal, else keep the reservation."""
    from tools.aura_budget import release_reservation

    ident = getattr(agent, "_aura_reservation", None)
    if not ident:
        return
    agent._aura_reservation = None
    status = getattr(error, "status_code", None)
    try:
        release_reservation(ident, http_status=status if type(status) is int else None)
    except Exception:
        logger.exception("Aura budget reservation %s was not settled after a failure", ident)
