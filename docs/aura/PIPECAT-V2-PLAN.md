# Pipecat voice v2: rebuild of PR #11 on the live branch

Base: `aura/working-product-20261111` at `e7882138` (PR #15 merge; Render deploys this branch).
Source: PR #11 (`aura/pipecat-voice`, 8 commits on old base `12c8f57e9f`).

## Decision

The live voice (`AuraVoice` in `apps/desktop/src/app/aura/voice-call.tsx`, with the turn-based
`AuraBrowserVoice` fallback) stays the default and is not edited: echo filtering
(`isEchoOfAura`), sentence-by-sentence speech (`speakableSoFar`/`speechChunks`) and the
Gemini-quota fallback (`speech_failed` -> device voice, `SPEECH_QUOTA_COOLDOWN_S`) are unchanged.
PR #11's continuous local voice (`AuraPipecatVoice`, `/api/audio/pipecat`, the speech worker,
played-text receipts, generation-only interruption) is selected only when
`aura.voice.full_duplex: true` in `config.yaml` (default false) and the separate speech runtime
is installed. Otherwise the composer renders `AuraVoice` exactly as today.

## Steps (one commit/push each)

1. This plan.
2. Cherry-pick PR #11's 8 commits with `-x` (authorship kept). Two conflicts
   (`browser-voice.tsx`, `composer/index.tsx`) resolved by keeping the live files.
3. Keep the default deploy path unchanged: revert PR #11's Dockerfile hunks (ffmpeg + baked
   `.voice-runtime`) and its `browser-voice.test.tsx` edit (the browser fallback is not changed).
4. The setting: `aura.voice.full_duplex` (default false), `GET /api/aura/voice/mode`, server-side
   refusal of `/api/audio/pipecat` when off, and a composer selector that falls back to `AuraVoice`
   when the setting is off, the request fails or the runtime is missing.
5. Type check, Vitest (aura + composer), focused pytest (voice + free-only), ruff.
6. Later, separate: browser check, real-model test (only with no new spend/secrets), Android test.

## Risk: memory

PR #11 measured the local speech process tree at 249 MiB RSS peak. Render free has 512 MiB and
the server was at ~479 MiB before an earlier deploy. The speech runtime is therefore **not** built
into the default Docker image here; enabling full duplex on Render needs Melvin's decision (a
larger instance or a separate speech host).
