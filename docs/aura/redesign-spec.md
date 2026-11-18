# Aura redesign v1 — specification

Branch `claude/aura-redesign-v1`, based on `aura/working-product-20261111` at
`e78821386a54` (PR #15 merge). PR #16 is not used. Not merged, not deployed.

## 1. Objective and decision

**Objective.** Bring Aura's webapp (Simple mode, `apps/desktop/src/app/aura/`)
to the interaction standard users now expect from Perplexity, Manus and
ChatGPT: a quiet shell, a centred composer, a readable thread, visible agent
work and clear approvals, on phone and desktop.

**Audience.** Melvin (owner, decides merge) and Aura's first users on phones.

**Decision this supports.** Whether to merge this redesign into the integration
branch (which auto-deploys to Render). This branch makes no merge or deploy.

**Constraints.** No change to auth, security checks, Dockerfile, Render config
or startup scripts. Manual approvals stay manual; YOLO stays off. The current
voice implementation stays the default. Never show a feature Aura's data does not
support. Shared desktop components change only behind `isBrowserHostedDesktop()`
or Aura-scoped CSS, so the Electron app is unaffected.

**Method.** Uizze `ui-design` (new-work, craft, operate) and `anti-ui-slop`
finish gate, read from `uizze/uizze@fc401e9e` and followed, not vendored. The
brief supplies the direction, so no alternative directions were proposed.

## 2. What the product can truthfully show (data audit)

| Pattern asked for | Aura data today | Decision |
|---|---|---|
| History grouped Today / Yesterday / Previous 7 days | `SessionInfo.last_active`, `started_at` | **Build** (client grouping; adds "Previous 7 days" and "Older") |
| Search (Cmd+K) | `$sessions` titles in memory | **Build** as a title filter dialog. Full-text message search is a backend capability (`hermes_state_search`) not exposed to Aura; **gap** |
| Projects | Desktop "projects" are git-repo workspace groups; every Aura chat shares one Aura workspace | **Gap — not shown.** Needs a real Aura project model first |
| + menu: attach | Existing context menu (files, images, URL, paste image) | **Build** (restyle only) |
| + menu: tools / modes | No user-selectable tools or modes exist in Aura | **Gap — not shown** |
| Mic (dictation) on the right | Server dictation is hidden in the webapp; browser `SpeechRecognition` exists | **Build** browser dictation into the composer, hidden when unsupported. No new server path |
| Voice session | Existing `AuraVoice` (continuous socket, browser fallback) | **Keep as default**, renamed "Voice chat" |
| Removable scope chips | Attachments and attached URLs (`AttachmentList`) | **Build** (restyle as chips) |
| Send becomes stop | Existing | Keep |
| Copy and retry under answers | Existing footer, hidden until hover | **Build**: always visible on the latest answer, hover/focus elsewhere |
| Numbered source chips + list | Markdown links in replies (`auraSources`) | **Build** numbered chips; list in the side panel |
| Steps pending / active / done, timer, tool icons | `auraSteps` statuses, `timestamp`, `completedAt`, tool name | **Build** |
| Inline Approve / Deny | Existing approval card (manual, single-use) | **Build** restyle; same `respond('once' / 'deny')` calls |
| Long outputs in a side panel / sheet | Long reply text; conversation files (name, size, download) | **Build** "Open" for long replies, and the panel lists files with download. File *preview* is a **gap** (no read endpoint used by Aura) |
| Settings with sections | Appearance, model settings, voice, sign out | **Build** |
| Sign-in | Server-rendered boot overlay shared with desktop | **Not changed** (auth scope). Copy still says "Run hermes webapp"; listed as a gap for Melvin |

## 3. Information architecture

```
Shell
├─ Sidebar (desktop ≥ 900 px, collapsible) / Drawer (phone)
│  ├─ Aura mark · collapse
│  ├─ New chat
│  ├─ Search  ⌘K
│  ├─ History: Today · Yesterday · Previous 7 days · Older (row: open, delete)
│  └─ Footer: Settings
├─ Top bar (phone: menu · Aura · new chat; desktop: sidebar toggle when collapsed, chat title, Work toggle)
├─ Main
│  ├─ Home (no messages): greeting · composer · 4 starter pills
│  └─ Thread: messages · inline approvals · work status strip · composer
├─ Side panel (desktop) / full sheet (phone): Work · Sources · Files · Reply
└─ Settings dialog (desktop modal / phone full sheet): Appearance · Model · Voice · Account
```

### Key flows

1. **Start**: open → Home → type or tap a starter → Send → thread; composer docks at the bottom.
2. **Agent work**: a reply with tool calls shows a status strip ("Working · Read a page · 0:12"); tap opens Work; each step shows its state; an approval card appears inline and the run waits.
3. **Approve / Deny**: Approve runs once; Deny declines and lets the user revise. Both call the existing approval request; no auto-approve.
4. **Resume**: open history → conversation loads → "Pick up where you left off" card (existing).
5. **Delete**: row trash → inline confirm → existing `onDeleteSession`.
6. **Search**: ⌘K / Ctrl+K or the Search row → dialog filters titles → Enter opens.
7. **Voice**: mic button dictates into the draft; "Voice chat" starts the existing voice session.
8. **Settings**: sidebar footer → dialog with sections → theme applies immediately.

## 4. Design system

All tokens live on `.aura-app` / `.aura-sheet` / `.aura-dialog` in `aura.css` and
map onto the shared `--ui-*` variables, so shared components inherit them.

| Token | Light | Dark |
|---|---|---|
| `--aura-page` | `#ffffff` | `#131315` |
| `--aura-sidebar` | `#f7f7f8` | `#0e0e10` |
| `--aura-surface` (cards, composer) | `#ffffff` | `#1b1b1e` |
| `--aura-subtle` (user bubble, hover) | `#f2f2f4` | `#232327` |
| `--aura-line` | `#e4e4e8` | `#2e2e33` |
| `--aura-ink` | `#18181b` | `#ececef` |
| `--aura-muted` | `#5f5f68` (6.3:1 on white) | `#a1a1aa` (7.2:1 on page) |
| `--aura-accent` (one accent) | `#1f6fb5` (5.3:1 on white) | `#7cc4f0` (9.7:1 on page) |
| `--aura-on-accent` | `#ffffff` | `#0b1b2b` |
| `--aura-danger` | `#b42318` | `#f97066` |
| `--aura-ok` | `#067647` | `#47cd89` |

- **Type**: one sans, Inter (bundled, OFL). Scale 12 / 13 / 14 / 16 (body) / 18 / 24 / 30. Weights 400, 500, 600. Line height 1.5 body, 1.2 headings. Tabular numerals for timers. Outfit is dropped.
- **Spacing**: 4 px base; steps 4, 8, 12, 16, 24, 32, 48.
- **Radius**: 8 px controls, 12 px cards and menus, 16 px composer and user bubble, 999 px only for pills and chips.
- **Elevation**: borders first; one shadow for floating surfaces (`0 8px 24px rgb(0 0 0 / 0.08)`).
- **Motion**: 120 ms (hover, press) and 200 ms (panels, drawer), ease-out; `prefers-reduced-motion` → 0 ms.
- **Focus**: 2 px accent outline, 2 px offset, on every interactive element.
- **Targets**: ≥ 44 × 44 px on touch; icon buttons are 44 px boxes.
- **Components**: Button (primary, ghost, danger), IconButton, Pill, Chip (removable), Status dot, Step row, Card, Drawer, Side panel, Sheet, Dialog, Skeleton line.
- **States**: every list and panel has empty, loading and error copy (§6).

## 5. Changes

### Frontend (all in `apps/desktop/src/app/aura/` unless noted)

| Piece | Files |
|---|---|
| Tokens / theme | `aura.css` (rewrite of token block, Aura-scoped) |
| Shell + nav | `shell.tsx`, new `history.ts` (grouping), new `search-dialog.tsx`, new `settings-dialog.tsx`, `conversation-row.tsx` |
| Home + composer | `empty.tsx`; new `dictation.tsx`; `voice-call.tsx` / `browser-voice.tsx` label only; `app/chat/composer/index.tsx` (one Aura-gated slot for dictation) |
| Thread | `message-sources.tsx` (numbered chips), `aura.css` (bubbles, action row) |
| Agent progress + approvals | new `work-status.tsx`, `step-history.tsx`, new `side-panel.tsx`, `conversation-cards.tsx`; `components/assistant-ui/tool/approval.tsx` (Aura copy only: "Deny") |
| Tests | `*.test.tsx` beside each piece; `scripts/reveta/aura_browser.mjs` (stale goal-card steps fixed), new `scripts/reveta/aura_screens.{py,mjs}` |

### Backend

**None.** Every pattern above uses data already sent to the webapp. If Melvin wants
Projects or full-text search, those are backend features to scope separately.

## 6. What stays

Auth and sign-in, CSRF/Origin/security checks, the free-only gate, manual single-use
approvals, YOLO off, the voice implementation and its fallbacks, the goal proposal
logic (`goals.ts`), the delete path, data contracts, all `data-aura-*` hooks used by
tests, the Electron desktop UI.

## 7. Acceptance checks per piece

| Piece | Check (how it is verified) |
|---|---|
| Tokens / theme | Light and dark screenshots; text contrast values in §4; reduced motion sets transitions to 0 (browser test) |
| Shell (desktop) | Sidebar visible at 1440 px; collapse hides it and the toggle restores it; New chat, Search, history groups, Settings present (browser test + unit) |
| Shell (phone) | At 390 px a top bar with menu / title / new chat; menu opens a drawer with the same items; Escape closes and returns focus (browser test) |
| History groups | Unit: Today / Yesterday / Previous 7 days / Older boundaries |
| Search ⌘K | Unit: Ctrl/Cmd+K opens; filter narrows; Enter opens the first match |
| Home | Greeting, centred composer, 4 starters; tapping a starter fills the draft (unit + screenshot) |
| Composer | + menu still attaches files / URL (browser test); dictation button hidden without `SpeechRecognition`, inserts text with a fake (unit); send ↔ stop (browser test) |
| Voice | "Voice chat" starts the existing session (browser product test still passes) |
| Thread | User bubble right, answer left; Copy and Retry visible on the latest answer; numbered source chips (unit + screenshot) |
| Agent work | Step states map Queued→pending, Running→active, Done→done, Failed/Refused/Stopped shown; timer ticks while running; status strip opens Work (unit) |
| Approvals | Approve runs exactly once; Deny runs nothing (browser test with loopback counter) |
| Side panel / sheet | Desktop: panel beside the thread; phone: full sheet; Escape closes (unit + screenshot) |
| Settings | Sections Appearance, Model, Voice, Account; theme select works; sign out works (browser test) |
| No horizontal overflow | 320, 375, 390 px (browser test) |
| No upstream branding | Body text has no Hermes / Nous (browser test) |

## 8. Carry-over to reveta-web and X-hunt (not changed here)

Reusable as specification only: the token table (§4), the shell pattern
(sidebar / drawer / top bar), the composer pattern (+ menu, mic, send ↔ stop,
chips), the step row and approval card, and the side panel ↔ sheet rule.
Neither repository is modified by this work.

## 9. Gaps (not faked)

Projects; tools/modes in the + menu; full-text search; file preview in the panel;
sign-in screen copy ("Run hermes webapp") and styling (auth scope); real-model and
Android verification.

## 10. Decisions for Melvin

1. Accept the accent `#1f6fb5` / `#7cc4f0` and the neutral palette, or supply brand values.
2. Approval wording: "Approve / Deny" (this branch) versus the previous "Approve / Change".
3. Whether Projects and full-text search should become backend work.
4. Whether to restyle the shared sign-in overlay (touches the auth surface; deliberately not done).
5. Whether and when to merge (merging deploys to Render and, on the free plan, a redeploy clears saved Settings keys and chats).
