#!/usr/bin/env python3
"""Release-preview acceptance behind the real sign-in gate, with a fake model only.

Signs in as the basic-auth owner (as on Render), switches on Settings -> Preview (run evidence,
companion, browser handoff), chats, checks the evidence record on disk, runs /venus-value, drives the
chat-to-browser handoff with the companion's key (the extension's side over HTTP), and checks the
companion's planning call answers on the free route. Run:

    AURA_CHROMIUM=/opt/pw-browsers/chromium python scripts/reveta/aura_preview_browser.py
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, write_hermes_home

    replies = [Text("Stub output: launch plan ready.")] * 40
    with tempfile.TemporaryDirectory(prefix="aura-preview-") as directory, FakeLLMServer(replies) as fake:
        home = Path(directory) / "home"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        write_hermes_home(home, fake.base_url, extra_config=(
            f"webapp:\n  enabled: true\n  host: 0.0.0.0\n  port: {port}\n  public_url: http://127.0.0.1:{port}\n"
            "approvals:\n  mode: manual\n"))
        password = secrets.token_urlsafe(16)
        env = {k: v for k, v in os.environ.items()
               if not any(p in k.upper() for p in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "AURA_COMPANION"))}
        env.update(HERMES_HOME=str(home), HERMES_YOLO_MODE="0", HERMES_PYTHON=sys.executable,
                   HERMES_DASHBOARD_BASIC_AUTH_USERNAME="melvin", HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=password,
                   HERMES_DASHBOARD_BASIC_AUTH_SECRET=secrets.token_hex(32))
        try:
            launch = subprocess.run([sys.executable, "-m", "hermes_cli.main", "webapp", "--no-open", "--skip-build"],
                                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=120, check=False)
            if launch.returncode:
                print("Webapp launch failed:", launch.stderr[-800:], file=sys.stderr)
                return 1
            return subprocess.run(
                ["node", "scripts/reveta/aura_preview_browser.mjs"], cwd=ROOT, env=env, timeout=420, check=False,
                input=json.dumps({"url": f"http://127.0.0.1:{port}", "user": "melvin", "password": password,
                                  "home": str(home)}), text=True).returncode
        finally:
            subprocess.run([sys.executable, "-m", "hermes_cli.main", "gateway", "stop", "--yes"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=30, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
