"""Full-duplex voice on a shared host: owner only, refused when memory is short, nothing loaded at boot."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from hermes_cli.web_routers import pipecat_voice

MIB = 1024 * 1024


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "melvin")
    monkeypatch.delenv("AURA_COMPANION_ADMINS", raising=False)
    (tmp_path / "config.yaml").write_text("aura:\n  voice:\n    full_duplex: true\n", encoding="utf-8")
    monkeypatch.setattr(pipecat_voice, "runtime_python", lambda: "synthetic-python")
    monkeypatch.setattr(pipecat_voice, "speech_ffmpeg", lambda: "synthetic-ffmpeg")
    monkeypatch.setattr(pipecat_voice, "_CGROUP_FILES", ())
    return tmp_path


def _app(monkeypatch, user_id, gated=True):
    def ws_auth(ws, **_kw):
        ws._hermes_auth_identity = {"user_id": user_id, "provider": "basic"}
        return True

    monkeypatch.setattr(pipecat_voice, "_require_token", lambda request: None)
    monkeypatch.setattr(pipecat_voice, "_ws_auth_ok", ws_auth)
    monkeypatch.setattr(pipecat_voice, "_ws_request_is_allowed", lambda ws: True)
    app = FastAPI()
    app.state.auth_required = gated

    @app.middleware("http")
    async def session(request: Request, call_next):
        request.state.session = SimpleNamespace(user_id=user_id, email="")
        return await call_next(request)

    app.include_router(pipecat_voice.router)
    return TestClient(app)


def _no_speech_process(monkeypatch):
    async def refuse(*_a, **_kw):
        raise AssertionError("no speech process may start")

    monkeypatch.setattr(pipecat_voice.asyncio, "create_subprocess_exec", refuse)


def test_only_the_owner_can_switch_full_duplex_or_see_it(monkeypatch):
    tester = _app(monkeypatch, "tester")
    assert tester.put("/api/aura/voice/mode", json={"full_duplex": False}).status_code == 403
    assert tester.get("/api/aura/voice/mode").json() == {"full_duplex": False, "enabled": False, "runtime": False}
    owner = _app(monkeypatch, "melvin")
    assert owner.get("/api/aura/voice/mode").json()["full_duplex"] is True
    assert owner.put("/api/aura/voice/mode", json={"full_duplex": False}).json()["enabled"] is False


def test_the_loopback_desktop_without_a_sign_in_gate_is_the_owner(monkeypatch):
    assert _app(monkeypatch, "", gated=False).get("/api/aura/voice/mode").json()["full_duplex"] is True


def test_a_non_owner_cannot_start_a_call(monkeypatch):
    _no_speech_process(monkeypatch)
    with _app(monkeypatch, "tester").websocket_connect("/api/audio/pipecat") as ws:
        frame = ws.receive_json()
    assert frame == {"type": "unavailable", "message": "Full-duplex voice is for the owner account only."}
    assert pipecat_voice._active is False


def _cgroup(tmp_path, current, limit):
    (tmp_path / "memory.current").write_text(str(current), encoding="utf-8")
    (tmp_path / "memory.max").write_text(str(limit), encoding="utf-8")
    return ((str(tmp_path / "memory.current"), str(tmp_path / "memory.max")),)


def test_a_call_is_refused_when_the_container_lacks_headroom(monkeypatch, tmp_path):
    _no_speech_process(monkeypatch)
    # Render free: 512 MiB, the server already near 479 MiB.
    monkeypatch.setattr(pipecat_voice, "_CGROUP_FILES", _cgroup(tmp_path, 479 * MIB, 512 * MIB))
    with _app(monkeypatch, "melvin").websocket_connect("/api/audio/pipecat") as ws:
        frame = ws.receive_json()
    assert frame["type"] == "unavailable" and "enough free memory" in frame["message"]
    assert pipecat_voice._active is False


@pytest.mark.parametrize("current,limit,expected", [
    (100 * MIB, 512 * MIB, 412 * MIB),
    (100 * MIB, "max", None),          # cgroup v2 without a limit
    (100 * MIB, 1 << 62, None),        # cgroup v1 without a limit
])
def test_memory_headroom_reads_cgroup_limits(monkeypatch, tmp_path, current, limit, expected):
    monkeypatch.setattr(pipecat_voice, "_CGROUP_FILES", _cgroup(tmp_path, current, limit))
    assert pipecat_voice.memory_headroom() == expected


def test_no_readable_cgroup_means_no_guard(monkeypatch, tmp_path):
    monkeypatch.setattr(pipecat_voice, "_CGROUP_FILES", ((str(tmp_path / "x"), str(tmp_path / "y")),))
    assert pipecat_voice.memory_headroom() is None


def test_enough_headroom_lets_the_owner_start_the_speech_process(monkeypatch, tmp_path):
    monkeypatch.setattr(pipecat_voice, "_CGROUP_FILES", _cgroup(tmp_path, 100 * MIB, 2048 * MIB))
    started = []

    async def spawn(*args, **_kw):
        started.append(args)
        raise OSError("synthetic: stop after the spawn attempt")

    monkeypatch.setattr(pipecat_voice.asyncio, "create_subprocess_exec", spawn)
    with _app(monkeypatch, "melvin").websocket_connect("/api/audio/pipecat") as ws:
        ws.send_json({"conversation_id": "c1", "client_id": "a" * 32})
        for _ in range(200):  # the server ends the call once the spawn attempt fails
            if started:
                break
            time.sleep(0.05)
    assert started and started[0][1:3] == ("-m", "hermes_cli.aura_voice_worker")
    assert pipecat_voice._active is False


def test_the_web_server_loads_no_speech_code_at_boot():
    probe = ("import sys, hermes_cli.web_server, hermes_cli.web_routers.audio, hermes_cli.web_routers.aura;"
             "print(sorted({m.split('.')[0] for m in sys.modules} & {'pipecat', 'onnxruntime', 'pocketsphinx', "
             "'torch', 'tools.aura_voice_call'} | {m for m in sys.modules if m == 'tools.aura_voice_call'}))")
    out = subprocess.run([sys.executable, "-c", probe], cwd=Path(__file__).resolve().parents[2],
                         capture_output=True, text=True, timeout=120, check=True).stdout.strip()
    assert out.splitlines()[-1] == "[]"
