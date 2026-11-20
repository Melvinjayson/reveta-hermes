# Aura model routing (20 Nov 2026)

Branch `aura/model-routing`, from `aura/working-product-20261111` at `f8fda1d3`. No real model was called and no
paid request was sent; every check below uses fixtures or `tests/fakes/fake_llm_provider.py`.

## What ships, and what stays off

| Piece | State |
|---|---|
| `tools/aura_model_routing.py`: tiers, deterministic `choose` / `fallback`, per-request `guard` | Built, tested |
| Paid tiers (Routine, Fallback, Reasoning) | **Configured, refused.** No budget authorizer exists (see Blockers) |
| Free test route (Nemotron 3 Ultra `:free`) | Built, **off by default**; needs `AURA_TEST_MODEL_ROUTE=1`, `OPENROUTER_API_KEY` and a non-production address |
| Settings → Model: routing rows, "Use the test model" | Built; paid tiers are plain rows, never choices |
| Refused step names the routing reason | Built (allow-listed sentences only) |
| Model per step in step history | **Not built:** needs an event-schema change (see Blockers) |
| `scripts/reveta/openrouter_catalog.py` + `tests/fixtures/aura/openrouter_candidates.json` | Built; snapshot from 20 Nov 2026 |

### How a request is decided

Every provider request already passes `tools.aura_free_only.require_model`: main turns, streaming, retries,
auto-recovery cycles and auxiliary calls (`agent/chat_completion_helpers.py:766/2941/3979`,
`agent/auxiliary_client.py` via `guarded_aux_callback`). `guard` now runs first there, **even with
`aura.free_only: false`**, which is how production runs today. So no request can reach a routed model without it.

* A paid tier model → refused with "Paid models stay off until Aura's budget authorization is in place." A
  `FreeOnlyRefused` is final in Hermes (`agent/turn_api_error.py:82`): no retry, no recovery ladder, no fallback,
  no tool runs.
* The test model while the route is off → refused with "The experimental test model is switched off on this
  deployment."
* The test model while it is on → sent only to `https://openrouter.ai/api/v1`, with
  `provider.max_price = 0/0` and `allow_fallbacks: false`; with the free-only rule on, it must also match the
  `free_models` allowlist entry that `aura_config.py` writes.
* Anything else → the existing gates decide (free Gemini default, the owner's capped paid route), unchanged.

`choose` / `fallback` hold the policy for when a budget authorizer exists. There is no router LLM call; nothing
escalates to Reasoning by itself (not long messages, not multi-step work, never a live voice call). Fallback only
goes from paid Routine to the configured Fallback, for `overloaded` / `server_error` / `timeout`, at most once,
never after a committed action, and through the budget gate again. A budget refusal is never retried or rerouted.
Free never falls back to paid.

## Verification (OpenRouter catalog, retrieved 20 Nov 2026 ~17:00 UTC)

This host's proxy blocks `openrouter.ai`, so the public `GET /api/v1/models/<id>/endpoints` responses were fetched
through Firecrawl and saved. `openrouter_catalog.py --from-raw` rebuilt the snapshot from them. Run without
`--from-raw` on a host that can reach openrouter.ai to refresh it.

| Claim | Source | Verified? | Impact |
|---|---|---|---|
| `deepseek/deepseek-v4.1-flash-1017` exists | OpenRouter catalog | **Yes**, 51 endpoints | Configuration |
| `z-ai/glm-5.3-flash` exists | OpenRouter catalog | **Yes**, 42 endpoints | Configuration |
| `moonshotai/kimi-k3.1-pro` exists | OpenRouter catalog | **Yes**, 28 endpoints | Configuration |
| `nvidia/nemotron-3-ultra-550b-a55b:free` exists | OpenRouter catalog | **Yes**, 1 endpoint (Nvidia) | Configuration |
| Pricing | OpenRouter catalog | **Yes, as ranges**: price depends on the serving endpoint | Budget |
| Tool calling | Catalog `supported_parameters` | **Yes**: every endpoint of all four lists `tools` | Hermes |
| Structured outputs | Catalog | **Partial**: 46/51, 39/42, 25/28 endpoints; Nemotron none | Not relied on |
| Context | Catalog | DeepSeek 1.0–1.05M; GLM 262k–1.05M; Kimi 1.05M; Nemotron 1M (max 65,536 out) | Configuration |
| DeepSeek V4.1 Flash 1017 licence | HF model card | MIT (weights) | Commercial use |
| GLM-5.3-Flash licence | HF `LICENSE` | MIT (weights) | Commercial use |
| Kimi K3.1 Pro licence | HF model card | Custom "Kimi K3.1 Pro License". A secondary source mentions a Model-as-a-Service clause; **the primary text was not read in full** | **Escalate** before commercial use |
| Nemotron 3 Ultra licence | HF model card, build.nvidia.com | OpenMDW-1.1 (weights). NVIDIA's hosted trial is under the NVIDIA API Trial Terms of Service | Test-only |
| Free-route limits | OpenRouter docs (limits, FAQ) | **Yes**: 20 req/min; 50 req/day, or 1,000/day after $10 of purchased credits | Test-only |
| Free-route data use / production terms | OpenRouter + NVIDIA trial terms | **Not verified**: the endpoint record carries no data policy; the trial ToS PDF was not read | Synthetic prompts only; blocked on the production address |

Price per million tokens, USD (min–max across endpoints), from the snapshot:

| Tier | Model | Input | Output |
|---|---|---|---|
| Routine | DeepSeek V4.1 Flash 1017 | 0.03 – 0.60 | 0.2352 – 2.40 |
| Fallback | GLM 5.3 Flash | 0.0399 – 0.225 | 0.0784 – 0.75 |
| Reasoning | Kimi K3.1 Pro | 0.2403 – 4.40 | 6 – 22 |
| Test | Nemotron 3 Ultra `:free` | 0 | 0 |

Provider choice changes the price 10–20×, and some endpoints are `flex`/`priority` service tiers. A budget must
therefore reconcile on the cost OpenRouter reports for the request, not on any catalog price. Nothing here bills.
Publisher benchmarks were not compared.

## Is quota the failure? Measured with the fake provider

Prompt: "Reply with AURA READY and tell me what two plus two equals." Real webapp, real gateway, fake provider.

| Provider behaviour | Provider calls for one user message | What the user saw |
|---|---|---|
| Healthy | **2** (1 main turn + 1 auxiliary title call) | Reply |
| 429 quota, `Retry-After: 1` | **1** | "custom is busy right now … rate limit. It resets at …" + Retry |
| 429 quota, no `Retry-After` | **1** | Same, "Wait a moment, then retry" |
| 503 overloaded | **6 within 2 min, still retrying** ("cycle 4/5") | A countdown, no answer for minutes |

So the simple prompt is not an agent-loop problem: it costs 2 calls. A quota 429 stops at once. The multiplier is
Hermes's documented recovery for **transient** errors: `agent.api_max_retries` (3) per attempt, then
`agent.auto_recovery_cycles` (5) with 15/30/60/60/60 s waits (`agent/turn_recovery_autorecover.py`). One provider
outage can mean 20+ calls and 4–5 minutes before an answer or an error. On a free tier counted per request, those
retries spend the allowance, and the later 429s are what users see. Tool tasks add one main call per tool step
(each tool result goes back to the model); multi-step tasks were not measured here.

Existing per-session accounting: `sessions.api_call_count` and per-model token usage (`hermes_state_runtime.py`).
No new telemetry was added; prompts are not stored.

## Recommendations (not applied: they change agent behaviour)

1. Set `agent.auto_recovery_cycles: 1` and `agent.api_max_retries: 1` in Aura's generated config. Estimated, not
   measured: a transient outage then costs about 4 calls and well under a minute before Aura says the model is
   unavailable.
2. Skip the auxiliary title call on the free tier (`auxiliary.title_generation`), or derive the title from the
   first message. That halves calls for one-message chats.
3. Count requests, not messages, in the readiness probe: the free Gemini allowance is per request.

## Blockers (stop conditions met)

1. **Resolved in `aura/configurable-model-budget`** (`docs/aura/model-budget.md`): the budget now exists and the
   guard reserves through it. Original finding: **No budget authorizer.** The €3 workstream is not in this repository: no branch, no open PR. The existing
   `tools/aura_provider.py` paid route (OpenAI and Anthropic only) checks caps *before* a call and records *after*
   ("one call can overshoot a cap by its own cost"). It has no reserve-then-reconcile step for multi-step agent
   runs and no OpenRouter provider. It cannot authorize these tiers safely; that is a **release blocker** for paid
   routing. Contract needed: `authorize(route) -> reservation` before each request (including retries, recovery
   cycles, fallbacks and auxiliary calls), `reconcile(reservation, actual_cost_usd)` from OpenRouter's reported
   usage cost, and release on refusal. `tools.aura_model_routing.budget_authorizer()` is the single place it
   plugs in.
2. **Step history cannot show the model per inference yet.** Steps are built from tool parts
   (`apps/desktop/src/app/aura/steps.ts`), and the UI knows only the session's current model. Needed: the
   gateway's per-call usage event carries `{tier, model, fallback_of, outcome, latency_ms}` and the message stream
   forwards it. That is a schema change, so it is not made here.
3. **Production runs `aura.free_only: false`** (owner decision, 15 Nov 2026), not the free-only rule the brief
   assumed. The routing guard does not depend on it.
4. **Kimi licence MaaS clause** and **NVIDIA trial terms** need reading before any customer use.

## Voice and conversation

Routing is per request, at the guard, so it does not touch conversation identity, project context, approvals,
transcripts or voice sessions. `choose(voice=True)` never changes tier. Pipecat, speech recognition and synthesis
are unchanged. Future: a voice call pins one route for its whole duration and shows it in the call header.
