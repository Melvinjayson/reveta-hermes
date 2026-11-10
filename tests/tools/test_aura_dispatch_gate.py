"""Loopback-only adversarial dispatch tests. No provider or external service."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import shlex
import subprocess
import sys
from threading import Event, Thread

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tools import approval
from tools.approval_context import reset_current_session_key, set_current_session_key
from tools.registry import ToolRegistry


@pytest.fixture
def lab(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (home / "config.yaml").write_text(
        f"webapp:\n  enabled: true\naura:\n  workspace_root: {workspace}\napprovals:\n  mode: manual\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    key = f"aura-test-{tmp_path.name}"
    ht = set_hermes_home_override(str(home))
    st = set_current_session_key(key)
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # These approval-focused fixtures are known synthetic zero-cost actions.
    # Cost refusal is tested separately against an unmodified ToolRegistry.
    class FixtureRegistry(ToolRegistry):
        def dispatch(self, name, args, **kwargs):
            from tests.fakes.aura_price_policy import attest_tool
            from hermes_constants import get_hermes_home
            attest_tool(get_hermes_home(), name, args)
            return super().dispatch(name, args, **kwargs)
    registry = FixtureRegistry()

    def command(args):
        result = subprocess.run(
            args["command"],
            shell=True,
            executable="/bin/bash",
            capture_output=True,
            timeout=10,
            check=False,
        )
        return json.dumps({"exit_code": result.returncode})

    registry.register(
        name="terminal",
        toolset="terminal",
        schema={"name": "terminal"},
        handler=command,
    )
    try:
        yield (
            registry,
            key,
            hits,
            f"http://127.0.0.1:{server.server_port}",
            home,
            workspace,
        )
    finally:
        approval.unregister_gateway_notify(key)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        reset_current_session_key(st)
        reset_hermes_home_override(ht)


def forms(url, workspace):
    curl = f"curl -sS --data synthetic {url}/action"
    script = workspace / "action.sh"
    script.write_text(curl, encoding="utf-8")
    python = shlex.quote(sys.executable)
    py = f"import urllib.request; urllib.request.urlopen(urllib.request.Request('{url}/action',data=b'synthetic'))"
    js = f"fetch('{url}/action',{{method:'POST',body:'synthetic'}}).then(r=>r.text())"
    encoded = base64.b64encode(curl.encode()).decode()
    return {
        "curl-data": curl,
        "curl-method": f"curl -sS -X POST {url}/action",
        "wget": f"wget -qO- --post-data=synthetic {url}/action",
        "python": f"{python} -c {shlex.quote(py)}",
        "node": f"node -e {shlex.quote(js)}",
        "script": f"bash {shlex.quote(str(script))}",
        "pipe": f"printf %s {shlex.quote(curl)} | sh",
        "base64": f"printf %s {encoded} | base64 -d | sh",
        "env": f'ACTION={shlex.quote(curl)}; eval "$ACTION"',
        "alias": f"shopt -s expand_aliases; alias upload={shlex.quote(curl)}; eval upload",
        "subshell": f"({curl})",
        "chain": f"true && {curl}; true",
    }


def pending(lab, args, choice, *, mutate=None):
    registry, key, hits, *_ = lab
    ready = Event()
    request = {}

    def notify(data):
        request.update(data)
        ready.set()

    approval.register_gateway_notify(key, notify)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(copy_context().run, registry.dispatch, "terminal", args)
        try:
            assert ready.wait(3), "dispatch executed without asking"
            assert hits == []
            if mutate:
                mutate()
            assert (
                approval.resolve_gateway_approval(
                    key, choice, request_id=request["request_id"]
                )
                == 1
            )
            result = json.loads(future.result(timeout=5))
        finally:
            if request:
                approval.resolve_gateway_approval(
                    key, "deny", request_id=request["request_id"]
                )
    return request, result


@pytest.mark.parametrize(
    "form",
    [
        "curl-data",
        "curl-method",
        "wget",
        "python",
        "node",
        "script",
        "pipe",
        "base64",
        "env",
        "alias",
        "subshell",
        "chain",
    ],
)
def test_command_indirections_wait_and_change_has_no_effect(lab, form):
    _, key, hits, url, _, workspace = lab
    args = {"command": forms(url, workspace)[form]}
    pending(lab, args, "deny")
    assert hits == []
    request, result = pending(lab, args, "once")
    assert result["exit_code"] == 0
    assert hits == ["/action"]  # fixtures are executable, not vacuously blocked
    assert (
        approval.resolve_gateway_approval(key, "once", request_id=request["request_id"])
        == 0
    )
    assert hits == ["/action"]


def test_changed_arguments_invalidate_approval(lab):
    _, _, hits, url, _, workspace = lab
    args = {"command": forms(url, workspace)["curl-data"]}
    _, result = pending(
        lab, args, "once", mutate=lambda: args.update(command=args["command"] + " ")
    )
    assert result["status"] == "refused"
    assert hits == []
    pending(lab, args, "deny")  # changed action asks again
    assert hits == []


def test_unknown_browser_and_app_writes_require_approval(lab):
    registry, key, hits, *_ = lab
    for name in (
        "browser_exec",
        "connectors__fixture__send",
        "skill_manage",
        "cronjob",
        "manage_connections",
        "delete_file",
        "future_tool",
    ):
        registry.register(
            name=name,
            toolset="fixture",
            schema={"name": name},
            handler=lambda args: hits.append("executed") or '{"success":true}',
        )

        def deny(data):
            assert hits == []
            approval.resolve_gateway_approval(
                key, "deny", request_id=data["request_id"]
            )

        approval.register_gateway_notify(key, deny)
        assert (
            json.loads(registry.dispatch(name, {"action": "submit"}))["status"]
            == "refused"
        )
        assert hits == []


def test_reads_and_internal_state_run_but_file_mutations_wait(lab):
    registry, _, _, _, _, workspace = lab
    path = workspace / "note.md"
    registry.register(
        name="read_file",
        toolset="file",
        schema={"name": "read_file"},
        handler=lambda args: json.dumps({"text": Path(args["path"]).read_text()}),
    )
    registry.register(
        name="write_file",
        toolset="file",
        schema={"name": "write_file"},
        handler=lambda args: (
            Path(args["path"]).write_text(args["content"]) and '{"success":true}'
        ),
    )
    assert (
        json.loads(
            registry.dispatch("write_file", {"path": str(path), "content": "synthetic"})
        )["status"]
        == "refused"
    )
    assert not path.exists()
    path.write_text("synthetic", encoding="utf-8")
    state = []
    registry.register(
        name="todo",
        toolset="todo",
        schema={"name": "todo"},
        handler=lambda args: state.append(args["text"]) or '{"success":true}',
    )
    assert json.loads(registry.dispatch("todo", {"text": "synthetic draft"}))["success"]
    assert state == ["synthetic draft"]
    assert (
        json.loads(registry.dispatch("read_file", {"path": str(path)}))["text"]
        == "synthetic"
    )


def test_expired_bulk_and_scope_approvals_cannot_execute(lab):
    registry, key, hits, url, _, workspace = lab
    ready = Event()
    data = {}
    approval.register_gateway_notify(
        key, lambda request: (data.update(request), ready.set())
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            copy_context().run,
            registry.dispatch,
            "terminal",
            {"command": forms(url, workspace)["curl-data"]},
        )
        assert ready.wait(3)
        rid = data["request_id"]
        assert approval.resolve_gateway_approval(key, "once", resolve_all=True) == 0
        assert approval.resolve_gateway_approval(key, "once") == 0
        assert approval.resolve_gateway_approval(key, "always", request_id=rid) == 0
        assert approval.resolve_gateway_approval(key, "session", request_id=rid) == 0
        with approval._lock:
            approval._gateway_queues[key][0].data["expires_at_monotonic"] = 0
        assert approval.resolve_gateway_approval(key, "once", request_id=rid) == 0
        approval.withdraw_gateway_approval(key, rid, "expired test fixture")
        assert json.loads(future.result(timeout=5))["status"] == "refused"
    assert hits == []


@pytest.mark.parametrize(
    "context",
    [{"cron_session": "1"}, {"platform": "webhook"}, {"platform": "api_server"}],
)
def test_cron_denies_even_with_auto_approve_configuration(lab, context):
    from gateway.session_context import clear_session_vars, set_session_vars

    registry, _, hits, url, home, workspace = lab
    config = home / "config.yaml"
    config.write_text(
        config.read_text() + "  cron_mode: approve\n  unattended_mode: approve\n",
        encoding="utf-8",
    )
    tokens = set_session_vars(**context)
    try:
        result = json.loads(
            registry.dispatch(
                "terminal", {"command": forms(url, workspace)["curl-data"]}
            )
        )
    finally:
        clear_session_vars(tokens)
    assert result["status"] == "refused"
    assert hits == []


def test_helper_cannot_self_approve(lab, monkeypatch):
    from agent.delegation_context import delegated_child_context
    from tools import terminal_tool

    monkeypatch.setattr(
        terminal_tool, "_get_approval_callback", lambda: lambda *a, **k: "once"
    )
    _, _, hits, url, _, workspace = lab
    with delegated_child_context():
        pending(lab, {"command": forms(url, workspace)["curl-data"]}, "deny")
    assert hits == []


def test_policy_errors_and_missing_policy_refuse(lab, monkeypatch):
    from tools import aura_dispatch_policy as policy

    registry, _, hits, url, home, workspace = lab
    args = {"command": forms(url, workspace)["curl-data"]}
    with monkeypatch.context() as patch:
        patch.setattr(
            policy,
            "_classification",
            lambda *args: (_ for _ in ()).throw(ValueError("fixture")),
        )
        assert json.loads(registry.dispatch("terminal", args))["status"] == "refused"
    (home / "config.yaml").unlink()
    assert json.loads(registry.dispatch("terminal", args))["status"] == "refused"
    assert hits == []


def test_symlink_and_outside_workspace_write_cannot_use_internal_classification(lab):
    registry, _, hits, _, home, workspace = lab
    outside = home / "outside.md"
    (workspace / "link.md").symlink_to(outside)
    registry.register(
        name="write_file",
        toolset="file",
        schema={"name": "write_file"},
        handler=lambda args: hits.append("write") or '{"success":true}',
    )
    for path in (outside, workspace / "link.md", Path("relative.md")):
        assert (
            json.loads(
                registry.dispatch("write_file", {"path": str(path), "content": "x"})
            )["status"]
            == "refused"
        )
    assert hits == []


def test_connected_app_real_dispatch_entry_does_not_reach_transport(lab, monkeypatch):
    from tools.connectors.dispatch import dispatch_connector_call
    from tools.connectors.gateway import bridge

    _, _, hits, _, home, _ = lab
    from tests.fakes.aura_price_policy import attest_tool
    attest_tool(home, "connectors__fixture__send", {"body": "synthetic"})
    monkeypatch.setattr(bridge, "run_remote", lambda *a, **k: hits.append("transport"))
    assert (
        json.loads(
            dispatch_connector_call(
                "connectors__fixture__send", {"body": "synthetic"}, "call"
            )
        )["status"]
        == "refused"
    )
    assert hits == []


def test_inline_setting_change_does_not_reach_callback(lab):
    from types import SimpleNamespace
    from agent.inline_tool_executors import INLINE_TOOL_EXECUTORS, InlineToolContext

    _, _, hits, _, home, _ = lab
    from tests.fakes.aura_price_policy import attest_tool
    attest_tool(home, "set_theme", {"mode": "dark"})
    agent = SimpleNamespace(theme_callback=lambda **kw: hits.append("theme"))
    result = INLINE_TOOL_EXECUTORS["set_theme"](
        agent, {"mode": "dark"}, InlineToolContext("task")
    )
    assert json.loads(result)["status"] == "refused"
    assert hits == []


def test_model_dispatch_cannot_skip_gate_with_hook_flags(lab, monkeypatch):
    import model_tools

    registry, _, hits, url, _, workspace = lab
    monkeypatch.setattr(model_tools, "registry", registry)
    result = model_tools.handle_function_call(
        "terminal",
        {"command": forms(url, workspace)["curl-data"]},
        skip_pre_tool_call_hook=True,
        skip_tool_request_middleware=True,
        skip_tool_execution_middleware=True,
    )
    assert json.loads(result)["status"] == "refused"
    assert hits == []


def test_off_mode_and_missing_config_do_not_disable_gate(lab):
    registry, _, hits, url, home, workspace = lab
    config = home / "config.yaml"
    config.write_text("approvals:\n  mode: off\n", encoding="utf-8")
    args = {"command": forms(url, workspace)["curl-data"]}
    assert json.loads(registry.dispatch("terminal", args))["status"] == "refused"
    config.unlink()
    assert json.loads(registry.dispatch("terminal", args))["status"] == "refused"
    assert hits == []


def test_approval_preview_masks_secret_arguments(lab):
    _, _, hits, url, _, workspace = lab
    args = {
        "command": forms(url, workspace)["curl-data"],
        "password": "synthetic-password-value",
    }
    request, _ = pending(lab, args, "deny")
    assert "synthetic-password-value" not in request["command"]
    assert hits == []


def test_parallel_identical_calls_do_not_share_one_approval(lab):
    from concurrent.futures import FIRST_COMPLETED, wait

    registry, key, hits, url, _, workspace = lab
    requests = []
    ready = Event()

    def notify(data):
        requests.append(data)
        if len(requests) == 2:
            ready.set()

    approval.register_gateway_notify(key, notify)
    args = {"command": forms(url, workspace)["curl-data"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(copy_context().run, registry.dispatch, "terminal", args)
            for _ in range(2)
        ]
        try:
            assert ready.wait(3)
            assert hits == []
            first, second = [request["request_id"] for request in requests]
            assert first != second
            assert approval.resolve_gateway_approval(key, "once", request_id=first) == 1
            done, pending_calls = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
            assert len(done) == len(pending_calls) == 1
            assert hits == ["/action"]
            assert approval.resolve_gateway_approval(key, "once", request_id=first) == 0
            assert (
                approval.resolve_gateway_approval(key, "deny", request_id=second) == 1
            )
            assert (
                json.loads(next(iter(pending_calls)).result(timeout=5))["status"]
                == "refused"
            )
            assert hits == ["/action"]
        finally:
            for request in requests:
                approval.withdraw_gateway_approval(
                    key, request["request_id"], "test cleanup"
                )


def test_multi_file_patch_cannot_launder_outside_changes_through_safe_path(lab):
    registry, _, hits, _, home, workspace = lab
    registry.register(
        name="patch",
        toolset="file",
        schema={"name": "patch"},
        handler=lambda args: hits.append("write") or '{"success":true}',
    )
    result = registry.dispatch(
        "patch",
        {
            "path": str(workspace / "safe.md"),
            "mode": "patch",
            "patch": f"*** Begin Patch\n*** Add File: {home}/outside.md\n+synthetic\n*** End Patch",
        },
    )
    assert hits == []
    assert json.loads(result)["status"] == "refused"
