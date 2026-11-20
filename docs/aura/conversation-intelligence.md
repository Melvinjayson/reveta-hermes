# Conversational intelligence — design note (decision C)

Branch `claude/aura-conversation-intent`, stacked on #24. Fake model only; **real-model behaviour is
BLOCKED until Melvin adds a key.**

## Problem

Aura's system prompt already asks the model to classify each turn (thinking aloud, unclear, clear
request, consequential; `AURA_SYSTEM_PROMPT` in `scripts/reveta/aura_config.py`). What it lacks is
**state across turns**. When the user steps out of a task ("you're not listening", "forget that, new
question", "no, I meant…"), nothing tells the model that the task it was running is paused, so it
snaps back to the earlier workflow on the next reply. In voice, interruptions and pauses add to this.

## Requirements (from the decision) and where each lands

| Requirement | This slice | Later |
|---|---|---|
| Track the active topic and intent across turns | **Yes**: the last substantive request is kept per session (`session["aura_topic"]`) | persist across restarts (session DB metadata) |
| Notice shifts and meta comments and follow them, not snap back | **Yes**: a deterministic cue classifier (`meta`, `shift`, `correction`) adds a per-turn note | a model-side classifier (aux call) when a key exists; measure against the cue list |
| Interruptions and barge-in in voice | Already present: `SPEECH_INTERRUPTED_NOTE` (`tools/tts_streaming.py`) is prepended on barge-in. Unchanged | combine with the topic note (interrupted *and* shifted) |
| Turn-taking: finished vs paused | **No** | client-side end-of-turn detection: hold the send when an utterance ends on a conjunction or filler ("and", "so", "um") or rises, with a longer silence window; Vitest with the speech fakes |

## Design

- **Where:** `tui_gateway/prompt_turn.py::_prepare_turn_input`, beside the barge-in, reaction and surface
  notes, through `_prepend_note`. The note reaches the **model input of this turn only**. It is not the
  system prompt and it is not written to the transcript, so the cached prompt prefix survives (root
  `AGENTS.md` invariant). No new tool, no new env var.
- **What:** `tools/aura_conversation.py`, pure functions plus a small per-session dict entry:
  - `classify(text)` → `"meta" | "shift" | "correction" | None`, from short, conservative cue lists,
    matched only near the start of the message (a cue buried in a long request does not count).
  - `turn_note(session, text, config)` returns the note for this turn and updates the session's topic.
    A normal request of four words or more becomes the topic. A shift replaces the topic with the
    new request; meta feedback keeps it (the task is paused, not done); a correction replaces it.
- **Gate:** only when `aura.enabled` is true, and off if the owner sets `aura.conversation_notes: false`.
  Outside Aura nothing changes.
- **Safety:** notes never grant anything. Approvals, the free-only gate and the dispatch policy are untouched.
  The quoted previous topic is the user's own words, clipped to 120 characters, with newlines removed.

## Tests (this slice)

- Unit: the classifier on positive and negative phrasings, and topic bookkeeping across a sequence of turns.
- Fake-model end to end: the real `AIAgent` runs a turn against `FakeLLMServer`, and the request the model
  received carries the note in the user message and not in the system prompt.
- Off-switch and non-Aura: no note.

## What would show it works with a real model (BLOCKED)

A scripted three-turn conversation: a research request, then "stop, you're not listening to me", then a
follow-up. Pass: reply 2 acknowledges and asks or adapts, with no research tool call. Reply 3 follows
the new direction.
