# Branch map and recovery record

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
