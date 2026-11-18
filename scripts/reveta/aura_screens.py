#!/usr/bin/env python3
"""Screenshot tour of the real local Aura Webapp with FakeLLMServer only.

Usage: python scripts/reveta/aura_screens.py OUTPUT_DIR

Launches a disposable HERMES_HOME (manual approvals, YOLO off, no real keys),
then runs aura_screens.mjs at 390x844 and 1440x900. Screens: sign-in, home,
thread (fake streamed reply with citations), agent work (approval card) and
settings. The tour is selector-tolerant so it can run on the base branch and on
the redesign for BEFORE/AFTER comparison. It asserts nothing about function;
aura_browser.py remains the acceptance gate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

REPLY = (
    "Stub output: here is a calm plan for your synthetic launch.\n\n"
    "1. **Pick one audience** and write the promise in a sentence.\n"
    "2. **Draft the page** with a single call to action.\n"
    "3. **Ship to ten people** and note what they ask.\n\n"
    "[Synthetic source one](https://example.test/one) · [Synthetic source two](https://example.test/two)"
)


def main() -> int:
    from tests.fakes.aura_price_policy import attest_tool
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_hermes_home

    output = Path(sys.argv[1] if len(sys.argv) > 1 else ".build/aura-screens").resolve()
    output.mkdir(parents=True, exist_ok=True)
    command = "echo synthetic-approval-preview"
    with tempfile.TemporaryDirectory(prefix="aura-screens-") as directory, FakeLLMServer(
        [
            Text(REPLY, chunk_chars=12, delay_per_chunk=0.02),
            ToolCall("terminal", {"command": command}, text="I will run one harmless command in my workspace."),
            Text("Stub output: nothing was run."),
        ]
    ) as fake:
        home = Path(directory) / "home"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        write_hermes_home(
            home,
            fake.base_url,
            extra_config=f"webapp:\n  enabled: true\n  port: {port}\napprovals:\n  mode: manual\n",
        )
        attest_tool(home, "terminal", {"command": command})
        env = {
            key: value
            for key, value in os.environ.items()
            if not any(part in key.upper() for part in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
        }
        env.update(HERMES_HOME=str(home), HERMES_YOLO_MODE="0", HERMES_PYTHON=sys.executable)
        try:
            launch = subprocess.run(
                [sys.executable, "-m", "hermes_cli.main", "webapp", "--no-open", "--skip-build"],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=90, check=False,
            )
            links = re.findall(rf"http://127\.0\.0\.1:{port}/[^\s]+", launch.stdout)
            if launch.returncode or not links:
                print("Temporary Webapp launch failed; private launcher output withheld.", file=sys.stderr)
                return 1
            return subprocess.run(
                ["node", os.environ.get("AURA_SCREENS_SCRIPT", "scripts/reveta/aura_screens.mjs")], cwd=ROOT, env=env,
                input=json.dumps({"url": links[-1], "output": str(output)}),
                text=True, timeout=300, check=False,
            ).returncode
        finally:
            subprocess.run(
                [sys.executable, "-m", "hermes_cli.main", "gateway", "stop", "--yes"],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=30, check=False,
            )


if __name__ == "__main__":
    raise SystemExit(main())
