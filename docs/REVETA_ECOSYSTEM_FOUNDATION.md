# Reveta and Hermes ecosystem foundation — Preview only

Status: implemented as a candidate on an isolated feature branch, not validated live or approved for production.

Reveta OS is the authority for cross-product decisions and architecture; the Reveta Execution Tracker remains the live operational record; product repositories own code, customers and releases. Hermes remains the agent runtime, tools and conversational interface. Aura contributes the identity and evidence-led UX direction.

## Components

1. The existing Hermes dashboard gains an optional Reveta workspace at /reveta. Sessions, chat, tools, Skills and existing navigation remain unchanged.
2. The backend exposes authenticated GET /api/reveta/overview. It reads an explicitly configured, metadata-only repository allowlist, queries the fixed GitHub repository-commit API with bounded timeouts, and reports an observed revision or unknown. A commit observation is NOT evidence of a green CI run, live deployment, or policy approval.
3. The approved Aura mark is copied as a self-contained visual asset into the derivative. Native app/package IDs and update feeds have not been rebranded.
4. The standalone governance classifier marks action categories as read-only, founder-approval-required, or unclassified-hold. This is advisory: no Hermes tool-execution boundary has been intercepted.
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

## Release gates

- [x] Isolated feature branch; source no longer tied to Hermes main.
- [x] Original Hermes chat, streaming and native agent runtime untouched.
- [x] No private Reveta OS document bodies or secrets committed.
- [ ] Python and TypeScript checks pass on exact branch revision.
- [ ] Responsive keyboard and reduced-motion UX review.
- [ ] Authenticated endpoint denies anonymous requests and returns metadata for an authorised operator.
- [ ] Render Docker startup, protected login and authenticated PTY WebSocket pass.
- [ ] Actual model-backed Hermes turn verified with approved provider.
- [ ] Durable storage, backup/restore, monitoring and rollback confirmed.
- [ ] Separate explicit approval for production.

Known Preview blocker, 6 November 2026: the Render image built but the service exited with status 128 and no HTTP listener. The frontend's Vercel READY state does not prove backend success; backend validation remains a hold.

## Rollback

Revert the feature branch or deploy the previously verified Preview commit. No database schema changes or private data migrations were made. Do not enable auto-deploy or promote to production until each relevant release gate is supported by evidence.
