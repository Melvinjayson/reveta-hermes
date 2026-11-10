# Aura interface handoff

## Step-history slice — 10 November 2026

Starting SHA: `2d77e5cbef0903f6c5fbd876f8eff12b8d87a649`; fetched remote
matched, with no local or concurrent modifications. Work remains on the same
feature branch / draft PR #3. The PR records the final exact SHA and clean-tree
gate results; this section describes a bounded first-priority slice, not the full
proposed product or a completed live loop.

Implementation commit: `9b929bfea498585cfafe110ae7eb71c244c4142e`. The follow-up
evidence commit changes only this handoff, screenshot index and synthetic images.

Implemented: the Progress card now projects real transcript tool-call parts,
including hydrated history, instead of manufacturing a two-row plan from a busy
flag. A single lookup checked against the existing presentation registry supplies
plain names; unknown actions say “Used a tool”. Rows collapse by default, carry
text statuses and recorded timing, and expose only allowlisted outcome facts.
Commands, arbitrary inputs/results, URLs and internal identifiers are withheld
from this new Details view because they may contain credentials. This does not
retroactively audit other existing runtime detail views.

Done requires a confirming result flag, completed status or zero exit code. Failed,
queued, running and interrupted outcomes remain distinct. Unrecognized results
say Result received; a settled call without a result says Unconfirmed. Missing
timestamps say Timing unavailable. Neither an assistant's prose nor a busy flag
creates a step. Progress announcements exclude the ticking timer and never move
focus. Native disclosure controls support keyboard operation.

This slice introduces no new semantic colours, movement, success toast or backend
authority. Pills use existing neutral text/background tokens: light primary on
white 16.35:1; dark primary on surface 16.13:1. Amber/red/green pills and the shared
Needs-you indicator are deferred, so no unmeasured colour or fixture is presented
as implemented. The existing approval card remains the authority-facing UI.

### Runtime seams and deferred work

- Approval requests already carry queue request IDs. `resolve_gateway_approval_card`
  resolves an exact ID and does not answer the next request when that ID is stale.
  The renderer's current `ApprovalRequest` has no tool-call ID or verified cost.
  This slice does not guess a per-row Needs-you binding or call unknown cost Free.
- A local-fake probe found that a plain `curl --data` loopback POST ran without an
  approval prompt. Manual mode is not an every-send/submit guard. The final isolated
  regression uses the existing pipe-to-shell guard, consuming a fixed harmless
  response from a loopback-only mock. It checks Change/Approve-once and a request
  counter, not generalized external-action enforcement. No real recipient or
  deletion is used by this updated harness. The old inherited deletion-based
  test was run before this replacement; it touched only its disposable fixture.
- `tools/mcp_tool_costs.py` provides declared per-server costs/limits; a zero limit
  is not a global zero-spend switch, and unknown tools are not established free.
  Aura-wide fail-closed free-only enforcement is **not implemented or verified**.
  No new policy plugin was enabled; the previous provider defaults are unchanged.
- Existing files: `desktop-fs.ts` sends owner/profile/session scope; the gateway's
  `/api/fs/read-text`, `/api/fs/read-data-url` and download path already exist.
  `preview-file.tsx`, `preview-artifact.tsx` and the artifact registry provide other
  preview surfaces. `_fs_owned_session` checks profile-owned sessions when supplied;
  this is not proof of per-user file isolation. No new public file route was added.
- A new File card/shared panel, task/routine lists, browser takeover/guards,
  Apps/Skills and workspace screens remain unwired. No fixture-only production
  surface was added. File bytes/download ownership and safe rendering still need
  focused end-to-end tests before reuse. Existing code-block artifacts do not
  establish that a real model wrote a workspace file.
- Goal edits remain in-memory annotations. The step reload test verifies only
  current-process history hydration, not edited-goal survival or restart durability.

### Live acceptance — BLOCKED

The local managed environment reports no configured secrets/runtime variables;
OPENROUTER_API_KEY, GEMINI_API_KEY and GOOGLE_API_KEY are absent. No authorized,
tool-capable exact free model, verified pricing/quota or disabled paid fallback
route was established. No provider call was made. Render belongs to the separate
deployment owner and was not inspected or changed. No physical phone is available.

| Gate | Local live-free / deployed live-free result |
|---|---|
| Real provider reply and follow-up context | BLOCKED: no verified free route |
| Actual example.com read invocation/result | NOT RUN: live route blocked |
| Model-written sourced file, bytes and download | NOT RUN: live route/file adapter acceptance pending |
| Reopening with source/file/context retained | NOT RUN for live loop; local-fake step reload tested separately |
| Isolated approval control | Local-fake browser harness only; not every-tool safety |
| Costed fixture refused under Aura free-only | BLOCKED: blanket free-only authority is not implemented |
| Physical phone / restart continuity | NOT VERIFIED; no production restart performed |

Focused verification before the evidence commit:

| Command | Exit | Result |
|---|---:|---|
| `pnpm --dir apps/desktop exec vitest run --project ui src/app/aura --maxWorkers=2 --reporter=dot` | 0 | 11 tests across 4 files |
| `HERMES_PYTHON=.venv/bin/python bash scripts/run_tests.sh tests/tools/test_mcp_tool_costs.py tests/tools/test_approval_gateway_wait_late_choice.py --noconftest -q` | 0 | 16 existing runtime contract tests; not blanket free-only proof |
| `pnpm --dir apps/desktop run build:webapp` with `NODE_OPTIONS=--max-old-space-size=4096` | 0 | Fresh candidate build |
| `python scripts/reveta/aura_browser.py` | 0 | Local-fake streaming, guarded loopback mock Change/Approve-once counter, confirmed step, page reload, attachments, no-model, mobile/theme regressions |
| ESLint on changed TS/TSX/browser harness; Ruff on Python browser harness | 0 | No new lint errors/warnings |

The final PR adds the exact final-head commands, exit codes and JSON. Final gates
are run once on the final committed tree: `just aura-check` (4096 MiB Node heap)
and the complete `vitest run --project ui --maxWorkers=3` project. The gate includes
the browser harness. Earlier build refusal while inputs changed, corrected import/
registry errors, and interrupted old-harness runs are not passing evidence.

No paid calls, new spending, private source/assets, deployments, Render, secrets,
authentication, hosting or repository-visibility changes. Next smallest step:
design/test a backend free-only refusal boundary including unknown costs, then
verify an authorized exact free model route; reuse the scoped file adapters only
after their user/session ownership and download acceptance pass. Do not infer the
requested live conversation → sourced file loop passed from these regressions.

Branch: `feat/aura-chat-slice-20261109`, draft PR #3 into
`fix/chat-session-ux-navigation-20261106`. The PR records the exact verified SHA,
command output, JSON gate result and screenshot links. Starting remote checkpoint:
`6eab4ad16a452d0435f2c326ca80fba25256e998`.

## App boundary and branding

`apps/desktop` is the chat-first browser Webapp, served by the gateway when
`webapp.enabled` is true. It uses the existing session, streaming, attachment and
approval APIs. `web` is the administration dashboard: its Chat page embeds a
terminal. This change does not restyle that terminal into Aura.

PR #5's branding at `af620af2a7da39d932c2e3d60db7d0b7d5c9b55b` is incorporated
with a feature-branch merge. Previously uncommitted Aura work was reviewed and
continued with founder authorization. No protected branch was merged or changed.
The existing sign-in page and public crystal mark are retained.

The Webapp opens its existing chat route inside an Aura shell, with no mode picker.
It adds a phone menu sheet / collapsible desktop rail, grouped conversation history
and search, appearance settings, a warm empty state, source chips, goal editing,
progress and resume cards, and a keyboard-aware composer. The existing approval
card answers the real pending request with Approve once / Change (deny); there is
no skip-all control in this interface. Runtime/session behavior is retained.

Palette, font, spacing-unit and radius **values** were reviewed against the approved
Reveta v2 tokens. No private token files, design-library source or illustrations
were copied. Inter and Outfit come from public Google Fonts sources with OFL
notices and SHA-256 records under `apps/desktop/public/fonts/aura`.

## Reproduce and evidence

Use Node 26.12.1, pnpm 12.15.0, Python 3.14, Ruff 0.15.22 and just 1.59.0:

```sh
uv sync --frozen --group dev
pnpm install --frozen-lockfile --ignore-scripts
. .venv/bin/activate
just aura-check > /tmp/aura-check.json
pnpm --dir apps/desktop exec vitest run --project ui --maxWorkers=2 --reporter=dot
```

The gate pins a 4 GiB Node heap. JSON goes to stdout and check output to stderr.
A failing required check exits nonzero. The browser check runs the real local
Webapp and FakeLLMServer with fresh temporary homes, synthetic credentials and
manual approvals. Private sign-in links are passed over stdin, not printed.
Cleanup deliberately interrupts only that temporary test gateway with
`gateway stop --yes`, including when an assertion fails mid-turn.

The browser flow checks sign-in into chat, fake streaming, no upstream branding
in the tested signed-in states, source chips, editable goal, grouped/searchable
history, reopening with a resume card, theme controls, header touch targets,
reduced motion and overflow at 320/375/390 px. The original checkpoint used a
disposable-directory approval fixture. The current harness replaces that with a
loopback-only mock: zero requests before approval or after Change, exactly one
after Approve once. No external recipient or customer data is involved. Image and URL attachment and the no-model
screen are separate assertions. Screenshots use synthetic data only.

The PR records actual exit codes and every unavailable check; this document is
not a claim that an unexecuted future run passed. `aura-check-live` remains a
refusal-only placeholder and was not run. Fake responses are not real-model proof.

## Recorded verification

Pre-commit working-tree verification on 10 November 2026 completed as follows.
The PR also contains the clean committed-tree rerun, its exact SHA and full JSON;
the pre-commit run must not be mistaken for that later evidence.

| Command / check | Exit | Observed result |
|---|---:|---|
| `just aura-check` | 0 | Webapp build, typecheck, desktop lint and the checks below passed |
| `pnpm --dir apps/desktop run typecheck` | 0 | 4 GiB Node heap |
| `pnpm --dir apps/desktop run lint` | 0 | 0 errors; existing warnings retained |
| Gate's selected UI test files | 0 | 88 tests passed |
| Gate's isolated foundation/config/runner tests | 0 | 15 tests passed |
| Gate's selected public-Origin contracts | 0 | 14 tests passed |
| `python scripts/reveta/aura_browser.py` | 0 | Real Webapp + fake streaming, approvals, reopening, attachments, no-model, mobile and desktop checks |
| `scripts/run_tests.sh tests/hermes_cli/test_dashboard_auth_prefix.py --noconftest -q` | 0 | 26 sign-in/prefix regression tests passed |
| `pnpm exec eslint -c apps/desktop/eslint.config.mjs scripts/reveta/aura_browser.mjs` | 0 | Browser harness lint passed |
| Ruff on the new Python harness/config files | 0 | Passed |

The broad `vitest run --project ui --maxWorkers=2 --reporter=dot` sweep was started
while development continued. Its eventual result and that limitation are recorded
separately in the PR; it is not substituted for the final gate on the committed
code. The final gate reruns all new/changed component contracts.

The first complete UI sweep at `fcc1aeab88a7fafae9def41edd0d8d55105de380`
ran 1,581 files: 1,577 passed; 25 assertions failed across four files. The new
browser branding exposed old title/default-mode expectations, a native-title
convention violation, and a renderer-only `window` lookup in runtime translations.
Corrections preserve the native translation path without `window`, use the house
Tip component, and retain the profile-door invariant under Aura's Simple default.
All four affected files then passed together (94 tests). They are now included in
the default gate. The PR records the clean corrective-commit gate and complete
suite rerun; the initial failing sweep is not described as passing.

Verified text/accent contrast pairs: light primary on Mist 15.31:1, light secondary
on Mist 5.26:1, white on link blue 4.62:1; dark primary on base 16.93:1, dark secondary
on surface 7.36:1, dark base on accent blue 6.77:1. This is not a blanket WCAG audit.

## Model configuration without provider calls

`scripts/reveta/aura_config.py` previews a configuration without network calls or
reading key files. `--write <config.yaml>` explicitly writes it, retaining unrelated
configuration entries. Key **values** never appear in its output or config file.
It selects `openrouter/free` when OPENROUTER_API_KEY is present, then Gemini
`gemini-2.5-flash` when GEMINI_API_KEY is present. With both keys, Gemini is the
fallback. With neither, a closed loopback custom endpoint makes the missing-model
state explicit instead of selecting an ambient paid provider.

Anthropic is disabled even if an Anthropic key exists. There is no verified
spending-cap integration, so enabling it is deliberately not implemented. Gemini
free-tier availability depends on the founder's project, region and quota settings;
no billing or free-tier claim was verified by contacting a provider.

## Render cutover — documentation only, not executed

The live preview was not changed. A deployment/restart needs separate founder
approval. The repository Dockerfile already builds the Webapp bundle.

1. Review and deploy the exact tested feature commit only after approval, keeping
   PR #3 draft until reviewed. Retain the current login configuration. Do not change
   repository visibility or create a new service.
2. Retain `HERMES_HOME=/opt/data`, set `PORT=10000`,
   `HERMES_DASHBOARD_PUBLIC_URL=https://aura-zero.onrender.com`, and
   `HERMES_YOLO_MODE=0`. Retain the existing
   `HERMES_DASHBOARD_BASIC_AUTH_USERNAME`; the founder enters/rotates
   `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` in Render, never in Git or chat.
   Optionally set OPENROUTER_API_KEY and/or GEMINI_API_KEY in Render's secret
   environment. Keep the chosen home free of provider keys in `.env`/auth files:
   the unchanged Hermes runtime supports those sources too and can prefer them.
3. Preview the generated config locally before approving the cutover. For a Docker
   Command override, the exact wrapper is:

   ```sh
   /bin/sh -c '/opt/hermes/.venv/bin/python /opt/hermes/scripts/reveta/aura_config.py --write "$HERMES_HOME/config.yaml" && exec /opt/hermes/docker/entrypoint-dispatch.sh gateway run'
   ```

   This replaces the old **dashboard** command with **gateway run**, preserving the
   dispatcher and its bootstrap. It does not launch a second frontend or a second
   listener on port 10000. The interpreter is the image's canonical Python
   (`HERMES_PYTHON` in Dockerfile). Verify the full command in an approved
   deployment rehearsal before changing the live service.
4. The generated Webapp config is:

   ```yaml
   webapp:
     enabled: true
     host: 0.0.0.0
     port: 10000
     public_url: https://aura-zero.onrender.com
   approvals:
     mode: manual
     cron_mode: deny
     unattended_mode: deny
     single_query_mode: deny
   ```

   `PORT` alone does not select the Webapp listener port. Do not run dashboard on
   that same port. Configure `dashboard.trusted_proxies` only with the verified
   Render proxy address/range if required for secure forwarded HTTPS cookies;
   do not guess a range or trust all addresses.
5. Founder acceptance: verify anonymous access is refused, existing login reaches
   Aura chat, sign out works, a no-key home displays the notice, and the selected
   model/quotas are correct before any separately authorized live prompt. Roll back
   to the previous approved image/command/config if this cutover fails. The free
   service remains ephemeral; this does not establish restart durability.

## Limits and founder decisions

- No deployment, Render configuration, authentication implementation, repository
  visibility, provider account or infrastructure was changed.
- No new Reveta policy enforcement was implemented. The approval negative test
  proves one guarded terminal action, not blanket coverage of every possible tool.
- Goal edits are UI annotations; they do not rewrite stored messages or system
  prompts. Source cards expose explicit citations; dates/metadata are not invented.
- Keyboard screenshots emulate a reduced viewport, not a physical phone keyboard.
  Real mobile IME behavior and exhaustive WCAG/manual assistive-technology review
  remain to be checked. The PR identifies actual automated coverage.
- Restart durability, real voice, automation canvas, knowledge graph and paid asset
  generation remain out of scope. Live provider behavior is unverified.
- Founder decisions: public versus private repository; final crystal versus plain
  Aura mark; model keys/free-tier quotas; enforceable spending cap before Anthropic;
  Render cutover approval and proxy/cookie validation.

Next smallest step after this handoff: review the screenshots and browser evidence,
then approve or decline a separate preview cutover rehearsal. Do not infer release
or production readiness from fake-provider acceptance.
