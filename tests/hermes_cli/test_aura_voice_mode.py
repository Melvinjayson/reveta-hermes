"""Full-duplex voice is opt-in: off by default, and on only with the setting AND the speech runtime."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.web_routers import pipecat_voice


def _write_config(text: str) -> None:
    from hermes_constants import get_hermes_home

    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(text, encoding="utf-8")


def _app(monkeypatch):
    monkeypatch.setattr(pipecat_voice, "_require_token", lambda request: None)
    monkeypatch.setattr(pipecat_voice, "_ws_auth_ok", lambda *a, **kw: True)
    monkeypatch.setattr(pipecat_voice, "_ws_request_is_allowed", lambda ws: True)
    app = FastAPI()
    app.include_router(pipecat_voice.router)
    return app


def _runtime_installed(monkeypatch):
    monkeypatch.setattr(pipecat_voice, "runtime_python", lambda: "synthetic-python")
    monkeypatch.setattr(pipecat_voice, "locate_command", lambda name: SimpleNamespace(found=True, command=[name]))


def test_full_duplex_is_off_without_the_setting_even_with_the_runtime(monkeypatch):
    _write_config("model:\n  default: x\n")
    _runtime_installed(monkeypatch)
    with TestClient(_app(monkeypatch)) as client:
        assert client.get("/api/aura/voice/mode").json() == {"full_duplex": False, "enabled": False, "runtime": False}
        with client.websocket_connect("/api/audio/pipecat") as ws:
            frame = ws.receive_json()
    assert frame["type"] == "unavailable"
    assert "off" in frame["message"]
    assert pipecat_voice._active is False


@pytest.mark.parametrize("runtime,expected", [(True, True), (False, False)])
def test_setting_on_selects_full_duplex_only_when_runtime_present(monkeypatch, runtime, expected):
    _write_config("aura:\n  voice:\n    full_duplex: true\n")
    if runtime:
        _runtime_installed(monkeypatch)
    else:
        monkeypatch.setattr(pipecat_voice, "runtime_python", lambda: None)
    with TestClient(_app(monkeypatch)) as client:
        mode = client.get("/api/aura/voice/mode").json()
    assert mode == {"full_duplex": expected, "enabled": True, "runtime": expected}


def test_non_boolean_setting_does_not_enable_full_duplex(monkeypatch):
    _write_config("aura:\n  voice:\n    full_duplex: 'yes please'\n")
    assert pipecat_voice.full_duplex_enabled() is False
