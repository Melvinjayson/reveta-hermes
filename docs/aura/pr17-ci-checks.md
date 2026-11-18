# PR #17 — the 3 failing GitHub checks (decision G)

Investigated 18 Nov 2026. PR #17 head `edcdeaaf`, CI run
[44408163849](https://github.com/Melvinjayson/reveta-hermes/actions/runs/44408163849). Base for comparison:
`e78821386a54` (PR #15 merge). Base itself has **no CI run** (`GET /commits/e7882138/check-runs` returns
none), so "base" evidence below comes from (a) reproducing the same job steps locally on a base worktree, and
(b) CI on PR #16, which is based on `e7882138`. Logs were read in full from the public job-log API.

## Answer

**None of the 3 failures is caused by PR #17.** Two are pre-existing on base with direct evidence. The third
(Windows) has the same failures as PR #16 on the same base, plus four PowerShell/named-pipe tests that timed out
in paths PR #17 does not touch; whether those four also time out on base is **UNVERIFIED** (no Windows host here).

| # | Check (job id) | What fails | New vs base `e7882138` | Label |
|---|---|---|---|---|
| 1 | **Python lints / Python lints** (135169617013) | Steps *footgun checker*, *no literal /tmp*, *ruff check* — all 6 findings are in `scripts/reveta/aura_voice_call_live.py`: `open()` without `encoding=` (line 22), `/tmp/tts_sample.wav` (line 27), 4 × ruff `UP031` (lines 64, 73, 79, 83) | **Pre-existing.** The file is byte-identical on base and PR #17 (blob `13ceec394f`). Local `scripts/check` on base fails the same three checks (handoff §2). PR #16's lints pass only because PR #16 changes this file (`5ed90c6b`, blob `c5bc4e2241`) | FAILED (pre-existing) |
| 2 | **JS & TS checks** (135169615896) | 2 of 10 workspace checks: (a) `apps/desktop :: check:test:desktop:platforms` — 1 test, `electron/source-backend.test.ts` "a PM source launcher reaches real health and RPC…": the backend exits with `ModuleNotFoundError: No module named 'reveta_ecosystem'`, imported by `hermes_cli/web_routers/reveta.py` (last changed `3d685fc4`, before base). (b) `tests-js :: check` — 1 test, `bundle-smoke-metadata.test.mjs` "channel smoke binds the complete admitted request…": **timed out at 15 s**. Everything else passed (desktop UI vitest 13,239/13,239, lint, ui-tui, web, shared) | (a) **Pre-existing**: running `pnpm run test:desktop:platforms` locally gives the identical single failure with the same `reveta_ecosystem` error on **both** base and head (1 failed / 4,090 passed each). (b) **Not reproducible**: the test passes locally on both base and head (4 passed, 1 skipped each); in CI it timed out on #17 and again on #18. PR #17 changes no file this test imports (`tests/install/e2e-assets/*`). Treated as a CI-runner timing failure; base CI result UNVERIFIED | (a) FAILED (pre-existing) · (b) FAILED in CI, PASSED locally on base and head |
| 3 | **OS-specific tests / Windows-only tests** (135169617410) | 7 files with failures + 3 files where no test ran: `test_control_socket_windows_live.py` (2), `test_git_trampoline_windows_live.py` (2), `test_local_runtime_processes.py` (2), `test_plugin_host.py` (4), `test_computer_use_native_platform.py` (4, refused by the Aura cost policy: "This would cost money…"), `test_code_execution_modes.py` (4), `test_install_ps1_iex_failure.py` (1, PowerShell 60 s timeout); no tests ran: `tests/ci/test_update_ci_routing.py`, `test_install_ps1_pinned_git_extract.py`, `test_install_ps1_native_calls.py` (300 s kill) | **Same as PR #16 (same base)** for 6 files and `test_update_ci_routing.py`. Differences vs PR #16: one more `control_socket` test and the three `install.ps1` files, all timeouts. PR #17 touches **0** files under `scripts/install*`, `tests/scripts/install`, `gateway/`, `tests/ci`, `hermes_cli/plugin_host*`. PR #18 (stacked on #17) shows the identical list | FAILED; 6 of 7 files pre-existing (PR #16 evidence); the 4 timeout differences UNVERIFIED on base |

Not failures, but not green either: `Python tests / Run tests (1–3/3)` and both `macOS-only tests` jobs were
**cancelled** (~30 and ~15 minutes in), and both `Windows-only tests (arm64)` jobs were still **queued** when read.
Their results are UNVERIFIED.

## Fixes (not made in PR #17; each is outside its scope)

1. Lints: cherry-pick PR #16's `5ed90c6b` (or the same three edits) when PR #16 joins the stack (decision B).
2. Electron source-launcher test: the PM source install used by the test does not ship `reveta_ecosystem`.
   Either package it, or make `web_routers/reveta.py` import it lazily. This is a base defect; it needs its own small PR.
3. Windows: the Aura cost policy refusing `computer_use` / plugin-host calls in upstream Windows tests is a
   base-wide conflict between Aura's free-only gate and upstream tests; out of scope here, listed for Melvin.

## How to reproduce

```bash
# job logs (public repo)
curl -sSL https://api.github.com/repos/Melvinjayson/reveta-hermes/actions/jobs/135169615896/logs > js.log
git worktree add --detach ../base e78821386a54b88a3f26844f9e8878ff19cf8a14
git worktree add --detach ../head edcdeaaf249c5b6c35bf24d6b0f1aa2f74ed147a
# in each, after source ./activate and pnpm install --frozen-lockfile --ignore-scripts:
(cd apps/desktop && pnpm run test:desktop:platforms)
(cd tests-js && pnpm exec vitest run bundle-smoke-metadata.test.mjs)
git rev-parse e7882138:scripts/reveta/aura_voice_call_live.py edcdeaaf:scripts/reveta/aura_voice_call_live.py
```
