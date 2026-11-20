"""Aura fails fast on a provider outage instead of retrying for minutes (fixture env only)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _aura_config():
    spec = importlib.util.spec_from_file_location("aura_config_retries", ROOT / "scripts" / "reveta" / "aura_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_config_bounds_retries_and_recovery_cycles():
    agent = _aura_config().aura_settings({})["agent"]
    # Hermes defaults (3 retries, 5 recovery cycles of 15-60 s) kept one message waiting 4-5 minutes.
    assert agent["api_max_retries"] == 2 and agent["auto_recovery_cycles"] == 1
