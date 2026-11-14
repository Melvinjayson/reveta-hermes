"""Live test of tools/aura_voice_call.py against real Gemini free-tier models.

Starts a FastAPI app on :8765 serving run_call, then drives it like the browser:
speech in -> VAD -> transcript; speak -> audio out; speech during reply -> interrupt.
"""
import asyncio, json, os, resource, sys, time, wave, audioop
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
assert os.environ.get('GEMINI_API_KEY'), 'set GEMINI_API_KEY (free-tier key)'

import uvicorn, websockets
from fastapi import FastAPI, WebSocket
from tools import aura_voice_call as avc

app = FastAPI()

@app.websocket('/ws')
async def ws_route(ws: WebSocket):
    await ws.accept()
    await avc.run_call(ws)

def rss_mb():
    for line in open('/proc/self/status'):
        if line.startswith('VmRSS'):
            return int(line.split()[1]) / 1024

def speech_16k():
    w = wave.open(os.environ.get('AURA_VOICE_SAMPLE', '/tmp/tts_sample.wav')); pcm = w.readframes(w.getnframes())
    out, _ = audioop.ratecv(pcm, 2, 1, w.getframerate(), 16000, None)
    return out

async def send_audio(ws, pcm, silence_s=1.5):
    chunk = 16000 * 2 // 50  # 20 ms
    data = pcm + b'\x00' * int(16000 * 2 * silence_s)
    for i in range(0, len(data), chunk):
        await ws.send(data[i:i + chunk]); await asyncio.sleep(0.02)

async def client():
    log = []
    base = rss_mb()
    async with websockets.connect('ws://127.0.0.1:8765/ws', max_size=None) as ws:
        audio_bytes = 0; first_audio = None
        async def reader():
            nonlocal audio_bytes, first_audio
            async for m in ws:
                t = time.time()
                if isinstance(m, bytes):
                    audio_bytes += len(m); first_audio = first_audio or t
                else:
                    log.append((round(t - t0, 2), json.loads(m))); print('  <-', log[-1], flush=True)
        t0 = time.time()
        r = asyncio.create_task(reader())
        await asyncio.sleep(1)
        print('[1] speech in -> transcript', flush=True)
        await send_audio(ws, speech_16k())
        for _ in range(60):
            if any(e[1].get('type') == 'transcript' for e in log): break
            await asyncio.sleep(0.5)
        print('[2] speak a reply', flush=True)
        ts = time.time()
        await ws.send(json.dumps({'type': 'speak', 'text': 'Sure. Here is a longer answer so there is time to cut in. We should merge the voice layer first, then test it on your phone, then look at browser control and the approval cards.'}))
        for _ in range(80):
            if any(e[1].get('type') == 'bot_speaking' for e in log): break
            await asyncio.sleep(0.25)
        print('   first audio after %.2fs, rss=%.0f MB' % ((first_audio or time.time()) - ts, rss_mb()), flush=True)
        await asyncio.sleep(1.5)
        print('[3] barge in while speaking', flush=True)
        before = audio_bytes
        await send_audio(ws, speech_16k(), silence_s=1.0)
        for _ in range(40):
            if sum(1 for e in log if e[1].get('type') == 'transcript') >= 2: break
            await asyncio.sleep(0.5)
        a1 = audio_bytes; await asyncio.sleep(2); a2 = audio_bytes
        print('   audio bytes during barge-in window=%d, after settling grew by %d' % (a1 - before, a2 - a1), flush=True)
        print('[4] tap interrupt with queued speech', flush=True)
        await ws.send(json.dumps({'type': 'speak', 'text': 'One more sentence to cut off with a tap.'}))
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({'type': 'interrupt'}))
        b = audio_bytes; await asyncio.sleep(4)
        print('   audio after tap interrupt grew by %d bytes' % (audio_bytes - b), flush=True)
        r.cancel()
    types = [e[1].get('type') for e in log]
    print('EVENTS', types)
    print('PEAK_RSS_MB %.0f base_before_call=%.0f' % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, base))

async def main():
    server = uvicorn.Server(uvicorn.Config(app, port=8765, log_level='warning'))
    st = asyncio.create_task(server.serve())
    await asyncio.sleep(1.5)
    print('settings', {k: v for k, v in avc.settings().items()})
    try:
        await asyncio.wait_for(client(), 150)
    finally:
        # reconnect test: a second call after the first hung up must get the slot
        await asyncio.sleep(2)
        async with websockets.connect('ws://127.0.0.1:8765/ws') as ws:
            m = json.loads(await asyncio.wait_for(ws.recv(), 20)); print('RECONNECT first message', m)
        server.should_exit = True; await st

asyncio.run(main())
