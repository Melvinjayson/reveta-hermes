# Reveta and Hermes ecosystem foundation — Preview only

Status: implemented as a candidate on an isolated feature branch, not validated live or approved for production.

Reveta OS is the authority for cross-product decisions and architecture; the Reveta Execution Tracker remains the live operational record; product repositories own code, customers and releases. Hermes remains the agent runtime, tools and conversational interface. Aura contributes the identity and evidence-led UX direction.

## Components

1. The existing Hermes dashboard gains an optional Reveta workspace at /reveta. Sessions, chat, tools, Skills and existing navigation remain unchanged.
2. The backend exposes authenticated GET /api/reveta/overview. It reads an explicitly configured, metadata-only repository allowlist, queries the fixed GitHub repository-commit API with bounded timeouts, and reports an observed revision or unknown. A commit observation is NOT evidence of a green CI run, live deployment, or policy approval.
3. The approved Aura mark is copied as a self-contained visual asset into the derivative. Native app/package IDs and update feeds have not been rebranded.
4. The standalone governance classifier marks action categories as read-only, founder-approval-required, or unclassified-hold. This is advisory: no Hermes tool-execution boundary has been intercepted. The enforcement point is identified (see "Governance enforcement path" below) but not yet wired.
5. Aura Brain, hosted GBrain, continuous ingestion, learning and automatic writeback are NOT connected. Hermes native memory is separate. Retrieval must later enforce source scope, provenance, corrections and permission checks.
6. The operator registry is runtime-owned. It must never include secret values, customer text, personal records or private governance documents in the public repository.

## Registry configuration

Create a local JSON document at $HERMES_HOME/reveta/registry.json, or provision the non-secret Render environment field REVETA_REGISTRY_JSON with the same JSON document:

~~~json
{
  "schema_version": 1,
  "systems": [
    {
      "id": "hermes",
      "name": "Reveta Hermes Preview",
      "repository": "Melvinjayson/reveta-hermes",
      "portfolio_status": "unknown"
    }
  ]
}
~~~

Only allowlisted owner/repo identifiers are fetched, from api.github.com. The optional server-only REVETA_GITHUB_READ_TOKEN allows access to approved private repository commit metadata; never print or commit the token. A GitHub revision observation is not health. Portfolio labels come from an operator and remain unverified.

## Source ownership and controls

- Reveta OS: decisions, architecture, policy and programme gates.
- Execution Tracker: current pipeline, operating decisions and active experiment gates.
- Linear REV: delivery ownership and issue dependencies.
- Product repositories: source code, review and CI.
- Vercel/Render: deployment commit, environment and observed runtime.
- GBrain/Aura: source-scoped retrieval only after explicit approved integration.
- Founder: approves L4 actions including production, spending, external messages, publishing, migrations, access changes and deletion.

Default operations are L0 read-only. L1/L2 edits require bounded scope. L3 integrations require scoped credentials, audit, limits and approval. No model can bypass a Hold. A missing or stale source is unknown, never green.

## Render Preview runtime (decision 2026-11-06)

Root cause of both failed Render deploys (exit 128, no log output, 15-minute port-scan timeout): a Render "Docker Command" **replaces the image ENTRYPOINT**, not just CMD. The services were configured with `dashboard --host 0.0.0.0 ...`, so Render tried to exec a non-existent binary named `dashboard`; the Hermes entrypoint never ran.

Chosen approach: upstream Hermes' own dispatcher, no fork-specific boot script. The Render service must use exactly:

~~~
/opt/hermes/docker/entrypoint-dispatch.sh dashboard --host 0.0.0.0 --port 10000 --no-open --skip-build
~~~

- If the container process is PID 1 the dispatcher starts s6-overlay `/init` (full supervision, stage2 bootstrap).
- If a platform init wraps it, the dispatcher runs the same `stage2-hook.sh` bootstrap and execs the dashboard directly (upstream's documented wrapped-runtime path).
- The earlier `render-preview-boot.sh` was removed: it skipped stage2 (config-schema migration, bundled-skills sync, install-tree protection, gateway API key), silently dropping Hermes capabilities. The earlier dispatcher edit also broke the PID-1 test (`"$"` instead of `"$$"`), which disabled s6 for every Docker user of the fork; the file is now byte-identical to the preserved base and a behavioural test guards it.
- `REVETA_RENDER_PREVIEW_BOOT` is now inert and can be deleted from the service.

Required service environment (secrets set in Render only, never in Git):

| Variable | Purpose |
|---|---|
| `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` | Operator login |
| `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH` | `scrypt$...` from `python -c "from plugins.dashboard_auth.basic import hash_password; print(hash_password('...'))"` |
| `HERMES_DASHBOARD_BASIC_AUTH_SECRET` | 32+ random bytes; without it every restart signs everyone out |
| `HERMES_DASHBOARD_PUBLIC_URL` | `https://reveta-hermes-ecosystem-preview.onrender.com` — trusted Host/Origin and engages the WebSocket Origin hardening |

Hermes refuses to bind a public interface with no auth provider registered (fail closed); there is no insecure override.

### Known limits of the free Render plan

- **No persistent disk.** `/opt/data` (sessions, memories, config, skills, logs) is wiped on every redeploy, restart and idle spin-down. Treat Preview state as disposable.
- **512 MB RAM.** Live idle usage 2026-11-06: ~239 MB of 536,870,900 bytes (~45%). A live terminal session adds a Node TUI and an agent process; peak under load is unmeasured.
- **Idle spin-down** after ~15 minutes; first request afterwards cold-starts.

### Security hardening carried by this fork

Classification: `SECURITY.md` §2.6(5)/§3.2 — a non-loopback bind is an operator decision and public-exposure hardening is the operator's responsibility, so this is ordinary public hardening, suitable for an upstream PR. On an all-interfaces bind upstream accepts any Host *and any Origin* on WebSocket upgrades, relying on the single-use ticket alone. When `dashboard.public_url` is declared, the fork now also requires a web Origin to name the declared host (or be exactly the targeted authority). LAN and desktop behaviour without a declared URL is unchanged. Candidate for upstreaming.

### Verification

`scripts/reveta/preview_smoke.py` runs the Phase 1 checks (anonymous refusal, login/invalid login, cookie flags, ticket mint, PTY ticket/forged/foreign-Origin/replay, logout) against a local instance or the live URL. It never prints credentials.

## Governance enforcement path (proposal, not implemented)

Every model-initiated tool call passes `model_tools.handle_function_call` → `_pre_dispatch_guards` → `pre_tool_call` plugin hooks, which can veto with `{"action": "block", "message": ...}`. Verified 2026-11-06: a callback that raises **fails closed** (the call is blocked) and timed-out callbacks fail closed. A Reveta policy plugin on this hook is the proposed enforcement point. Open questions before implementation: (1) safe-worker mode skips all plugin hooks — confirm which tools safe workers can reach; (2) dashboard REST endpoints and the human-driven terminal do not pass through this hook by design; (3) where approval records live (Reveta OS is the authority; the hook needs a signed, expiring, environment-scoped record it can verify offline). Until wired and tested against the mandatory safety scenarios, governance remains **advisory**.

## Release gates

- [x] Isolated feature branch; source no longer tied to Hermes main.
- [x] Original Hermes chat, streaming and native agent runtime untouched.
- [x] No private Reveta OS document bodies or secrets committed.
- [x] Authenticated endpoint denies anonymous requests and returns metadata for an authorised operator (local, Render-proxy emulation, 2026-11-06).
- [x] Login, invalid-login, HttpOnly/Secure `__Host-` cookies, WS ticket single-use, foreign-Origin refusal (local emulation).
- [x] Session survives restart with a fixed signing secret; is invalidated without one (local).
- [x] Render service Docker Command corrected (founder, 21:35) and deploy reaches a listening port (dep-dbn4j2p5efls739eda80, commit b4b48f05, `HERMES_DASHBOARD_READY port=10000` at 21:43:11 UTC).
- [x] Live: s6 supervised runtime as PID 1, stage2 bootstrap and bundled-skills sync ran; no errors, tracebacks or OOM in startup logs.
- [x] Live: `/api/auth/providers` lists `basic` — the operator username/password-hash are configured and consumed (values never read).
- [x] Live: root serves the server-rendered sign-in page ("Public bind · Auth required"); anonymous `/api/sessions` and `/api/reveta/overview` refused with client errors.
- [ ] Live authenticated checks (sign-in, session cookie, `/reveta`, chat, WebSocket): require the operator's own browser session — the build agent holds no credential for this service.
- [ ] PTY terminal child starts in the Render container (not testable in the build sandbox: Node runtime download blocked).
- [ ] Python and TypeScript checks pass on exact branch revision in CI.
- [ ] Responsive keyboard and reduced-motion UX review.
- [ ] Actual model-backed Hermes turn verified with approved provider. Decision: Anthropic. `HERMES_INFERENCE_MODEL=claude-haiku-5-5` set on Render; awaiting operator-provided `ANTHROPIC_API_KEY`. Verified locally that with only that key present `provider: auto` resolves to Anthropic and failures are reported, never fabricated. Note: `HERMES_INFERENCE_PROVIDER` is ignored because the seeded config sets `provider: "auto"` and config outranks the env (`resolve_requested_provider`).
- [ ] Governance policy hook implemented and the mandatory safety scenarios tested.
- [ ] Durable storage, backup/restore, monitoring and rollback confirmed.
- [ ] Separate explicit approval for production.

## Rollback

Revert the feature branch or deploy the previously verified Preview commit. No database schema changes or private data migrations were made. Do not enable auto-deploy or promote to production until each relevant release gate is supported by evidence.
