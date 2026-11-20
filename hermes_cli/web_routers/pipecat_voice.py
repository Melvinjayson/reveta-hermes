"""Authenticated WSS speech edge. Agent execution stays on the ordinary gateway."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

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


def has_flite(ffmpeg: str) -> bool:
    """Whether this ffmpeg can speak: the pipeline's TTS is its ``flite`` filter. Some builds (the
    PM-managed ffmpeg among them) have none, and full duplex would then start and stay silent."""
    import subprocess

    try:
        out = subprocess.run([ffmpeg, '-hide_banner', '-filters'], capture_output=True, text=True, timeout=10,
                             check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.split()[1:2] == ['flite'] for line in out.splitlines() if line.strip())


def speech_ffmpeg():
    """The first ffmpeg that can synthesise speech, or None. The image puts the PM-managed ffmpeg (no
    ``flite``) first on PATH, so the distribution's ``/usr/bin/ffmpeg`` is probed after it."""
    found = locate_command('ffmpeg', known_dirs=('/usr/bin',))
    for candidate in found.candidates:
        if candidate.present and has_flite(candidate.value):
            return candidate.value
    return None


MIN_HEADROOM = 280 * 1024 * 1024  # PR #16 measured the speech process tree at ~273 MiB RSS.
_CGROUP_FILES = (('/sys/fs/cgroup/memory.current', '/sys/fs/cgroup/memory.max'),  # cgroup v2
                 ('/sys/fs/cgroup/memory/memory.usage_in_bytes', '/sys/fs/cgroup/memory/memory.limit_in_bytes'))


def memory_headroom():
    """Bytes left under this container's memory limit, or None when there is no readable limit."""
    for current_path, limit_path in _CGROUP_FILES:
        try:
            current = int(Path(current_path).read_text(encoding='utf-8-sig').strip())
            limit = Path(limit_path).read_text(encoding='utf-8-sig').strip()
        except (OSError, ValueError):
            continue
        # cgroup v2 says "max"; v1 reports a huge number when unlimited.
        if limit == 'max' or int(limit) >= 1 << 60:
            return None
        return int(limit) - current
    return None


def owner_call(auth_required: bool, identity: dict) -> bool:
    from tools.aura_owner import caller_is_owner

    return caller_is_owner(auth_required, str(identity.get('user_id') or ''), str(identity.get('email') or ''))


def voice_mode() -> dict:
    """Which voice the composer shows. Full duplex needs the setting AND the separate speech runtime
    (its Python and an ffmpeg with Flite); otherwise the composer keeps the browser voice."""
    enabled = full_duplex_enabled()
    runtime = enabled and runtime_python() is not None and speech_ffmpeg() is not None
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


def _request_owner(request: Request) -> bool:
    session = getattr(request.state, 'session', None)
    return owner_call(getattr(request.app.state, 'auth_required', False),
                      {'user_id': getattr(session, 'user_id', ''), 'email': getattr(session, 'email', '')})


@router.get('/api/aura/voice/mode')
async def aura_voice_mode(request: Request):
    _require_token(request)
    mode = await asyncio.to_thread(voice_mode)
    # Full duplex is the owner's alone: everyone else keeps the browser voice.
    return mode if _request_owner(request) else {'full_duplex': False, 'enabled': False, 'runtime': False}


def set_full_duplex(enabled: bool) -> dict:
    """The owner's Settings switch, ``aura.voice.full_duplex``. It survives boots because
    scripts/reveta/aura_config.py keeps every ``aura.*`` key it does not generate."""
    from hermes_cli.config import load_config, save_config

    config = load_config()
    aura = config.get('aura') if isinstance(config.get('aura'), dict) else {}
    voice = aura.get('voice') if isinstance(aura.get('voice'), dict) else {}
    config['aura'] = {**aura, 'voice': {**voice, 'full_duplex': bool(enabled)}}
    save_config(config)
    return voice_mode()


@router.put('/api/aura/voice/mode')
async def aura_voice_mode_set(request: Request):
    _require_token(request)
    if not _request_owner(request):
        raise HTTPException(status_code=403, detail='Only the owner account can change this.')
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get('full_duplex'), bool):
        raise HTTPException(status_code=422, detail='full_duplex must be true or false.')
    return await asyncio.to_thread(set_full_duplex, body['full_duplex'])


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
    if not owner_call(getattr(ws.app.state, 'auth_required', False), getattr(ws, '_hermes_auth_identity', None) or {}):
        await ws.send_json({'type': 'unavailable', 'message': 'Full-duplex voice is for the owner account only.'})
        await ws.close()
        return
    python = await asyncio.to_thread(runtime_python)
    ffmpeg = await asyncio.to_thread(speech_ffmpeg)
    if _active:
        await ws.send_json({'type': 'busy'})
        await ws.close()
        return
    if python is None or ffmpeg is None:
        await ws.send_json({'type': 'unavailable', 'message': 'Continuous voice unavailable; use labelled turn-based voice.'})
        await ws.close()
        return
    headroom = await asyncio.to_thread(memory_headroom)
    if headroom is not None and headroom < MIN_HEADROOM:
        # A speech process on top would risk the whole service being killed for memory.
        await ws.send_json({'type': 'unavailable', 'message': "The server doesn't have enough free memory for a "
                            'voice call right now. Aura keeps the browser voice; try again later.'})
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
        process.stdin.write((json.dumps({'conversation_id': conversation, 'ffmpeg': ffmpeg}) + '\n').encode())
        await process.stdin.drain()
        await _proxy(ws, process, replay)
    except (WebSocketDisconnect, RuntimeError, ValueError, TimeoutError, OSError):
        pass
    finally:
        try:
            await _stop_speech(process)
        finally:
            _active = False
