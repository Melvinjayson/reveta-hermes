"""Private speech worker. The parent authenticates WSS and never delegates agent tools here."""
from __future__ import annotations

import asyncio
import base64
import json
import sys


async def serve(configuration, reader, emit):
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from pipecat.frames.frames import InputAudioRawFrame, InterruptionFrame
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.workers.runner import WorkerRunner
    from hermes_cli.aura_voice_pipeline import HermesReplyFrame, RATE, build_pipeline

    pipeline, bridge, recorder = build_pipeline(emit, configuration["ffmpeg"])
    worker = PipelineWorker(pipeline, enable_rtvi=False, conversation_id=configuration["conversation_id"],
                            params=PipelineParams(audio_in_sample_rate=RATE, audio_out_sample_rate=RATE),
                            idle_timeout_secs=None)
    runner = WorkerRunner(handle_sigint=False)
    ready = asyncio.Event()

    @worker.event_handler("on_pipeline_started")
    async def started(worker, frame):
        ready.set()
        emit("ready", sample_rate=RATE)

    @worker.event_handler("on_pipeline_error")
    async def failed(worker, frame):
        emit("error", message="The local voice pipeline failed")

    async def audio(item):
        pcm = base64.b64decode(item["pcm"], validate=True)
        if len(pcm) > 32000 or len(pcm) % 2:
            raise ValueError("Invalid PCM frame")
        await worker.queue_frame(InputAudioRawFrame(pcm, RATE, 1))

    async def reply(item):
        text = item.get("text", "")
        index = item.get('message_index', 0)
        if not isinstance(text, str) or len(text) > 16384 or type(index) is not int or not 0 <= index < 1000:
            raise ValueError("Invalid reply delta")
        await worker.queue_frame(HermesReplyFrame(item["turn_id"], text, bool(item.get("done")), index))

    async def ack(item):
        recorder.acknowledge(item["packet_id"])

    async def interrupt(item):
        turn_id = item.get("turn_id") or bridge.reply_turn
        if not isinstance(turn_id, str) or len(turn_id) > 256:
            raise ValueError("Invalid interrupted turn")
        bridge.cancelled.add(turn_id)
        recorder.interrupt(turn_id)
        await worker.queue_frame(InterruptionFrame())

    handlers = {'audio': audio, 'reply': reply, 'ack': ack, 'interrupt': interrupt, 'close': ack}
    await runner.add_workers(worker)
    task = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(ready.wait(), timeout=15)
        while not task.done():
            line = await reader()
            if not line:
                break
            if len(line) > 1024 * 1024:
                raise ValueError("Voice frame too large")
            item = json.loads(line)
            kind = item.get("type")
            handler = handlers.get(kind)
            if handler is None:
                raise ValueError("Unknown voice frame")
            if kind == 'close':
                break
            await handler(item)
    finally:
        recorder.interrupt(bridge.reply_turn)
        await runner.cancel()
        await asyncio.wait_for(task, timeout=5)


def main():
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    def emit(kind, **payload):
        print(json.dumps({"type": kind, **payload}, ensure_ascii=False), flush=True)

    async def read():
        return await asyncio.to_thread(sys.stdin.buffer.readline)

    configuration = json.loads(sys.stdin.buffer.readline(16384))
    asyncio.run(serve(configuration, read, emit))


if __name__ == "__main__":
    main()
