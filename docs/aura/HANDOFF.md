# Aura interface handoff

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
reduced motion and overflow at 320/375/390 px. A disposable directory must exist
while an approval is pending and is removed only after Approve. No external
recipient or customer data is involved. Image and URL attachment and the no-model
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
