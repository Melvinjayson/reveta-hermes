# Aura Zero branch map and recovery record

## Consolidation status — 18 November 2026

Checked against GitHub on 18 Nov 2026 around 23:30 GMT (`git ls-remote`, `gh pr list`, `gh pr checks`).
Nothing below was merged, deleted, closed or deployed by this record.

### Open branches and pull requests

| Branch | Head | Base | PR | Ahead / behind live | State |
|---|---|---|---|---|---|
| `aura/working-product-20261111` | `e78821386a54` | — | — | live line | Render (`https://aura-zero.onrender.com`) deploys every push |
| `main` | `a776809ad81e` | — | — | 0 / 103 | Upstream Hermes Agent baseline, never pushed to |
| `claude/aura-redesign-v1` | `edcdeaaf249c` | live | #17 draft | 19 / 0 | Mergeable; GitHub checks failing (decision G) |
| `claude/aura-persistence-notes` | `b2e5a5af08db` | #17 | #18 draft | 23 / 0 | Mergeable; GitHub checks failing |
| `claude/aura-handoff-20261118` | `ea7b4916d759` | #18 | none | 24 / 0 | Handoff doc only |
| `claude/aura-pipecat-voice-v2-3p4qpx` | `816cd981dd24` | live | #16 draft | 16 / 0 | Mergeable alone; conflicts with #17 in 3 browser-test scripts |
| `aura/browser-companion` | `7ddaa8e1714850` | live | #10 open | 2 / 13 | One feature commit `f58e8cbf` (Melvin Jayson); no file overlap with #16, #17 or #18 |
| `aura/pipecat-voice` | `db19b9a98315` | live | #11 draft | 8 / 24 | Conflicting. Superseded: all 8 commits are cherry-picked with `-x` into #16; only its Dockerfile hunks were dropped on purpose |
| `aura-zero/consolidation-20261118` | this branch | live | draft | stack + docs | Release carrier for the stack; report titles say Aura Zero |

File overlap measured from each branch's merge base: #16 and the #17/#18 stack share only
`scripts/reveta/aura_browser.mjs`, `scripts/reveta/aura_browser.py` and
`scripts/reveta/aura_product_browser.mjs`. A trial merge of #16 onto the stack stops on exactly those
three files: #17 rewrote the theme, panel and voice steps for the new shell, and #16 added a voice-mode
scenario and moved the product flow's voice steps to `continuousVoiceFlow`. Resolving them is a test
rewrite, so it belongs with decision B. A trial merge of #10 onto the stack had no conflicts.

### One release line

1. Decision G names #17's failing checks against base `e7882138`. Only checks that fail on the stack and
   not on the base block the release.
2. Decision D (`aura_config.py` carry-over and configurable public address) lands next, so settings
   survive the restart that every deploy causes.
3. Decisions F, A and B land as their own draft PRs stacked on the redesign: A carries PR #10's
   `f58e8cbf` with Melvin's authorship, B carries PR #16 and resolves the three test files.
4. Each approved slice is merged into this branch with a merge commit (never a squash), so every
   commit and author is kept. Decisions E and C follow the same path when ready.
5. Then #10, #11 and #16 can be closed as carried, and their branches kept or tagged as in the
   table below. PR #11 needs Melvin's word before it is closed.
6. Deploy = merging this branch into `aura/working-product-20261111` with a merge commit, after the
   checks above pass with no new failures against the base. On Render free the redeploy wipes the
   saved key and chat history, and full duplex voice cannot run there (memory), so it stays off.

Consolidated 15 November 2026. Live preview then: `e2e7c1ac1843` on `aura/working-product-20261111`.

## Kept

| Branch | Why |
|---|---|
| `aura/working-product-20261111` | Canonical product line. Render deploys from it; every push redeploys and wipes the saved key and chat history on the free plan. |
| `main` | Default branch; untouched upstream Hermes Agent baseline (`a776809ad81e`), an ancestor of the canonical line. Not pushed to: pushes to `main` fire Docker publish, docs deploy and autofix workflows. |
| `aura/goal-intent-voice-ui` (PR #12) | Next release carrier: CI fixes, contributor mapping, Aura rebrand of the repo docs, this record. Merge with a merge commit, not a squash. |
| `aura/browser-companion` (PR #10) | Companion extension, off by default; canonical merged in, lint fixed. Release together with the browser-action work. |
| `aura/pipecat-voice` (PR #11) | Draft voice work with unique commits; conflicts with PR #12 in `voice-call.tsx`. |
| `aura/local-talk-prototype` (PR #15) | Draft opt-in on-device chat; needs a phone test and review. |

Active task branches (`aura/browser-action-loop`, `aura/pdf-composer`) were local only at consolidation time and were not touched.

## Retired

Every tip below is either contained in the canonical line or kept by a tag. Recover with `git push origin <sha>:refs/heads/<branch>`.

| Branch | Tip | Preserved by | PR |
|---|---|---|---|
| `preview/hermes-preserved-ui-20261106` | `a776809ad81e5ff239de037befb14f41be96edcf` | `main` (same commit) | base of #1 |
| `feat/reveta-ecosystem-foundation-20261106` | `1ebc275fef38c4de5519838445ddf6b8fa9a86ce` | canonical history | #1 closed |
| `fix/chat-session-ux-navigation-20261106` | `be04ce9bfab76466bf4e1bbad82c37be6efe7ca2` | canonical history | #2 closed |
| `feat/aura-chat-slice-20261109` | `135185c286a52717390736918aa367fcb66c7992` | canonical history | #3 closed |
| `feat/aura-min-branding-20261109` | `af620af2a7da39d932c2e3d60db7d0b7d5c9b55b` | canonical history | none |
| `aura/chat-context-collapse-20261113` | `4e042fa4afbb892e2e95137ab780c71ec50abdc4` | canonical history | none |
| `aura/pipecat-duplex-20261114` | `cc3214262a7e9b8985b097d10a1b84c8c270b626` | canonical history | none |
| `aura/tonight-voice-models` | `e8f7a5e13bbf1f940dbbf25658a897a446a78dad` | canonical history | none |
| `aura/conversation-intent` | `4ba101ddaf2e2e4671ea0b07d24635cc0b1129c9` | canonical history | #14 merged |
| `aura/release-candidate-20261115` | `e2e7c1ac18432a2770eb19557c05a29b40d2ea40` | canonical tip (same commit) | none |
| `aura/fix-quota-model-follow` | `01f2d3d6b588734f0289a1bb63e204897ed22dff` | PR #12 branch; tag `archive/fix-quota-model-follow` | #13 merged |
| `feat/aura-simple-mode-acceptance-20261109` | `e0c59aee49b7176b1aa79527bb16ed31a1f2f091` | tag `archive/aura-simple-mode-acceptance` | #4 closed: canonical already opens browser builds in Simple mode |
| `feat/aura-waking-page-20261109` | `a4506126115c3ced629a59634b6879927ab45894` | tag `archive/aura-waking-page` | none: static page needed a separate host that was never set up |

PR #6 (canonical branch into the stale `feat/aura-chat-slice-20261109`) was closed; its branch is the canonical line and stays.
