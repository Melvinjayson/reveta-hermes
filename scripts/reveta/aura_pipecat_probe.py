#!/usr/bin/env python3
"""Offline real speech-graph probe. Synthetic speech/audio stays in RAM; no model/provider calls."""
from __future__ import annotations
import argparse
import asyncio
import base64
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def probe(python):
    import psutil
    from hermes_platform.resolver import locate_command
    ffmpeg = locate_command('ffmpeg').command[0]
    process = await asyncio.create_subprocess_exec(python, '-m', 'hermes_cli.aura_voice_worker', cwd=ROOT,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, limit=2097152)
    peak = 0

    async def sample():
        nonlocal peak
        while process.returncode is None:
            parent = psutil.Process(process.pid)
            with __import__('contextlib').suppress(psutil.Error):
                total = sum(child.memory_info().rss for child in [parent, *parent.children(recursive=True)]
                            if child.is_running())
                peak = max(peak, total)
            await asyncio.sleep(0.01)

    async def send(frame):
        process.stdin.write((json.dumps(frame) + '\n').encode())
        await process.stdin.drain()

    async def receive():
        while line := await asyncio.wait_for(process.stdout.readline(), timeout=20):
            try:
                return json.loads(line)
            except ValueError:
                continue
        raise RuntimeError('Speech worker closed unexpectedly')

    sampling = asyncio.create_task(sample())
    try:
        await send({'conversation_id': 'synthetic-same-thread', 'ffmpeg': ffmpeg})
        while (await receive())['type'] != 'ready':
            pass
        turn = 'a' * 32
        started = time.monotonic()
        await send({'type': 'reply', 'turn_id': turn, 'text': 'Change the request and tell me the time.', 'done': True})
        while (packet := await receive())['type'] != 'audio':
            pass
        first_audio_ms = (time.monotonic() - started) * 1000
        await send({'type': 'ack', 'packet_id': packet['packet_id']})
        played = await receive()
        await send({'type': 'interrupt'})
        interrupted = await receive()
        pcm = base64.b64decode(packet['pcm']) + b'\0' * 32000

        async def capture():
            for offset in range(0, len(pcm), 640):
                await send({'type': 'audio', 'pcm': base64.b64encode(pcm[offset:offset + 640]).decode()})
                await asyncio.sleep(0.02)
        capture_task = asyncio.create_task(capture())
        partials = []
        while True:
            event = await receive()
            if event['type'] == 'partial':
                partials.append(event['text'])
            if event['type'] == 'final':
                final = event
                break
        await capture_task
        await send({'type': 'close'})
        await asyncio.wait_for(process.wait(), timeout=10)
        return {'pipecat': '1.15.0', 'real': ['Silero VAD', 'PocketSphinx bundled English', 'FFmpeg Flite slt'],
            'fake': ['synthetic speech source', 'Hermes reply'], 'provider_calls': 0,
            'reply_to_first_pcm_ms': round(first_audio_ms, 1), 'speech_process_tree_peak_rss_mib': round(peak / 1048576, 2),
            'partial_count': len(partials), 'final': final, 'played': played, 'interrupted': interrupted,
            'limit': 'Local speech process tree only; total deployed host and real phone acceptance remain separate.'}
    finally:
        if process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=3)
        await sampling


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(probe(args.python)), indent=2))


if __name__ == '__main__':
    main()
