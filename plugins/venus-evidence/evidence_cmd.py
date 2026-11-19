"""``/evidence``: list recent runs as the Data Foundry grades them, or sign one off.

Output is metadata only (ids, environment, grade, labels, gaps, minutes); it never shows prompts,
responses, tool payloads, sign-off notes or secrets. A sign-off is appended as its own attestation
record; the run record is never touched.
"""

from __future__ import annotations

import shlex
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from . import foundry
from .storage import EvidenceSink

DEFAULT_LIMIT = 5
MAX_LIMIT = 50
SHORT_ID = 8
USAGE = ("usage: /evidence [N]  (latest N runs, default 5)\n"
         "       /evidence signoff <run> <accept|reject|needs_more> [minutes] [note]")


def _fmt_minutes(score: foundry.Score) -> str:
    return f"{score.value:g} min" if score.scored else "unknown"


def _line(a: dict) -> str:
    labels = " ".join(f"{k}={v}" for k, v in a["labels"].items())
    gaps = ",".join(a["capture_gaps"]) or "none"
    return (f"{a['run_id'][:SHORT_ID] or '?':<8}  {a['environment'] or 'none':<7}  {a['grade']:<17}  "
            f"{a['completeness_pct']:>3}%  {labels}  gaps={gaps}  time_saved={_fmt_minutes(a['time_saved_minutes'])}")


def _footer(assessments: list[dict]) -> str:
    live = [a for a in assessments if a["environment"] == "live"]
    saved = foundry.total(a["time_saved_minutes"] for a in live)
    cost = foundry.total(
        foundry.Score.of(float(a["metrics"]["cost_usd"]["value"]))
        if a["metrics"].get("cost_usd", {}).get("label", "unknown") != "unknown"
        else foundry.Score.unscored("cost unknown") for a in live)
    saved_text = f"{saved['sum']:g} min" if saved["count"] else "unknown"
    cost_text = f"${cost['sum']:.4f}" if cost["count"] else "unknown"
    return (f"live runs: {len(live)} (not counted: {len(assessments) - len(live)} fixture/local/preview/unknown); "
            f"time saved: {saved_text} over {saved['count']} (skipped {saved['skipped']} unscored); "
            f"cost: {cost_text} over {cost['count']} (skipped {cost['skipped']} unknown)")


def list_runs(sink: EvidenceSink, limit: int = DEFAULT_LIMIT) -> str:
    runs = foundry.index(sink.read_all())[-limit:]
    if not runs:
        return "evidence: no runs recorded yet"
    assessments = [foundry.assess(*run) for run in runs]
    header = f"evidence: latest {len(assessments)} run(s)"
    return "\n".join([header, *(_line(a) for a in assessments), _footer(assessments)])


def _find_run(sink: EvidenceSink, ref: str) -> tuple[dict, list]:
    matches = [(run, amendments) for run, amendments, _ in foundry.index(sink.read_all())
               if foundry.run_id_of(run).startswith(ref)]
    if not matches:
        raise LookupError(f"no run matching {ref!r}")
    if len(matches) > 1:
        raise LookupError(f"{ref!r} matches {len(matches)} runs; give more of the id")
    return matches[0]


def _parse_signoff(tokens: list[str]) -> tuple[str, str, Optional[Decimal], str]:
    if len(tokens) < 2:
        raise ValueError(USAGE)
    ref, verdict, rest = tokens[0].lower(), tokens[1].lower(), tokens[2:]
    if len(ref) < SHORT_ID or any(c not in "0123456789abcdef" for c in ref):
        raise ValueError(f"run must be at least {SHORT_ID} hex characters of a run id")
    if verdict not in foundry.VERDICTS:
        raise ValueError(f"verdict must be one of: {', '.join(foundry.VERDICTS)}")
    minutes = None
    if rest:
        try:
            minutes = Decimal(rest[0])
        except InvalidOperation:
            minutes = None  # not a number: the note starts here
        else:
            if not minutes.is_finite() or minutes < 0:
                raise ValueError("minutes must be a non-negative number")
            rest = rest[1:]
    return ref, verdict, minutes, " ".join(rest)


def reviewer_of(source: Any, platform: str = "") -> str:
    """Who signed: the messaging user when the surface knows one, else ``unknown``."""
    # shortcut: CLI/TUI/desktop sources carry no user identity, so their sign-offs read
    # reviewer=unknown; bind a real identity here once those surfaces pass one.
    user = getattr(source, "user_id", None) or getattr(source, "user_name", None)
    platform = platform or str(getattr(getattr(source, "platform", None), "value", "") or "")
    return f"{platform}:{user}" if user and platform else (str(user) if user else "unknown")


def signoff(sink: EvidenceSink, tokens: list[str], reviewer: str) -> str:
    ref, verdict, minutes, note = _parse_signoff(tokens)
    run, amendments = _find_run(sink, ref)
    statement = foundry.signoff_statement(run, amendments, verdict=verdict, reviewer=reviewer,
                                          minutes=minutes, note=note)
    sink.write(statement)
    graded = foundry.assess(run, amendments, [statement])
    return (f"evidence: sign-off {verdict} saved for {foundry.run_id_of(run)[:SHORT_ID]} "
            f"(sha256 {statement['subject'][0]['digest']['sha256'][:12]}); grade={graded['grade']}")


def handle(raw_args: str, sink: EvidenceSink, *, reviewer: str = "unknown") -> str:
    try:
        tokens = shlex.split(raw_args or "")
    except ValueError as exc:
        return f"evidence: {exc}\n{USAGE}"
    try:
        if tokens and tokens[0] == "signoff":
            return signoff(sink, tokens[1:], reviewer)
        if len(tokens) > 1 or (tokens and not tokens[0].isdigit()):
            return USAGE
        limit = int(tokens[0]) if tokens else DEFAULT_LIMIT
        return list_runs(sink, max(1, min(limit, MAX_LIMIT)))
    except (ValueError, LookupError) as exc:
        return f"evidence: {exc}"
    except OSError as exc:
        return f"evidence: could not read or write evidence ({exc.__class__.__name__})"
