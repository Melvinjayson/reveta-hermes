"""Speech-edge fake contracts; run with the locked voice interpreter, no providers."""
import pytest

pytest.importorskip('pipecat')
from hermes_cli.aura_voice_pipeline import HermesBridge, HermesReplyFrame, PlayedTextRecorder
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.frames.frames import LLMContextFrame
from pipecat.processors.frame_processor import FrameDirection


def test_barge_in_freezes_at_last_fully_played_sentence():
    events = []
    recorder = PlayedTextRecorder(lambda kind, **body: events.append((kind, body)))
    recorder.offered('1', 'turn', 'Heard.')
    recorder.offered('2', 'turn', 'Never heard.')
    recorder.acknowledge('1')
    recorder.interrupt('turn')
    recorder.acknowledge('2')
    recorder.acknowledge('1')
    assert len(events) == 2
    assert events[-1] == ('played', dict(turn_id='turn', message_index=0, text='Heard.', interrupted=True))


@pytest.mark.asyncio
async def test_one_final_is_one_admission_and_cancelled_reply_cannot_speak():
    events, frames = [], []
    recorder = PlayedTextRecorder(lambda *a, **kw: None)
    bridge = HermesBridge(lambda kind, **body: events.append((kind, body)), recorder)
    bridge.speech_started('a' * 32)
    context = LLMContext([{'role': 'user', 'content': 'Same chat request'}])
    for _ in range(2):
        await bridge.process_frame(LLMContextFrame(context), FrameDirection.DOWNSTREAM)
    assert [e for e in events if e[0] == 'final'] == [('final', {
        'turn_id': 'a' * 32, 'text': 'Same chat request'})]
    async def push(frame, *args):
        frames.append(frame)
    bridge.push_frame = push
    bridge.reply_turn = 'a' * 32
    bridge.speech_started('b' * 32)
    await bridge.process_frame(HermesReplyFrame('a' * 32, 'Must not speak.', True), FrameDirection.DOWNSTREAM)
    assert frames == []
