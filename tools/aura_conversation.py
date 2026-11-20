"""Aura: follow the user when they step out of the current task (docs/aura/conversation-intelligence.md).

The system prompt already asks the model to read each turn. What it lacks is state across turns: after
"you're not listening" or "forget that, new question", nothing says the running task is paused, so the
model snaps back to it. This module keeps the session's active topic and returns a per-turn note.
tui_gateway/prompt_turn.py prepends it to this turn's model input only (``_prepend_note``): never the
system prompt and never the transcript, so the cached prompt prefix survives.

Deterministic and conservative: a cue counts only at the start of the message. Notes grant nothing;
approvals and the free-only gate are unchanged. Aura only, and the owner can switch it off with
``aura.conversation_notes: false``.
"""

from __future__ import annotations

import re
from typing import Optional

TOPIC_KEY = "aura_topic"
TOPIC_LIMIT = 120

# Cues at the start of a message (after an optional "no,", "ok," or "hey,"). Order matters: the first match wins.
_LEAD = r"^\s*(?:(?:no|nope|ok|okay|hey|wait|hold on|um+|uh+)[,.!]*\s+)*"
CUES: tuple[tuple[str, re.Pattern], ...] = (
    ("correction", re.compile(_LEAD + r"(?:i meant|i mean|that's not what i meant|not that[,.]|what i meant)", re.IGNORECASE)),
    ("meta", re.compile(
        _LEAD + r"(?:you(?:'re| are) not (?:listening|hearing me|getting it)|you keep\b|why do you keep|"
        r"that's not what i (?:asked|said|wanted)|i didn't ask|stop (?:it|that|doing|asking|talking)|"
        r"too long|that was too|this isn't working|this is not working|you're not helping|not helpful|"
        r"let's step back|step back|slow down|listen to me|can you just listen)", re.IGNORECASE)),
    ("shift", re.compile(
        _LEAD + r"(?:actually[,]?\s+(?:let's|can we|i want|different|new|forget)|forget (?:that|it|about)|"
        r"new (?:topic|question)|different (?:topic|question|thing)|change of plan|let's talk about|"
        r"never ?mind|moving on|on another note|something else)", re.IGNORECASE)),
)

NOTES = {
    "meta": ("[Aura context] The user is commenting on how this conversation is going, not asking you to "
             "continue the current task{topic}. Respond to that first, in a sentence or two: acknowledge it "
             "without excuses, change how you answer, and ask what they want next if it is unclear. Do not "
             "resume the task or run tools for it in this reply."),
    "shift": ("[Aura context] The user is changing the subject{topic}. Follow the new request. Do not go back "
              "to the earlier topic or its workflow unless they ask for it."),
    "correction": ("[Aura context] The user is correcting how you understood their request{topic}. Drop your "
                   "previous interpretation completely and follow the corrected one."),
}


def classify(text: str) -> Optional[str]:
    """``"meta"``, ``"shift"``, ``"correction"`` or None for an ordinary turn."""
    if not isinstance(text, str):
        return None
    for kind, pattern in CUES:
        if pattern.search(text):
            return kind
    return None


def _clip(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= TOPIC_LIMIT else flat[: TOPIC_LIMIT - 1] + "…"


def enabled(config: dict) -> bool:
    aura = config.get("aura") if isinstance(config, dict) else None
    return isinstance(aura, dict) and aura.get("enabled") is True and aura.get("conversation_notes") is not False


def turn_note(session: dict, text, config: dict) -> str:
    """The note for this turn ("" for none), updating ``session[TOPIC_KEY]``."""
    if not enabled(config) or not isinstance(text, str) or not text.strip():
        return ""
    kind = classify(text)
    previous = session.get(TOPIC_KEY) or ""
    if kind is None:
        if len(text.split()) >= 4:
            session[TOPIC_KEY] = _clip(text)
        return ""
    if kind in {"shift", "correction"}:
        session[TOPIC_KEY] = _clip(text)
    topic = f' (the earlier topic was: "{previous}")' if previous else ""
    return NOTES[kind].format(topic=topic)


def session_turn_note(session: dict, text) -> str:
    """``turn_note`` with this process's config; the seam tui_gateway/prompt_turn.py calls."""
    from hermes_cli.config import load_config_readonly

    return turn_note(session, text, load_config_readonly())
