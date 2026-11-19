"""venus-evidence — one metadata-only evidence record per Hermes run.

Observer only: every callback returns ``None``, swallows its own errors and never approves,
blocks, modifies or dispatches anything. Opt-in like every bundled plugin
(``hermes plugins enable venus-evidence``). Records land in
``<hermes home>/plugin-data/venus-evidence/evidence-YYYY-MM-DD.jsonl``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from . import evidence as ev
from .storage import EvidenceSink, JsonlDailySink

logger = logging.getLogger(__name__)

MAX_OPEN_RUNS = 128
MAX_PENDING_HUMAN_INPUTS = 128
MAX_PENDING_WRITES = 100
_VALUE_FIELDS = ("baseline_minutes", "human_review_minutes", "delivery_cost", "comparison_method")


class EvidenceRecorder:
    """Thread-safe owner of open runs; observer hooks fire on worker threads concurrently."""

    def __init__(self, sink: Optional[EvidenceSink] = None, estimator: ev.CostEstimator = ev.usage_pricing_estimator):
        self.sink: EvidenceSink = sink or JsonlDailySink()
        self.estimator = estimator
        self._lock = threading.Lock()
        self._runs: dict[str, ev.RunAccumulator] = {}
        self._human: dict[str, tuple[float, str]] = {}
        self._values: dict[str, dict] = {}
        self._pending = ev.BoundedBuffer(MAX_PENDING_WRITES)
        self._dropped_records = 0
        self._unattributed = 0

    # -- run lookup ---------------------------------------------------------------------------
    def begin_run(self, session_id: str, *, source: str = "measured_runtime") -> ev.RunAccumulator:
        with self._lock:
            return self._open(session_id, source=source)

    def _open(self, session_id: str, *, source: str = "measured_runtime") -> ev.RunAccumulator:
        run = self._runs.get(session_id)
        if run is None:
            if len(self._runs) >= MAX_OPEN_RUNS:
                oldest = min(self._runs, key=lambda sid: self._runs[sid].last_seen)
                del self._runs[oldest]
                self._dropped_records += 1
            run = self._runs[session_id] = ev.RunAccumulator(session_id, source=source)
        return run

    def _attributed(self, session_id: Any) -> Optional[ev.RunAccumulator]:
        """Human-input hooks may lack a session id; attribute only when exactly one run is open."""
        if session_id:
            return self._open(str(session_id))
        if len(self._runs) == 1:
            return next(iter(self._runs.values()))
        self._unattributed += 1
        return None

    # -- observer events ------------------------------------------------------------------------
    def on_api_success(self, kw: dict) -> None:
        with self._lock:
            self._open(str(kw.get("session_id") or "")).add_api_success(
                model=kw.get("model"), provider=kw.get("provider"), base_url=kw.get("base_url"),
                api_duration=kw.get("api_duration"), usage=kw.get("usage"), platform=kw.get("platform"))

    def on_api_error(self, kw: dict) -> None:
        with self._lock:
            self._open(str(kw.get("session_id") or "")).add_api_error(
                api_duration=kw.get("api_duration"), retryable=kw.get("retryable"))

    def on_tool(self, kw: dict) -> None:
        with self._lock:
            run = self._attributed(kw.get("session_id"))
            if run is not None:
                run.add_tool(tool_name=kw.get("tool_name"), status=kw.get("status"),
                             result=kw.get("result"), duration_ms=kw.get("duration_ms"))

    def on_human_request(self, kw: dict) -> None:
        request_id = str(kw.get("request_id") or "")
        if not request_id:
            return
        with self._lock:
            if len(self._human) >= MAX_PENDING_HUMAN_INPUTS:
                self._human.pop(next(iter(self._human)))
                self._unattributed += 1
            self._human[request_id] = (time.monotonic(), str(kw.get("session_id") or ""))

    def on_human_resolved(self, kw: dict) -> None:
        with self._lock:
            started = self._human.pop(str(kw.get("request_id") or ""), None)
            wait_ms = int((time.monotonic() - started[0]) * 1000) if started else None
            run = self._attributed(kw.get("session_id") or (started[1] if started else ""))
            if run is not None:
                run.add_approval(kind=kw.get("kind"), outcome=kw.get("outcome"), wait_ms=wait_ms)

    def on_session_end(self, kw: dict) -> Optional[dict]:
        session_id = str(kw.get("session_id") or "")
        with self._lock:
            run = self._runs.pop(session_id, None)
            if run is None:
                return None
            record = run.finalize(
                completed=kw.get("completed"), failed=kw.get("failed"), interrupted=kw.get("interrupted"),
                turn_exit_reason=kw.get("turn_exit_reason"), task_id=kw.get("task_id"),
                turn_id=kw.get("turn_id"), value_inputs=self._values.pop(session_id, None),
                dropped_records=self._dropped_records + self._pending.dropped, estimator=self.estimator)
            record["buffer"]["unattributed_events"] = self._unattributed
            if not record["model"]:
                record["model"] = ev.safe_name(kw.get("model"))
            self._write(record)
        return record

    def _write(self, record: dict) -> None:
        backlog = self._pending.drain() + [record]
        for index, item in enumerate(backlog):
            try:
                self.sink.write(item)
            except Exception:
                logger.debug("venus-evidence write failed; buffering", exc_info=True)
                for unsent in backlog[index:]:
                    self._pending.add(unsent)
                return

    # -- human-supplied / provisional inputs ----------------------------------------------------
    def set_value_inputs(self, session_id: str, **inputs: Any) -> None:
        unknown = set(inputs) - set(_VALUE_FIELDS)
        if unknown:
            raise ValueError(f"unknown value fields: {sorted(unknown)}")
        with self._lock:
            self._values.setdefault(session_id, {}).update(inputs)

    def record_route_suggestion(self, route: str, confidence: Any, source: str, *, session_id: str = "") -> None:
        item = ev.route_suggestion(route, confidence, source)
        logger.info("venus-evidence route suggestion (provisional, no action): route=%s confidence=%s source=%s",
                    item["route"], item["confidence"], item["source"])
        with self._lock:
            run = self._attributed(session_id)
            if run is not None:
                run.add_route_suggestion(item)


_recorder = EvidenceRecorder()


def get_recorder() -> EvidenceRecorder:
    return _recorder


def record_route_suggestion(route: str, confidence: Any, source: str, *, session_id: str = "") -> None:
    """Log a provisional routing guess (conversation / clarify / tool). Logging only: it never
    creates tasks or goals, calls tools, or contacts a router."""
    _recorder.record_route_suggestion(route, confidence, source, session_id=session_id)


def _observer(method_name: str):
    def callback(**kwargs: Any) -> None:
        try:
            getattr(_recorder, method_name)(kwargs)
        except Exception:
            logger.debug("venus-evidence %s failed", method_name, exc_info=True)
        return None
    callback.__name__ = f"_venus_{method_name}"
    return callback


_HOOKS = {
    "post_api_request": _observer("on_api_success"),
    "api_request_error": _observer("on_api_error"),
    "post_tool_call": _observer("on_tool"),
    "on_human_input_request": _observer("on_human_request"),
    "on_human_input_resolved": _observer("on_human_resolved"),
    "on_session_end": _observer("on_session_end"),
}


def register(ctx) -> None:
    for hook_name, callback in _HOOKS.items():
        ctx.register_hook(hook_name, callback)
