"""The local verification gate must preserve failed-command evidence."""
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts.reveta import aura_check


def test_nonzero_command_is_reported_as_failed():
    result = aura_check.execute("synthetic failure", [sys.executable, "-c", "raise SystemExit(7)"], {})
    assert result["exit_code"] == 7
    assert result["status"] == "failed"


def test_wrong_tool_version_fails_even_when_command_succeeds():
    with patch.object(aura_check.subprocess, "run",
                      return_value=subprocess.CompletedProcess([], 0, "11.25.0\n")):
        result = aura_check.execute("pnpm version", ["pnpm", "--version"], {})
    assert result["status"] == "failed"
    assert "required: 12.15.0" in result["detail"]


def test_required_failure_returns_nonzero_json_and_strips_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-do-not-forward")
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    seen = []

    def run_check(name, command, env, timeout=1800):
        assert "OPENAI_API_KEY" not in env
        assert env["HERMES_YOLO_MODE"] == "0"
        seen.append(name)
        failed = name == "TypeScript typecheck"
        return {"name": name, "command": command, "exit_code": int(failed),
                "status": "failed" if failed else "passed"}

    output = io.StringIO()
    with patch.object(sys, "argv", ["aura_check.py"]), \
            patch.object(aura_check, "execute", side_effect=run_check), \
            patch.object(aura_check.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "synthetic\n")), \
            redirect_stdout(output):
        assert aura_check.main() == 1
    report = json.loads(output.getvalue())
    assert report["failed_checks"] == ["TypeScript typecheck"]
    assert "fake provider HTTP integration" in seen
    assert report["skipped_checks"]
    assert report["real_model_calls"] is False
