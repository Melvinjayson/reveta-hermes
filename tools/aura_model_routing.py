"""Aura model routing: tiers, the free test route, and the per-request guard.

Aura owns the conversation; models are replaceable. This module decides *which* configured
model may serve a request and refuses everything else. It never calls a model itself, so a
routing decision costs no inference request.

Configuration lives in ``config.yaml`` under ``aura.model_routing`` and is written at boot by
``scripts/reveta/aura_config.py``:

* ``tiers.default`` / ``tiers.fallback`` / ``tiers.reasoning``: paid OpenRouter models.
  **They stay refused** until an authoritative budget authorizer exists (``budget_authorizer``
  returns None today): a model ID in configuration never makes a paid route usable.
* ``test_route``: one free OpenRouter model, off unless the deployment sets
  ``AURA_TEST_MODEL_ROUTE=1`` (never on the production address). It is never a default, never a
  fallback target, and its requests are pinned to zero price with provider fallbacks off.

Every provider request (main turn, streaming, retries, auto-recovery cycles, auxiliary calls)
already passes ``tools.aura_free_only.require_model``; ``guard`` runs there, so no request can
reach a routed model without this check. Model IDs, prices and capabilities come from the
OpenRouter catalog snapshot in ``tests/fixtures/aura/openrouter_candidates.json``
(``scripts/reveta/openrouter_catalog.py``); no price here feeds billing.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlsplit

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIERS = ("default", "fallback", "reasoning")
TIER_LABELS = {"default": "Routine", "fallback": "Fallback", "reasoning": "Reasoning", "test": "Test"}
# One substitute model per request at most; Hermes's own retry/auto-recovery budget is separate
# and stays on the *same* model (agent.api_max_retries, agent.auto_recovery_cycles).
MAX_FALLBACKS = 1
# Transient provider verdicts (agent.error_classifier.FailoverReason values). Everything else —
# budget, authorization, unsupported operation, unknown model, policy, cancellation — never
# falls back.
FALLBACK_ELIGIBLE = frozenset({"overloaded", "server_error", "timeout"})

REASONS = {
    "budget_unavailable": "Paid models stay off until Aura's budget authorization is in place.",
    "budget_reached": "Budget reached. Aura did not send this request.",
    "model_not_permitted": "Model not permitted. Aura only uses the models set up for it.",
    "model_unavailable": "Model unavailable. No permitted model can take this request right now.",
    "capability_unavailable": "Requested capability unavailable on the permitted models.",
    "test_route_off": "The experimental test model is switched off on this deployment.",
    "cancelled": "Stopped. Nothing more was sent.",
}

Authorizer = Callable[["Route"], bool]
logger = logging.getLogger(__name__)


class RouteRefused(PermissionError):
    """A request the routing policy will not send; ``user_message`` is safe to show."""

    def __init__(self, kind: str):
        self.kind = kind
        self.user_message = REASONS[kind]
        super().__init__(f"AURA_ROUTE_REFUSED[{kind}]: {self.user_message}")


@dataclass(frozen=True)
class Route:
    tier: str
    model: str
    paid: bool
    provider: str = "openrouter"
    base_url: str = OPENROUTER_BASE_URL
    capabilities: frozenset = frozenset()
    fallback_of: Optional[str] = None

    @property
    def label(self) -> str:
        """What the step history shows, e.g. ``Fallback · z-ai/glm-5.3-flash``."""
        return f"{TIER_LABELS[self.tier]} · {self.model}"


def settings(config: dict) -> dict:
    """``aura.model_routing`` with types checked; anything malformed reads as routing off."""
    value = ((config or {}).get("aura") or {}).get("model_routing")
    if not isinstance(value, dict):
        return {"enabled": False, "tiers": {}, "test_route": {"enabled": False}}
    tiers = value.get("tiers") if isinstance(value.get("tiers"), dict) else {}
    test = value.get("test_route") if isinstance(value.get("test_route"), dict) else {}
    return {"enabled": value.get("enabled") is True,
            "tiers": {name: tiers[name] for name in TIERS if isinstance(tiers.get(name), dict)},
            "test_route": {**test, "enabled": test.get("enabled") is True}}


def _route(tier: str, entry: dict, fallback_of: Optional[str] = None) -> Route:
    model = entry.get("model")
    if not isinstance(model, str) or not model.strip() or model != model.strip():
        raise RouteRefused("model_not_permitted")
    caps = entry.get("capabilities") or []
    return Route(tier=tier, model=model, paid=entry.get("paid") is not False,
                 capabilities=frozenset(c for c in caps if isinstance(c, str)), fallback_of=fallback_of)


def budget_authorizer() -> Optional[Authorizer]:
    """The authoritative paid-inference budget gate, or None while it does not exist.

    The €3 experimental budget is a separate workstream; until it exposes a reserve-then-
    reconcile authorizer, this returns None and every paid tier is refused. Do not add a local
    counter here: the budget has exactly one authority.
    """
    return None


def _authorized(route: Route, authorize: Optional[Authorizer]) -> Route:
    if not route.paid:
        return route
    if authorize is None:
        raise RouteRefused("budget_unavailable")
    try:
        allowed = authorize(route)
    except Exception:
        # Fail closed: an authorizer that breaks has not authorized anything.
        logger.warning("budget authorizer failed for %s; refusing", route.model, exc_info=True)
        allowed = False
    if allowed is not True:
        raise RouteRefused("budget_reached")
    return route


def choose(config: dict, *, selection: str = "auto", needs: Iterable[str] = (), voice: bool = False,
           authorize: Optional[Authorizer] = None, cancelled: bool = False) -> Route:
    """The route for one request. No model call; deterministic for the same inputs.

    ``selection`` is the user's explicit choice: ``auto`` (routine), ``reasoning`` or ``test``.
    Nothing escalates to Reasoning on its own — not a long message, not a multi-step task, and
    never an active voice call, which keeps one predictable model for its latency.
    """
    if cancelled:
        raise RouteRefused("cancelled")
    cfg = settings(config)
    needs = frozenset(needs)
    if selection == "test":
        return test_route(config)
    if selection not in ("auto", "reasoning"):
        raise RouteRefused("model_not_permitted")
    if not cfg["enabled"]:
        raise RouteRefused("budget_unavailable")
    tier = "reasoning" if selection == "reasoning" else "default"
    del voice  # documented above: voice never changes the tier by itself
    entry = cfg["tiers"].get(tier)
    if entry is None:
        raise RouteRefused("model_unavailable")
    route = _route(tier, entry)
    if not needs <= route.capabilities:
        raise RouteRefused("capability_unavailable")
    return _authorized(route, authorize)


def fallback(config: dict, failed: Route, failure: str, *, attempt: int, needs: Iterable[str] = (),
             authorize: Optional[Authorizer] = None, cancelled: bool = False,
             committed_action: bool = False) -> Route:
    """The one permitted substitute after *failed* hit a transient *failure*, or a refusal.

    Only the paid Routine tier falls back, only to the configured Fallback tier, only for a
    transient provider failure, at most ``MAX_FALLBACKS`` times, never after a consequential
    action ran (it would repeat), and always through the budget gate again.
    """
    if cancelled:
        raise RouteRefused("cancelled")
    if (failure not in FALLBACK_ELIGIBLE or committed_action or attempt >= MAX_FALLBACKS
            or failed.tier != "default" or not failed.paid):
        raise RouteRefused("model_unavailable")
    entry = settings(config)["tiers"].get("fallback")
    if entry is None:
        raise RouteRefused("model_unavailable")
    route = _route("fallback", entry, fallback_of=failed.model)
    if not route.paid or route.model == failed.model or not frozenset(needs) <= route.capabilities:
        raise RouteRefused("model_unavailable")
    return _authorized(route, authorize)


def test_route(config: dict) -> Route:
    """The free experimental route, only when the deployment switched it on."""
    test = settings(config)["test_route"]
    if not test["enabled"]:
        raise RouteRefused("test_route_off")
    route = _route("test", test)
    return Route(tier="test", model=route.model, paid=False, capabilities=route.capabilities)


def _same_openrouter(provider: Any, endpoint: Any) -> bool:
    url = urlsplit(str(endpoint or "").rstrip("/"))
    return (str(provider or "").lower() == "openrouter" and url.scheme == "https"
            and url.hostname == "openrouter.ai" and url.path == "/api/v1" and not url.username)


def guard(config: dict, provider: Any, endpoint: Any, request: dict,
          authorize: Optional[Authorizer] = None) -> Optional[dict]:
    """Check one outgoing provider request against the routing configuration.

    Returns None when the request names no routed model (the free-only gate and the owner's
    capped paid route decide it as before), a pinned copy for the free test route, or raises
    ``RouteRefused``. Runs for every request, so retries and recovery cycles are each checked.
    """
    model = request.get("model") if isinstance(request, dict) else None
    cfg = settings(config)
    test = cfg["test_route"]
    if isinstance(model, str) and model and model == test.get("model"):
        route = test_route(config)
        if not _same_openrouter(provider, endpoint):
            raise RouteRefused("model_not_permitted")
        body = dict(request.get("extra_body") or {})
        if any(key in body for key in ("model", "models", "route")):
            raise RouteRefused("model_not_permitted")
        preferences = body.get("provider") if isinstance(body.get("provider"), dict) else {}
        body["provider"] = {**preferences, "allow_fallbacks": False,
                            "max_price": {"prompt": 0, "completion": 0}}
        return {**request, "model": route.model, "extra_body": body}
    for tier, entry in cfg["tiers"].items():
        if model == entry.get("model"):
            _authorized(_route(tier, entry), authorize if authorize is not None else budget_authorizer())
            return None
    return None


def status(config: dict) -> dict:
    """What Settings shows: configured tiers and whether each can run. No secrets."""
    cfg = settings(config)
    authorize = budget_authorizer()
    tiers = []
    for tier in TIERS:
        entry = cfg["tiers"].get(tier)
        if entry is None:
            continue
        state = "available" if cfg["enabled"] and authorize is not None else "disabled"
        tiers.append({"tier": tier, "label": TIER_LABELS[tier], "model": entry.get("model"),
                      "paid": entry.get("paid") is not False, "state": state,
                      "reason": None if state == "available" else REASONS["budget_unavailable"]})
    test = cfg["test_route"]
    return {"enabled": cfg["enabled"], "tiers": tiers,
            "test_route": {"label": TIER_LABELS["test"], "model": test.get("model"),
                           "state": "available" if test["enabled"] else "disabled",
                           "experimental": True, "production_allowed": False}}
