# Aura Zero — Neon persistence migration preflight

Status: **read-only preflight implementation; NOT a storage migration or a deployment**.
Date: 2026-11-20. Target environment: Render Free, Aura Zero.

## Verified current state

- The Render service tracks `aura/working-product-20261111` and currently runs
  `f8fda1d3b52cc9161748542ed7d6f6e757a32fe5`.
- PR #39 (`52448c3e`) is a draft unified candidate; it has **failed** JS/TS
  and platform-specific CI jobs, notwithstanding successful Docker and Nix jobs.
- Hermes sessions, full-text search, drafts and related state use SQLite through
  `hermes_state.py`, `SessionDB`, FTS5, and sidecar/WAL semantics.
- `tools/aura_budget.py` in PR #39 stores the configurable USD spending budget
  and transactional reservation ledger in `$HERMES_HOME/aura-budget.db`.
  Moving a budget setting without its ledger would allow the old spend history
  to disappear after a Render restart.
- The connected Reveta Neon account has `aura-backend` in Frankfurt,
  PostgreSQL 17, with an **archived** default branch and no application tables.
  The separate `aura-one-preview` project has existing authentication and
  preview data: DO NOT use or mutate it for this migration.
- Neither Neon project was modified during this inspection.

## Why DATABASE_URL alone is unsafe

SQLite SQL, write transactions (`BEGIN IMMEDIATE`), WAL, file locking and
FTS5 are not PostgreSQL wire protocols or equivalent SQL semantics. A
`DATABASE_URL` environment variable does not replace these file stores.
Missing application wiring should fail closed, not leave budget limits on the
ephemeral filesystem while UI implies durability.

## Immediate preflight (nonmutating)

The repository already pins `asyncpg` on Linux. No new dependency is proposed.
Use a Neon connection URL stored in a local secret environment variable, not in
a GitHub commit or a command-line argument:

```bash
export AURA_NEON_DATABASE_URL='(set securely, never commit)'
export AURA_NEON_EXPECTED_DB='(database reported by Neon)'
python scripts/reveta/aura_neon_preflight.py
```

The script uses a **read-only PostgreSQL transaction** to check target
identity and schema. It refuses unexpected existing Aura preview/auth tables.
It returns only a status, PostgreSQL major version and count/flags for tables;
it does not print hostnames, table names, credentials, or account records.
It does not create or migrate tables.

## Ordered migration work — not yet implemented

1. **Budget ledger first.** Create a Postgres budget schema in a separate
   migration review, with an atomic row-level lock for limit updates and
   reservations. Ensure `spent + in_flight + new_reservation <= limit`
   across concurrent workers and retries. Preserve the owner-only API.
2. **Data transfer.** Account for existing SQLite budget/settings history
   before cutover. Do not silently reset either spend totals or the paid-model
   switch. Fail closed if Postgres is unavailable. Keep paid inference disabled
   until real restart, concurrency and reconciliation tests pass.
3. **Conversations and projects.** Port the SessionDB contract explicitly,
   including FTS search, messages, compression lineage, projects, idempotent
   submission, voice played-text receipts and approvals. Verify round trips
   with copied, non-sensitive test fixtures before touching live data.
4. **Sign-in and secrets.** Confirm session-signing identity is stable across
   restarts and settings source is persisted. Do not copy plaintext secrets
   into Neon or weaken owner authentication.
5. **Runtime.** Configure Render secret connection **only after** persistence
   adapter tests, schema migration approval, and a rollback/backup procedure.
   Verify Render Free cold starts and memory behavior separately. PostgreSQL
   does not increase the service's 512 MiB memory allocation.
6. **Deployment.** Re-run the exact final integrated SHA's CI, Android layout,
   chat submit/reopen, budget reservation, voice startup, and restart tests.
   Production deploy only when release gates pass. Do not promote PR #39
   merely because an isolated preflight passes.

## Release gates and status

| Gate | Status | Reason |
| --- | --- | --- |
| Neon account and candidate target | PASS (metadata) | `aura-backend` exists |
| Read-only Neon connection | UNVERIFIED | Credentialed preflight not executed |
| Existing data preserved | PASS (no mutation) | No database writes performed |
| PostgreSQL budget authority | BLOCKED | SQLite implementation still active |
| Conversation persistence | BLOCKED | SQLite SessionDB implementation still active |
| Main unified CI | FAIL | JS/TS and OS-specific jobs failed |
| Production deployment | NOT STARTED | No safe persistence cutover |

**Do not enable paid models on Render Free until a durable budget authority
and the no-bypass tests are verified.**
