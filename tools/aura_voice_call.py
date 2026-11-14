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
from pathlib import Path
import json
import logging
import os
import sys
from typing import Any, Optional

_log = logging.getLogger(__name__)

# The Docker image installs Pipecat outside the sealed venv (see Dockerfile); append it LAST so
# every package the venv already has wins over the copy pulled in for Pipecat.
_VOICE_SITE = os.environ.get("AURA_VOICE_SITE", "/opt/aura-voice/site")
if os.path.isdir(_VOICE_SITE) and _VOICE_SITE not in sys.path:
    sys.path.append(_VOICE_SITE)

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


# OpenAI speech, used when the owner saved an OpenAI key in Aura Settings. Prices from
# platform.openai.com/docs/pricing (Nov 2026): transcribe $0.003/min; TTS charged here at
# $1.08/hour of audio, a little above OpenAI's ~$0.015/min estimate.
OPENAI_STT_MODEL, OPENAI_TTS_MODEL, OPENAI_VOICE = "gpt-4o-mini-transcribe", "gpt-4o-mini-tts", "coral"
OPENAI_STT_USD_PER_SECOND, OPENAI_TTS_USD_PER_SECOND = 0.003 / 60, 1.08 / 3600
KOKORO_MODEL, KOKORO_VOICES, KOKORO_VOICE = "kokoro-v1.0.int8.onnx", "voices-v1.0.bin", "af_heart"
OPENAI_TTS_STYLE = "Speak naturally and warmly at a relaxed conversational pace, like a thoughtful colleague."


def _key(env: dict[str, str]) -> str:
    return (env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY") or "").strip()


def _model(env: dict[str, str], name: str, default: str) -> Optional[str]:
    """The model for *name* (STT/TTS), or None when an override is not confirmed free."""
    value = (env.get(f"AURA_VOICE_{name}_MODEL") or "").strip() or default
    if value == default:
        return value
    confirmed = (env.get(f"AURA_VOICE_{name}_MODEL_CONFIRMED_FREE") or "").strip().lower() == "true"
    return value if confirmed else None


def _paid_voice(env: dict[str, str]) -> Optional[dict]:
    """OpenAI speech when the owner saved an OpenAI key and set caps in Aura Settings, else None."""
    if not (env.get("OPENAI_API_KEY") or "").strip():
        return None
    try:
        from tools.aura_provider import route
        return route()
    except Exception:
        return None


def settings(env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """What a call would use, and why it cannot start when it cannot (no secrets in it)."""
    env = _env(env)
    paid = _paid_voice(env)
    if paid:
        stt, tts, voice, backend = OPENAI_STT_MODEL, OPENAI_TTS_MODEL, OPENAI_VOICE, "openai"
    else:
        stt, tts = _model(env, "STT", DEFAULT_STT_MODEL), _model(env, "TTS", DEFAULT_TTS_MODEL)
        voice, backend = (env.get("AURA_VOICE_NAME") or "").strip() or DEFAULT_VOICE, "gemini"
    kokoro = _kokoro_dir(env)
    if kokoro:
        tts, voice, backend = "kokoro-82m-int8", (env.get("AURA_KOKORO_VOICE") or "").strip() or KOKORO_VOICE, \
            f"{backend}+kokoro"
    reason = None
    if (env.get("AURA_VOICE_PIPECAT") or "").strip().lower() in {"0", "false", "off"}:
        reason = "disabled by AURA_VOICE_PIPECAT"
    elif importlib.util.find_spec("pipecat") is None:
        reason = "Pipecat is not installed on this server"
    elif not paid and not _key(env):
        reason = "no voice key on this server: add an OpenAI key in Aura Settings"
    elif stt is None or tts is None:
        reason = "voice model override is not confirmed free"
    return {"available": reason is None, "reason": reason, "backend": backend, "stt_model": stt,
            "tts_model": tts, "voice": voice, "in_rate": IN_RATE, "out_rate": OUT_RATE}


def _env(env: Optional[dict[str, str]]) -> dict[str, str]:
    """Process env plus keys saved from Aura Settings (``.env``), which a running server may not have loaded."""
    if env is not None:
        return dict(env)
    from hermes_cli.config import load_env
    return {**load_env(), **{k: v for k, v in os.environ.items() if v}}


class GeminiSpeech:
    def __init__(self, client, key: str, config: dict):
        self._client, self._key, self._config = client, key, config

    async def transcribe(self, wav: bytes) -> str:
        return await transcribe(self._client, self._key, self._config["stt_model"], wav)

    async def synthesize(self, text: str) -> bytes:
        return await synthesize(self._client, self._key, self._config["tts_model"], self._config["voice"], text)


def _kokoro_dir(env: dict[str, str]) -> Optional[Path]:
    """Local Kokoro TTS when AURA_KOKORO_DIR holds the kokoro-onnx model and voices files."""
    raw = (env.get("AURA_KOKORO_DIR") or "").strip()
    if not raw or importlib.util.find_spec("kokoro_onnx") is None:
        return None
    folder = Path(raw)
    return folder if (folder / KOKORO_MODEL).is_file() and (folder / KOKORO_VOICES).is_file() else None


class KokoroSpeech:
    """Speaks with local Kokoro (no provider, no spend); hears with the wrapped backend.

    Measured 14 Nov 2026 on one CPU core: ~1.1 s for a short sentence, real-time factor 0.62-0.75,
    peak RSS ~365 MB. Needs about one dedicated core; Render free (0.1 CPU, 512 MB) cannot hold it.
    """

    _engine = None

    def __init__(self, ear, folder: Path, voice: str):
        self._ear, self._folder, self._voice = ear, folder, voice

    async def transcribe(self, wav: bytes) -> str:
        return await self._ear.transcribe(wav)

    def _load(self):
        if KokoroSpeech._engine is None:
            import onnxruntime
            from kokoro_onnx import Kokoro

            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = max(1, min(4, len(os.sched_getaffinity(0))))
            options.inter_op_num_threads = 1
            session = onnxruntime.InferenceSession(str(self._folder / KOKORO_MODEL), options,
                                                   providers=["CPUExecutionProvider"])
            KokoroSpeech._engine = Kokoro.from_session(session, str(self._folder / KOKORO_VOICES))
        return KokoroSpeech._engine

    def _speak(self, text: str) -> bytes:
        import numpy

        samples, rate = self._load().create(text[:1000], voice=self._voice, speed=1.0, lang="en-us")
        if rate != OUT_RATE:
            raise RuntimeError(f"Kokoro returned {rate} Hz audio, expected {OUT_RATE}")
        return (numpy.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()

    async def synthesize(self, text: str) -> bytes:
        return await asyncio.to_thread(self._speak, text)


class OpenAISpeech:
    """OpenAI STT/TTS, metered into the Aura Settings daily cap (tools/aura_provider.py)."""

    def __init__(self, client, key: str, config: dict):
        self._client, self._config = client, config
        self._headers = {"Authorization": f"Bearer {key}"}

    @staticmethod
    def _gate() -> None:
        from tools.aura_provider import check, route
        check(route())

    @staticmethod
    def _charge(usd: float) -> None:
        from tools.aura_provider import charge
        charge("voice", "openai", "voice", usd)

    async def _post(self, path: str, **kwargs):
        response = await self._client.post(f"https://api.openai.com/v1/{path}", headers=self._headers, **kwargs)
        if response.status_code >= 400:
            try:
                message = response.json().get("error", {}).get("message", "")
            except ValueError:
                message = response.text
            raise RuntimeError(f"OpenAI HTTP {response.status_code}: {message[:200]}")
        return response

    async def transcribe(self, wav: bytes) -> str:
        self._gate()
        response = await self._post("audio/transcriptions", data={"model": self._config["stt_model"]},
                                    files={"file": ("speech.wav", wav, "audio/wav")})
        self._charge(max(0, len(wav) - 44) / (IN_RATE * 2) * OPENAI_STT_USD_PER_SECOND)
        return str(response.json().get("text") or "").strip()

    async def synthesize(self, text: str) -> bytes:
        self._gate()
        response = await self._post("audio/speech", json={
            "model": self._config["tts_model"], "voice": self._config["voice"], "input": text[:4000],
            "response_format": "pcm", "instructions": OPENAI_TTS_STYLE})
        pcm = response.content
        self._charge(len(pcm) / (OUT_RATE * 2) * OPENAI_TTS_USD_PER_SECOND)
        return pcm


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
        def __init__(self, *, speech, model: str, **kwargs):
            super().__init__(sample_rate=IN_RATE, settings=STTSettings(model=model, language=None), **kwargs)
            self._speech_api = speech

        async def run_stt(self, audio: bytes):
            try:
                text = await self._speech_api.transcribe(audio)
            except Exception as exc:  # a failed segment is reported, the call goes on
                yield ErrorFrame(error=f"Speech recognition failed: {exc}")
                return
            if text:
                yield TranscriptionFrame(text=text, user_id="", timestamp=time_now_iso8601(), finalized=True)

    class Conversation(FrameProcessor):
        """Turn and barge-in state between the ear and the mouth; tells the client what happens."""

        def __init__(self, *, speech, **kwargs):
            super().__init__(**kwargs)
            self._speech_api = speech
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
                    pcm = await self._speech_api.synthesize(text)
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
    env = _env(env)
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
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            if config["backend"].startswith("openai"):
                speech = OpenAISpeech(client, env["OPENAI_API_KEY"].strip(), config)
            else:
                speech = GeminiSpeech(client, _key(env), config)
            if config["backend"].endswith("+kokoro"):
                speech = KokoroSpeech(speech, _kokoro_dir(env), config["voice"])
            transport = FastAPIWebsocketTransport(ws, FastAPIWebsocketParams(
                audio_in_enabled=True, audio_out_enabled=True, audio_in_sample_rate=IN_RATE,
                audio_out_sample_rate=OUT_RATE, add_wav_header=False, serializer=Serializer()))
            pipeline = Pipeline([
                transport.input(),
                VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.7))),
                GeminiSTT(speech=speech, model=config["stt_model"]),
                Conversation(speech=speech),
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
