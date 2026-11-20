# Aura spending budget (20 Nov 2026)

Branch `aura/configurable-model-budget`, stacked on `aura/model-routing` (PR #37). Mocked providers only: no paid
or real model call was made.

## What the owner gets (Settings → Model → Spending budget)

- **Budget limit (USD)**: initially $3, editable from $0 to $1,000. It is not a fixed cap; the server validates
  every change and rejects negative, non-finite and over-$1,000 values.
- **Allow paid models**: a switch, **off by default**. Off means no paid request is sent, whatever the limit.
- **Figures**: spent, reserved now (requests in flight), remaining, percent used; state Active / Approaching
  limit (≥ 80 %) / Reached; last-updated time.
- **Spending by model** and **recent requests**: model, status (In progress, Settled, Cost not reported · full
  estimate counted, Not charged) and amount.
- The note that the budget does not buy provider credit.
- Owner only: `GET`/`PUT /api/aura/budget` use the same owner check as the preview switches; others get 403.
- A refused request shows its reason in the chat's step list (budget reached, paid models off, budget
  unavailable, routing off).

## Architecture

```
router (tools/aura_model_routing.py)     which model may serve this request?
        │ guard() at require_model — every provider request, free_only on or off
        ▼
paid boundary (tools/aura_paid_requests.py)   bound → reserve → settle
        │ authorize_or_reserve / reconcile / release_reservation
        ▼
budget (tools/aura_budget.py)            may Aura pay for it?  one SQLite ledger per profile
```

- **Bound.** Before reserving, the request is capped. `max_tokens` (or `max_completion_tokens`) is limited to the
  tier's `max_output_tokens`. For OpenRouter, `provider.max_price` is set to the tier's price ceiling, so
  OpenRouter fails the request rather than use a dearer endpoint (OpenRouter docs: provider-selection,
  max_price). Input is bounded by the UTF-8 byte length of messages and tools plus 1,024 tokens. The
  reservation, input bound × prompt ceiling + output cap × completion ceiling, is therefore an upper bound on
  the request's cost.
- **Reserve.** `authorize_or_reserve` checks the switch, then `spent + reserved + estimate ≤ limit`, then inserts
  the reservation. All of this happens in one `BEGIN IMMEDIATE` transaction, which serializes concurrent
  requests across threads and processes. A refusal raises before any client is built.
- **Settle.**
  - After a main-agent response (`agent/turn_usage.py`), the reservation is replaced by OpenRouter's reported
    `usage.cost` (the request asks for `usage: {include: true}`). For the legacy OpenAI/Anthropic route, it is
    replaced by the bundled-rate estimate that route already computes.
  - With no reported cost, the whole reservation counts as spent.
  - On a failure (`agent/turn_api_error.py`), it is released only for an HTTP 4xx refusal (nothing processed).
    A 5xx, timeout or cancellation keeps it.
  - A reservation still open when the agent's next request starts is closed at its full amount.
  - Auxiliary calls (title generation, compression) are reserved and settled in `guarded_aux_callback`,
    including async callbacks.
- **What counts as spent:** reconciled actual costs + cost-unknown reservations. **Remaining** = limit − spent −
  open reservations. Lowering the limit below spent leaves history intact and refuses every new paid request.
- **Fail closed.** Any store error raises `BudgetRefused('unavailable')`, and the request is refused.
- **Ledger** (`$HERMES_HOME/aura-budget.db`): request id, session id, model, tier, reserved, actual, status,
  cost basis, times. Budget changes keep time, actor, previous and new limit, and previous and new switch. No
  prompts, keys or content are stored.
- **Profiles.** The store lives under the profile's `HERMES_HOME`, so each profile has its own budget.

### Every paid path goes through it

| Path | Where it reserves | Where it settles |
|---|---|---|
| Routine / Fallback / Reasoning (OpenRouter) | `aura_model_routing.guard` → `aura_paid_requests.reserve` | `turn_usage` (reported cost), `turn_api_error`, next request |
| Retries and auto-recovery cycles | each attempt calls `require_model` again, so it reserves again | same |
| Auxiliary calls on a paid model (titles) | `guarded_aux_callback` | same wrapper, after the result |
| Owner route (OpenAI / Anthropic, `aura.paid_route`) | `aura_free_only._legacy_paid_reservation` | `turn_usage` (bundled-rate estimate) |
| `aura_complex` Anthropic tool | `aura_spend.complex_workflow` | same function |

Free requests (Gemini default, the free test route) never touch the budget. Free never falls back to paid:
the router allows fallback only from the paid Routine tier, and `fallback_model` stays empty.

## Behaviour changes to note before release

1. **Paid models are off by default.** If production uses the owner route today, its replies show "Paid models
   are switched off in Settings → Model" until the owner switches them on. The total budget then also applies,
   on top of the route's per-day and per-chat caps.
2. **The owner route's output is capped at 4,096 tokens** when the request has no lower limit, so its cost has a
   ceiling.
3. **Paid routing stays off** (`aura.model_routing.enabled: false` in the generated config). Switching it on is
   a separate step once live behaviour is verified.

## Integration with PR #37

This branch contains #37's commit and changes three of its contracts:

- `guard` takes `chat`, and its paid branch reserves through the budget (`_paid_request`). #37's placeholder
  refusal ("budget authorization not in place") is gone.
- `budget_authorizer()` returns a planning check over `get_budget_status`. It is not a second authority: every
  request still reserves.
- `REASONS` gains `routing_off`; tiers gain `price_ceiling` and `max_output_tokens` (`scripts/reveta/aura_config.py`).

Merge #37 first, or merge this PR in its place; it contains #37's commit unchanged.

## Not verified here

- OpenRouter's `usage.cost` field on a real response. The parser accepts it as an attribute or in
  `model_extra`; if it is absent, the whole reservation counts, which is safe but pessimistic.
- That every OpenRouter endpoint counts reasoning tokens inside `max_tokens`. If one does not, the bound is
  exceeded by those tokens. Verify on the first live paid call before switching routing on.
- Real concurrency across gateway processes. The thread test uses separate SQLite connections; separate
  processes share the same file lock.
