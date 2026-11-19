"""``/venus-value``: a person supplies comparison figures for a recorded run.

The run record is never rewritten. Each entry appends an amendment record that carries the fields
given now plus the value block recomputed from every amendment for that run, so savings stay
``"unknown"`` until both baseline and review minutes have been supplied.
"""

from __future__ import annotations

import re
import shlex
import uuid
from decimal import Decimal, InvalidOperation
from typing import Optional

from . import evidence as ev
from .storage import EvidenceSink

AMENDMENT_SCHEMA = "venus.evidence.amendment.v1"
_RECORD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_NUMERIC = ("baseline_minutes", "human_review_minutes", "delivery_cost")
FIELDS = (*_NUMERIC, "comparison_method")

USAGE = (
    "usage: /venus-value <record_id> [baseline_minutes=N] [human_review_minutes=N] "
    "[delivery_cost=N] [comparison_method=manual|existing_ai_tool]\n"
    "With no fields, shows the run's current value block."
)


def parse_fields(tokens: list[str]) -> dict:
    """``key=value`` tokens to validated fields; raises ``ValueError`` with a user-facing reason."""
    fields: dict = {}
    for token in tokens:
        key, sep, raw = token.partition("=")
        if not sep or key not in FIELDS:
            raise ValueError(f"unknown field {key!r}; expected one of: {', '.join(FIELDS)}")
        if key == "comparison_method":
            if raw not in ev.COMPARISON_METHODS:
                raise ValueError(f"comparison_method must be one of: {', '.join(sorted(ev.COMPARISON_METHODS))}")
            fields[key] = raw
            continue
        try:
            number = Decimal(raw)
        except InvalidOperation:
            raise ValueError(f"{key} must be a number, got {raw!r}") from None
        if not number.is_finite() or number < 0:
            raise ValueError(f"{key} must be a non-negative number")
        fields[key] = str(number)
    return fields


def _history(sink: EvidenceSink, record_id: str) -> tuple[Optional[dict], dict]:
    """The run record and the inputs merged from its own value block and every amendment."""
    run, merged = None, {}
    for record in sink.read_all():
        if record.get("schema") == ev.SCHEMA and record.get("record_id") == record_id:
            run = record
            merged.update({k: v for k, v in (record.get("value") or {}).items() if k in FIELDS and v is not None})
        elif record.get("schema") == AMENDMENT_SCHEMA and record.get("amends_record_id") == record_id:
            merged.update(record.get("fields") or {})
    return run, merged


def amend_value(sink: EvidenceSink, record_id: str, fields: dict) -> dict:
    """Append one amendment for ``record_id``; raises ``LookupError`` for an unknown run."""
    run, merged = _history(sink, record_id)
    if run is None:
        raise LookupError(f"no evidence record with id {record_id}")
    merged.update(fields)
    amendment = {
        "schema": AMENDMENT_SCHEMA,
        "record_id": uuid.uuid4().hex,
        "amends_record_id": record_id,
        "session_id": run.get("session_id", ""),
        "fields": dict(fields),
        "value": ev.value_block(merged),
        "provenance": {"source": "human_input", "plugin": ev.PLUGIN_NAME,
                       "plugin_version": ev.PLUGIN_VERSION, "recorded_at": ev.utc_iso()},
    }
    sink.write(amendment)
    return amendment


def _describe(value: dict) -> str:
    shown = ", ".join(f"{k}={value.get(k) if value.get(k) is not None else 'unset'}" for k in FIELDS)
    return f"{shown}; savings_minutes={value['savings_minutes']} ({value['savings_status']})"


def handle(raw_args: str, sink: EvidenceSink) -> str:
    try:
        tokens = shlex.split(raw_args or "")
    except ValueError as exc:
        return f"venus-value: {exc}\n{USAGE}"
    if not tokens or not _RECORD_ID_RE.fullmatch(tokens[0]):
        return USAGE
    record_id = tokens[0]
    try:
        fields = parse_fields(tokens[1:])
        if not fields:
            run, merged = _history(sink, record_id)
            if run is None:
                raise LookupError(f"no evidence record with id {record_id}")
            return f"venus-value {record_id}: {_describe(ev.value_block(merged))}"
        amendment = amend_value(sink, record_id, fields)
    except (ValueError, LookupError) as exc:
        return f"venus-value: {exc}"
    except OSError as exc:
        return f"venus-value: could not write the amendment ({exc.__class__.__name__})"
    return f"venus-value {record_id}: amendment {amendment['record_id']} saved; {_describe(amendment['value'])}"
