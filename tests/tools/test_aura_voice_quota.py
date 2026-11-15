"""Server voice must stop hammering the speech provider after a quota (429) and hand text back instead."""
from tools.aura_voice_call import SPEECH_QUOTA_COOLDOWN_S, SpeechQuotaCooldown, is_quota_error


def test_live_gemini_429_message_counts_as_quota():
    live = RuntimeError(
        "gemini-3.8-flash-lite HTTP 429: You exceeded your current quota, please check your plan and billing details"
    )
    assert is_quota_error(live)
    assert is_quota_error(RuntimeError("RESOURCE_EXHAUSTED"))


def test_other_failures_do_not_start_a_cooldown():
    assert not is_quota_error(RuntimeError("gemini HTTP 500: internal"))
    assert not is_quota_error(SpeechQuotaCooldown("resting"))
    assert SPEECH_QUOTA_COOLDOWN_S >= 30
