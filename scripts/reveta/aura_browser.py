#!/usr/bin/env python3
"""Real local Webapp acceptance with synthetic data and FakeLLMServer only."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
from threading import Thread

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def browser_session(
    home: Path, base_url: str, target: Path, *, no_model: bool = False
) -> int:
    from tests.fakes.fake_llm_provider import write_hermes_home

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    write_hermes_home(
        home,
        base_url,
        extra_config=f"webapp:\n  enabled: true\n  port: {port}\napprovals:\n  mode: manual\n",
    )
    if no_model:
        from ruamel.yaml import YAML
        from scripts.reveta.aura_config import aura_settings

        yaml = YAML()
        config = yaml.load((home / "config.yaml").read_text(encoding="utf-8"))
        config["model"] = aura_settings({})["model"]
        with (home / "config.yaml").open("w", encoding="utf-8") as output:
            yaml.dump(config, output)
        (home / ".env").write_text("", encoding="utf-8")
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(
            part in key.upper() for part in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
        )
    }
    env.update(
        HERMES_HOME=str(home), HERMES_YOLO_MODE="0", HERMES_PYTHON=sys.executable
    )
    try:
        launch = subprocess.run(
            [
                sys.executable,
                "-m",
                "hermes_cli.main",
                "webapp",
                "--no-open",
                "--skip-build",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if launch.returncode:
            print(
                "Temporary Webapp launch failed; private launcher output withheld.",
                file=sys.stderr,
            )
            return 1
        links = re.findall(rf"http://127\.0\.0\.1:{port}/[^\s]+", launch.stdout)
        if not links:
            print("No private launch link was returned.", file=sys.stderr)
            return 1
        return subprocess.run(
            ["node", "scripts/reveta/aura_browser.mjs"],
            cwd=ROOT,
            env=env,
            input=json.dumps(
                {"url": links[-1], "target": str(target), "noModel": no_model}
            ),
            text=True,
            timeout=240,
            check=False,
        ).returncode
    finally:
        stop = subprocess.run(
            [sys.executable, "-m", "hermes_cli.main", "gateway", "stop", "--yes"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if stop.returncode:
            raise RuntimeError(
                f"Temporary gateway cleanup failed: {stop.stdout[:500]} {stop.stderr[:500]}"
            )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="aura-browser-") as directory:
        target = Path(directory) / "synthetic-action-count.json"
        target.write_text("0", encoding="utf-8")
        hits = 0

        class MockAction(BaseHTTPRequestHandler):
            def do_POST(self):
                nonlocal hits
                body = self.rfile.read(
                    min(int(self.headers.get("Content-Length", "0")), 128)
                )
                if self.path != "/approval" or body != b"synthetic-approval":
                    self.send_error(400)
                    return
                hits += 1
                staging = target.with_suffix(".tmp")
                staging.write_text(str(hits), encoding="utf-8")
                staging.replace(target)
                self.send_response(200)
                self.end_headers()
                # The guarded pipe consumes only this fixed harmless fixture.
                self.wfile.write(b"printf 'Synthetic mock action received'")

            def log_message(self, *_args):
                pass

        action_server = HTTPServer(("127.0.0.1", 0), MockAction)
        action_thread = Thread(target=action_server.serve_forever, daemon=True)
        action_thread.start()
        command = f"curl -sS --data synthetic-approval http://127.0.0.1:{action_server.server_port}/approval | sh"
        try:
            return run_scenarios(directory, target, command)
        finally:
            action_server.shutdown()
            action_server.server_close()
            action_thread.join(timeout=2)


def run_scenarios(directory: str, target: Path, command: str) -> int:
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall

    with FakeLLMServer(
        [
            Text(
                "Stub output: A clear next step for your synthetic project.\n\n[Synthetic source](https://example.test/source)",
                chunk_chars=4,
                delay_per_chunk=0.2,
            ),
            ToolCall("terminal", {"command": command}),
            Text("Stub output: Synthetic action was not run."),
            ToolCall("terminal", {"command": command}),
            Text("Stub output: Approved synthetic action complete."),
        ]
    ) as fake:
        result = browser_session(Path(directory) / "connected", fake.base_url, target)
        if result:
            return result
        if len(fake.main_requests()) < 5:
            print(
                "Browser did not complete the scripted provider flow.", file=sys.stderr
            )
            return 1
        return browser_session(
            Path(directory) / "no-model", fake.base_url, target, no_model=True
        )


if __name__ == "__main__":
    raise SystemExit(main())
