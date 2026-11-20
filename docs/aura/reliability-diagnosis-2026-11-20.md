# Aura reliability — phase 1 diagnosis (20 Nov 2026)

Branch `claude/aura-reliability-repair`, cut from `aura/working-product-20261111` at
**`befe4c2a`** ("Release Aura Zero 2026-11-19", which includes #17, #18, #20–#23, #27 and the Venus plugin).
This is evidence gathering only. **No fixes, deploys or setting changes were made.** Labels:
PASSED / FAILED / BLOCKED / UNVERIFIED. **Evidence** below means a measurement or code read here.
**Hypothesis** means consistent with the evidence but not proven on the live service.

## What could not be observed (BLOCKED)

| Need | Blocker | Smallest remedy (Melvin) |
|---|---|---|
| Which revision is live | This container's network proxy refuses `aura-zero.onrender.com` (`CONNECT tunnel failed, response 403`) | Add `aura-zero.onrender.com` to this environment's allowed hosts (read-only `GET /api/health`), or paste its `deploy_commit` |
| Live logs, memory, restarts, OOM kills | The Render connector here sees workspace "Reveta Inc." (12 services); **no `aura-zero` service is in it** | Connect the Render account/workspace that owns `aura-zero`, read-only; or paste its Events page (restarts, `server_failed` reasons) and memory graph for the reported times |
| Real-phone voice, real provider latency | No device; no model key in this environment | A phone test session; a key entered by Melvin himself |

## Symptom by symptom

### 1. Basic replies take ~5 minutes
- **Evidence — Aura's own overhead is small when warm.** Real webapp and gateway, fake model, headless Chromium at 390×844, 10 sequential sends in one chat, on this container:

  | Measure | p50 | p95 |
  |---|---|---|
  | Message shown | 85 ms | 1,626 ms |
  | First reply text | 100 ms | 1,634 ms |
  | Reply complete | 292 ms | 3,557 ms |

  The p95 is the first send of a new chat (it builds the agent: 1.6 s / 3.6 s). Script: `scripts/reveta/aura_latency.mjs` (needs a plain-text-only fake script; harness wiring is a phase-2 item).
- **Evidence — timing budgets that can stack** (`hermes_cli/config_defaults.py`, `agent/agent_init.py:1335`, `agent/turn_api_error.py`):
  - a 180 s request timeout;
  - `api_max_retries: 3` with jittered backoff (`compute_error_backoff`, capped by `RETRY_AFTER_CAP_S`);
  - a 60 s no-progress stream detector.
- **Evidence (Render docs):** a free service spins down after 15 idle minutes and takes about a minute to start again.
- **Hypothesis (needs live logs):** the stall is host and provider time. Possible causes:
  - a cold start;
  - provider rate limits (Gemini free tier, `429`), retried with backoff;
  - a stalled stream waiting out the 60–180 s budgets;
  - a process restart in the middle of a turn.
- **Not yet checked:** whether the UI shows *why* it is waiting during backoff or retry (a phase-2 UI item).

### 2. Logged out after seconds
- **Evidence (code):** the webapp's browser sign-in is valid only while the gateway's session token is unchanged (`hermes_cli/webapp_sign_in.py` docstring).
  - `hermes_cli/web_server_session_token.py::resolve_session_token` returns `secrets.token_urlsafe(32)`, **a new random token, on every process start**, unless `HERMES_DASHBOARD_SESSION_TOKEN` is set.
  - The listener keeps it at `$HERMES_HOME/webapp/session-token` (`gateway/webapp_listener.py:32`).
- **Evidence (docs):**
  - Render free erases the local filesystem on every restart, redeploy **and** idle spin-down (render.com/docs/free).
  - The documented Render variables (`docs/aura/HANDOFF.md` §Render cutover) do not include `HERMES_DASHBOARD_SESSION_TOKEN`.
- **Mechanism (evidence-backed, live occurrence unverified):** any restart or spin-down mints a new token, so every browser's sign-in binding stops matching and the user is signed out.
- **"After seconds" points to frequent restarts.** Restarts can come from spin-downs or from crashes (out of memory). That last part needs the Events page.
- **Ruled out:** cookie lifetimes. The access token is short by design, but `dashboard_auth/middleware.py` refreshes it with a 30-day refresh cookie (`_RT_MAX_AGE`).

### 3. Model-key retention
- **Evidence (code):** Settings → Model saves keys with `hermes_cli/credential_lifecycle.py::save_provider_env_credential`, into `$HERMES_HOME/.env` and `auth.json`.
- **Consequence:** on Render free these are erased on every restart and spin-down. Keys typed into Settings do **not** persist there. Keys set as Render environment variables do, because they come from the service configuration, not the disk.
- **Not done:** live verification (BLOCKED, as above).

### 4. Conversation and settings persistence
- **Evidence:** `state.db`, `projects.db`, `config.yaml` and memory all live under `$HERMES_HOME` (`docs/aura/persistence-options.md`).
- On Render free they are lost on every restart and spin-down. #20 makes owner settings survive boots *on a persistent disk*. It cannot help on an erased disk.
- Remedy already decided: **E (mounted `$HERMES_HOME`, #24)**. Not provisioned.

### 5. Browser tool fails repeatedly
- **Not reproduced here.** In this container the real-Chromium product flow passes (`aura_browser`, 3 real pages) and the unlocked `browser_exec` reaches its approval card (`scripts/reveta/aura_browser.py`).
- **Hypotheses for the live service:**
  - Chromium memory on a 512 MiB host already near its limit, leading to launch failure or an OOM restart (which would also sign users out, see 2);
  - a missing Chromium path in the image;
  - repeated retries by the model after a failure.
- **Needed:** live logs for a failing attempt; the exact error text the user saw.

### 6. Voice times out in under a minute, stop is unclean
- **Evidence (code, `f2dbfb53`):** full duplex is owner-only and **refuses to start when cgroup `memory.max − memory.current` < 280 MiB**. On a 512 MiB instance with the server at about 479 MiB (earlier measurement), that refuses and falls back to browser voice.
- **Hypotheses:**
  - The browser fallback ends when the browser's speech recognition stops (Android Chrome ends recognition after silence).
  - Gemini TTS quota errors (`speech_failed`).
  - A restart in the middle of a call (see 2).
- **Needs:** a phone session with the console visible, and the server Events.

## Phase 2 plan (repair branch, draft PR; nothing deployed)

Ordered by user impact and how directly it can be done without live access:

1. **Sign-in survives restarts.**
   - Melvin sets a stable `HERMES_DASHBOARD_SESSION_TOKEN` secret in the `aura-zero` Render service. That is his step: a secret, set in Render.
   - In code: a clear "you were signed out because the server restarted" notice, instead of a silent drop.
2. **Truthful waiting states.** Surface the server's retry and backoff status, plus cold-start and provider-delay messages, in the composer strip. Add a cancel path. Add regression tests that use the fake provider's `Error(429)` and `Hang`.
3. **Keys and settings on an erasable host.** In Settings → Model, say plainly when the host does not persist the saved key. Recommend Render environment variables or the mounted-home host (E).
4. **Browser and voice failure states.** Show an explicit "unavailable: <reason>" in place of repeated attempts. Show voice states only from real events. Test that Stop releases the microphone (fake device).
5. **Latency harness** (`lat.mjs` as a repo script) and the UI acceptance set from the brief (360/390/768/1440 px). Then the reference screenshot, once supplied.

## Approvals requested (smallest first)

1. Read-only visibility of `aura-zero`: its Render workspace connected read-only, *or* its Events page and memory graph pasted. Optionally add `aura-zero.onrender.com` to this environment's allowed hosts.
2. Melvin sets `HERMES_DASHBOARD_SESSION_TOKEN` (and provider keys) as Render secrets himself. Restarting the service to apply them is his call.
3. Proceeding with E (mounted home) remains the durable fix for chats, settings and keys. #24 already holds the steps.

Not run: `npx skills add ComposioHQ/composio`. It installs third-party code into the agent environment, the repair doesn't need it, and Composio is BLOCKED without a key.
