# Aura for invited testers: what this release fixes, what the owner must do, what comes next

Branch `aura/real-users-foundation`, based on production `e0365fc2` (21 Nov 2026).

## Bottom line

This release makes the product calmer for first-time users: shorter waits when a provider fails, a
first-run welcome, and fixes for the layout and voice glitches found in the audit. It does **not**
make Aura safe for several people to share yet. Every signed-in person still shares one workspace:
the same chats, memory, keys and budget. Until the invited-tester design below is built, give
access only to people you would let read your chats.

Two of the four complaints need owner action, not code. Sign-outs and lost chats come from the
hosting setup (see "Owner steps").

## Shipped in this branch

| Complaint | Cause found | Fix | Evidence |
|---|---|---|---|
| Slow replies, long waits | Hermes defaults retry a failing provider 3 times and then run 5 recovery cycles (15/30/60/60/60 s), so a 503 could hold a reply for minutes | Aura sets `agent.api_max_retries: 2` and `agent.auto_recovery_cycles: 1` | Against a fake provider that always returns 503: about 26 s, 5 calls, then a clear "overloaded, try again" card. `tests/scripts/test_aura_config_retries.py` |
| No onboarding | — | Three-step welcome: what Aura does, how approvals and data storage work, a starter prompt. Skippable. Shown once per profile, stored in `HERMES_HOME/aura-onboarding.json` | `onboarding.test.tsx`, `test_aura_onboarding_routes.py`; `aura_browser.py` asserts the welcome appears on a fresh profile; screenshots at 390 and 1440 px |
| Honest storage message | Settings said "on the current free hosting plan…" whatever the host | The welcome and Settings read `storage_durable` from the server: true only when `HERMES_HOME` sits on a mounted volume | `settings-sections.test.tsx` |
| Layout: starters cut off on phones | A sideways scroller capped at 340 px clipped "Explore" | Starters wrap and stay centred | Screenshot, 390 px |
| Layout: hole in the composer | The hidden Send button still reserved its slot, and the mic was placed to leave room for it | When nothing is typed, the mic takes Send's slot; Send appears beside it once you type | Screenshots, idle and typed |
| Voice: confusing end button | Browser voice ended the call with a muted-mic icon (reads as "mute") | Hang-up icon, the same as full-duplex voice | Voice tour: listening, hearing and speaking states at 390 and 1440 px, no horizontal overflow |

Checks: `scripts/check` passes against the production base. Python and desktop tests pass,
including 1,767 Aura and chat UI tests. The full `aura_browser.py` acceptance gate passes, with all
8 flows.

## Owner steps (needed for "real people")

These are paid or configuration changes, so they are yours to make. Nothing here was changed on
Render.

1. **Move the service off the free plan.** Render free wipes the filesystem on every redeploy *and*
   whenever it spins down after 15 idle minutes (`docs/aura/persistence-options.md`). Testers would
   lose chats between visits. The 512 MB instance was also OOM-killed earlier. Choose at least
   Standard (2 GB).
2. **Attach a persistent disk mounted at `/opt/data`.** That path is the image's `HERMES_HOME` and
   holds chats (`state.db`), projects, memory, skills, jobs, the budget ledger and the onboarding
   flag. After the next boot, the welcome's step 2 and Settings → Memory stop saying "this server
   doesn't keep data across restarts". That is your confirmation the disk is seen.
3. **Set a fixed sign-in signing secret** `HERMES_DASHBOARD_BASIC_AUTH_SECRET` (the output of
   `openssl rand -base64 32`) as a Render secret, if it is not set already. Without it, every
   restart mints a new key and signs everyone out. That matches the "getting signed out"
   complaint. Its absence is logged only at INFO, so check the variable list in the Render
   dashboard.
4. Keep `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` strong and unique, and do not share it with
   testers (see below).

Neon is not needed for these steps. Aura's stores are SQLite files under `HERMES_HOME`; a disk
makes them durable with no code change. Moving to Postgres is a scaling step for when one instance
is no longer enough, and it means rewriting SessionDB.

## Invited testers: design (not built yet)

**Why it is not in this release.** The web app is built for one operator. There is one basic-auth
username. Chats, memory, keys, connectors, the shell and the budget belong to one `HERMES_HOME`.
Adding a second password would give a tester your chats and your terminal. A half-built version is
worse than none, so this is a design for review.

**Shape.** Use one Hermes profile per tester. Profiles are already isolated data islands
(separate `HERMES_HOME`, sessions, memory and budget), and the server can serve many profiles.

1. **Identity.** Either an owner-managed invite list (email → hashed password, stored in the
   owner's `HERMES_HOME`) on the existing basic-auth provider, or the existing self-hosted OIDC
   provider with an email allowlist. Recommendation: OIDC with an allowlist. It avoids storing
   passwords and gives testers "Sign in with Google".
2. **Binding.** The server, not the browser, maps each signed-in identity to that person's
   profile. Every `/api/*` request and every chat runs under the bound profile scope. A request
   naming any other profile is refused. This is the security boundary and needs tests that prove
   tester A cannot list, read, search or resume tester B's sessions.
3. **Owner-only powers.** Shell and background commands, code execution, keys and connectors,
   global settings, the budget limit, and the invite list. Testers get chat, research, voice,
   projects and their own memory.
4. **Cost.** Each tester profile gets its own budget ledger (already per `HERMES_HOME`) with an
   owner-set limit. The default is free models only.
5. **Owner screen.** Settings → People: invite, revoke, see each tester's spend, and reset a
   tester's data.

**Acceptance before inviting anyone.** Cross-tenant read, write and search tests are red on
`main` and green after the change. A browser run shows two testers who cannot see each other. The
owner's commands are refused for testers server-side, not just hidden. A revoked tester's next
request returns 401.

**Estimate.** This is a multi-PR change touching auth, profile scoping in the web routers, and
Settings. It needs a security review before any tester gets access.

## Still open

- **Bundle size.** First load is about 12 MB raw (about 3 MB compressed), across 211 requests. The
  main chunk is 3.4 MB. Splitting rarely used panels (plugin catalog, KaTeX, capabilities) behind
  dynamic imports is the next performance step. It needs a bundle analyser run first, so the cuts
  are measured rather than guessed.
- **Settings tabs on phones.** Tabs scroll sideways with no visual hint that more exist.
- **Skills list.** Testers see developer skills (claude-code, codex, computer-use). Hide these
  once per-tester profiles exist.
- **Composio.** The owner's key was rejected and needs replacing in the server environment.
