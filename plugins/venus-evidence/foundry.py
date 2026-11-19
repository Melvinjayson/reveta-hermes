"""Data Foundry rules: which Venus evidence records count, and as what.

Pure functions over stored records (no I/O). The rules:

* every value has provenance — a record without a provenance facet is ``not_evidence``;
* a model repeating a claim does not verify it — value figures count only as ``user_reported``
  human input, and a value claim needs a separate human sign-off attestation;
* missing stays missing — unknown metrics are unscored (``Score.unscored``), never 0, and
  totals skip them and say how many were skipped;
* fixture / local / preview / live never mix — only ``live`` records grade above ``not_evidence``.

Human sign-off is an in-toto-style Statement, never a flag on the record: its subject is the
sha256 of the canonical run record (and of the run's amendment list), so any edit after
sign-off shows as a hash mismatch.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from . import evidence as ev
from . import lineage
from .value_cmd import AMENDMENT_SCHEMA

logger = logging.getLogger(__name__)

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
SIGNOFF_PREDICATE = "reveta.dev/venus-signoff/v1"
VERDICTS = ("accept", "reject", "needs_more")
GRADES = ("not_evidence", "runtime_evidence", "value_claim_ready")
# Fields a run must have measured to be runtime evidence. Cost is reported as a gap, not a gate:
# a route usage_pricing cannot price (e.g. a subscription it does not model) would otherwise
# disqualify every run on it.
RUNTIME_METRICS = ("outcome", "duration_ms", "api_attempts", "tokens_total", "tool_calls", "approvals")
_SUBJECT_PREFIX = "venus-run/"


@dataclass(frozen=True)
class Score:
    """A metric outcome that is either a number or explicitly unscored (Inspect AI style)."""

    value: Optional[float]
    scored: bool
    reason: str = ""

    @classmethod
    def of(cls, value: float) -> Score:
        return cls(float(value), True)

    @classmethod
    def unscored(cls, reason: str) -> Score:
        return cls(None, False, reason)

    def to_dict(self) -> dict:
        return {"value": self.value, "scored": self.scored, "reason": self.reason or None}


def total(scores: Iterable[Score]) -> dict:
    """Sum of scored values; unscored items are skipped and counted, never added as 0."""
    values, skipped = [], 0
    for score in scores:
        if score.scored:
            values.append(score.value)
        else:
            skipped += 1
    return {"sum": sum(values) if values else None, "count": len(values), "skipped": skipped,
            "mean": (sum(values) / len(values)) if values else None}


# --- canonical hashing and sign-off --------------------------------------------------------------

def canonical_sha256(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_id_of(record: Mapping) -> str:
    run = record.get("run")
    if isinstance(run, Mapping) and isinstance(run.get("runId"), str):
        return run["runId"]
    return str(record.get("record_id") or "")


def signoff_statement(record: Mapping, amendments: list, *, verdict: str, reviewer: str,
                      minutes: Optional[Decimal] = None, note: str = "") -> dict:
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of: {', '.join(VERDICTS)}")
    run_id = run_id_of(record)
    return {
        "_type": STATEMENT_TYPE,
        "subject": [
            {"name": f"{_SUBJECT_PREFIX}{run_id}", "digest": {"sha256": canonical_sha256(record)}},
            {"name": f"{_SUBJECT_PREFIX}{run_id}/amendments", "digest": {"sha256": canonical_sha256(amendments)}},
        ],
        "predicateType": SIGNOFF_PREDICATE,
        "predicate": {"verdict": verdict, "reviewer": ev.safe_name(reviewer, 128) or "unknown",
                      "minutes": str(minutes) if minutes is not None else None,
                      "note": ev.safe_name(note, 500), "signed_at": ev.utc_iso()},
    }


def is_signoff(record: Mapping) -> bool:
    return record.get("_type") == STATEMENT_TYPE and record.get("predicateType") == SIGNOFF_PREDICATE


def _subject_digests(statement: Mapping) -> dict:
    digests = {}
    for item in statement.get("subject") or []:
        if isinstance(item, Mapping) and isinstance(item.get("digest"), Mapping):
            digests[str(item.get("name"))] = item["digest"].get("sha256")
    return digests


def signoff_run_id(statement: Mapping) -> str:
    for name in _subject_digests(statement):
        if name.startswith(_SUBJECT_PREFIX) and not name.endswith("/amendments"):
            return name[len(_SUBJECT_PREFIX):]
    return ""


def signoff_matches(statement: Mapping, record: Mapping, amendments: list) -> bool:
    run_id = run_id_of(record)
    digests = _subject_digests(statement)
    return (digests.get(f"{_SUBJECT_PREFIX}{run_id}") == canonical_sha256(record)
            and digests.get(f"{_SUBJECT_PREFIX}{run_id}/amendments") == canonical_sha256(amendments))


# --- grouping stored lines --------------------------------------------------------------------------

def is_run_record(record: Mapping) -> bool:
    return record.get("schema") == ev.SCHEMA or record.get("schema_version") == lineage.SCHEMA_VERSION


def index(records: Iterable[Mapping]) -> list[tuple[Mapping, list, list]]:
    """``(run_record, amendments, signoffs)`` per run, in first-seen order. A later event for the
    same run (a terminal after a START) replaces the earlier one."""
    runs: dict[str, Mapping] = {}
    amendments: dict[str, list] = {}
    signoffs: dict[str, list] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if is_signoff(record):
            signoffs.setdefault(signoff_run_id(record), []).append(record)
        elif record.get("schema") == AMENDMENT_SCHEMA:
            amendments.setdefault(str(record.get("amends_record_id") or ""), []).append(record)
        elif is_run_record(record) and run_id_of(record):
            runs[run_id_of(record)] = record
    return [(run, amendments.get(rid, []), signoffs.get(rid, [])) for rid, run in runs.items()]


# --- assessment -------------------------------------------------------------------------------------

def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _provenance(record: Mapping) -> Optional[str]:
    facet = _mapping(_mapping(_mapping(record.get("run")).get("facets")).get("provenance"))
    env = facet.get("environment")
    return env if env in lineage.ENVIRONMENTS else None


def _metrics(record: Mapping) -> dict:
    facet = _mapping(_mapping(_mapping(record.get("run")).get("facets")).get("evidence"))
    stored = facet.get("metrics")
    # Old records (no facet) and malformed facets fall back to deriving it from the v1 body.
    base = stored if isinstance(stored, Mapping) and stored else lineage.evidence_facet(record)["metrics"]
    metrics = {}
    for name, metric in base.items():
        metric = _mapping(metric)
        label = metric.get("label") if metric.get("label") in lineage.LABELS else "unknown"
        metrics[str(name)] = {**metric, "label": label, "value": metric.get("value") if label != "unknown" else None}
    return metrics


def _apply_amendments(metrics: dict, amendments: list) -> None:
    """``/venus-value`` amendments are human input: they stay user_reported, latest wins."""
    for amendment in amendments:
        for key, raw in _mapping(_mapping(amendment).get("fields")).items():
            amount = ev._decimal(raw)
            if key in ("baseline_minutes", "human_review_minutes") and amount is not None:
                metrics[key] = {"value": float(amount), "label": "user_reported", "source": "venus-value"}


def _event_type(record: Mapping) -> Optional[str]:
    event = record.get("eventType")
    if event in lineage.EVENT_TYPES:
        return event
    status = _mapping(record.get("outcome")).get("status")
    return lineage.event_type_for(status) if status in ev.RUN_OUTCOMES and status != "unknown" else None


def _latest_signoff(record: Mapping, amendments: list, signoffs: list) -> Optional[dict]:
    if not signoffs:
        return None
    latest = _mapping(signoffs[-1])
    predicate = _mapping(latest.get("predicate"))
    return {"verdict": predicate.get("verdict"), "minutes": ev._decimal(predicate.get("minutes")),
            "matches": signoff_matches(latest, record, amendments)}


def _gaps(record: Mapping, metrics: dict, env: Optional[str], event: Optional[str],
          signoff: Optional[dict]) -> list[str]:
    buffer = _mapping(record.get("buffer"))
    checks = (
        ("no_terminal_event", event not in ("COMPLETE", "FAIL")),
        ("unattributed_human_input", bool(buffer.get("unattributed_events"))),
        ("dropped_records", bool(buffer.get("dropped_records"))),
        ("cost_unknown", metrics.get("cost_usd", {}).get("label", "unknown") == "unknown"),
        ("no_baseline", metrics.get("baseline_minutes", {}).get("label") != "user_reported"),
        ("no_review_minutes", metrics.get("human_review_minutes", {}).get("label") != "user_reported"),
        ("no_provenance", env is None),
        ("signoff_hash_mismatch", signoff is not None and not signoff["matches"]),
    )
    return [name for name, failed in checks if failed]


def _grade(env: Optional[str], event: Optional[str], metrics: dict, gaps: list, signoff: Optional[dict]) -> str:
    if env != "live":
        return "not_evidence"
    runtime_complete = (event in ("COMPLETE", "FAIL")
                        and all(metrics.get(m, {}).get("label", "unknown") != "unknown" for m in RUNTIME_METRICS)
                        and not {"unattributed_human_input", "dropped_records"} & set(gaps))
    if not runtime_complete:
        return "not_evidence"
    accepted = signoff is not None and signoff["matches"] and signoff["verdict"] == "accept"
    if event == "COMPLETE" and accepted and not {"no_baseline", "no_review_minutes"} & set(gaps):
        return "value_claim_ready"
    return "runtime_evidence"


def _time_saved(grade: str, metrics: dict) -> Score:
    if grade != "value_claim_ready":
        return Score.unscored(f"grade is {grade}")
    return Score.of(metrics["baseline_minutes"]["value"] - metrics["human_review_minutes"]["value"])


def _assess(record: Mapping, amendments: list, signoffs: list) -> dict:
    env = _provenance(record)
    metrics = _metrics(record)
    _apply_amendments(metrics, amendments)
    signoff = _latest_signoff(record, amendments, signoffs)
    if (signoff and signoff["matches"] and signoff["verdict"] == "accept" and signoff["minutes"] is not None
            and metrics.get("human_review_minutes", {}).get("label") != "user_reported"):
        # The reviewer's own minutes on an accepted sign-off are human review time.
        metrics["human_review_minutes"] = {"value": float(signoff["minutes"]), "label": "user_reported",
                                           "source": "signoff"}
    event = _event_type(record)
    gaps = _gaps(record, metrics, env, event, signoff)
    grade = _grade(env, event, metrics, gaps, signoff)
    labels = dict.fromkeys(lineage.LABELS, 0)
    for metric in metrics.values():
        labels[metric["label"]] += 1
    known = len(metrics) - labels["unknown"]
    return {
        "run_id": run_id_of(record), "environment": env, "event_type": event, "grade": grade,
        "completeness_pct": round(100 * known / len(metrics)) if metrics else 0,
        "labels": labels, "metrics": metrics, "capture_gaps": gaps,
        "time_saved_minutes": _time_saved(grade, metrics),
        "signoff": {"verdict": signoff["verdict"], "matches": signoff["matches"]} if signoff else None,
    }


def assess(record: Any, amendments: Any = (), signoffs: Any = ()) -> dict:
    """Grade one run record. Never raises: a malformed record is ``not_evidence``."""
    amendments = [a for a in (amendments or []) if isinstance(a, Mapping)]
    signoffs = [s for s in (signoffs or []) if isinstance(s, Mapping)]
    if isinstance(record, Mapping):
        try:
            return _assess(record, amendments, signoffs)
        except Exception:  # a hand-edited or foreign line must degrade to not_evidence, not crash a listing
            logger.debug("venus-evidence foundry: malformed record", exc_info=True)
    run_id = run_id_of(record) if isinstance(record, Mapping) else ""
    return {"run_id": run_id, "environment": None, "event_type": None, "grade": "not_evidence",
            "completeness_pct": 0, "labels": dict.fromkeys(lineage.LABELS, 0), "metrics": {},
            "capture_gaps": ["malformed_record", "no_provenance"],
            "time_saved_minutes": Score.unscored("malformed record"), "signoff": None}
