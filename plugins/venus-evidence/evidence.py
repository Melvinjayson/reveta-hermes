"""Pure, metadata-only evidence accumulator for one Hermes run (no I/O, no hooks, no network).

A run is one ``run_conversation`` call: the events between the first observer hook for a session
and its ``on_session_end``. Only names, counts, durations and statuses are kept. Prompts,
responses, tool arguments, tool results, error messages and approval prompt text never enter a
record: the API below takes those values only to classify them and drops them immediately.

Unknown stays unknown: a cost with no reported or estimable price is ``None`` with status
``"unknown"``, never ``0``; value figures stay ``None`` until a human supplies them.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

SCHEMA = "venus.evidence.v1"
PLUGIN_NAME = "venus-evidence"
PLUGIN_VERSION = "0.1.0"
SOURCES = frozenset({"measured_runtime", "fixture"})
RUN_OUTCOMES = ("completed", "failed", "partial", "unknown")
TOOL_OUTCOMES = ("success", "error", "denied", "blocked")
ROUTES = frozenset({"conversation", "clarify", "tool"})
COMPARISON_METHODS = frozenset({"manual", "existing_ai_tool"})

MAX_TOOL_EVENTS = 256
MAX_APPROVAL_EVENTS = 64
MAX_ROUTE_SUGGESTIONS = 32

_APPROVED = frozenset({"once", "session", "always", "approve", "approved", "allow", "yes"})
_DENIED = frozenset({"deny", "denied", "reject", "rejected", "no"})
_TOKEN_RE = re.compile(r"[^a-z0-9_.:-]+")
_NAME_RE = re.compile(r"[\x00-\x1f\x7f]+")


def utc_iso(epoch: Optional[float] = None) -> str:
    moment = datetime.fromtimestamp(epoch, UTC) if epoch is not None else datetime.now(UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def safe_name(value: Any, limit: int = 128) -> str:
    """A tool/model/provider name: printable, bounded. Names are metadata, not content."""
    return _NAME_RE.sub("", str(value or ""))[:limit]


def safe_token(value: Any, limit: int = 32) -> str:
    """A status-like token (lowercase, no spaces); anything else collapses to ``"other"``."""
    token = _TOKEN_RE.sub("_", str(value or "").strip().lower()).strip("_")[:limit]
    return token or "other"


def _ms(seconds: Any) -> Optional[int]:
    try:
        return max(0, round(float(seconds) * 1000))
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


class BoundedBuffer:
    """Keeps at most ``limit`` items; every rejected item is counted, never silently lost."""

    def __init__(self, limit: int):
        self.limit = max(0, int(limit))
        self.items: list[Any] = []
        self.dropped = 0

    def add(self, item: Any) -> bool:
        if len(self.items) >= self.limit:
            self.dropped += 1
            return False
        self.items.append(item)
        return True

    def drain(self) -> list[Any]:
        items, self.items = self.items, []
        return items


# --- classification (values in, labels out; inputs are never retained) -------------------------

def _result_markers(result: Any) -> dict:
    """Structural keys of a tool result envelope, read only to classify it."""
    parsed = result
    if isinstance(result, str):
        if not result.startswith("{") or len(result) > 65536:
            return {}
        try:
            import json
            parsed = json.loads(result)
        except ValueError:
            return {}
    if not isinstance(parsed, dict):
        return {}
    return {"status": parsed.get("status"), "user_consent": parsed.get("user_consent"),
            "approved": parsed.get("approved"), "user_summary": bool(parsed.get("user_summary"))}


def classify_tool(status: Any, result: Any = None, *, approval_denied: bool = False) -> str:
    """Map an observer ``post_tool_call`` to success/error/denied/blocked. Only an observer
    ``ok`` with no non-consent marker is ``success``; unknown statuses are never success."""
    markers = _result_markers(result)
    human_refused = (approval_denied or markers.get("user_consent") is False
                     or markers.get("approved") is False
                     or (markers.get("status") == "blocked" and markers.get("user_summary")))
    if human_refused:
        return "denied"
    observer = str(status or "").lower()
    if observer == "blocked" or markers.get("status") in ("blocked", "pending_approval"):
        return "blocked"
    if observer == "denied":
        return "denied"
    return "success" if observer == "ok" else "error"


def approval_decision(kind: str, outcome: Any) -> str:
    token = safe_token(outcome)
    if kind != "approval":
        return token
    if token in _APPROVED:
        return "approved"
    if token in _DENIED:
        return "denied"
    return token if token in ("timeout", "cancelled", "error") else "other"


def run_outcome(*, completed: Any, failed: Any, interrupted: Any, api_ok: int, api_errors: int) -> str:
    if interrupted:
        return "partial"
    if failed:
        return "failed"
    if completed is True:
        return "completed"
    if completed is False:
        if api_ok:
            return "partial"
        return "failed" if api_errors else "unknown"
    return "unknown"


# --- value block -------------------------------------------------------------------------------

def value_block(inputs: Optional[dict] = None) -> dict:
    """Human-supplied comparison figures. Savings exist only when both baseline and review
    minutes were supplied; otherwise they are ``"unknown"`` (never 0)."""
    inputs = inputs or {}
    baseline = _decimal(inputs.get("baseline_minutes"))
    review = _decimal(inputs.get("human_review_minutes"))
    delivery = _decimal(inputs.get("delivery_cost"))
    method = inputs.get("comparison_method")
    method = method if method in COMPARISON_METHODS else None
    if baseline is not None and review is not None:
        savings: Any = float(baseline - review)
        status = "computed"
    else:
        savings, status = "unknown", "unknown"
    return {
        "baseline_minutes": float(baseline) if baseline is not None else None,
        "human_review_minutes": float(review) if review is not None else None,
        "delivery_cost": str(delivery) if delivery is not None else None,
        "comparison_method": method,
        "savings_minutes": savings,
        "savings_status": status,
        "supplied_by": "human" if any(v is not None for v in (baseline, review, delivery, method)) else None,
    }


# --- cost --------------------------------------------------------------------------------------

CostEstimator = Callable[[str, str, str, dict], tuple[Optional[Decimal], str, str]]


def usage_pricing_estimator(model: str, provider: str, base_url: str, tokens: dict
                            ) -> tuple[Optional[Decimal], str, str]:
    """Estimate via ``agent.usage_pricing``; returns ``(amount_usd, status, source)``."""
    try:
        from agent.usage_pricing import CanonicalUsage, estimate_usage_cost
        usage = CanonicalUsage(
            input_tokens=tokens["input"], output_tokens=tokens["output"],
            cache_read_tokens=tokens["cache_read"], cache_write_tokens=tokens["cache_write"],
            reasoning_tokens=tokens["reasoning"], request_count=tokens["requests"])
        result = estimate_usage_cost(model, usage, provider=provider or None, base_url=base_url or None)
    except Exception:  # pricing lookups can fail many ways; an unpriced run is "unknown", not a crash
        logger.debug("venus-evidence cost estimate failed", exc_info=True)
        return None, "unknown", "none"
    if result.amount_usd is None or result.status not in ("estimated", "included", "actual"):
        return None, "unknown", str(result.source or "none")
    return result.amount_usd, ("reported" if result.status == "actual" else result.status), str(result.source)


@dataclass
class _RouteUsage:
    tokens: dict = field(default_factory=lambda: dict.fromkeys(
        ("input", "output", "cache_read", "cache_write", "reasoning", "requests"), 0))
    reported_usd: Decimal = Decimal(0)
    reported_calls: int = 0
    calls_without_usage: int = 0


def _cost_block(routes: dict, estimator: CostEstimator) -> dict:
    if not routes:
        return {"amount_usd": None, "status": "unknown", "source": "none"}
    total, statuses, sources = Decimal(0), set(), set()
    for (model, provider, base_url), usage in routes.items():
        if usage.calls_without_usage:
            return {"amount_usd": None, "status": "unknown", "source": "missing_usage"}
        if usage.reported_calls == usage.tokens["requests"]:
            total += usage.reported_usd
            statuses.add("reported")
            sources.add("provider_reported")
            continue
        amount, status, source = estimator(model, provider, base_url, dict(usage.tokens))
        if amount is None:
            return {"amount_usd": None, "status": "unknown", "source": source or "none"}
        total += amount
        statuses.add(status)
        sources.add(source)
    status = statuses.pop() if len(statuses) == 1 else "estimated"
    return {"amount_usd": str(total), "status": status, "source": ",".join(sorted(sources))}


# --- accumulator -------------------------------------------------------------------------------

class RunAccumulator:
    """Aggregates one run's observer events into a metadata-only record."""

    def __init__(self, session_id: str, *, source: str = "measured_runtime", now: Optional[float] = None):
        if source not in SOURCES:
            raise ValueError(f"unknown evidence source: {source!r}")
        self.session_id = safe_name(session_id)
        self.source = source
        self.started_at = now if now is not None else time.time()
        self.last_seen = time.monotonic()
        self.api_ok = self.api_errors = self.api_retries = 0
        self.latency_ms_total = self.latency_ms_max = 0
        self.routes: dict[tuple[str, str, str], _RouteUsage] = {}
        self.tool_counts = dict.fromkeys(TOOL_OUTCOMES, 0)
        self.tool_events = BoundedBuffer(MAX_TOOL_EVENTS)
        self.approval_events = BoundedBuffer(MAX_APPROVAL_EVENTS)
        self.route_suggestions = BoundedBuffer(MAX_ROUTE_SUGGESTIONS)
        self.pending_denials = 0
        self.model = self.platform = ""

    def _touch(self) -> None:
        self.last_seen = time.monotonic()

    def _latency(self, api_duration: Any) -> None:
        ms = _ms(api_duration)
        if ms is not None:
            self.latency_ms_total += ms
            self.latency_ms_max = max(self.latency_ms_max, ms)

    def add_api_success(self, *, model: Any = "", provider: Any = "", base_url: Any = "",
                        api_duration: Any = None, usage: Any = None, platform: Any = "") -> None:
        self._touch()
        self.api_ok += 1
        self._latency(api_duration)
        self.model = safe_name(model) or self.model
        self.platform = safe_name(platform, 32) or self.platform
        key = (safe_name(model), safe_name(provider, 64), safe_name(base_url, 256))
        route = self.routes.setdefault(key, _RouteUsage())
        route.tokens["requests"] += 1
        if not isinstance(usage, dict):
            route.calls_without_usage += 1
            return
        for bucket, field_name in (("input", "input_tokens"), ("output", "output_tokens"),
                                   ("cache_read", "cache_read_tokens"), ("cache_write", "cache_write_tokens"),
                                   ("reasoning", "reasoning_tokens")):
            route.tokens[bucket] += _int(usage.get(field_name))
        reported = _decimal(usage.get("cost_usd", usage.get("cost")))
        if reported is not None:
            route.reported_usd += reported
            route.reported_calls += 1

    def add_api_error(self, *, api_duration: Any = None, retryable: Any = None) -> None:
        self._touch()
        self.api_errors += 1
        if retryable:
            self.api_retries += 1
        self._latency(api_duration)

    def add_tool(self, *, tool_name: Any, status: Any, result: Any = None, duration_ms: Any = None) -> str:
        self._touch()
        observer_ok = str(status or "").lower() == "ok"
        outcome = classify_tool(status, result, approval_denied=self.pending_denials > 0 and not observer_ok)
        if outcome == "denied" and self.pending_denials:
            self.pending_denials -= 1
        self.tool_counts[outcome] += 1
        self.tool_events.add({"name": safe_name(tool_name), "outcome": outcome,
                              "duration_ms": _int(duration_ms) if duration_ms is not None else None})
        return outcome

    def add_approval(self, *, kind: Any, outcome: Any, wait_ms: Optional[int]) -> None:
        self._touch()
        kind_token = safe_token(kind)
        decision = approval_decision(kind_token, outcome)
        if kind_token == "approval" and decision == "denied":
            self.pending_denials += 1
        self.approval_events.add({"kind": kind_token, "outcome": decision, "wait_ms": wait_ms})

    def add_route_suggestion(self, item: dict) -> None:
        self._touch()
        self.route_suggestions.add(item)

    def _tokens(self) -> dict:
        totals = dict.fromkeys(("input", "output", "cache_read", "cache_write", "reasoning"), 0)
        missing = 0
        for usage in self.routes.values():
            missing += usage.calls_without_usage
            for bucket in totals:
                totals[bucket] += usage.tokens[bucket]
        totals["total"] = totals["input"] + totals["output"] + totals["cache_read"] + totals["cache_write"]
        totals["calls_without_usage"] = missing
        totals["complete"] = bool(self.routes) and missing == 0
        return totals

    def finalize(self, *, completed: Any = None, failed: Any = None, interrupted: Any = None,
                 turn_exit_reason: Any = None, task_id: Any = "", turn_id: Any = "",
                 value_inputs: Optional[dict] = None, dropped_records: int = 0,
                 estimator: CostEstimator = usage_pricing_estimator, now: Optional[float] = None) -> dict:
        ended = now if now is not None else time.time()
        approvals = self.approval_events.items
        return {
            "schema": SCHEMA,
            "record_id": uuid.uuid4().hex,
            "session_id": self.session_id,
            "task_id": safe_name(task_id),
            "turn_id": safe_name(turn_id),
            "platform": self.platform,
            "model": self.model,
            "provenance": {"source": self.source, "plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION,
                           "started_at": utc_iso(self.started_at), "ended_at": utc_iso(ended),
                           "recorded_at": utc_iso()},
            "outcome": {"status": run_outcome(completed=completed, failed=failed, interrupted=interrupted,
                                              api_ok=self.api_ok, api_errors=self.api_errors),
                        "exit_reason": safe_token(turn_exit_reason) if turn_exit_reason else None,
                        "duration_ms": _ms(ended - self.started_at)},
            "api": {"attempts": self.api_ok + self.api_errors, "succeeded": self.api_ok,
                    "errors": self.api_errors, "retries": self.api_retries,
                    "latency_ms_total": self.latency_ms_total, "latency_ms_max": self.latency_ms_max},
            "tokens": self._tokens(),
            "cost": _cost_block(self.routes, estimator),
            "tools": {"total": sum(self.tool_counts.values()), **self.tool_counts,
                      "calls": list(self.tool_events.items), "dropped": self.tool_events.dropped},
            "approvals": {"total": len(approvals) + self.approval_events.dropped,
                          "wait_ms_total": sum(e["wait_ms"] or 0 for e in approvals),
                          "events": list(approvals), "dropped": self.approval_events.dropped},
            "route_suggestions": {"items": list(self.route_suggestions.items),
                                  "dropped": self.route_suggestions.dropped},
            "value": value_block(value_inputs),
            "buffer": {"dropped_events": (self.tool_events.dropped + self.approval_events.dropped
                                          + self.route_suggestions.dropped),
                       "dropped_records": int(dropped_records)},
        }


def route_suggestion(route: Any, confidence: Any, source: Any) -> dict:
    """Validate a provisional route suggestion into a log item. Pure: it creates nothing."""
    if route not in ROUTES:
        raise ValueError(f"route must be one of {sorted(ROUTES)}, got {route!r}")
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        conf = None
    if conf is not None and not 0.0 <= conf <= 1.0:
        conf = None
    return {"route": route, "confidence": conf, "source": safe_token(source, 48),
            "provisional": True, "at": utc_iso()}

