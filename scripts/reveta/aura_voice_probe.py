#!/usr/bin/env python3
"""Measure the pinned Pipecat/Silero import floor, not voice acceptance.

Run with an isolated PM-built interpreter containing pipecat-ai[silero]==1.15.0.
This script downloads nothing, opens no microphone, invokes no provider and
stores no audio. JSON goes to
stdout. Exit 2 means the complete server voice stack has NOT been established.
"""
from __future__ import annotations

import asyncio
from importlib.metadata import version
import json
import sys
import time

PIPECAT_VERSION = "1.15.0"


def peak_mib() -> float:
    """Linux ru_maxrss is KiB; macOS reports bytes."""
    import resource

    scale = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / scale, 3)


async def probe() -> dict:
    if version("pipecat-ai") != PIPECAT_VERSION:
        raise RuntimeError(f"This measurement requires pipecat-ai=={PIPECAT_VERSION}")
    stages = {"interpreter_peak_mib": peak_mib()}
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.services.stt_service import STTService
    from pipecat.services.tts_service import TTSService

    vad = SileroVADAnalyzer(sample_rate=16000)
    vad.set_sample_rate(16000)
    started = time.perf_counter()
    try:
        for _ in range(100):
            await vad.analyze_audio(bytes(1024))
        stages["silero_100_synthetic_frames_seconds"] = round(time.perf_counter() - started, 4)
        stages["pipecat_silero_peak_mib"] = peak_mib()
    finally:
        await vad.cleanup()
    return {
        "pipecat_ai": PIPECAT_VERSION,
        "python": sys.version.split()[0],
        "stages": stages,
        "render_limit_mib": 512,
        "complete_voice_stack_verified": False,
        "limits": [
            "No TTS model loaded; no real speech or playback measured.",
            "Import/synthetic-frame RSS is a lower bound, not a capacity guarantee.",
            "No active Hermes session, browser, concurrent turn or container overhead measured.",
            "This probe is not a production voice pipeline or proof that no free stack can fit.",
        ],
    }


def main() -> int:
    print(json.dumps(asyncio.run(probe()), indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
