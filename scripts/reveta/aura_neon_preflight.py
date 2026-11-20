#!/usr/bin/env python3
"""Read-only, fail-closed Neon target preflight for Aura Zero.

Usage:
    AURA_NEON_DATABASE_URL='<credential set outside the repo>' \\
        python scripts/reveta/aura_neon_preflight.py

Never prints or logs a connection string, password, hostname, or account data.
This is a verification tool, NOT a SQLite-to-Postgres migration or an activation
switch. No application behavior changes when this script is present.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys


class PreflightError(RuntimeError):
    """A safe-to-display preflight failure; do not include the raw exception."""


def validate_target(*, database_url: str, expected_database: str) -> None:
    # Read the credential only from the process environment, never from CLI
    # arguments, a source file, or repo configuration.
    if not database_url:
        raise PreflightError("AURA_NEON_DATABASE_URL is not configured.")
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise PreflightError("A PostgreSQL connection URL is required.")
    if not expected_database:
        raise PreflightError("AURA_NEON_EXPECTED_DB must name the target database.")


async def inspect_target(database_url: str, expected_database: str) -> dict[str, object]:
    try:
        import asyncpg
    except ImportError as exc:
        raise PreflightError("asyncpg is unavailable in this runtime.") from exc

    connection = None
    try:
        # asyncpg is already pinned for Linux in the Hermes project.
        connection = await asyncpg.connect(database_url, timeout=10, command_timeout=10)
        async with connection.transaction(readonly=True):
            identity = await connection.fetchrow(
                "SELECT current_database() AS database_name, "
                "current_setting('server_version_num')::int AS version_num"
            )
            if not identity or identity["database_name"] != expected_database:
                raise PreflightError("Connected database does not match AURA_NEON_EXPECTED_DB.")
            tables = await connection.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
            names = [str(record["table_name"]) for record in tables]
            # Protect existing auth/preview deployments. Avoid printing table
            # names because names may reveal an unrelated project's structure.
            if any(name.startswith(("aura_auth_", "aura_preview_")) for name in names):
                raise PreflightError("Existing Aura preview/auth tables detected: target refused.")
            return {
                "status": "read_only_preflight_pass",
                "postgres_major": int(identity["version_num"]) // 10000,
                "public_table_count": len(names),
                "has_aura_budget_tables": all(
                    name in names for name in ("aura_budget", "aura_budget_ledger")
                ),
                "migration_applied": False,
                "production_ready": False,
            }
    except PreflightError:
        raise
    except Exception as exc:
        # Never include network or driver exception strings: they can contain
        # connection endpoints and credential-bearing DSNs.
        raise PreflightError("Unable to verify PostgreSQL target (connection or query failure).") from exc
    finally:
        if connection is not None:
            await connection.close()


def main() -> int:
    try:
        database_url = os.environ.get("AURA_NEON_DATABASE_URL", "")
        expected_database = os.environ.get("AURA_NEON_EXPECTED_DB", "")
        validate_target(database_url=database_url, expected_database=expected_database)
        result = asyncio.run(inspect_target(database_url, expected_database))
    except PreflightError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
