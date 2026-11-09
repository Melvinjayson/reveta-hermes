# Aura verification foundation

Repository: `Melvinjayson/reveta-hermes`. Branch: `feat/aura-chat-slice-20261109`.
Baseline: `be04ce9bfab76466bf4e1bbad82c37be6efe7ca2`.
Surface A: existing browser Webapp; Simple mode is the next product target.
The draft PR records the exact checkpoint SHA and post-commit JSON summary.
Obtain the containing checkpoint with `git log -1 --format=%H -- docs/aura/HANDOFF.md`.

## Reproduce

Use Node 26.12.1, pnpm 12.15.0, Python 3.14 and Ruff 0.15.22.
Install into isolated tool directories and activate the project environment:

```sh
uv sync --frozen --group dev
pnpm install --frozen-lockfile --ignore-scripts
. .venv/bin/activate
just aura-check > aura-check.json
```

Keep the result outside the checkout for a clean-tree run. `just` 1.59.0 was
installed as an isolated development tool. For pnpm installed with lifecycle
scripts disabled, inspect and explicitly run its own `install.js` to expose the
native executable: its placeholder can fall through to another pnpm when
launched without a shell. The gate checks exact tool versions.

The runner builds the Webapp, typechecks, lints, runs 60 selected UI contracts,
the existing isolated foundation/container/skill tests, runner failure tests,
14 dashboard public-Origin contracts, and fake-provider streaming/fault HTTP
integration. Command output goes to stderr; JSON goes to stdout. Any required
failure exits nonzero. A temporary Hermes home and a credential allowlist isolate
checks from operator model configuration. Node receives a 4 GiB heap: the initial
typecheck exhausted its default 2 GiB heap; the 4 GiB rerun passed.

Before this commit, all selected checks passed. Desktop lint reported 378 existing
warnings and zero errors after the prop-order correction. The original targeted
lint reproduced one `perfectionist/sort-jsx-props` error; the corrected file passed.
The PR supplies the post-commit result; this document does not self-certify an
unexecuted future run.

An additional local probe launched and stopped a temporary gateway with the existing
FakeLLMServer and manual approvals, and rendered the Webapp root in headless system
Chromium at 390 × 844 using the installed Playwright package. This proves initial
rendering only, not chat acceptance. No sign-in links or credentials are retained.

## Remaining acceptance

G1 test 1 has a foundation gate; the complete G1 gate is not implemented.
Tests 2–10 (browser chat, all mobile/theme/accessibility cases, browser reopening,
logout/login, local restart history, retry deduplication, interruption and anonymous
session boundaries) are unverified. Test 11 has selected unit/boundary coverage;
dashboard browser smoke and the full desktop/Electron suites are unverified.
Test 12, live-model verification, was not run. `just aura-check-live` refuses with
exit 2: live implementation and execution require a separately authorized step.
The fake HTTP probe is not a Hermes turn or real-model evidence.

No governance plugin or stretch work was implemented. No branding assets, product
defaults, runtime, session or authentication behavior were changed. No proprietary
source documents or tokens were copied. No infrastructure or deployment was changed.

Next smallest step: add a browser acceptance test that signs in to a temporary
Webapp, selects Simple mode, submits synthetic text and observes a streamed reply
from FakeLLMServer through the real Hermes runtime. Preserve existing approvals.

## Existing shortcut markers

`git grep -nE '(#|//|/[*]) ?(shortcut|ponytail):'` returned nine existing markers,
in `apps/desktop/src/components/assistant-ui/thread/list.tsx:923`,
`hermes_cli/_launchers.py:846`, `hermes_cli/main_desktop.py:1266`,
`hermes_cli/process_identity.py:642`, `hermes_cli/venv_sync.py:585`,
`hermes_state_dbfile.py:337`, and
`optional-skills/creative/auteur/scripts/slopscan.mjs:62`, `:82`, `:371`.
This checkpoint introduces none.
