# On-device conversation prototype (opt-in)

Branch `aura/local-talk-prototype`, based on the live branch `aura/working-product-20261111` at `e2e7c1ac18`.
Off by default. Nothing changes for anyone who hasn't opened `?aura-local=1`.

## What it does

- **On-device** button next to Voice (browser build only, only after `?aura-local=1`; `?aura-local=0` turns it off).
- Checks WebGPU, grades the device (S/A/B/C from estimated graphics memory, adapted from webllm.io, MIT notice kept in `local-model.ts`), reads battery level and charging, and online state. Shows them and any warning before anything downloads.
- Explicit opt-in download of **Qwen2.5-0.5B-Instruct** (Apache-2.0), WebLLM 0.2.87 prebuilt `q4f16_1` (GPUs with `shader-f16`) or `q4f32_1`. About 290 MB, once, from Hugging Face into the browser's Cache Storage. Progress bar, Cancel (terminates the worker), Remove download.
- WebLLM runs in a module web worker (`local-engine.worker.ts`), lazy-loaded: the 6 MB WebLLM chunk is not in the main bundle.
- Multi-turn text conversation on the device. No tools are passed to the model. Tool-call-shaped output is never shown or run. Messages that need tools, live facts or deeper thinking (search, email, book, PDF, latest, "hand it to Aura", "go deeper"...) are routed by fixed rules to the hand-off, not by the small model's judgement.
- Each on-device reply carries an **On device** badge with WebLLM's measured decode speed (tokens/s) and "cut off" when it hit the length limit. Server replies carry **Aura** (free model) or **Paid model** (Anthropic/OpenAI), read from the chat's own provider and model.
- The local conversation is kept in this browser (localStorage, last 24 turns) so a reload doesn't lose it. **Clear** removes it; handing off removes it.
- **Hand to Aura** is always a tap: the on-device model drafts "what you want so far", the user can edit it, the panel shows where it goes and today's spend from `GET /api/aura/provider`, then **Send to Aura** posts one normal chat message (history + intent, marked "nothing has been done or approved"). Blocked when offline or when the paid daily cap is used. The server's guard, caps and Hermes approvals apply exactly as for any typed message. No keys in the browser, no automatic paid fallback, no new endpoint.

## Costs that are not zero

No per-token bill for on-device replies. Still costs: the ~290 MB download, device storage, battery and memory, and Aura's hosting. Speech is not made free by this: it's text only and Voice still uses the existing speech path.

## Tests (automated, not a phone)

- `local-model.test.ts`, `local-talk.test.tsx`: support probe, device grade, memory estimate, battery and offline warnings, routing rules, tool-call detection, hand-off content and size bounds, budget-blocked and offline hand-off, download failure, cancel, cleanup on unmount, persistence and Clear, empty replies, badges.
- On the rebased branch: `vitest --project ui` over `app/aura`, `components/assistant-ui/thread`, `app/chat/composer`: 170 files, 1115 tests passed. `tsc --build` and ESLint on the changed files clean. `vite build` produced the worker and a separate WebLLM chunk.
- **Not tested:** a real WebGPU device, the real model download, reply quality, speed, memory on a phone.

## Phone test (to do)

1. Chrome on Android (WebGPU), open `https://<preview>/?aura-local=1`, sign in, Wi-Fi.
2. Tap On-device. Note grade, battery, warnings. Tap Download; time it; note MB used.
3. Five turns developing an idea, including one correction ("actually, not X but Y"). Note tokens/s on the badges, whether the correction stuck, phone heat.
4. Ask "search for competitors": it should point to Hand to Aura, not answer.
5. Hand to Aura: edit the intent, check the cost line, Send. Aura's reply should show Aura or Paid model and continue from the intent.
6. Airplane mode: on-device chat still works once loaded; hand-off says offline and sends nothing.
7. iPhone Safari: record whether WebGPU is offered; if not, the panel must say so and send nothing.

## Sources checked (15 Nov 2026) and what they changed

Changed the code:
- **mlc-ai/web-llm-chat** (Apache-2.0, pins web-llm 0.2.82): per-reply speed from `usage.extra` via `stream_options.include_usage`, finish reason handling, keep the conversation locally. Adopted. Its Service Worker engine and full chat app were not adopted: Aura's own chat UI stays, and a dedicated worker per panel is simpler to cancel.
- **webllm.io** (MIT): device grading and memory estimate adapted (~60 lines), SDK not added.
- **web.dev, "AI chatbot with WebLLM"**: confirms the shape used here (worker, progress callback, Cache API storage, offline after download).
- **Koyeb hybrid WebLLM + Qwen3 tutorial**: local-or-cloud switch is a user toggle with the key on the server; same principle as the explicit hand-off. Its Qwen3 model is not used because WebLLM 0.2.87's smallest Qwen3 build is larger than Qwen2.5-0.5B.
- **WebLLM 0.2.88**: not adopted. The repo's pnpm `minimumReleaseAge` policy refused it as too new. 0.2.87 stays pinned; revisit when the policy allows.

Not applicable to this prototype (no browser-local path):
- **Fireworks** (hosted inference) and **Pulumi** (infrastructure as code): provider and infrastructure choices. Nothing adopted; no spend added.
- **ByteDance Seeduplex**: hosted full-duplex speech model in the Doubao app; no weights or code published on the page.
- **Block Dessa**: product page; no local LLM, weights or reusable code found on it.
- **arXiv 2608.01119, wrice full-duplex collection, NVIDIA PersonaPlex**: speech-to-speech models (PersonaPlex 7B, Moshi-based, PyTorch on a CUDA GPU; weights gated on Hugging Face). Audio-token models need a GPU server; a browser port would be a large conversion project, not a WebLLM model swap.
- **adventists-ai/sophon-realtime**: 32B model, 4-bit MLX, runs on Apple Silicon Macs with large unified memory; its browser page is only audio transport. Not usable on a phone or in a browser.
- **Qwen3-TTS** (Apache-2.0, 0.6B and 1.7B): text-to-speech only, PyTorch with FlashAttention 2 recommended on GPU, or vLLM-Omni. Claims first audio in 97 ms; the README doesn't state the hardware. Could replace the speech provider later on a GPU host; it does not solve listening, turn-taking or interruptions. No change made.
