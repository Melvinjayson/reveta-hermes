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
    home: Path,
    base_url: str,
    target: Path,
    *,
    no_model: bool = False,
    cost_blocked: bool = False,
    product: bool = False,
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
    from tests.fakes.aura_price_policy import attest_tool

    # The test owns this exact loopback action and its zero-cost attestation.
    command = json.loads((home.parent / "command.json").read_text())
    attest_tool(home, "terminal", {"command": command})
    if product:
        from ruamel.yaml import YAML

        yaml = YAML()
        config = yaml.load((home / "config.yaml").read_text(encoding="utf-8"))
        config['aura']['enabled'] = True
        config['platform_toolsets'] = {'cli': ['aura', 'todo'], 'api_server': ['aura', 'todo']}
        config['tools'] = {'tool_search': {'enabled': 'off'}}
        config['browser'] = {'cloud_provider': 'local', 'engine': 'auto', 'executable_path': '/usr/bin/chromium',
                             'harness_home': str(home / 'cache' / 'browser-harness'),
                             'chromium_args': ['--no-sandbox', '--disable-dev-shm-usage']}
        # This managed test host uses an outbound proxy. Never persist proxy credentials.
        from urllib.parse import urlsplit
        proxy = urlsplit(os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy') or '')
        if proxy.hostname and proxy.port:
            config['browser']['chromium_args'].append(f'--proxy-server={proxy.scheme}://{proxy.hostname}:{proxy.port}')
        config['terminal'] = {'backend': 'local', 'cwd': str(home / 'aura-workspace')}
        with (home / "config.yaml").open("w", encoding="utf-8") as output:
            yaml.dump(config, output)
    if cost_blocked:
        from ruamel.yaml import YAML

        yaml = YAML()
        config = yaml.load((home / "config.yaml").read_text(encoding="utf-8"))
        config["aura"]["free_models"] = []
        with (home / "config.yaml").open("w", encoding="utf-8") as output:
            yaml.dump(config, output)
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
                {
                    "url": links[-1],
                    "target": str(target),
                    "noModel": no_model,
                    "costBlocked": cost_blocked,
                    "product": product,
                }
            ),
            text=True,
            timeout=360,
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
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product-only', action='store_true')
    args = parser.parse_args()
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
                self.wfile.write(b"Synthetic mock action received")

            def log_message(self, *_args):
                pass

        action_server = HTTPServer(("127.0.0.1", 0), MockAction)
        action_thread = Thread(target=action_server.serve_forever, daemon=True)
        action_thread.start()
        command = f"curl -sS --data synthetic-approval http://127.0.0.1:{action_server.server_port}/approval"
        (Path(directory) / "command.json").write_text(
            json.dumps(command), encoding="utf-8"
        )
        try:
            if args.product_only:
                return product_scenario(directory, target)
            return run_scenarios(directory, target, command)
        finally:
            action_server.shutdown()
            action_server.server_close()
            action_thread.join(timeout=2)


def run_scenarios(directory: str, target: Path, command: str) -> int:
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall

    result = product_scenario(directory, target)
    if result:
        return result

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
        before = len(fake.main_requests())
        result = browser_session(
            Path(directory) / "cost-blocked", fake.base_url, target, cost_blocked=True
        )
        if result:
            return result
        if len(fake.main_requests()) != before:
            raise RuntimeError("A cost-blocked model reached the fake provider")
        return browser_session(
            Path(directory) / "no-model", fake.base_url, target, no_model=True
        )


def product_scenario(directory: str, target: Path) -> int:
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall

    urls = ['https://raw.githubusercontent.com/python/cpython/main/Doc/library/http.rst',
            'https://raw.githubusercontent.com/nodejs/node/main/doc/api/http.md',
            'https://raw.githubusercontent.com/curl/curl/master/docs/libcurl/opts/CURLOPT_HTTPGET.md']
    brief = ('# HTTP client requests\n\nHTTP clients send methods, headers and optional bodies, '
             'then receive response status codes, headers and data. Python defines HTTPStatus '
             'and HTTPMethod enums. Node exposes streaming HTTP messages rather than buffering '
             'entire requests or responses. libcurl HTTPGET selects an HTTP GET request.\n\n'
             '## Sources\n' + '\n'.join(f'- [{url}]({url})' for url in urls))
    with FakeLLMServer([
        ToolCall('aura_fetch', {'url': urls[0]}, text='I will read three sources, compare the HTTP guidance, and write a one-page cited brief.'),
        ToolCall('aura_browser', {'url': urls[1], 'screenshot': True}),
        ToolCall('aura_browser', {'url': urls[2]}),
        ToolCall('aura_file', {'name': 'brief.md', 'action': 'write', 'content': brief}),
        Text('Brief ready. HTTP methods, status codes and representations define the exchange.\n\n' + '\n'.join(f'[Source {index}]({url})' for index, url in enumerate(urls, 1))),
        Text('Remember the HTTP methods and status codes from your brief.', chunk_chars=4, delay_per_chunk=0.15),
    ]) as fake:
        result = browser_session(Path(directory) / 'product', fake.base_url, target, product=True)
        if result:
            requests = fake.main_requests()
            # Names only: never dump requests, launch links or credentials.
            print(json.dumps({'exposed_tools': [tool['function']['name'] for tool in requests[0].get('tools', [])] if requests else [],
                              'generation_count': len(requests)}), file=sys.stderr)
            from agent.redact import redact_sensitive_text
            for row in requests[-1].get('messages', []) if requests else []:
                if row.get('role') == 'tool':
                    try:
                        data = json.loads(row.get('content', '{}'))
                    except (ValueError, TypeError):
                        continue
                    if data.get('error') or data.get('success') is False:
                        detail = data.get('error') or data.get('stderr') or data.get('output')
                        print(redact_sensitive_text(str(detail), force=True)[:1000], file=sys.stderr)
            return result
        requests = fake.main_requests()
        if len(requests) != 6:
            raise AssertionError(f'Product loop expected 6 fake generations, got {len(requests)}')
        history = requests[-1]['messages']
        tool_results = [message for message in history if message.get('role') == 'tool']
        if len(tool_results) < 4 or any('"success": false' in str(row.get('content')) for row in tool_results):
            raise AssertionError('Real source/file adapters did not succeed')
        if not any('Research HTTP client requests' in str(row.get('content')) for row in history):
            raise AssertionError('Voice follow-up lost the original text context')
        if not any('HTTPStatus' in str(row.get('content')) for row in tool_results):
            raise AssertionError('Real Python HTTP documentation did not reach the chat agent')
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
