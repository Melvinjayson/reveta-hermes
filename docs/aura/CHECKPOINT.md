# Aura Zero checkpoint — read this first

Updated 14 November 2026, about 11 PM Dublin. Replace this file at the end of every session; keep it short.

## Fixed points

- **Repository:** `Melvinjayson/reveta-hermes` (Aura Zero). No other repo or deployment is the product.
- **Integration branch:** `aura/working-product-20261111`. Render (`https://aura-zero.onrender.com`) auto-deploys it.
- **Writer:** the single release task. Feature work lands on short branches merged here; no parallel rebuilds.
- **Chat UI:** `apps/desktop/src/app/aura/` (not the legacy `web/` dashboard).
- **Upstream attribution:** Hermes Agent (MIT, Nous Research). Keep `LICENSE` and notices.
- **Rollback:** integration head before the voice increment was `42a9ef428b` (PR #8 merge).

## Voice increment (this deploy) — tested vs not

| Piece | Where | Evidence |
| --- | --- | --- |
| Settings → Model: OpenAI or Anthropic, key, daily and per-chat USD caps | `tools/aura_provider.py`, `hermes_cli/web_routers/aura.py`, `app/aura/model-settings.tsx` | 70 Python tests pass (provider, free-only guard, dispatch gate); route test: key stored write-only, switch back to Gemini works. **Real provider reply unverified** (no key on build machine). |
| Guard allows only that exact provider/host/model; refuses at a cap with a readable message | `tools/aura_free_only.py`, `agent/turn_api_error.py` | tested |
| Spend recorded per main-model call at Hermes's bundled prices | `agent/turn_usage.py` | tested with fixtures |
| Continuous voice socket `/api/audio/voice-call` + composer voice screen (barge-in, reconnect, no replay of old replies, transcripts queue behind a running turn) | `hermes_cli/web_routers/aura.py`, `app/aura/voice-call.tsx` | Vitest 733/733 (aura + composer), eslint clean, webapp build OK. Pipeline driven over a local WebSocket with real Gemini free models and Pipecat loaded from the image-style `--target` dir: transcript correct, first audio 2.14 s after `speak`, barge-in → 0 further audio bytes, reconnect OK, peak RSS 153 MB. **Not run through the deployed site or a real phone.** |
| Pipecat in the image | `Dockerfile` (`/opt/aura-voice/site`, appended last to `sys.path`) | Docker build not run locally (no Docker on build machine). Pinned with `--exclude-newer 2026-11-12T01:00Z`; Pipecat 1.16.0 itself is ~3 days old, just inside the repo's 3-day quarantine. |
| OpenAI speech (used when an OpenAI paid route is set), metered into the daily cap | `tools/aura_voice_call.py` | code only |
| Kokoro local speech, off unless `AURA_KOKORO_DIR` holds the model | `tools/aura_voice_call.py` | measured on one CPU core: short sentence 1.1 s, real-time factor 0.62–0.75, 365 MB alone. Does **not** fit Render free (0.1 CPU, 512 MB). |

## Not in this deploy (next, in order)

1. PR #10 Aura Companion (merged cleanly on `aura/consolidate-20261114`; keep both `aura` and `aura_companion` router registrations in `hermes_cli/web_server.py`).
2. `feat/aura-waking-page-20261109` (static page, not wired).
3. Close superseded PRs (#1–#6, #9) after `git cherry` shows no unique commits. PR #4 is superseded: browser build already defaults to Simple mode.
4. Chat interface rebuild inside `app/aura/`.

## Blockers

- **Keys on Render free are not durable:** a key saved in Settings lives in `/opt/data/.env` on the container disk; a restart or redeploy loses it and Aura drops back to free Gemini. Re-enter, add a persistent disk, or move host (user decision, costs money).
- **Gemini free tier** voice has per-minute limits; with an OpenAI route set, voice uses OpenAI speech instead.
- **No Render access** from the build machine: the serving commit is inferred from the new route answering (401 when signed out) rather than read from Render.
- **No real phone test yet.**

## Exact next steps for the user

1. Open `https://aura-zero.onrender.com` on the phone, sign in.
2. Settings → Model → Anthropic or OpenAI, paste key, keep the caps, Save. Send one typed message; confirm a reply.
3. In chat tap **Start voice**, allow the microphone, speak; talk over Aura mid-reply to check it stops.

## Quota / model / first-turn increment (branch `aura/fix-quota-model-follow`, stacked on `aura/goal-intent-voice-ui`, 15 Nov ~12:35 AM) — draft PR, NOT merged or deployed

Batched into the next single release with `aura/goal-intent-voice-ui` (UI, goals, identity, voice) and the conversational-intelligence branch. Do not deploy it alone.

| Change | Where | Evidence |
| --- | --- | --- |
| Google **per-day** quota 429 (`QuotaFailure` quotaId `...PerDay...`) ends the turn on the first call instead of ~3 min of retries (live: 191 s and 220 s, then empty/"not processed"). Per-minute 429s are still retried. | `agent/error_classifier.py` | pytest: real `run_conversation` makes 1 call on a daily-quota 429, >1 on a per-minute 429; both fail on the base commit |
| Every Aura chat (`aura.enabled`) follows the model in Aura Settings: new chats are marked follow-profile at creation; chats an earlier build froze move on next open (`session.resume`). History untouched. An explicit `follow_profile_config: false` stays frozen; non-Aura installs unchanged. | `gateway/session_local.py`, `gateway/session_local_migration.py` | pytest with real SessionStore/authority: new chat Gemini→Haiku on Settings change; old frozen chat moves on open with the same 2 messages; 2 guard tests. New-chat and old-chat tests fail on the base commit |
| Python-toolchain probe off for Aura. It runs pip/python subprocesses (measured 9.0 s on this 8-core VM) and the first prompt build after each restart waits up to 10 s. Likely the ~13 s gap before the first model call seen live; **not confirmed live**. | `scripts/reveta/aura_config.py` | pytest config assertion |
| Identity: reused `AURA_SOUL` from `aura/goal-intent-voice-ui` (no second copy). | — | its tests pass on this branch |

Prompt size measured locally with the Aura config: system prompt ~9–10k chars (~2.3–2.5k tokens) + 6 tool schemas (~0.9k tokens). The live 7,521 tokens is larger than that; the rest was not traced (memory/skills/context on the live disk are the likely extra). Hermes's default guidance blocks were **not** cut: they carry tool-use and safety rules and the intelligence task owns prompt behaviour.

Tests: 328 passed in the touched and neighbouring suites (error classifier, follow-profile gateway suites, aura config, aura tools). `tests/agent/test_fallback_429_after_timeout.py::...after_timeout_recovery` fails here and on the base commit alike (pre-existing).

Gemini **speech** 429 ("gemini-3.8-flash-lite text-to-speech HTTP 429") is handled on `aura/goal-intent-voice-ui` (cooldown + device voice), not here.
