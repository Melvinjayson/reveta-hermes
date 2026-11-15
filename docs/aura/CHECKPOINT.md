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

## UI + identity increment (branch `aura/goal-intent-voice-ui`, 14 Nov ~11:59 PM) — PR open, NOT merged or deployed

| Change | Where | Evidence |
| --- | --- | --- |
| First message is never a goal. Aura proposes one only once intent is clear (`Proposed goal: …` line, prompt rule); user taps Save / Edit / Not now. Confirmed goals saved per conversation in localStorage (`aura.goals.v1`, existing `persistentAtom`), shown in a collapsed context row; no repeated cards | `app/aura/goals.ts`, `conversation-cards.tsx`, `aura.css` | Vitest: first message not saved; proposal saved only on confirm; dismissed not re-offered; edit persists per chat |
| Voice control: compact pill (Voice / state dot + word), 44 px targets, mute (mic track off), stop-speaking, End voice; sr-only live status; reduced-motion respected | `voice-call.tsx`, `browser-voice.tsx`, `aura.css` | Vitest mute/end test; eslint clean on touched files; tsc: no errors in `app/aura` (51 pre-existing errors in `../shared` test typings) |
| Walkie-talkie fix: transcript pieces held until 1.2 s after you stop (`TURN_SETTLE_MS`), then sent as one turn | `voice-call.tsx` | Vitest: two phrases split by a pause → one submit |
| No voice reply when server speech fails (quota): server sends `speech_failed` with the text; app speaks it with the device voice and says so once | `tools/aura_voice_call.py`, `voice-call.tsx` | client Vitest; server side py_compile only (no Pipecat test harness) |
| Aura identity: `AURA_SOUL` written to `$HERMES_HOME/SOUL.md` on `aura_config.py --write` (replaces stock Hermes soul, keeps an owner-edited one); system prompt carries goal, file and no-internal-paths rules | `scripts/reveta/aura_config.py`, `docs/aura/ATTRIBUTION.md` | pytest: real `build_system_prompt` for a fresh agent starts "You are Aura…", contains Reveta OS/Xhunt/Venus, no "You are Hermes Agent" |
| Workspace EACCES (phone test 11:36 PM): `aura-workspace` created by root at start → chowned to hermes each boot and pre-created as hermes | `docker/stage2-hook.sh` | pytest runs the hook's own functions with chown/find shims. **No Docker build or live check.** |

Totals on this branch: Vitest 738/738 (aura + composer), pytest 26/27 in the touched suites (the 1 failure, `test_keygen_readonly_env_degrades_to_warning_not_boot_abort`, fails identically without these changes on this root VM).

**Overlap warning:** while this ran, tasks "Fix Aura quota hangs, model selection and identity" and "Prioritize Aura empathic conversational intelligence" were also running and may touch `aura_config.py` prompts and goal behaviour. Merge one at a time and re-run the tests above after each.

## Next blockers from the 11:36 PM phone test

- **Uploaded PDFs are not reachable by Aura's tools.** Uploads are staged to the profile `attachments/` dir, but Aura's toolsets are only `aura` + `todo`, `aura_file` reads only `aura-workspace/<conversation>/`, and the image has no `pdftotext`. Local extraction already exists (`tools/read_extract.py`, anydoc + pypdf in the image). Fix: stage Aura uploads into the conversation workspace (or let `aura_file read` open this conversation's own attachments, never another user's), then phone-test. Until then the prompt tells Aura to say plainly it can't open uploads yet, never "paid service".
- Goals are per device (localStorage), not synced across devices.
- Voice settle delay (1.2 s) and device-voice fallback are untested on a real phone.

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
