"""Explicit, cost-bound Anthropic calls; never part of provider recovery.

Reservations survive process restart. Unknown usage retains the full reservation.
Costs are derived from provider token usage and Hermes's bundled rate snapshot,
not represented as an invoice retrieved from Anthropic.
"""
from __future__ import annotations

from datetime import datetime, timezone, UTC
from decimal import Decimal
import hashlib
import json
import math
import sqlite3
import uuid

from tools.aura_dispatch_policy import _approve, _canonical, _config
from tools.aura_product import workspace
from hermes_constants import get_hermes_home


def spend_config():
    cfg = _config().get('aura', {}).get('anthropic', {})
    for key in ('per_chat_usd', 'per_day_usd'):
        value = cfg.get(key, 0)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise PermissionError('Anthropic is disabled: set positive per-chat and per-day USD caps')
    return cfg


def price(model):
    # Snapshot only: no metadata/pricing network request before user approval.
    from agent.usage_pricing import _lookup_official_docs_pricing, resolve_billing_route
    entry = _lookup_official_docs_pricing(resolve_billing_route(model, provider='anthropic'))
    if entry is None or entry.input_cost_per_million is None or entry.output_cost_per_million is None:
        raise PermissionError('Anthropic model has no bundled price; route stays disabled')
    return entry


def cost(entry, input_tokens, output_tokens):
    return (Decimal(input_tokens) * entry.input_cost_per_million
            + Decimal(output_tokens) * entry.output_cost_per_million) / 1_000_000


def ledger():
    db = sqlite3.connect(get_hermes_home() / 'aura-spend.db', timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS spend (id TEXT PRIMARY KEY, chat TEXT, day TEXT, model TEXT, reserved REAL, actual REAL, status TEXT)')
    return db


def reserve(cfg, model, amount):
    ident = uuid.uuid4().hex
    day = datetime.now(UTC).date().isoformat()
    chat = workspace().name
    with ledger() as db:
        db.execute('BEGIN IMMEDIATE')
        chat_total = db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM spend WHERE chat=?', (chat,)).fetchone()[0]
        day_total = db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM spend WHERE day=?', (day,)).fetchone()[0]
        if chat_total + float(amount) > cfg['per_chat_usd'] or day_total + float(amount) > cfg['per_day_usd']:
            raise PermissionError('Estimated cost would exceed the chat or daily cap')
        db.execute('INSERT INTO spend VALUES (?,?,?,?,?,NULL,?)', (ident, chat, day, model, float(amount), 'reserved'))
    return ident


def settle(ident, actual, status):
    with ledger() as db:
        db.execute('UPDATE spend SET actual=?, status=? WHERE id=?', (None if actual is None else float(actual), status, ident))


def complex_workflow(args):
    from agent.secret_scope import get_secret
    cfg = spend_config()
    key = get_secret('ANTHROPIC_API_KEY')
    if not key:
        raise PermissionError('Anthropic is disabled: ANTHROPIC_API_KEY is missing')
    task = args['task']
    maximum = args.get('max_output_tokens', 2048)
    if not isinstance(task, str) or len(task.encode()) > 12000 or type(maximum) is not int or not 1 <= maximum <= 4096:
        raise ValueError('Task must fit 12 KB and output must be 1–4096 tokens')
    model = cfg.get('model', '')
    entry = price(model)
    # One token per UTF-8 byte + protocol overhead conservatively bounds input;
    # no thinking, caching, tools or automatic retries on this opt-in subrequest.
    estimated = cost(entry, len(task.encode()) + 1024, maximum)
    ident = reserve(cfg, model, estimated)
    bound = {**args, 'provider': 'anthropic', 'model': model, 'estimated_usd': str(estimated), 'caps': cfg}
    digest = hashlib.sha256((str(get_hermes_home().resolve()) + _canonical(bound)).encode()).hexdigest()
    description = (f'Opt-in Anthropic · {model}. Estimated maximum ${estimated:.6f}. '
                   f'Chat cap ${cfg["per_chat_usd"]}; daily cap ${cfg["per_day_usd"]}. '
                   'Approve once buys only this request; Change spends nothing. Cost uses bundled token rates.')
    try:
        approved = _approve('Anthropic complex workflow', bound, digest, description=description)
        if not approved or spend_config() != cfg:
            settle(ident, 0, 'declined')
            return json.dumps({'status': 'refused', 'error': 'Anthropic request was not approved or its caps changed'})
        from agent.anthropic_adapter import build_anthropic_client
        with build_anthropic_client(key, base_url='https://api.anthropic.com', timeout=90).with_options(max_retries=0) as client:
            result = client.messages.create(model=model, max_tokens=maximum,
                                            messages=[{'role': 'user', 'content': task}])
        usage = result.usage
        actual = cost(entry, usage.input_tokens, usage.output_tokens)
        settle(ident, actual, 'completed')
        return json.dumps({'success': True, 'provider': 'anthropic', 'model': model,
                           'text': '\n'.join(block.text for block in result.content if block.type == 'text'),
                           'cost_usd': str(actual), 'cost_basis': 'actual provider token usage × bundled rate snapshot',
                           'input_tokens': usage.input_tokens, 'output_tokens': usage.output_tokens})
    except Exception:
        # A transport error may occur after billing; retain the reservation.
        settle(ident, None, 'usage_unknown')
        raise
