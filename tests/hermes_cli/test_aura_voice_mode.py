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
    monkeypatch.setattr(pipecat_voice, "has_flite", lambda ffmpeg: True)


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


FILTERS = """Filters:
  T.. = Timeline support
 ... aevalsrc          |->A       Generate an audio signal specified by an expression.
 ... anullsrc          |->A       Null audio source, return empty audio frames.
"""


def _fake_ffmpeg(tmp_path, with_flite):
    """A real executable that answers ``-filters`` like an ffmpeg build with or without Flite."""
    listing = FILTERS + (" ... flite             |->A       Synthesize voice from text using libflite.\n" if with_flite else "")
    path = tmp_path / ("ffmpeg-flite" if with_flite else "ffmpeg-plain")
    path.write_text("#!/bin/sh\ncat <<'EOF'\n" + listing + "EOF\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


@pytest.mark.platforms("posix")
def test_an_ffmpeg_without_flite_keeps_the_browser_voice(monkeypatch, tmp_path):
    """PM's ffmpeg has no flite filter: full duplex would start and stay silent, so it reports unavailable."""
    _write_config("aura:\n  voice:\n    full_duplex: true\n")
    monkeypatch.setattr(pipecat_voice, "runtime_python", lambda: "synthetic-python")
    for with_flite, expected in ((False, False), (True, True)):
        ffmpeg = _fake_ffmpeg(tmp_path, with_flite)
        monkeypatch.setattr(pipecat_voice, "locate_command", lambda name, f=ffmpeg: SimpleNamespace(found=True, command=[f]))
        assert pipecat_voice.has_flite(ffmpeg) is with_flite
        assert pipecat_voice.speech_ffmpeg() == (ffmpeg if with_flite else None)
        assert pipecat_voice.voice_mode() == {"full_duplex": expected, "enabled": True, "runtime": expected}
    # The socket refuses before starting the speech process, so nothing runs silently.
    with TestClient(_app(monkeypatch)) as client:
        monkeypatch.setattr(pipecat_voice, "locate_command",
                            lambda name: SimpleNamespace(found=True, command=[_fake_ffmpeg(tmp_path, False)]))
        with client.websocket_connect("/api/audio/pipecat") as ws:
            frame = ws.receive_json()
    assert frame["type"] == "unavailable"
    assert pipecat_voice._active is False


def test_a_missing_or_broken_ffmpeg_is_not_a_speech_runtime(tmp_path):
    assert pipecat_voice.has_flite(str(tmp_path / "no-such-ffmpeg")) is False


def test_the_settings_switch_writes_the_setting_and_it_survives_a_boot(monkeypatch, tmp_path):
    import sys

    from ruamel.yaml import YAML
    from hermes_constants import get_hermes_home
    from scripts.reveta import aura_config

    _write_config("model:\n  default: x\n")
    _runtime_installed(monkeypatch)
    with TestClient(_app(monkeypatch)) as client:
        assert client.put("/api/aura/voice/mode", json={"full_duplex": "yes"}).status_code == 422
        assert client.put("/api/aura/voice/mode", json={"full_duplex": True}).json() == {
            "full_duplex": True, "enabled": True, "runtime": True}
    path = get_hermes_home() / "config.yaml"
    monkeypatch.setattr(sys, "argv", ["aura_config.py", "--write", str(path)])
    assert aura_config.main() == 0  # the boot step that used to reset every aura.* key
    assert YAML().load(path.read_text(encoding="utf-8"))["aura"]["voice"] == {"full_duplex": True}
    with TestClient(_app(monkeypatch)) as client:
        assert client.put("/api/aura/voice/mode", json={"full_duplex": False}).json()["enabled"] is False
