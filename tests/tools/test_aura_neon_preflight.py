"""Neon preflight contract: no connection attempted and no credentials printed."""
import asyncio

import pytest

from scripts.reveta.aura_neon_preflight import PreflightError, inspect_target, validate_target


def test_requires_explicit_database_url_and_database_name():
    with pytest.raises(PreflightError, match="not configured"):
        validate_target(database_url="", expected_database="neondb")
    with pytest.raises(PreflightError, match="PostgreSQL"):
        validate_target(database_url="sqlite:///tmp/aura.db", expected_database="neondb")
    with pytest.raises(PreflightError, match="AURA_NEON_EXPECTED_DB"):
        validate_target(database_url="postgresql://redacted", expected_database="")


def test_connection_failure_does_not_echo_dsn(monkeypatch):
    """The preflight must not leak a host or credential in errors."""
    import sys
    from types import SimpleNamespace

    secret = "PASSWORD-MUST-NEVER-APPEAR"

    async def fails(*_args, **_kwargs):
        raise RuntimeError(f"connect failed with {secret}")

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(connect=fails))
    with pytest.raises(PreflightError) as result:
        asyncio.run(inspect_target(f"postgresql://user:{secret}@invalid.example/db", "db"))
    assert secret not in str(result.value)


def test_default_environment_refuses_without_contacting_database(monkeypatch, capsys):
    from scripts.reveta.aura_neon_preflight import main

    monkeypatch.delenv("AURA_NEON_DATABASE_URL", raising=False)
    monkeypatch.delenv("AURA_NEON_EXPECTED_DB", raising=False)
    assert main() == 2
    assert "blocked" in capsys.readouterr().out
