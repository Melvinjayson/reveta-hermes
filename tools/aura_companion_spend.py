"""The browser companion's planning call on the owner's capped paid route.

Used only while ``aura.free_only`` is ``false`` (the owner's 15 Nov decision; Melvin approved this
use on 19 Nov). It runs only when all hold:

* the caller is the owner or a listed admin (``tools.aura_owner.is_owner``); testers and everyone
  else are refused, as before;
* Aura Settings has a paid route with its caps (``tools.aura_provider.route``) and that provider's
  key is stored;
* today's spend is under the route's daily cap (``tools.aura_provider.check``), the same cap chat
  and voice calls count against.

Each call is charged to the same ledger at the bundled price snapshot. When the provider reports no
usage, the call is charged as if it used ``max_tokens`` and about one token per two characters of
input, so a missing usage report never makes a call free. Same shortcut as chat: the check reads
spend recorded after each call, so one call can overshoot the cap by its own cost.
"""
from __future__ import annotations

import os
from typing import Any

REFUSED = "The companion's model call isn't available for this account."
LEDGER_CHAT = "companion"


def _first_positive(usage: Any, *names: str) -> int:
    for name in names:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if type(value) is int and value > 0:
            return value
    return 0


def _tokens(resp: Any, messages: list[dict], max_tokens: int) -> dict:
    usage = getattr(resp, "usage", None)
    input_tokens = _first_positive(usage, "prompt_tokens", "input_tokens") if usage is not None else 0
    output_tokens = _first_positive(usage, "completion_tokens", "output_tokens") if usage is not None else 0
    if not input_tokens or not output_tokens:
        chars = sum(len(str(m.get("content") or "")) for m in messages)
        input_tokens = input_tokens or (chars // 2 + 1)
        output_tokens = output_tokens or max_tokens
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


def paid_planning(messages: list[dict], max_tokens: int, who: dict) -> str:
    from hermes_cli.config import load_env
    from tools.aura_owner import is_owner
    from tools.aura_provider import PROVIDERS, charge, check, route, usd_for

    if not is_owner(str(who.get("sub") or ""), str(who.get("email") or "")):
        raise PermissionError(REFUSED)
    paid = route()
    if paid is None:
        raise PermissionError("Set a paid model and its spending limits in Aura Settings first.")
    spec = PROVIDERS[paid["provider"]]
    if not ((load_env().get(spec["env"]) or os.environ.get(spec["env"]) or "").strip()):
        raise PermissionError(f"Add your {spec['label']} API key in Aura Settings first.")
    check(paid)

    from agent.auxiliary_client import call_llm

    resp = call_llm(task="aura_companion", provider=paid["provider"], model=paid["model"],
                    base_url=spec["base_url"], messages=messages, temperature=0.2, max_tokens=max_tokens,
                    timeout=60)
    charge(LEDGER_CHAT, paid["provider"], paid["model"], usd_for(paid, **_tokens(resp, messages, max_tokens)))
    return resp.choices[0].message.content or ""
