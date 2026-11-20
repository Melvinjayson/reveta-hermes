# Aura Zero — Precision Workspace Design System (provisional)

Date: 20 November 2026  
Status: Candidate on an isolated review branch. Not deployed or accepted.

## Sources and boundaries

- User-provided `DESIGN.md` (Linear — midnight precision instrument), corresponding to https://styles.refero.design/style/90ce5883-bb24-4466-93f7-801cd617b0d1.
- Uizze reference: https://uizze.com/packs/4b66f12c-c30d-4448-a568-93713e347ed9 — the exact pack was not retrievable during this change; no unverified pack components were copied.
- The existing `apps/desktop/DESIGN.md` remains the **shared Hermes Desktop** contract; this document scopes overrides to **Aura Zero**. It does not replace or silently rewrite global Hermes primitives.
- Existing Aura implementation: `apps/desktop/src/app/aura/tokens.css`, `shell.css`, `aura.css` and the existing component registry.

This is a translation of *principles*, not a copy of Linear branding or a claim about its underlying implementation. Keep Aura's own icon, name, language and workflows.

## Product hierarchy

1. Project: durable goal and scope.
2. Conversation: primary way to guide the work.
3. Contextual pane: actual selected work/source/approval/output, never a duplicated transcript.
4. Composer: stable with explicit send/stop, optional browser/voice attachments and retained drafts.
5. Task, evidence and output: inspectable records with state/provenance, not decorative dashboard metrics.

Only surface an Overview, Research, Work or Outputs destination when the implementation can open real records. Empty tabs are not a design deliverable.

## Colour semantics

| Aura token | Light mode | Dark mode | Role |
| --- | --- | --- | --- |
| `--aura-page` | `#ffffff` | `#08090a` | Primary canvas |
| `--aura-sidebar` | `#f7f7f8` | `#0f1011` | Navigation surface |
| `--aura-surface` | `#ffffff` | `#161718` | Composer and panels |
| `--aura-subtle` | `#f2f2f4` | `#23252a` | Hover/selected backgrounds |
| `--aura-line` | `#e4e4e8` | `#383b3f` | Perceptible borders |
| `--aura-ink` | `#18181b` | `#ffffff` | Primary text |
| `--aura-muted` | `#5f5f68` | `#a9adb5` | Secondary text |
| `--aura-accent` | `#1f6fb5` | `#e4f222` | Primary action, focus and selected marker |
| `--aura-on-accent` | `#ffffff` | `#08090a` | Action text |

The dark-mode accent adopts the supplied reference; light mode retains Aura's established blue until a separate brand decision is approved. Never use lime for ordinary body copy, status claims, or decorative gradients. A single accent is an interface priority rule, **not** a reason to remove error/success/warning semantics.

## Typography and geometry

- Inter with system fallback; 16 px body as the baseline, compact 12–14 px metadata only when contrast and readability allow.
- `font-feature-settings: 'cv01' on, 'ss03' on, 'zero' on`. Avoid importing proprietary fonts.
- Prefer 400–600 weights, restrained heading tracking (approximately `-0.012em`), and legible line-height for long messages.
- Spacing scale uses 4 / 8 / 12 / 16 / 24 / 32 / 48 px. Dense navigation, spacious reading.
- Buttons/inputs 6 px radius, cards 12 px, pills fully rounded. Avoid nested-card overuse.
- Hairline borders and a subtle shadow only for floating overlays. No ornamental gradient layers.
- All primary touch targets >= 44 x 44 CSS px; distinguish visual glyph size from hit area.

## Stateful components: required variants

| Surface | States and contract |
| --- | --- |
| Composer | idle, sending, streaming, stopping, failed, recovering; never double send; retain unsent drafts |
| Conversation | loading, saved, interrupted, retrieving, failed; status tied to real backend state |
| Project | not loaded, available, unavailable, pending association; failed association must not open an unscoped chat |
| Task | queued, running, awaiting input, awaiting approval, blocked, completed, failed, cancelled |
| Browser | disconnected, awaiting extension, working, awaiting approval, denied, failed, completed; no action replay |
| Voice | connecting, listening, thinking, speaking, interrupted, reconnecting, stopping, disconnected; resource cleanup on end |
| Outputs | draft, saved version, accepted, conflict; never silently overwrite newer work |

Do not render fabricated percentages or imply a capability works because its switch is visible.

## Mobile and accessibility contract

- 360, 390, 768, 1440 CSS px, record actual viewport heights and device/browser.
- One primary surface at phone widths. Contextual panels become dedicated sheets with a clear return.
- Keep the composer above the Android keyboard and safe area. Do not steal reading position during streaming.
- WCAG 2.2 AA target; visible keyboard focus, accessible labels, polite status updates (not every token), adequate contrast.
- Disclose human/device checks separately from automated scans; do not claim phone or voice acceptance from component tests.

## P0 → P1 release gates

P0: durable `HERMES_HOME` or an approved equivalent, stable session secret, verified sign-in recovery, persisted conversations and settings, traceable first token and completion latency, no unexplained spinner.

P1: project-linked real records; draft-safe chat transitions; verified browser approval boundary and cancellation; full-duplex voice maintained as a target, with a host capable of running the speech graph; keyboard-open and cross-project isolation tests.

No infrastructure, database/schema, paid-provider, auth weakening, production merge or production deploy is authorised by this design-system change. Host-specific fixes require independent approval.

## Implementation & validation evidence

- **Implemented on this branch:** semantic dark palette in Aura tokens, typography feature settings, compact control radius, reduced overlay shadows, selection indicator, >=44px conversation and settings control targets.
- **Not implemented by these CSS changes:** persistence, authentication, browser runtime integration, Pipecat repairs, new project data models.
- **Verification needed:** desktop typecheck/build, changed-file lint, screen captures at the four widths in both themes, real Android keyboard-open flow, focus contrast audit, real hosted journey, visual-regression review.
- Rollback: revert the design-system commits. The changes touch only Aura CSS and this design note; no data migration.
