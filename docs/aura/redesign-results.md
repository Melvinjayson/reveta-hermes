# Aura Zero redesign v1 — results

Branch `claude/aura-redesign-v1`, final code commit `a66eef18`, base `aura/working-product-20261111`
at `e7882138` (PR #15). Fake model only (`tests/fakes/fake_llm_provider.py`). No real-model call,
merge, deploy, hosting, visibility or access change, and no secrets.

Labels: **PASSED** (a check ran and passed), **FAILED**, **BLOCKED** (needs something this
session may not have, such as a key or a device), **UNVERIFIED** (not checked).

## Checks: this branch against base

| Check | Base `e7882138` | This branch `a66eef18` | New failures |
|---|---|---|---|
| Type check, `NODE_OPTIONS=--max-old-space-size=4096` | PASSED (exit 0) | **PASSED** (exit 0) | none |
| Desktop ESLint | PASSED | **PASSED** | none |
| Vitest: Aura, composer, approval, assistant message, right rail, host capabilities, no-native-title | FAILED: 1 of 1,095 (no-native-title, 6 Aura `title=` buttons) | **PASSED**: 1,112 / 1,112 in 139 files | none; the base failure is fixed |
| `python scripts/check` | FAILED: footguns, no-tmp, blob-size, ruff, health | FAILED: the same 5 checks | **none**: the finding lists diff equal apart from shifted line numbers (2 shifted lines in `tools/aura_free_only.py`) |
| Aura Python tests (aura_check list + every `test_aura_*.py`, with conftest) | PASSED: 514 in 21 files | **PASSED**: 525 in 24 files | none (11 new tests in 3 new files) |
| Webapp build | PASSED | **PASSED** | none |
| Browser acceptance `scripts/reveta/aura_browser.py`, 390×844 + 1440×900 | FAILED: product flow looked for `.aura-browser-voice` and "Full duplex unavailable", removed in 22dbc621 | **PASSED**: 6 scenarios, 8 PASS lines | none |
| Full Python suite (base has 103 known failures) | not run | **UNVERIFIED** | 7,426 test files would take hours on this 4-core VM; Python changes are limited to new Aura modules and `tools/aura_free_only.py`, which the Aura suite covers |

`scripts/check`'s five pre-existing failures are in files this branch does not touch (for example
`apps/desktop/public/fonts/aura/inter.ttf` is over the blob limit, and ruff UP031 fails in
`scripts/reveta/aura_voice_call_live.py`). Two findings this branch had introduced (a
BOM-intolerant read in `/api/aura/memory`, and one more line in `ChatBar`) were fixed before the
final run.

## What the browser acceptance proves (fake model, real webapp and gateway)

1. **Retired model:** a provider 404 shows "Model unavailable" and nothing is retried or routed to a paid fallback.
2. **Product flow (390×844):**
   - reads three real sources and passes the manual approval for `pwd`, exactly once;
   - writes the cited brief, which shows 5 Done steps in the Work panel;
   - the Files panel downloads and previews `brief.md`;
   - reload and reopen keep the chat;
   - fake speech covers listening, transcript, thinking, speaking, barge-in and the mic being denied.
3. **Capabilities, unlocked, free-only rule off as live:**
   - a clarifying question asks for approval, then shows its choices, and the answer reaches the model;
   - a click-and-type browser step (`browser_exec`) waits on the approval card, and Change returns a refusal without running it.
4. **Main scenario:**
   - sign-in gate for an anonymous browser; four starters; Voice chat present;
   - all 8 Settings sections; drawer items (New chat, Search, Settings, New project); Escape returns focus;
   - streamed reply with a numbered source chip and copy under the answer; no upstream branding;
   - keyboard inset, and no horizontal overflow at 320, 375 and 390 px;
   - reopen and resume through the drawer (this replaces the stale goal-card steps); Ctrl+K search finds message text;
   - approval: Change runs nothing, Approve runs once (loopback counter = 1), and still once after reload;
   - Work panel shows a Done step and a Refused step;
   - the conversation strip is under 120 px and the chat at least 60% of the screen;
   - attach an image and a URL; the + menu shows the modes;
   - desktop sidebar collapses and reopens; delete asks first, Cancel keeps the chat, Delete removes it;
   - sign out from Settings → Account.
5. **Cost-blocked model:** refused and shown as a step, with no provider request.
6. **No model:** the notice shows in light and dark mode, with no provider calls.

## Capabilities

| Capability | Status | Evidence |
|---|---|---|
| Shell: collapsible sidebar, phone drawer, top bar, history Today / Yesterday / Previous 7 days / Older | **PASSED** | `history.test.ts`, browser scenario 4, `after/home-*.png`, `after/thread-*.png` |
| Search ⌘K over titles and message text (`GET /api/sessions/search`) | **PASSED** | `search-dialog.test.tsx` (stale reply ignored), browser scenario 4, `after/search-light.png` |
| Home: greeting, centred composer (≥640 px), 4 starters | **PASSED** | `empty.test.tsx`, `after/home-desktop.png`, `after/home-mobile.png` |
| + menu: modes for new chats and Tools… (`/api/aura/capabilities`) | **PASSED** | `tests/tools/test_aura_capabilities.py` (6), `tools-menu.test.tsx`, `after/plus-menu-desktop.png`, `after/tools-*.png` |
| Dictation mic (browser speech; types into the draft and never sends) | **PASSED** (unit) / **UNVERIFIED** (on real phones) | `dictation.test.tsx`; mounted through the `composer.actions` seam |
| Voice chat (current voice stays default; labels only) | **PASSED** | `voice-call.test.tsx`, `browser-voice.test.tsx`, product flow voice section |
| Thread: soft user bubble, plain answer, copy and retry visible, numbered sources | **PASSED** | browser scenario 4, `after/thread-*.png` |
| Agent work: steps with pending / working / done states, timers, tool icons; live strip | **PASSED** | `side-panel.test.tsx`, `steps.test.tsx`, browser scenarios 2 and 4, `after/panel-*.png` |
| Subagents and background tasks in the Work panel | **PASSED** (unit, from the live stores) / **UNVERIFIED** (with a real delegated run) | `side-panel.test.tsx` |
| Inline approvals stay manual (Approve / Change) | **PASSED** | browser scenarios 2–4 (counter = 1; Change runs nothing) |
| Side panel ≥1200 px / full sheet on phone; Files preview (text, Markdown, image, PDF) | **PASSED** (text and Markdown in browser) / **UNVERIFIED** (PDF and images in a browser; their routing is unit-tested) | product flow `product-file-preview-mobile.png`, `side-panel.test.tsx` |
| Projects: create, rename, notes, add or remove a chat, new chat in project, delete keeps chats | **PASSED** | `tests/tools/test_aura_projects.py` (4), `projects.test.tsx`, `after/project-desktop.png` |
| Project instructions reaching the model | **Gap (not built)** | needs per-session prompt plumbing at agent creation; notes are stored but not sent to the model |
| Settings → Model / provider (existing) | **PASSED** (UI) / **BLOCKED** (paid reply needs Melvin's key) | browser scenario 4 |
| Settings → Memory: view, and clear after a confirm (`/api/aura/memory`, `/api/memory/reset`) | **PASSED** | `test_aura_memory_view.py`, `settings-sections.test.tsx`, `after/settings-memory-mobile.png` |
| Settings → Skills: search, read, on/off | **PASSED** | `after/settings-skills-mobile.png` |
| Settings → Scheduled jobs: pause, resume, run now, delete after a confirm | **PASSED** (unit) / **UNVERIFIED** (with a real job; the cronjob toolset is unavailable in this VM) | `settings-sections.test.tsx` |
| Settings → Connectors (MCP on/off) | **PASSED** (unit) | `settings-sections.test.tsx` |
| Composio Connect | **BLOCKED** (needs `COMPOSIO_API_KEY` set by the owner); shown as not set up | `after/settings-connectors-mobile.png` |
| Full browser (click and type) under approval | **PASSED** (approval and decline) / **UNVERIFIED** (an approved real run on Render, including fit in 512 MB) | browser scenario 3, `after/browser-approval-mobile.png` |
| Clarifying questions | **PASSED** | browser scenario 3, `after/clarify-mobile.png` |
| Web search | **BLOCKED** (every backend needs a key; free `ddgs` is not in the image's `[all]` extra and the Dockerfile is out of scope) | `tools/web_tools.py` |
| Image generation | **BLOCKED** (key) | `tools/image_generation_tool.py` |
| Vision | **UNVERIFIED** (depends on the model) | — |
| Real-model end to end | **BLOCKED** (Melvin enters a key himself) | — |
| Android | **BLOCKED** (no device) | — |

## Depends on Melvin's hosting decision

On Render free, a restart or redeploy can erase `$HERMES_HOME` (`docs/aura/HANDOFF.md`
§ Persistence). That covers chats and the search index, memory, created skills, scheduled jobs,
projects (`projects.db`), uploads and workspace files, saved provider keys and the spend ledger.
The Memory and Scheduled jobs settings say so on screen.

## Decisions for Melvin (current defaults kept)

1. Accent colour `#1f6fb5` light / `#7cc4f0` dark (kept).
2. Approval buttons: Approve / Change (kept; Approve / Deny not applied).
3. Sign-in screen not restyled (auth surface untouched).
4. When to merge: merging deploys to Render, and on the free plan a redeploy wipes saved keys and chats.
5. **New:** clarifying questions currently need one approval tap before the question appears, because the
   dispatch gate treats every non-read tool as consequential. The gate was not changed. Decide
   whether `clarify` (which only asks you something) should skip approval.
6. **New:** project instructions are stored but not sent to the model (gap above).
7. Governance activation: a later decision; not touched.
