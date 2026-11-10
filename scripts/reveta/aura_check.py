#!/usr/bin/env python3
"""Local Surface A verification. JSON on stdout, command output on stderr.

Activate the frozen project environment and install frozen pnpm dependencies first.
This foundation checks the browser bundle and existing contracts; it does not
claim G1 browser acceptance or runtime conversation persistence.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
SURFACE = "A: Aura chat on Hermes Webapp (Simple mode)"


def fake_provider_check() -> None:
    """Exercise the existing fake over HTTP/SSE, including a scripted fault."""
    sys.path.insert(0, str(ROOT))
    from openai import APIStatusError, OpenAI
    from tests.fakes.fake_llm_provider import Error, FakeLLMServer, Text

    with FakeLLMServer([Text("Stub output: Aura checkpoint"), Error(500)]) as fake:
        with OpenAI(base_url=fake.base_url, api_key="synthetic-test-key", max_retries=0) as client:
            args = dict(model="fake-model", messages=[{"role": "user", "content": "Synthetic probe"}],
                        tools=[{"type": "function", "function": {"name": "unused", "parameters": {"type": "object"}}}])
            with client.chat.completions.create(**args, stream=True) as stream:
                reply = "".join(chunk.choices[0].delta.content or "" for chunk in stream if chunk.choices)
            if reply != "Stub output: Aura checkpoint":
                raise AssertionError("Fake streaming response differed")
            try:
                client.chat.completions.create(**args)
            except APIStatusError as exc:
                if exc.status_code != 500:
                    raise
            else:
                raise AssertionError("Scripted provider error was not delivered")
            if len(fake.main_requests()) != 2:
                raise AssertionError("Unexpected fake provider request count")
    print("Fake HTTP streaming and provider fault passed; no runtime chat claim.")


def execute(name: str, command: list[str], env: dict[str, str], timeout: int = 1800) -> dict:
    started = time.monotonic()
    print(f"[{name}] {command}", file=sys.stderr, flush=True)
    detail = ""
    try:
        version = name.endswith(" version")
        result = subprocess.run(command, cwd=ROOT, env=env,
                                stdout=subprocess.PIPE if version else sys.stderr,
                                stderr=sys.stderr, text=True, timeout=timeout, check=False)
        code = result.returncode
        if version:
            detail = result.stdout.strip()
            print(detail, file=sys.stderr)
            expected = {"node version": "v26.12.1", "pnpm version": "12.15.0",
                        "ruff version": "ruff 0.15.22"}.get(name)
            if expected and detail != expected:
                code = 1
                detail += f" (required: {expected})"
    except (OSError, subprocess.TimeoutExpired) as exc:
        code, detail = 1, str(exc)
    return {"name": name, "command": command, "exit_code": code,
            "status": "passed" if code == 0 else "failed", "detail": detail,
            "duration_seconds": round(time.monotonic() - started, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--fake-provider-check", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.live:
        print("Live verification is unavailable in this checkpoint. It requires separate explicit "
              "authorization and provider/cost review before implementation and execution.", file=sys.stderr)
        return 2
    if args.fake_provider_check:
        fake_provider_check()
        return 0

    started = time.monotonic()
    # Do not inherit model credentials or behavior switches from an operator's shell.
    keep = {"PATH", "HOME", "USER", "TMPDIR", "SYSTEMROOT", "VIRTUAL_ENV",
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "AURA_CHROMIUM", "AURA_SCREENSHOT_DIR"}
    env = {key: value for key, value in os.environ.items() if key in keep}
    env.update(TZ="UTC", LANG="C.UTF-8", PYTHONHASHSEED="0", HERMES_YOLO_MODE="0",
               HERMES_PYTHON=sys.executable, NODE_OPTIONS="--max-old-space-size=4096")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True, check=True).stdout.strip()
    pnpm = ["pnpm", "--dir", "apps/desktop"]
    checks = []
    with tempfile.TemporaryDirectory(prefix="aura-check-") as home:
        env["HERMES_HOME"] = home
        checks.extend(execute(name, command, env, 30) for name, command in [
            ("node version", ["node", "--version"]), ("pnpm version", ["pnpm", "--version"]),
            ("python version", [sys.executable, "--version"]),
            ("ruff version", [sys.executable, "-m", "ruff", "--version"]),
        ])
        for name, command in [
            ("Webapp build", pnpm + ["run", "build:webapp"]),
            ("TypeScript typecheck", pnpm + ["run", "typecheck"]),
            ("desktop ESLint", pnpm + ["run", "lint"]),
            ("Webapp unit contracts", pnpm + ["exec", "vitest", "run", "--project", "ui",
                "src/store/interface-mode.test.ts", "src/lib/browser-desktop-bridge.test.ts",
                "src/app/session/hooks/use-session-actions/restore-pending-clarify.test.ts",
                "src/app/aura", "src/store/browser-tab-title.test.ts",
                "src/components/assistant-ui/tool/approval.test.tsx"]),
            ("Reveta isolated Python tests", ["bash", "scripts/run_tests.sh",
                "tests/test_reveta_foundation.py", "tests/test_reveta_container_entrypoint.py",
                "tests/skills/test_reveta_ecosystem_skill.py", "tests/scripts/test_aura_check.py",
                "tests/scripts/test_aura_config.py",
                "--noconftest", "-q"]),
            ("dashboard public Origin contracts", ["bash", "scripts/run_tests.sh",
                "tests/hermes_cli/test_web_server_host_header.py", "--noconftest", "-q", "-k",
                "declared_public_url or without_public_url"]),
            ("fake provider HTTP integration", [sys.executable, __file__, "--fake-provider-check"]),
            ("browser Simple-mode acceptance", [sys.executable, "scripts/reveta/aura_browser.py"]),
            ("browser ESLint", ["pnpm", "exec", "eslint", "-c", "apps/desktop/eslint.config.mjs", "scripts/reveta/aura_browser.mjs"]),
            ("runner Ruff", [sys.executable, "-m", "ruff", "check", __file__, "scripts/reveta/aura_browser.py", "scripts/reveta/aura_config.py"]),
        ]:
            checks.append(execute(name, command, env))
    skipped = [
        {"name": name, "reason": "G1 acceptance suite not implemented in this foundation checkpoint"}
        for name in ["complete mobile light/dark accessibility",
                     "browser reopening", "logout/login history", "local restart persistence",
                     "provider retry without duplicates", "interrupt streaming",
                     "anonymous session boundary", "dashboard browser smoke"]
    ]
    skipped.extend([
        {"name": "full desktop unit and Electron E2E suites", "reason": "This gate selects relevant Webapp unit contracts"},
        {"name": "live provider verification", "reason": "Unavailable; separate explicit authorization required"},
    ])
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout
    summary = {"commit_sha": commit, "working_tree_dirty": bool(dirty), "surface": SURFACE,
               "environment": {"platform": platform.platform(), "python": sys.version,
                               "python_executable": sys.executable, "node_heap_mb": 4096,
                               "tools": {c["name"]: c.get("detail", "") for c in checks
                                         if c["name"].endswith(" version")}},
               "commands_executed": checks,
               "passed_checks": [c["name"] for c in checks if c["status"] == "passed"],
               "failed_checks": [c["name"] for c in checks if c["status"] == "failed"],
               "skipped_checks": skipped, "real_model_calls": False,
               "model_call_statement": "No real-model calls occurred; provider checks use FakeLLMServer only.",
               "duration_seconds": round(time.monotonic() - started, 3)}
    print(json.dumps(summary, indent=2))
    return int(bool(summary["failed_checks"]))


if __name__ == "__main__":
    raise SystemExit(main())
