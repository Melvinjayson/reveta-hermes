"""OpenLineage-shaped envelope for evidence records, built natively (no OpenLineage dependency).

A finished run record keeps its ``venus.evidence.v1`` body (so ``/venus-value`` and old readers keep
working) and gains a run-event envelope: ``eventType``, ``eventTime``, ``schema_version``,
``producer``, ``run.runId`` (= ``record_id``), ``job`` and ``run.facets``. Two facets:

* ``provenance``: which environment produced the record (fixture | local | preview | live) and how
  that was decided. Environments never mix: only ``live`` can grade as evidence.
* ``evidence``: every metric as ``{value, label, source}``; ``label`` is measured | estimated |
  user_reported | unknown. Unknown carries ``value: None`` — never 0.

``evidence_facet`` also runs over pre-envelope v1 bodies, so old records stay readable.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

from . import evidence as ev

SCHEMA_VERSION = "venus.run_event.v1"
PROVENANCE_FACET = "venus.provenance_facet.v1"
EVIDENCE_FACET = "venus.evidence_facet.v1"
JOB = {"namespace": "reveta.venus", "name": "hermes.run_conversation"}
EVENT_TYPES = ("START", "COMPLETE", "FAIL", "ABORT")
ENVIRONMENTS = ("fixture", "local", "preview", "live")
LABELS = ("measured", "estimated", "user_reported", "unknown")

# shortcut: only the terminal event is written (no START line), so a run that dies before
# on_session_end leaves no record; write a START from EvidenceRecorder._open when crashed runs matter.
_EVENT_FOR_OUTCOME = {"completed": "COMPLETE", "failed": "FAIL", "partial": "ABORT", "unknown": "ABORT"}
# usage_pricing's vocabulary; v1 bodies wrote a provider-reported cost as "reported".
_COST_STATUS = {"reported": "actual", "actual": "actual", "estimated": "estimated", "included": "included"}
_COST_LABEL = {"actual": "measured", "estimated": "estimated", "included": "estimated", "unknown": "unknown"}
_HOOKS = "observer_hooks"


def event_type_for(outcome_status: Any) -> str:
    return _EVENT_FOR_OUTCOME.get(outcome_status, "ABORT")


def resolve_environment(source: str, environ: Optional[Mapping[str, str]] = None) -> tuple[str, str]:
    """``(environment, decided_by)``. Fixture data is always ``fixture``; an unrecognised
    ``VENUS_EVIDENCE_ENV`` resolves to ``local`` so a typo can never promote a run to live."""
    environ = os.environ if environ is None else environ
    if source == "fixture":
        return "fixture", "evidence_source"
    explicit = str(environ.get("VENUS_EVIDENCE_ENV") or "").strip().lower()
    if explicit:
        return (explicit if explicit in ENVIRONMENTS else "local"), "VENUS_EVIDENCE_ENV"
    if str(environ.get("IS_PULL_REQUEST") or "").strip().lower() == "true":
        return "preview", "IS_PULL_REQUEST"
    if environ.get("RENDER"):
        return "live", "RENDER"
    return "local", "default"


def git_commit(environ: Optional[Mapping[str, str]] = None) -> str:
    environ = os.environ if environ is None else environ
    commit = ev.safe_token(environ.get("RENDER_GIT_COMMIT") or "", 40)
    return commit[:7] if commit != "other" else "unknown"


def producer(environ: Optional[Mapping[str, str]] = None) -> str:
    return f"{ev.PLUGIN_NAME}/{ev.PLUGIN_VERSION}+{git_commit(environ)}"


def _metric(value: Any, label: str, source: str, **extra: Any) -> dict:
    if label == "unknown":
        value = None
    return {"value": value, "label": label, "source": source, **extra}


def _known(value: Any, source: str = _HOOKS) -> dict:
    return _metric(value, "measured" if value is not None else "unknown", source)


def _d(body: Mapping, key: str) -> Mapping:
    value = body.get(key)
    return value if isinstance(value, Mapping) else {}


def cost_metric(cost: Mapping) -> dict:
    status = _COST_STATUS.get(cost.get("status"), "unknown")
    amount = cost.get("amount_usd") if status != "unknown" else None
    if amount is None:
        status = "unknown"
    return _metric(amount, _COST_LABEL[status], str(cost.get("source") or "none"), status=status)


def _human_minutes(value: Mapping, key: str) -> dict:
    amount = ev._decimal(value.get(key))
    if amount is None:
        return _metric(None, "unknown", "none")
    return _metric(float(amount), "user_reported", "human_input")


def evidence_facet(body: Mapping) -> dict:
    """Metrics of one v1 body. Runtime counts are measured by the observer hooks; tokens are
    unknown unless every API call reported usage; human minutes are user_reported or unknown."""
    outcome, api, tokens, tools = _d(body, "outcome"), _d(body, "api"), _d(body, "tokens"), _d(body, "tools")
    approvals, value = _d(body, "approvals"), _d(body, "value")
    status = outcome.get("status")
    metrics = {
        "outcome": _known(status if status in ev.RUN_OUTCOMES and status != "unknown" else None),
        "duration_ms": _known(outcome.get("duration_ms")),
        "api_attempts": _known(api.get("attempts")),
        "api_errors": _known(api.get("errors")),
        "tokens_total": _known(tokens.get("total") if tokens.get("complete") is True else None),
        "tool_calls": _known(tools.get("total")),
        "approvals": _known(approvals.get("total")),
        "approval_wait_ms": _known(approvals.get("wait_ms_total")),
        "cost_usd": cost_metric(_d(body, "cost")),
        "baseline_minutes": _human_minutes(value, "baseline_minutes"),
        "human_review_minutes": _human_minutes(value, "human_review_minutes"),
    }
    return {"_schema": EVIDENCE_FACET, "metrics": metrics}


def envelope(body: dict, environ: Optional[Mapping[str, str]] = None) -> dict:
    """Add the run-event envelope to a finalized v1 body (mutates and returns it)."""
    prov = _d(body, "provenance")
    environment, decided_by = resolve_environment(str(prov.get("source") or ""), environ)
    body.update({
        "schema_version": SCHEMA_VERSION,
        "eventType": event_type_for(_d(body, "outcome").get("status")),
        "eventTime": prov.get("ended_at") or ev.utc_iso(),
        "producer": producer(environ),
        "job": dict(JOB),
        "run": {"runId": body.get("record_id"), "facets": {
            "provenance": {"_schema": PROVENANCE_FACET, "environment": environment,
                           "decided_by": decided_by, "source": prov.get("source"),
                           "git_commit": git_commit(environ)},
            "evidence": evidence_facet(body),
        }},
    })
    return body
