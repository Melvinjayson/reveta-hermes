# Aura interface handoff

## Radix focus teardown correction

Base verified clean and remote-matching: `13fead82b6f4d2c976127b579e4487059d599f9e`.
Only the fleet-rail test lifecycle changes; no application, free-only allowlist,
provider, deployment, Render, authentication or secrets changes.

The preceding complete UI run passed 13,174 assertions but exited 1 because a
Radix focus-scope zero-delay unmount timer dispatched a CustomEvent after its
jsdom environment had changed. Synchronous Testing Library cleanup removed the
portal but returned before that callback. The affected file now awaits one real
event-loop turn inside React `act` after cleanup, before resetting mocks/stores
and letting Vitest dispose the environment. The callback executes normally; no
exception filter, timer cancellation, skip, suppression or timeout increase is used.

A regression opens the real condensed rail menu, observes Radix's unmount-focus
event, calls the same teardown helper, and checks one callback using the current
window's CustomEvent plus absence of the menu and portal. With synchronous cleanup
it failed (callback count 0, 31 existing tests passed, exit 1); with the fix all
32 tests passed, exit 0, 7.91s. This proves the lifetime gap without relying on a
random cross-file race to reproduce the old full-suite error.

Focused command (Node 26.12.1, pnpm 12.15.0, Linux, 4096 MiB heap):

```sh
NODE_OPTIONS=--max-old-space-size=4096 pnpm --dir apps/desktop exec vitest run --project ui src/app/chat/sidebar/profile-rail-fleet.test.tsx
```

Changed-file ESLint and `git diff --check` are required before commit. The complete
UI project then runs once on the committed implementation tree with the command
below. Its exact exit code, counts, tested SHA and gate JSON will be recorded here
in an evidence-only follow-up; no UI changes follow that run.

```sh
NODE_OPTIONS=--max-old-space-size=4096 pnpm --dir apps/desktop exec vitest run --project ui --maxWorkers=3 --reporter=dot --reporter=json --outputFile.json=/workspace/aura-evidence/focus-final-ui.json
```

Evidence: `/workspace/aura-evidence/focus-timer-red.log`,
`focus-timer-green.log`, `focus-final-ui.log`, `focus-final-ui.json` and
`focus-final-gate.json`. The gate records the process exit code separately because
Vitest's JSON `success` alone did not reflect the preceding unhandled exception.
The earlier `just aura-check` exit 0 at 13fead82 remains historical evidence;
this test-only correction reruns the requested focused and complete UI project,
not providers, backend tests, browser acceptance or deployments. Live-model,
physical-phone, restart and OS containment limitations below remain unchanged.

## Free-only routing increment — local fixtures, no live provider authorization

Starting branch/remote SHA verified clean: `3e3845d090a4568f76308546e4545ed016bc2eda`.
This section supersedes the missing-free-only statements in the historical
checkpoint below. Final implementation SHA, gate JSON and exit codes are recorded
in draft PR 3 after the committed-tree checks finish. No live loop is claimed.

### Server enforcement

`tools/aura_free_only.py` checks the final provider, exact model ID, endpoint and
request payload before main and auxiliary chat-completion requests. There are no
real model IDs or price attestations shipped. Missing lists deny all generation
and all tool execution, including otherwise read-only tools. A key or provider
name does not authorize a call. The server-owned configuration is:

```yaml
aura:
  free_only: true
  free_models: []
  free_tools: []
```

A model entry requires exact `provider`, `model`, `base_url`, `confirmed_free: true`
and numeric `cost_usd: 0`. A tool entry requires exact `name`, `arguments_sha256`
(SHA-256 of canonical sorted compact UTF-8 JSON arguments), the same confirmed
zero price, and exactly one match. There is no wildcard command attestation.
Positive, unknown, malformed, duplicate or unconfirmed prices refuse. Only the
true setting is supported: false or malformed settings refuse instead of enabling
paid mode. Spending-cap/paid operation needs a separately authorized increment.
These are owner attestations, not independent billing/pricing verification.

The tool gate checks price before approval and again after waiting for approval;
revocation cannot release the pending action. Known positive connected-tool
charges override an erroneous zero attestation, including the legacy connector
handler. Approval binding and all existing tool guards remain in force. All file
mutations still ask, even workspace drafts; they also need exact zero-price
attestations. Unknown tools are both unknown-price and consequential.

Main fallback activation and auxiliary recovery routes stop under free-only;
quota, error and rate-limit recovery cannot construct a paid fallback. Normal
same-route transient retries may remain. Model-routing aliases, payload model
substitution and priority tiers refuse. Provider fallback is disabled in outgoing
requests; OpenRouter also receives zero maximum input/output prices. Standard
HTTPX-backed chat-completion clients have redirects disabled. Unsupported modes,
composite routes and unrecognized client transports refuse even if listed.
No real provider was called to test these controls.

The existing key-driven `aura_config.py` generator is not a price authority. Its
OpenRouter automatic alias / Gemini fallback defaults are not authorized by this
policy. A future live route requires founder-confirmed exact pricing, an explicit
model/endpoint, and review of generated configuration before any live cutover.
No Render command or deployment was changed by this increment.

### UI and fixture boundaries

Structured backend cost refusals produce a Refused step showing:
"This would cost money, so I didn't run it." Assistant prose alone cannot create
that status. Approval cards say Free only after an exact zero-price attestation.
No other screens, file viewer or live loop were added.

`tests/fakes/aura_price_policy.py` attests exact synthetic actions in temporary
fixture homes. Existing permission tests now supply those fixture attestations;
the cost guard is never switched off. FakeLLMServer's temporary configuration
attests only its owned loopback fixture model. None is a founder-confirmed real
provider/tool entry. Browser and connected-app writes use synthetic executable
handlers, not real accounts or browser submits.

### Coverage

| Action type | Classification | Guarded on server? | Test | Focused result |
|---|---|---|---|---|
| Non-allowlisted main model | Unknown price → Refused | Before client creation | `test_non_allowlisted_model_never_constructs_or_calls_transport` | Passed |
| Paid/unconfirmed/unknown model or endpoint | Refused | Final request identity | `test_paid_unknown_or_unconfirmed_price_is_refused` | Passed (4 cases) |
| Confirmed zero-price fixture model | Allowed | Main dispatch | `test_allowlisted_fixture_model_runs_through_main_route` | Passed; fixture only |
| Free quota → paid fallback | Refused fallback | Main and auxiliary routes | `test_free_quota_error_does_not_activate_paid_fallback`, `test_auxiliary_quota_stops_before_any_recovery_route` | Passed; simulated quota |
| Model/payload override, priority tier, redirect | Refused / redirect not followed | Request and HTTP client | `test_wire_overrides_cannot_escape_allowlist`, `test_redirect_cannot_escape_confirmed_endpoint` | Passed; local SDK transport |
| Unknown/paid tool or add-on | Refused before prompt/handler | Shared dispatch | `test_unknown_tool_price_refuses_before_approval_and_side_effect`, `test_positive_tool_price_cannot_be_marked_confirmed_free` | Passed |
| Positive declared connected-tool cost | Refused despite zero attestation | Shared gate and connector handler | `test_declared_mcp_charge_overrides_zero_attestation_before_approval` | Passed; fixture only |
| Price revoked during approval | Refused | Recheck before execution | `test_revoked_zero_price_while_approval_pending_prevents_execution` | Passed |
| Auxiliary sync/async/stream unknown model | Refused | Final provider callback | `test_auxiliary_sync_async_and_stream_routes_cannot_call_unknown_model` | Passed |
| False/malformed free-only setting | Refused | Config validation | `test_disabling_or_malformed_mode_cannot_enable_paid_calls` | Passed (4 cases) |
| Browser submit / connected-app write | Consequential after price check | Same registry approval gate | `test_browser_and_connected_app_fixture_use_same_single_use_gate` | Passed (2 fixture cases): Change=0, Approve once=1, replay=0 |
| Shell variants, helpers, unattended, binding/replay/expiry | Existing permission policy | Shared server gate | `tests/tools/test_aura_dispatch_gate.py` | 29 passed with explicit synthetic zero-price attestations |
| Non-allowlisted model in Webapp | Refused step, no generation request | Real local Webapp route | `scripts/reveta/aura_browser.py` | Passed with zero additional FakeLLMServer generation requests |

Focused evidence, all exit 0:

- `HERMES_PYTHON=$PWD/.venv/bin/python bash scripts/run_tests.sh tests/tools/test_aura_free_only.py tests/tools/test_aura_dispatch_gate.py --noconftest -q`: **54 passed** (25 cost cases + 29 approval tests).
- Same runner with the two existing `test_approval_gateway_wait_*` files: 13 legacy approval tests passed (earlier 66-test run, before final auxiliary quota test).
- `pnpm --dir apps/desktop exec vitest run --project ui src/app/aura`: focused Aura contracts **12 passed across 4 files**.
- `pnpm --dir apps/desktop run build:webapp`: passed.
- `python scripts/reveta/aura_browser.py`: passed normal chat/approval, cost-refused and no-model scenarios after redirect protection; existing fake provider only.

Final gates run once on the committed tree with Node heap 4096 MiB: `just
aura-check` (includes these pricing/approval Python tests, selected UI contracts,
build/typecheck/lint, fake HTTP integration and browser harness), plus the full UI
project. Their exact exit codes/counts and machine-readable output belong in PR 3;
this paragraph is the verification plan, not a claim that pending gates passed.
Screenshots from the final harness use the existing screenshot index; additional
cost-refusal behavior is asserted in the browser, not represented as a new screen.

### Remaining risks and unverified boundaries

- No live provider/model, billing-account/quota validation, external price lookup,
  actual provider fallback or paid-tool account was exercised. Allowlist pricing
  is a trusted owner's assertion and can be wrong or become stale; no real route
  is approved by this work. An arbitrary command's price cannot be inferred safely.
- Browser submits and connected-app writes are fixture-only approval evidence;
  not proof that every live action/adapter reaches dispatch. Raw SDK use by trusted
  installed code or approved commands is not universally contained.
- No OS-level egress containment is verified. An approved arbitrary command is
  capable of network access; a false zero-price attestation can misdescribe it.
- Real phone, full Python repository suite, Electron end-to-end, deployment smoke,
  server-restart durability and live conversation/tool/file loop remain unrun.
- Free-only rejects unsupported provider adapters and all unclassified operations;
  read/internal regressions require explicit synthetic zero-price fixtures. This
  is deliberately restrictive, not evidence that all prior runtime paths work.
- No spend, real model calls, deploys, Render, AWS, authentication, secrets or
  repository-visibility changes. Live work waits for review and a founder-confirmed
  exact free route; no general claim that Aura is safe follows from these tests.

## Dispatch approval increment — safety slice remains incomplete

Base verified clean and remote-matching: `1995763097c489e2394fc3e45d0fea94de66a586`.
The final PR records the exact implementation/evidence SHA and final-tree gate
outputs. This increment stops at the dispatch gate and command-family negatives,
as allowed by the safety directive's budget rule. **Free-only provider/tool routing
has not been implemented. The overall safety slice has not passed; live work waits.**

### Enforcement and binding

`tools/aura_dispatch_policy.py` is one policy implementation called at the registry,
connected-app, inline-agent, sequential helper, context-engine and memory-provider
execution boundaries. It runs after argument-transforming middleware. The new gate
is default-on across profiles, including missing configuration; no mode-off, YOLO,
permanent/session approval or helper callback disables it. This is intentionally
stricter than legacy native/programmatic behavior. Without a registered user
approval bridge, consequential actions are refused rather than auto-approved.

Only reviewed named reads and internal todo state bypass prompts. **All file
mutations require approval in this increment**, even inside the workspace. Profile
settings alone do not attest a session's actual backend, so automatic internal file
edits are deferred rather than allowing an uncertain classification. Multi-file
patch bodies cannot launder outside targets through a decoy top-level path. That
regression failed on the first candidate and passed after correction. No shell
command/interpreter is considered provably read-only: all command strings ask.
Unknown/new tool names ask too. Existing handler guards remain in place and can
require another approval or block an action already approved at dispatch.

Approvals bind the current profile/home, tool name and canonical exact arguments
with SHA-256. The handler receives a JSON snapshot; mutation of the original
arguments or a profile change invalidates it. Each queue entry has a unique ID,
nonce and a maximum 120-second lifetime. The resolver rejects expired/replayed
IDs, FIFO/bulk approval, session and permanent choices for these requests. One
request releases one invocation, never future or parallel calls. Change refuses
execution. Known sensitive argument patterns are masked with the existing forced
redactor. Oversized payloads and policy/config/serialization errors refuse before
the handler. Cron/unattended contexts refuse even if legacy config says approve.

The existing card remains in use, with unknown cost explicitly described as not
verified; it is never labelled Free. Step rows now recognize Refused. No other
screen, File card, panel or provider capability was added.

### Coverage

Tests use an actual loopback HTTP listener and the production `ToolRegistry`
dispatcher with executable shell handlers. Each command variant is first denied
with zero hits, then explicitly approved and proven executable with exactly one
hit. Replaying its request adds no hit. All twelve command negatives failed on
the pinned old dispatcher (12 failures, exit 1); the read/internal regression is
expected to pass on both versions. Other new negative tests were not all separately
run against the old checkout and are not claimed as baseline-red evidence.

| Action type | Classification | Guarded on server? | Test | Result before final gates |
|---|---|---|---|---|
| curl data / explicit POST | Consequential | Yes, registry | `test_command_indirections_wait_and_change_has_no_effect[curl-data/curl-method]` | Passed |
| wget POST | Consequential | Yes | same `[wget]` | Passed |
| Python / Node POST | Consequential | Yes | same `[python/node]` | Passed |
| Written script / pipe to sh / base64 | Consequential | Yes | same `[script/pipe/base64]` | Passed |
| Environment / alias / subshell / chain | Consequential | Yes | same `[env/alias/subshell/chain]` | Passed |
| Argument mutation, replay, bulk/session/always, expiry | Refused | Yes | `test_changed_arguments_invalidate_approval`, `test_expired_bulk_and_scope_approvals_cannot_execute` | Passed |
| Helper action | Consequential | Yes in simulated delegated context | `test_helper_cannot_self_approve` | Passed; no live child model |
| Cron / webhook / programmatic action | Refused | Yes in real session-context machinery | `test_cron_denies_even_with_auto_approve_configuration` | Passed; scheduler run not exercised |
| Browser submit | Consequential | Registry gate | `test_unknown_browser_and_app_writes_require_approval` | Fixture-only; no live browser submission |
| Connected-app write | Consequential | Registry + connector dispatch | previous test + `test_connected_app_real_dispatch_entry_does_not_reach_transport` | Fixture-only; no app account |
| Skills, routine creation, connect, deletion | Consequential | Registry / inline gate | unknown-action test; `test_inline_setting_change_does_not_reach_callback` | Fixtures; full backend action lifecycles unrun |
| Reads / internal todo-state edits | Read / Internal | Yes | `test_reads_and_internal_state_run_but_file_mutations_wait` | Passed; unapproved filesystem mutations refused |
| Automatic workspace file edits | Consequential pending backend attestation | Approval required | same test | Automatic no-prompt editing NOT implemented |
| Outside/symlink/relative file write | Consequential | Yes | `test_symlink_and_outside_workspace_write_cannot_use_internal_classification` | Passed |
| Missing config, off mode, policy exception, hook skip flags | Refused | Yes | policy-errors, off-mode and model-dispatch tests | Passed |
| Provider model IDs, quota fallback, paid/unknown-price tool | Not implemented | **No free-only cost guard** | Not run | BLOCKED / next increment |

The browser harness now uses the original plain loopback POST, without the old
pipe-to-shell trigger. Its user-facing Change/Approve-once counter test passed
locally with FakeLLMServer. The final gate also rebuilds the Refused renderer and
asserts that declined action's Refused row. No real provider or recipient is used.

### Residual risks and limits

- **Cost enforcement is absent.** The previous `openrouter/free` auto-router and
  Gemini fallback configuration is unchanged and is not a verified free route.
  Models, auxiliary calls, tools and add-ons need a complete fail-closed price and
  routing boundary next. No live calls are authorized by this handoff.
- This is application dispatch enforcement, not containment of adversarial Python,
  trusted plugins/hooks, installed code or an already-approved arbitrary command.
  Direct internal handler calls outside the instrumented dispatch boundaries, and
  user/operator REST actions, have not all been audited. No every-entry-point or
  every-tool safety claim is made.
- An approved script can depend on files/environment that change independently of
  its argument string. Arbitrary commands can perform multiple effects. Approval
  binds the invocation, not a verified semantic decomposition of shell programs.
- Automatic workspace filesystem editing is deferred; all file mutations ask.
  No atomic no-follow file adapter or per-user file isolation proof was added.
  Approved file operations still use the existing backend and its guards. Reads
  retain existing access policy. Session/backend ownership needs further tests.
- A capability probe `unshare -Urn true` succeeded in this managed executor. That
  does not establish namespace availability on Render. A namespace alone blocks
  legitimate approved outbound operations too; selective egress requires a mediated
  network boundary. No wrapper, proxy, hosting configuration or deployment was
  provisioned. Outer containment remains a required separate verification.
- Forced redaction covers known secret patterns, not arbitrary undisclosed secret
  prose. No authenticated connection, saved-login browser guard, actual external
  service, physical phone or restart-continuity test ran.
- Full-repository Python compatibility is not established. Default-on denial with
  no user bridge intentionally changes legacy direct/native/unattended execution.
  The final PR lists exactly which Python and UI gates ran; no skipped gate passes.

Focused evidence: `safety-base-command-family.log` (old code, 12 failed),
`safety-precommit.log` (27 new + 13 existing tests passed before final minor
classification/test additions), `safety-browser.log` (plain-POST browser passed),
and `safety-runtime-ruff.log` (changed runtime files passed). Files are in the local
`/workspace/aura-evidence` directory; final clean-tree command/exit-code evidence is
recorded in draft PR #3. No secrets/private Reveta OS source, paid or real-model
calls, deployments, Render, auth, visibility, or infrastructure changes occurred.

The final focused candidate run `safety-ready.log` passed **41 tests** (28 new
policy tests and 13 existing approval/race contracts), exit 0. Changed Python
runtime files, policy/tests and harness passed Ruff; the minimal UI/harness edits
passed ESLint. The required final `just aura-check` adds the policy tests and lint
to its default checks. Final-tree JSON and the complete UI run are recorded in the
PR after execution, including any failure; they must not be inferred from these
pre-commit focused results. The full repository Python suite remains unrun.
After review, `safety-conservative.log` passed all **29 current policy tests**,
exit 0. This final candidate deliberately requires approval for filesystem edits;
it does not satisfy the requested automatic internal-workspace-edit acceptance.
The earlier final-gate/UI runs were interrupted for the patch correction and are
not passing evidence. Only the restarted final-commit results in the PR count.

Next smallest step is **complete server-side free-only provider/tool routing and
its quota/unknown-price negatives**, followed by remaining authority-path tests.
Do not choose a live model or start the file loop before that slice passes.

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
