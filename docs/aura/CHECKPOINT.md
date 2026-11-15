# Aura Zero checkpoint — read this first

Updated 14 November 2026, about 11 PM Dublin. Replace this file at the end of every session; keep it short.

## Fixed points

- **Repository:** `Melvinjayson/reveta-hermes` (Aura Zero). No other repo or deployment is the product.
- **Integration branch:** `aura/working-product-20261111`. Render (`https://aura-zero.onrender.com`) auto-deploys it.
- **Writer:** the single release task. Feature work lands on short branches merged here; no parallel rebuilds.
- **Chat UI:** `apps/desktop/src/app/aura/` (not the legacy `web/` dashboard).
- **Upstream attribution:** Hermes Agent (MIT, Nous Research). Keep `LICENSE` and notices.
- **Rollback:** integration head before the voice increment was `42a9ef428b` (PR #8 merge).

## Release 15 Nov, about 12:50 AM — live commit `e2e7c1ac1843`

- **Live:** `/api/health` reports `deploy_commit: e2e7c1ac1843` (= `origin/aura/working-product-20261111`). It holds PR #12's goal/voice/delete/steps/identity/workspace commits, PR #13's quota fail-fast, chats-follow-Settings and probe skip, and `aura/conversation-intent` (turn rules, echo drop, quick-reply chips). Merged by the conversation-intent task, not via the PR buttons, so PRs #12/#13 still show open.
- **Rollback:** `12c8f57e9fa4` (previous live head).
- **Checked live, signed in, no message sent:** app connects; Voice control shows; Settings shows "Replying with Google Gemini's free tier" (the saved Anthropic key was lost by the redeploy, as the blocker below says); conversation list empty after the redeploy.
- **Tests on PR #12 + #13 combined (agent VM):** Vitest `src/app/aura` + `src/app/chat/composer` 105 files / 732 tests pass; pytest Aura config, workspace ownership, voice quota, Gemini daily quota, chats-follow, bot-chat follow, error classifier, `tests/tools/test_aura_*` 375 pass; ruff clean on changed Python.
- **Left on PR #12 (not live, CI hygiene only):** code-health split of `voice-call.tsx`, BOM-tolerant SOUL.md read, ruff fix in the ownership test, contributor email mappings for the repo guard. Land with the next deploy; do not redeploy for these alone (a redeploy wipes Settings keys and chats on Render free).

## Phone acceptance test (user, 15 Nov): end-to-end agentic loop

The phone test must cover: a voice request → Aura uses browser or computer control → an approval handoff → a spoken result. What the live build can do toward it:

- `aura_computer`: terminal command or code in the conversation workspace on the server; **every command needs a single-use approval** (`tools/aura_dispatch_policy.py`). This is the only path that exercises the approval handoff today.
- `aura_browser`: real headless Chromium, **read-only** (the model passes only a URL; no click, type, submit or sign-in), no approval because it changes nothing.
- Not live: clicking/typing on sites, handing the browser to the user, the Aura Companion extension (PR #10, open, off by default), control of the user's own computer.
- Unverified: whether the approval card shows and resolves while a voice call is running, and whether the result is spoken; whether Chromium fits Render free's 512 MB (server was at ~479 MB before this deploy).
- Test script: re-enter a model key in Settings, start voice, say "Open example.com and tell me its heading, then run a command that counts the words in it." Expect a read-only browse (no approval), then an approval card for the `aura_computer` command; approve on the phone; hear the result spoken. (A brand-new file via `aura_file` is created without approval; only overwrites and commands ask.)

## Voice increment (previous deploy) — tested vs not

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

Second commit (15 Nov ~12:30 AM), from the live voice preview reports:

| Change | Where | Evidence |
| --- | --- | --- |
| Text-to-speech gap: speech used to start only after the whole turn settled. Now each finished sentence is sent while the reply streams; the first chunk is short (120 chars) so audio starts sooner; nothing is repeated; cutting in stops the rest of a streaming reply | `voice-call.tsx` (`speakableSoFar`) | Vitest streaming + cut-in tests. Latency **not measured** live |
| Gemini TTS `HTTP 429 exceeded your current quota` (seen live): after a quota error the server stops calling the provider for 60 s and hands each sentence back as `speech_failed`; the app speaks it with the device voice | `tools/aura_voice_call.py` | pytest `test_aura_voice_quota.py`; no live run |
| Aura's own speech heard as the user (reported: it echoed deploy status, offered to "monitor the inspection", suggested pre-routing): transcripts that mostly repeat what Aura said in the last 30 s are dropped; device speech is cut only by a real transcript, not by any detected sound | `voice-call.tsx` (`isEchoOfAura`) | Vitest. **Cause unverified:** consistent with speaker echo reaching the mic; silence detection not proven at fault |
| Delete conversations: trash button per row in Aura's conversation list, inline "Delete …? This can't be undone" confirm, then the app's existing `onDeleteSession` → `removeSession` → `DELETE /api/sessions/{id}` (owner-resolved, idempotent, restores the row on failure). No new endpoint | `conversation-row.tsx`, `shell.tsx` | Vitest with synthetic rows only; **no real conversation deleted** |
| Progress steps: refused steps now say why (server policy text) and "Nothing was charged." for the free-only block; the "Inputs and result content are hidden…" filler is gone; the busy line names the running step | `steps.ts`, `step-history.tsx`, `conversation-cards.tsx` | Vitest |

Totals on this branch: Vitest 745/745 (107 files, aura + composer); pytest 13/13 in the Aura suites touched (`test_aura_config`, `test_aura_workspace_ownership`, `test_aura_voice_quota`). Earlier: `test_keygen_readonly_env_degrades_to_warning_not_boot_abort` fails identically without these changes on this root VM.

**Merge conflict to resolve at integration:** PR #11 (`aura/pipecat-voice`) also edits `browser-voice.tsx`; `git merge-tree` shows a content conflict there. Nothing else overlaps.

**Overlap warning:** while this ran, tasks "Fix Aura quota hangs, model selection and identity" and "Prioritize Aura empathic conversational intelligence" were also running and may touch `aura_config.py` prompts and goal behaviour. Merge one at a time and re-run the tests above after each.

## Conversation-first increment (branch `aura/conversation-intent`, stacked on `aura/goal-intent-voice-ui`, 15 Nov) — NOT merged or deployed

The empathic intelligence layer from the requirements, built on what exists (no framework, no new state store). The boundary is: inferred intent stays a tentative line in the conversation; it becomes a saved goal only when the user taps Save on the `Proposed goal:` card (PR #12, functional, client-side); consequential actions still need the existing approval cards; clear requests run now.

| Change | Where | Evidence |
| --- | --- | --- |
| Prompt: classify each turn as thinking aloud / unclear / clear request / consequential. Thinking aloud → a tentative one-line reading, at most one question, no tools; a correction drops the old reading; a clear request runs without a confirm; never states the user's feelings as fact | `scripts/reveta/aura_config.py` (`AURA_SYSTEM_PROMPT`) | pytest asserts the rules are in the prompt. **Model behaviour not measured** (no paid model test run) |
| Role confusion / status parroting (live voice preview): a user turn that repeats Aura's own recent reply is not a request; status only when asked or just changed. Complements PR #12's client echo filter (`isEchoOfAura`), which drops the transcript before it is sent | same | pytest (prompt text). Cause of the echo still **unverified** (speaker-to-mic fits; silence detection not proven) |
| The refused steps ("This would cost money", live session `local-5cdcb7bd…`): Aura offered the model tools its own free-only gate refuses by construction (`desktop_preview` and other desktop/catalog/project tools added for the GUI surface). Aura now only offers Aura-owned tools and attested `free_tools`; dispatch is still gated by `require_tool`. Outside Aura nothing changes | `tools/aura_free_only.py` (`advertised_tools`), `model_tools.py` | pytest `test_aura_advertised_tools.py` (owned kept, refused hidden, attested kept, non-Aura unchanged, real `_compute_tool_definitions`) |

| AI tag + quick-reply chips (ledger A-018, rebuilt from WebInfer's Smart Tags / Reply Suggestions idea, no code copied): a compact row beside the goal suggestion. "AI · Asking you" when Aura ends on a question; chips from the options in that question ("X, Y or Z?"), Yes / Not yet for yes-no questions. Built from Aura's own reply, no extra model call; hidden while busy, after you answer, or when the goal card asks. Tap submits like a typed reply. Wraps on desktop, scrolls sideways on phones, 44px targets | `apps/desktop/src/app/aura/goals.ts` (`auraReplyHints`), `conversation-cards.tsx`, `aura.css` | Vitest 2 new tests. Not seen on a phone |

Tests: pytest 75/75 across `test_aura_advertised_tools`, `test_aura_free_only`, `test_aura_product`, `test_aura_dispatch_gate`, `test_aura_config`, `test_aura_check`; Vitest `src/app/aura` 32/32. `tests/tools/test_registry.py` + `test_model_tools_async_bridge.py` (11 failures) and the 8 `get_tool_definitions` suites (16 failures) fail identically with and without this change on this VM.

## Next blockers from the 11:36 PM phone test

- **Uploaded PDFs are not reachable by Aura's tools.** Uploads are staged to the profile `attachments/` dir, but Aura's toolsets are only `aura` + `todo`, `aura_file` reads only `aura-workspace/<conversation>/`, and the image has no `pdftotext`. Local extraction already exists (`tools/read_extract.py`, anydoc + pypdf in the image). Fix: stage Aura uploads into the conversation workspace (or let `aura_file read` open this conversation's own attachments, never another user's), then phone-test. Until then the prompt tells Aura to say plainly it can't open uploads yet, never "paid service".
- Goals are per device (localStorage), not synced across devices.
- Voice settle delay (1.2 s), streamed speech, echo filter and device-voice fallback are untested on a real phone.
- **Why tools were refused ("This would cost money"):** `tools/aura_free_only.py` blocks any non-Aura tool while free-only is on. `aura/conversation-intent` stops offering those tools to the model, so the refusals should stop appearing; it does not loosen the rule. Giving Aura a live preview/canvas tool needs it added to Aura's owned set or attested in `free_tools` (user decision).
- **Status parroting / role confusion:** prompt rule on `aura/conversation-intent` plus PR #12's echo filter.
- **Fixed widget layout:** the user wants results to surface and render in the conversation dynamically instead of fixed widgets taking screen space. Not built yet; the desktop preview pane exists in Hermes but is not mounted in the Aura shell.
- **Composer text box and voice input feel unintuitive (user, 15 Nov):** only the voice pill was reworked here; the text box itself is unchanged and still needs a pass.
- **"The two users are failing"** (user, unclear). A later message suggests it meant the two refused steps in the progress list; not confirmed.
- Integrated release: this branch, quota/model/identity task and conversational-intelligence task should land as one release candidate on `aura/working-product-20261111` with one combined test run, then one deploy.

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

### CI on PR #13 (00:45 AM)
- Python lints fail **only on code from the #12 base** (commit 22dbc621de): `scripts/reveta/aura_config.py:66` (`read_text` encoding), `scripts/reveta/aura_voice_call_live.py` (UP031, `open()` without encoding), `tests/test_aura_workspace_ownership.py` (FURB167). None of the files this branch changes fail lint (ruff clean locally).
- Repository guards fail on contributor attribution: unmapped emails `chineduogbalu@gmail.com`, `melvinjayson@users.noreply.github.com`, `noreply@sprites.dev` from earlier commits. The fix is `python3 scripts/audit_pr_attribution.py --fix`, committed once on the integration branch. Same failure as #9/#10.
- Python test shards were still pending when this was written.

### Next step for this lane (not started): configurable Aura model profiles
User said "proceed" on the WebLLM findings (Reveta OS ledger A-018, commit 185ee01). Replace the hardcoded `PROVIDERS[...]["models"]` lists in `tools/aura_provider.py` (OpenAI: gpt-5.6-luna/terra/sol, gpt-4.1-mini; Anthropic: claude-sonnet-5, claude-haiku-4-5, claude-sonnet-4-6, claude-opus-5) with configurable **model profiles**. Each profile records role, provider, model, spending caps and last-validated date. Show them in `apps/desktop/src/app/aura/model-settings.tsx`.
- A profile changes only after a recorded quality, latency, cost and tool-use check. There is no automatic upgrade to whichever model is called the best.
- Keep the server-side caps (`MAX_CAP_USD`, per-user daily caps) and the existing-chat routing from this PR (Aura chats follow the Settings model).
- Too large for this increment, which is already in review for the batched release. Do it on its own branch after #12/#13 merge.

### Unclear report
The user said "the two users are failing". It has not been interpreted or investigated, and no fix is claimed for it. Ask the user what it refers to.
