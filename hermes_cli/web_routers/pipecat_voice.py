"""Authenticated WSS speech edge. Agent execution stays on the ordinary gateway."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
import time
import uuid

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from hermes_cli.web_server_chat import _ws_auth_ok, _ws_request_is_allowed
from hermes_cli.web_deps import late
from hermes_platform.resolver import locate_command

ROOT = str(Path(__file__).resolve().parents[2])
router = APIRouter()
# One decoder per free instance. Replay contains text/control only, never PCM.
_active = False
_replays = {}
MAX_FRAME = 1024 * 1024


_require_token = late("_require_token")


def full_duplex_enabled() -> bool:
    """``aura.voice.full_duplex`` in config.yaml; off unless set to true."""
    from hermes_cli.config import load_config_readonly

    aura = load_config_readonly().get('aura')
    voice = aura.get('voice') if isinstance(aura, dict) else None
    return isinstance(voice, dict) and voice.get('full_duplex') is True


def voice_mode() -> dict:
    """Which voice the composer shows. Full duplex needs the setting AND the separate speech runtime."""
    enabled = full_duplex_enabled()
    runtime = enabled and runtime_python() is not None and locate_command('ffmpeg').found
    return {'full_duplex': bool(runtime), 'enabled': enabled, 'runtime': bool(runtime)}


def runtime_python():
    root = Path(__file__).resolve().parents[2]
    python = root / '.voice-runtime' / 'bin' / 'python'
    return python if python.is_file() else None


async def _proxy(ws, process, replay):
    async def incoming():
        while True:
            raw = await ws.receive_text()
            if len(raw) > MAX_FRAME:
                raise ValueError('Voice frame too large')
            frame = json.loads(raw)
            if frame.get('type') == 'adopt':
                conversation = frame.get('conversation_id')
                if not isinstance(conversation, str) or not 0 < len(conversation) <= 256:
                    raise ValueError('Invalid conversation identity')
                replay['conversation_id'] = conversation
                continue
            if frame.get('type') not in {'audio', 'reply', 'ack', 'interrupt', 'close'}:
                raise ValueError('Invalid voice frame')
            process.stdin.write((raw + '\n').encode())
            await process.stdin.drain()

    async def outgoing():
        while line := await process.stdout.readline():
            frame = json.loads(line)
            replay['seq'] += 1
            frame.update(seq=replay['seq'], epoch=replay['epoch'], conversation_id=replay['conversation_id'])
            if frame['type'] in {'final', 'played'}:
                replay['frames'].append(frame)
                del replay['frames'][:-128]
            await ws.send_json(frame)
        await ws.send_json({'type': 'unavailable'})

    tasks = [asyncio.create_task(incoming()), asyncio.create_task(outgoing())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _stop_speech(process):
    if process is None or process.returncode is not None:
        return
    try:
        with contextlib.suppress(BrokenPipeError, ConnectionResetError, TimeoutError):
            process.stdin.write(b'{"type":"close"}\n')
            await asyncio.wait_for(process.stdin.drain(), timeout=1)
            await asyncio.wait_for(process.wait(), timeout=2)
    finally:
        if process.returncode is None:
            # Only the speech child, which owns no agent/tool work, is stopped.
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=3)


@router.get('/api/aura/voice/mode')
async def aura_voice_mode(request: Request):
    _require_token(request)
    return await asyncio.to_thread(voice_mode)


@router.websocket('/api/audio/pipecat')
async def voice_ws(ws: WebSocket):
    global _active
    if not _ws_auth_ok(ws, socket='pipecat'):
        await ws.close(code=4401)
        return
    if not _ws_request_is_allowed(ws):
        await ws.close(code=4403)
        return
    await ws.accept(subprotocol=getattr(ws, '_hermes_ws_subprotocol', None))
    if not await asyncio.to_thread(full_duplex_enabled):
        await ws.send_json({'type': 'unavailable', 'message': 'Full-duplex voice is off in Settings.'})
        await ws.close()
        return
    python = await asyncio.to_thread(runtime_python)
    ffmpeg = await asyncio.to_thread(locate_command, 'ffmpeg')
    if _active:
        await ws.send_json({'type': 'busy'})
        await ws.close()
        return
    if python is None or not ffmpeg.found:
        await ws.send_json({'type': 'unavailable', 'message': 'Continuous voice unavailable; use labelled turn-based voice.'})
        await ws.close()
        return
    _active = True
    process = None
    try:
        hello = await asyncio.wait_for(ws.receive_json(), timeout=10)
        conversation = hello.get('conversation_id') or 'unadopted'
        nonce = hello.get('client_id', '')
        if len(nonce) != 32 or any(c not in '0123456789abcdef' for c in nonce):
            raise ValueError('Invalid voice client identity')
        identity = getattr(ws, '_hermes_auth_identity', None) or {}
        from gateway.session_identity import authenticated_subject
        principal = authenticated_subject(identity)
        key = (principal, ws.query_params.get('profile'), nonce)
        now = time.monotonic()
        for old in [k for k, v in _replays.items() if now - v['at'] > 300]:
            del _replays[old]
        if key not in _replays and len(_replays) >= 8:
            del _replays[min(_replays, key=lambda key: _replays[key]['at'])]
        replay = _replays.setdefault(key, {'epoch': uuid.uuid4().hex, 'seq': 0, 'frames': [], 'at': now})
        replay['at'] = now
        replay['conversation_id'] = conversation
        for frame in replay['frames']:
            if frame['seq'] > int(hello.get('after_seq', 0)):
                await ws.send_json(frame)
        # No provider keys/config are inherited by a speech-only child.
        environment = {k: v for k, v in os.environ.items() if k in {'PATH', 'LANG', 'LC_ALL', 'TMPDIR'}}
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        process = await asyncio.create_subprocess_exec(str(python), '-m', 'hermes_cli.aura_voice_worker',
            cwd=ROOT, env=environment,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=2 * MAX_FRAME)
        process.stdin.write((json.dumps({'conversation_id': conversation, 'ffmpeg': ffmpeg.command[0]}) + '\n').encode())
        await process.stdin.drain()
        await _proxy(ws, process, replay)
    except (WebSocketDisconnect, RuntimeError, ValueError, TimeoutError, OSError):
        pass
    finally:
        try:
            await _stop_speech(process)
        finally:
            _active = False
