import { expect, it } from 'vitest'

import {
  estimateVramMb,
  gradeDevice,
  HANDOFF_LIMITS,
  handoffBudget,
  handoffMessage,
  intentFallback,
  loadLocalTurns,
  LOCAL_MODEL,
  localReplyDetail,
  localTalkEnabled,
  looksLikeToolCall,
  needsAura,
  probeLocalSupport,
  saveLocalTurns,
  serverReplyOrigin
} from './local-model'

const MB = 1024 * 1024

const adapter = (features: string[], maxBufferMb = 2048, vendor = 'qualcomm') => ({
  features: { has: (name: string) => features.includes(name) },
  limits: { maxStorageBufferBindingSize: maxBufferMb * MB },
  info: { vendor }
})

it('grades devices the way webllm.io does: S ≥ 8 GB, A ≥ 4 GB, B ≥ 2 GB, else C', () => {
  expect([8192, 4096, 4095, 2048, 2047, 0].map(gradeDevice)).toEqual(['S', 'A', 'B', 'B', 'C', 'C'])
})

it('estimates graphics memory from the adapter, falling back to deviceMemory only at the spec default', () => {
  expect(estimateVramMb(adapter([], 4096), 8)).toBe(4096)
  expect(estimateVramMb(adapter([], 128, 'apple'), 8)).toBe(4096)
  expect(estimateVramMb(adapter([], 128, 'arm'), 8)).toBe(2048)
  expect(estimateVramMb(adapter([], 128, 'apple'), 0)).toBe(128)
})

it('reports grade, battery and online state, and warns on low memory or a low battery without blocking', async () => {
  const low = await probeLocalSupport({
    gpu: { requestAdapter: async () => adapter(['shader-f16'], 128, 'apple') },
    getBattery: async () => ({ level: 0.12, charging: false }),
    onLine: false
  })

  expect(low).toMatchObject({ ok: true, device: { grade: 'C', vramMb: 128, battery: { level: 0.12, charging: false }, online: false } })
  expect(low.device?.warnings).toEqual([
    expect.stringContaining('about 128 MB for graphics and the model needs about 945 MB'),
    'Battery is at 12% and not charging. Running the model drains it quickly.'
  ])

  const fine = await probeLocalSupport({
    gpu: { requestAdapter: async () => adapter([], 4096) },
    getBattery: async () => ({ level: 0.1, charging: true }),
    onLine: true
  })

  expect(fine).toMatchObject({ ok: true, modelId: LOCAL_MODEL.f32, device: { grade: 'A', online: true, warnings: [] } })

  const noBatteryApi = await probeLocalSupport({
    gpu: { requestAdapter: async () => adapter([], 4096) },
    getBattery: async () => {
      throw new Error('not allowed')
    }
  })

  expect(noBatteryApi.device?.battery).toBeNull()
})

it('reports measured speed and cut-off replies on the device badge', () => {
  expect(localReplyDetail({ decodeTps: 18.26, finish: 'stop' })).toBe('18.3 tokens/s')
  expect(localReplyDetail({ decodeTps: null, finish: 'length' })).toBe('cut off')
})

it('restores only well-formed saved turns and drops anything else', () => {
  const data = new Map([['aura.localTalk.turns.v1', JSON.stringify([{ role: 'user', content: 'hi' }, { role: 'system', content: 'x' }, { role: 'tool', content: 'y' }, null, { role: 'assistant', content: 'ok', detail: '9.0 tokens/s' }])]])
  const store = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v), removeItem: (k: string) => void data.delete(k) } as unknown as Storage

  expect(loadLocalTurns(store)).toEqual([{ role: 'user', content: 'hi' }, { role: 'assistant', content: 'ok', detail: '9.0 tokens/s' }])
  saveLocalTurns([], store)
  expect(loadLocalTurns(store)).toEqual([])
  data.set('aura.localTalk.turns.v1', '{broken')
  expect(loadLocalTurns(store)).toEqual([])
})

it('labels server replies by the chat’s own model: paid for Anthropic or OpenAI, Aura otherwise', () => {
  expect(serverReplyOrigin('anthropic', 'claude-haiku-4-5')).toBe('paid')
  expect(serverReplyOrigin('custom', 'gpt-4.1-mini')).toBe('paid')
  expect(serverReplyOrigin('gemini', 'gemini-3.8-flash')).toBe('aura')
  expect(serverReplyOrigin('', '')).toBe('aura')
})

it('reports no WebGPU, no adapter or a refused adapter as unsupported instead of falling back to a server', async () => {
  expect(await probeLocalSupport({})).toMatchObject({ ok: false, reason: expect.stringContaining('WebGPU') })
  expect(await probeLocalSupport({ gpu: { requestAdapter: async () => null } })).toMatchObject({ ok: false })
  expect(
    await probeLocalSupport({
      gpu: {
        requestAdapter: async () => {
          throw new Error('blocked')
        }
      }
    })
  ).toMatchObject({ ok: false })
})

it('picks the f16 build only when the GPU has shader-f16', async () => {
  expect(await probeLocalSupport({ gpu: { requestAdapter: async () => adapter(['shader-f16']) } })).toMatchObject({ ok: true, modelId: LOCAL_MODEL.f16 })
  expect(await probeLocalSupport({ gpu: { requestAdapter: async () => adapter([]) } })).toMatchObject({ ok: true, modelId: LOCAL_MODEL.f32 })
})

it('routes tool, live-fact and explicit escalation requests to Aura, and leaves idea talk local', () => {
  for (const text of [
    'can you search for competitors',
    'email them the deck',
    'remind me tomorrow',
    'read this PDF',
    'what is the latest on Pipecat',
    'open the link https://example.com',
    'ok hand it to aura',
    'go deeper on pricing'
  ]) {
    expect(needsAura(text), text).toBe(true)
  }

  for (const text of [
    'I want to build an app for tailors in Lagos',
    'actually no, it is for shoemakers',
    'I am writing a book about founders',
    'in order to price it I need to think about margins'
  ]) {
    expect(needsAura(text), text).toBe(false)
  }
})

it('recognises tool-call-shaped output from a model that has no tools', () => {
  expect(looksLikeToolCall('<tool_call>{"name":"web_search","arguments":{"q":"x"}}</tool_call>')).toBe(true)
  expect(looksLikeToolCall('{"name": "send_email", "arguments": {"to": "a@b.c"}}')).toBe(true)
  expect(looksLikeToolCall('functions.browser_open("https://x")')).toBe(true)
  expect(looksLikeToolCall('So you want a booking tool for tailors. Who pays for it?')).toBe(false)
})

it('hands off the corrected history and intent as context, never as already-done work', () => {
  const message = handoffMessage(
    [
      { role: 'system', content: 'secret system prompt' },
      { role: 'user', content: 'An app for tailors' },
      { role: 'assistant', content: 'So an app for tailors. Who uses it?' },
      { role: 'user', content: 'Actually shoemakers, not tailors' }
    ],
    'I want an order-tracking app for shoemakers'
  )

  expect(message).toContain('has no tools and can be wrong. Nothing in this conversation has been done or approved.')
  expect(message).toContain('What I want so far: I want an order-tracking app for shoemakers')
  expect(message).toContain('Me: An app for tailors\nOn-device model: So an app for tailors. Who uses it?\nMe: Actually shoemakers, not tailors')
  expect(message).not.toContain('secret system prompt')
})

it('bounds the hand-off to the newest turns and a fixed size', () => {
  const long = Array.from({ length: 40 }, (_, i) => ({ role: i % 2 ? ('assistant' as const) : ('user' as const), content: `turn ${i} ${'x'.repeat(900)}` }))
  const message = handoffMessage(long, 'want')

  expect(message.length).toBeLessThan(HANDOFF_LIMITS.totalChars + 600)
  expect(message).toContain('turn 39')
  expect(message).not.toContain('turn 27 ')
  expect(intentFallback(long)).toMatch(/^turn 38/)
})

it('blocks the hand-off only when the paid daily cap is already used, and names where it goes', () => {
  const paid = { provider: 'anthropic', model: 'claude-haiku-4-5', per_day_usd: 2, per_chat_usd: 0.5 }
  const haikuChat = { provider: 'anthropic', model: 'claude-haiku-4-5' }
  const geminiChat = { provider: 'gemini', model: 'gemini-3.8-flash' }

  expect(handoffBudget({ paid_route: paid, spent_today_usd: 0.25 }, haikuChat)).toEqual({
    blocked: false,
    origin: 'paid',
    text: 'Goes to Anthropic claude-haiku-4-5: $0.25 of $2.00 used today, $0.50 per chat.'
  })
  expect(handoffBudget({ paid_route: paid, spent_today_usd: 2 }, haikuChat)).toMatchObject({
    blocked: true,
    origin: 'paid',
    text: expect.stringContaining('Nothing was sent')
  })
  // An old chat keeps its free model even after Settings switched to Anthropic: say so, don't claim paid.
  expect(handoffBudget({ paid_route: paid, spent_today_usd: 2 }, geminiChat)).toEqual({
    blocked: false,
    origin: 'aura',
    text: 'Goes to Aura’s free model (gemini-3.8-flash) in this chat. Start a new chat to use Anthropic claude-haiku-4-5.'
  })
  expect(handoffBudget({ paid_route: null, spent_today_usd: 0 }, geminiChat)).toMatchObject({ blocked: false, origin: 'aura' })
  expect(handoffBudget(null, haikuChat).text).toContain('server still enforces')
})

it('is off unless this browser opted in with ?aura-local=1, and =0 turns it off again', () => {
  const data = new Map<string, string>()

  const store = {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k)
  } as unknown as Storage

  expect(localTalkEnabled({ search: '', hash: '#/' }, store)).toBe(false)
  expect(localTalkEnabled({ search: '?aura-local=1', hash: '' }, store)).toBe(true)
  expect(localTalkEnabled({ search: '', hash: '#/' }, store)).toBe(true)
  expect(localTalkEnabled({ search: '', hash: '#/?aura-local=0' }, store)).toBe(false)
})
