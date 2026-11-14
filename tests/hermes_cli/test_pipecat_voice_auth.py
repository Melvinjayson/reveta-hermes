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


@pytest.mark.asyncio
async def test_cancellation_during_speech_cleanup_still_releases_decoder(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    configured, closing, never = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Pipe:
        calls = 0
        def write(self, raw):
            pass
        async def drain(self):
            self.calls += 1
            if self.calls == 1:
                configured.set()
                return
            closing.set()
            await never.wait()

    class Process:
        returncode = None
        stdin = Pipe()
        stdout = SimpleNamespace(readline=never.wait)
        def kill(self):
            self.returncode = -9
        async def wait(self):
            return self.returncode

    class Socket:
        query_params = {}
        async def accept(self, **kwargs):
            pass
        async def receive_json(self):
            return {'conversation_id': 'chat', 'client_id': 'd' * 32}
        async def receive_text(self):
            await never.wait()

    process = Process()
    async def spawn(*args, **kwargs):
        return process
    monkeypatch.setattr(pipecat_voice, '_ws_auth_ok', lambda *a, **kw: True)
    monkeypatch.setattr(pipecat_voice, '_ws_request_is_allowed', lambda ws: True)
    monkeypatch.setattr(pipecat_voice, 'runtime_python', lambda: 'synthetic-python')
    monkeypatch.setattr(pipecat_voice.asyncio, 'create_subprocess_exec', spawn)
    task = asyncio.create_task(pipecat_voice.voice_ws(Socket()))
    await asyncio.wait_for(configured.wait(), 5)
    task.cancel()
    await asyncio.wait_for(closing.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode == -9
    assert pipecat_voice._active is False
