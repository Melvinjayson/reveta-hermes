"""The speech edge reuses the chat socket's credential and Origin gates."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from hermes_cli.web_routers import pipecat_voice


@pytest.mark.parametrize('authenticated,allowed,code', [(False, True, 4401), (True, False, 4403)])
def test_voice_rejects_missing_auth_or_wrong_origin(monkeypatch, authenticated, allowed, code):
    sockets = []
    monkeypatch.setattr(pipecat_voice, '_ws_auth_ok', lambda ws, *, socket: sockets.append(socket) or authenticated)
    monkeypatch.setattr(pipecat_voice, '_ws_request_is_allowed', lambda ws: allowed)
    app = FastAPI()
    app.include_router(pipecat_voice.router)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect('/api/audio/pipecat'):
                pass
    assert refused.value.code == code
    assert sockets == ['pipecat']


def test_unavailable_speech_never_uses_configured_paid_provider(monkeypatch):
    monkeypatch.setattr(pipecat_voice, '_ws_auth_ok', lambda *args, **kw: True)
    monkeypatch.setattr(pipecat_voice, '_ws_request_is_allowed', lambda ws: True)
    monkeypatch.setattr(pipecat_voice, 'runtime_python', lambda: None)
    app = FastAPI()
    app.include_router(pipecat_voice.router)
    with TestClient(app) as client:
        with client.websocket_connect('/api/audio/pipecat') as ws:
            assert ws.receive_json()['type'] == 'unavailable'
