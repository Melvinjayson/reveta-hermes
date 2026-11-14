"""Pipecat's speech-only edge. Hermes replies arrive through the authenticated chat client.

conversation_id is Aura's durable chat id. turn_id is also prompt.submit's
submission_id: partials never submit, and replayed finals retain that identity.
Only acknowledged output packets advance the played prefix. No LLM lives here.
"""
from __future__ import annotations

import asyncio
import base64
from collections import defaultdict
from dataclasses import dataclass
import tempfile
import time
import textwrap
import uuid

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    DataFrame, Frame, InputAudioRawFrame, InterimTranscriptionFrame, InterruptionFrame,
    LLMContextFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame,
    TranscriptionFrame, TTSAudioRawFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.stt_service import STTService
from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

RATE = 16000


class WebSocketInput(FrameProcessor):
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


@dataclass
class HermesReplyFrame(DataFrame):
    turn_id: str
    text: str
    done: bool = False
    message_index: int = 0


@dataclass
class SpeechSentenceFrame(DataFrame):
    turn_id: str
    message_index: int
    text: str


@dataclass
class SentenceAudioFrame(TTSAudioRawFrame):
    packet_id: str = ""
    turn_id: str = ""
    text: str = ""
    message_index: int = 0


class PlayedTextRecorder(FrameProcessor):
    """Conservative sentence acknowledgements, never generated-but-unplayed words."""

    def __init__(self, emit):
        super().__init__()
        self.emit = emit
        self.packets = {}
        self.order = defaultdict(list)
        self.acked = set()
        self.frozen = set()

    def offered(self, packet_id, turn_id, text, message_index=0):
        if packet_id not in self.packets:
            self.packets[packet_id] = (turn_id, text, message_index)
            self.order[(turn_id, message_index)].append(packet_id)

    def played(self, turn_id, message_index=0):
        pieces = []
        for packet in self.order[(turn_id, message_index)]:
            if packet not in self.acked:
                break
            pieces.append(self.packets[packet][1])
        return " ".join(pieces)

    def acknowledge(self, packet_id):
        if packet_id not in self.packets or packet_id in self.acked:
            return
        turn_id, _, index = self.packets[packet_id]
        if turn_id in self.frozen:
            return
        self.acked.add(packet_id)
        self.emit("played", turn_id=turn_id, message_index=index, text=self.played(turn_id, index), interrupted=False)

    def interrupt(self, turn_id):
        if turn_id and turn_id not in self.frozen:
            self.frozen.add(turn_id)
            indexes = {index for turn, index in self.order if turn == turn_id} or {0}
            for index in indexes:
                self.emit("played", turn_id=turn_id, message_index=index, text=self.played(turn_id, index), interrupted=True)

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class PocketSphinxSTT(STTService):
    """Bundled English model; no keys, model download or raw-audio file."""

    def __init__(self, emit, on_start):
        from pocketsphinx import Decoder
        super().__init__(sample_rate=RATE, ttfs_p99_latency=0.5,
                         settings=STTSettings(model="pocketsphinx-en-us", language=Language.EN_US))
        self.decoder = Decoder(samprate=RATE)
        self.emit, self.on_start = emit, on_start
        self.speaking = False
        self.preroll = bytearray()
        self.partial = ""
        self.turn_id = ""
        self.audio_bytes = 0

    async def run_stt(self, audio):
        if not self.speaking:
            self.preroll.extend(audio)
            del self.preroll[:-16000]  # half a second, including VAD's start delay
            return
        self.audio_bytes += len(audio)
        if self.audio_bytes > RATE * 2 * 30:
            return  # bounded utterances; VAD stop will finalize the retained audio
        self.decoder.process_raw(audio, False, False)
        hyp = self.decoder.hyp()
        text = hyp.hypstr if hyp else ""
        if text and text != self.partial:
            self.partial = text
            self.emit("partial", turn_id=self.turn_id, text=text)
            yield InterimTranscriptionFrame(text, "", time_now_iso8601())

    async def process_frame(self, frame, direction):
        if isinstance(frame, VADUserStartedSpeakingFrame) and not self.speaking:
            self.turn_id = uuid.uuid4().hex
            self.on_start(self.turn_id)
            self.speaking, self.partial, self.audio_bytes = True, "", 0
            self.decoder.start_utt()
            self.decoder.process_raw(bytes(self.preroll), False, False)
            self.preroll.clear()
        elif isinstance(frame, VADUserStoppedSpeakingFrame) and self.speaking:
            self.speaking = False
            self.decoder.end_utt()
            hyp = self.decoder.hyp()
            self.emit("speech_end", turn_id=self.turn_id, monotonic=time.monotonic())
            if hyp and hyp.hypstr.strip():
                await self.push_frame(TranscriptionFrame(hyp.hypstr, "", time_now_iso8601(), finalized=True))
        await super().process_frame(frame, direction)


class HermesBridge(FrameProcessor):
    """Admit finals through Aura's existing onSubmit, then speak that same chat stream."""

    def __init__(self, emit, recorder):
        super().__init__()
        self.emit, self.recorder = emit, recorder
        self.turn_id = ""
        self.reply_turn = ""
        self.submitted = set()
        self.cancelled = set()
        self.aggregator = SimpleTextAggregator()
        self.message_index = 0

    def speech_started(self, turn_id):
        old = self.reply_turn
        self.cancelled.add(old)
        self.recorder.interrupt(old)
        self.turn_id = turn_id
        self.emit("speech_start", turn_id=turn_id, interrupt_turn_id=old, monotonic=time.monotonic())

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            messages = frame.context.get_messages()
            text = messages[-1].get("content", "") if messages else ""
            if isinstance(text, str) and text.strip() and self.turn_id not in self.submitted:
                self.submitted.add(self.turn_id)
                self.emit("final", turn_id=self.turn_id, text=text.strip())
            frame.context.set_messages([])  # packaging only; Hermes owns the chat context
        elif isinstance(frame, HermesReplyFrame):
            if frame.turn_id in self.cancelled:
                return
            if (frame.turn_id, frame.message_index) != (self.reply_turn, self.message_index):
                self.aggregator = SimpleTextAggregator()
            self.reply_turn, self.message_index = frame.turn_id, frame.message_index
            async for sentence in self.aggregator.aggregate(frame.text):
                await self.push_frame(SpeechSentenceFrame(frame.turn_id, frame.message_index, sentence.text))
            if frame.done:
                sentence = await self.aggregator.flush()
                if sentence and sentence.text.strip():
                    await self.push_frame(SpeechSentenceFrame(frame.turn_id, frame.message_index, sentence.text))
        else:
            await self.push_frame(frame, direction)


class FliteTTS(FrameProcessor):
    """Local sentence TTS; immutable packet identities survive queued synthesis."""

    def __init__(self, ffmpeg, bridge, recorder):
        super().__init__()
        self.ffmpeg, self.bridge, self.recorder = ffmpeg, bridge, recorder
        self.sentences = defaultdict(int)

    async def synthesize(self, text):
        # FFmpeg's Flite textfile must be seekable. Only text, never audio, touches disk.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="aura-speech-", suffix=".txt") as source:
            source.write(text)
            source.flush()
            process = await asyncio.create_subprocess_exec(
                self.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                f"flite=textfile={source.name}:voice=slt", "-f", "s16le", "-ar", str(RATE), "-ac", "1", "pipe:1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                pcm, _error = await asyncio.wait_for(process.communicate(), timeout=20)
                if process.returncode:
                    raise RuntimeError("Local speech synthesis failed")
                return pcm
            finally:
                if process.returncode is None:
                    process.kill()
                    await asyncio.wait_for(process.wait(), timeout=3)

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if not isinstance(frame, SpeechSentenceFrame):
            await self.push_frame(frame, direction)
            return
        for text in textwrap.wrap(frame.text, width=240, break_long_words=True, break_on_hyphens=False):
            if frame.turn_id in self.bridge.cancelled:
                return
            self.sentences[frame.turn_id] += 1
            packet_id = f"{frame.turn_id}:{self.sentences[frame.turn_id]}"
            self.recorder.offered(packet_id, frame.turn_id, text, frame.message_index)
            pcm = await self.synthesize(text)
            if frame.turn_id not in self.bridge.cancelled:
                await self.push_frame(SentenceAudioFrame(pcm, RATE, 1, packet_id=packet_id,
                    turn_id=frame.turn_id, message_index=frame.message_index, text=text))


class WebSocketOutput(FrameProcessor):
    def __init__(self, emit, tts):
        super().__init__()
        self.emit, self.tts = emit, tts

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame):
            self.emit("audio", turn_id=frame.turn_id, packet_id=frame.packet_id, text=frame.text,
                      message_index=frame.message_index, sample_rate=RATE, pcm=base64.b64encode(frame.audio).decode("ascii"))
        if not isinstance(frame, InputAudioRawFrame):
            await self.push_frame(frame, direction)


def build_pipeline(emit, ffmpeg):
    """The host owns authenticated WSS; this isolated process owns only the speech graph."""
    recorder = PlayedTextRecorder(emit)
    bridge = HermesBridge(emit, recorder)
    stt = PocketSphinxSTT(emit, bridge.speech_started)
    context = LLMContext()
    user, _assistant = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(sample_rate=RATE, params=VADParams(start_secs=0.15, stop_secs=0.35)),
        user_turn_strategies=UserTurnStrategies(stop=[SpeechTimeoutUserTurnStopStrategy()]),
    ))
    tts = FliteTTS(ffmpeg, bridge, recorder)
    pipeline = Pipeline([WebSocketInput(name="AuthenticatedWebSocketInput"), stt, user,
                         bridge, tts, WebSocketOutput(emit, tts), recorder])
    return pipeline, bridge, recorder
