"""Aura full-duplex voice: a Pipecat pipeline that hears, detects turns and barge-in, and speaks.

It is an ear and a mouth, never a second brain. The browser sends each final transcript
through the same chat composer as typed text, so the Hermes session, its tools, approvals
and spend controls stay the only agent. The client then streams the reply's text back
here to be spoken. Barge-in stops speech only: it never cancels the running agent turn.

Wire protocol on ``/api/audio/voice-call``:
  client -> binary s16le mono PCM at 16 kHz (the mic)
            {"type": "speak", "text": ...}   speak this reply text (sentence-sized chunks)
            {"type": "interrupt"}           stop speaking now (tap)
  server -> binary s16le mono PCM at 24 kHz (the voice)
            {"type": "ready"} | {"type": "user_speaking"} | {"type": "user_stopped"}
            {"type": "transcript", "text": ...} | {"type": "interrupt"}
            {"type": "bot_speaking"} | {"type": "bot_idle"} | {"type": "error", "message": ...}

Speech-to-text and text-to-speech use the deployment's existing Gemini key on models whose
free tier is the default; another model must be confirmed free like ``AURA_GEMINI_MODEL``.
Pipecat is imported only when a call starts, so an idle server pays no memory for it.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import logging
import os
from typing import Any, Optional

_log = logging.getLogger(__name__)

IN_RATE = 16000
OUT_RATE = 24000
DEFAULT_STT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_TTS_MODEL = "gemini-3.8-flash-lite-tts"
DEFAULT_VOICE = "Kore"
_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_STT_PROMPT = ("Transcribe this speech verbatim in the language spoken. Reply with only the words "
               "spoken. If there is no intelligible speech, reply with nothing.")

# Render's free instance has 512 MB; one call costs Pipecat + Silero about 113-179 MB.
_calls = asyncio.Semaphore(max(1, int(os.environ.get("AURA_VOICE_MAX_CALLS", "1") or 1)))


def _key(env: dict[str, str]) -> str:
    return (env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY") or "").strip()


def _model(env: dict[str, str], name: str, default: str) -> Optional[str]:
    """The model for *name* (STT/TTS), or None when an override is not confirmed free."""
    value = (env.get(f"AURA_VOICE_{name}_MODEL") or "").strip() or default
    if value == default:
        return value
    confirmed = (env.get(f"AURA_VOICE_{name}_MODEL_CONFIRMED_FREE") or "").strip().lower() == "true"
    return value if confirmed else None


def settings(env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """What a call would use, and why it cannot start when it cannot (no secrets in it)."""
    env = dict(os.environ if env is None else env)
    stt, tts = _model(env, "STT", DEFAULT_STT_MODEL), _model(env, "TTS", DEFAULT_TTS_MODEL)
    reason = None
    if (env.get("AURA_VOICE_PIPECAT") or "").strip().lower() in {"0", "false", "off"}:
        reason = "disabled by AURA_VOICE_PIPECAT"
    elif importlib.util.find_spec("pipecat") is None:
        reason = "Pipecat is not installed on this server"
    elif not _key(env):
        reason = "no Gemini key on this server"
    elif stt is None or tts is None:
        reason = "voice model override is not confirmed free"
    return {"available": reason is None, "reason": reason, "stt_model": stt, "tts_model": tts,
            "voice": (env.get("AURA_VOICE_NAME") or "").strip() or DEFAULT_VOICE,
            "in_rate": IN_RATE, "out_rate": OUT_RATE}


async def _gemini(client, key: str, model: str, body: dict) -> dict:
    response = await client.post(_API.format(model=model), json=body, headers={"x-goog-api-key": key})
    if response.status_code >= 400:
        try:
            message = response.json().get("error", {}).get("message", "")
        except ValueError:
            message = response.text
        raise RuntimeError(f"{model} HTTP {response.status_code}: {message[:200]}")
    return response.json()


async def transcribe(client, key: str, model: str, wav: bytes) -> str:
    data = await _gemini(client, key, model, {
        "contents": [{"parts": [{"text": _STT_PROMPT},
                                {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(wav).decode()}}]}],
        "generationConfig": {"temperature": 0}})
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return " ".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


async def synthesize(client, key: str, model: str, voice: str, text: str) -> bytes:
    data = await _gemini(client, key, model, {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}})
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return b"".join(base64.b64decode(p["inlineData"]["data"]) for p in parts if p.get("inlineData"))


def _pipeline_classes():
    """Pipecat classes, built on first call so importing this module never loads Pipecat."""
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.frames.frames import (
        BotStartedSpeakingFrame, BotStoppedSpeakingFrame, ErrorFrame, InputAudioRawFrame,
        InputTransportMessageFrame, InterruptionFrame, OutputAudioRawFrame,
        OutputTransportMessageFrame, OutputTransportMessageUrgentFrame, StartFrame,
        TranscriptionFrame, TTSAudioRawFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
    from pipecat.processors.audio.vad_processor import VADProcessor
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.serializers.base_serializer import FrameSerializer
    from pipecat.services.settings import STTSettings
    from pipecat.services.stt_service import SegmentedSTTService
    from pipecat.utils.time import time_now_iso8601

    class Serializer(FrameSerializer):
        async def serialize(self, frame):
            if isinstance(frame, OutputAudioRawFrame):
                return frame.audio
            if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
                return json.dumps(frame.message)
            if isinstance(frame, InterruptionFrame):
                return json.dumps({"type": "interrupt"})
            return None

        async def deserialize(self, data):
            if isinstance(data, (bytes, bytearray)):
                return InputAudioRawFrame(audio=bytes(data), sample_rate=IN_RATE, num_channels=1)
            try:
                message = json.loads(data)
            except ValueError:
                return None
            if message.get("type") == "speak" and str(message.get("text") or "").strip():
                return InputTransportMessageFrame(message={"type": "speak", "text": str(message["text"])[:4000]})
            if message.get("type") == "interrupt":
                return InputTransportMessageFrame(message={"type": "interrupt"})
            return None

    class GeminiSTT(SegmentedSTTService):
        def __init__(self, *, client, key: str, model: str, **kwargs):
            super().__init__(sample_rate=IN_RATE, settings=STTSettings(model=model, language=None), **kwargs)
            self._client, self._key, self._stt_model = client, key, model

        async def run_stt(self, audio: bytes):
            try:
                text = await transcribe(self._client, self._key, self._stt_model, audio)
            except Exception as exc:  # a failed segment is reported, the call goes on
                yield ErrorFrame(error=f"Speech recognition failed: {exc}")
                return
            if text:
                yield TranscriptionFrame(text=text, user_id="", timestamp=time_now_iso8601(), finalized=True)

    class Conversation(FrameProcessor):
        """Turn and barge-in state between the ear and the mouth; tells the client what happens."""

        def __init__(self, *, client, key: str, model: str, voice: str, **kwargs):
            super().__init__(**kwargs)
            self._client, self._key, self._tts_model, self._voice = client, key, model, voice
            self._bot_speaking = False
            self._speech: asyncio.Queue[str] = asyncio.Queue()
            self._epoch = 0
            self._speaker: Optional[asyncio.Task] = None

        async def _tell(self, message: dict):
            await self.push_frame(OutputTransportMessageUrgentFrame(message=message))

        async def _barge_in(self):
            self._epoch += 1
            while not self._speech.empty():
                self._speech.get_nowait()
            await self.broadcast_interruption()

        async def _speak_loop(self):
            while True:
                text = await self._speech.get()
                epoch = self._epoch
                try:
                    pcm = await synthesize(self._client, self._key, self._tts_model, self._voice, text)
                except Exception as exc:
                    await self._tell({"type": "error", "message": f"Speech synthesis failed: {exc}"})
                    continue
                if epoch != self._epoch or not pcm:
                    continue  # interrupted while synthesizing: never speak a stale reply
                step = OUT_RATE * 2 // 10  # 100 ms frames, so an interruption cuts in quickly
                for start in range(0, len(pcm) - len(pcm) % 2, step):
                    if epoch != self._epoch:
                        break
                    await self.push_frame(TTSAudioRawFrame(audio=pcm[start:start + step], sample_rate=OUT_RATE,
                                                           num_channels=1, context_id=str(epoch)))

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, StartFrame):
                self._speaker = self.create_task(self._speak_loop())
                await self.push_frame(frame, direction)
            elif isinstance(frame, InputAudioRawFrame):
                return  # the mic stops here; only speech goes on to the output
            elif isinstance(frame, VADUserStartedSpeakingFrame):
                await self._tell({"type": "user_speaking"})
                if self._bot_speaking or not self._speech.empty():
                    await self._barge_in()
                await self.push_frame(frame, direction)
            elif isinstance(frame, VADUserStoppedSpeakingFrame):
                await self._tell({"type": "user_stopped"})
                await self.push_frame(frame, direction)
            elif isinstance(frame, TranscriptionFrame):
                await self._tell({"type": "transcript", "text": frame.text})
            elif isinstance(frame, InputTransportMessageFrame):
                if frame.message.get("type") == "speak":
                    self._speech.put_nowait(frame.message["text"])
                elif frame.message.get("type") == "interrupt":
                    await self._barge_in()
            elif isinstance(frame, BotStartedSpeakingFrame):
                if not self._bot_speaking:
                    self._bot_speaking = True
                    await self._tell({"type": "bot_speaking"})
                await self.push_frame(frame, direction)
            elif isinstance(frame, BotStoppedSpeakingFrame):
                if self._bot_speaking:
                    self._bot_speaking = False
                    await self._tell({"type": "bot_idle"})
                await self.push_frame(frame, direction)
            elif isinstance(frame, ErrorFrame) and not getattr(frame, "fatal", False):
                await self._tell({"type": "error", "message": str(frame.error)[:300]})
            else:
                await self.push_frame(frame, direction)

        async def cleanup(self):
            if self._speaker is not None:
                await self.cancel_task(self._speaker)
            await super().cleanup()

    return Serializer, GeminiSTT, Conversation, VADProcessor, SileroVADAnalyzer, VADParams


async def run_call(ws, env: Optional[dict[str, str]] = None) -> None:
    """Run one voice call on an accepted WebSocket until the client hangs up."""
    env = dict(os.environ if env is None else env)
    config = settings(env)
    if not config["available"]:
        await ws.send_json({"type": "error", "message": f"Voice call unavailable: {config['reason']}"})
        await ws.close()
        return
    if _calls.locked():
        await ws.send_json({"type": "error", "message": "Another voice call is using this server. Try again shortly."})
        await ws.close()
        return
    async with _calls:
        import httpx
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.runner import PipelineRunner
        from pipecat.pipeline.task import PipelineParams, PipelineTask
        from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

        Serializer, GeminiSTT, Conversation, VADProcessor, SileroVADAnalyzer, VADParams = _pipeline_classes()
        key = _key(env)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            transport = FastAPIWebsocketTransport(ws, FastAPIWebsocketParams(
                audio_in_enabled=True, audio_out_enabled=True, audio_in_sample_rate=IN_RATE,
                audio_out_sample_rate=OUT_RATE, add_wav_header=False, serializer=Serializer()))
            pipeline = Pipeline([
                transport.input(),
                VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.7))),
                GeminiSTT(client=client, key=key, model=config["stt_model"]),
                Conversation(client=client, key=key, model=config["tts_model"], voice=config["voice"]),
                transport.output(),
            ])
            task = PipelineTask(pipeline, enable_rtvi=False, params=PipelineParams(
                audio_in_sample_rate=IN_RATE, audio_out_sample_rate=OUT_RATE))

            @transport.event_handler("on_client_connected")
            async def _connected(_transport, _ws):
                from pipecat.frames.frames import OutputTransportMessageUrgentFrame
                await task.queue_frame(OutputTransportMessageUrgentFrame(message={
                    "type": "ready", "in_rate": IN_RATE, "out_rate": OUT_RATE}))

            @transport.event_handler("on_client_disconnected")
            async def _disconnected(_transport, _ws):
                await task.cancel()

            runner = PipelineRunner(handle_sigint=False)
            await runner.add_workers(task)
            await runner.run()
