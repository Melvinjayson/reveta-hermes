import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { $currentModel, $currentProvider } from '@/store/session'

import type * as LocalModel from './local-model'
import type { LocalTurn } from './local-model'
import { AuraLocalTalk } from './local-talk'

const engine = vi.hoisted(() => ({
  replies: [] as string[],
  calls: [] as LocalTurn[][],
  dispose: vi.fn(),
  cancel: vi.fn(),
  stop: vi.fn(),
  fail: null as Error | null,
  hold: null as null | ((value: unknown) => void),
  cached: false
}))

const device = { grade: 'B', vramMb: 2048, battery: { level: 0.8, charging: false }, online: true, warnings: [] as string[] }

const support = vi.hoisted(() => ({ value: null as unknown as Record<string, unknown> }))

vi.mock('./local-model', async importOriginal => ({
  ...(await importOriginal<typeof LocalModel>()),
  localTalkEnabled: () => true,
  probeLocalSupport: async () => support.value
}))

vi.mock('./local-engine', () => ({
  isLocalModelCached: async () => engine.cached,
  removeLocalModel: vi.fn(async () => {}),
  startLocalEngine: (_model: string, onProgress: (fraction: number, text: string) => void) => {
    onProgress(0.5, 'Fetching param cache[3/6]')

    const ready = new Promise((resolve, reject) => {
      if (engine.fail) {
        reject(engine.fail)

        return
      }

      const value = {
        chat: async (messages: LocalTurn[], onText: (text: string) => void) => {
          engine.calls.push(messages)
          const reply = engine.replies.shift() ?? 'ok'
          onText(reply)

          return { text: reply, finish: reply === '' ? 'abort' : 'stop', decodeTps: 12.34, prefillTps: 80 }
        },
        stop: engine.stop,
        dispose: engine.dispose
      }

      if (engine.hold === null) {
        resolve(value)
      } else {
        engine.hold = () => resolve(value)
      }
    })

    return { ready, cancel: engine.cancel }
  }
}))

const api = vi.fn()

beforeEach(() => {
  Object.assign(engine, { replies: [], calls: [], fail: null, hold: null, cached: false })
  localStorage.clear()
  engine.dispose.mockClear()
  engine.cancel.mockClear()
  support.value = { ok: true, modelId: 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC', device }
  $currentProvider.set('anthropic')
  $currentModel.set('claude-haiku-4-5')
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
  api.mockReset()
  api.mockResolvedValue({ paid_route: { provider: 'anthropic', model: 'claude-haiku-4-5', per_day_usd: 2, per_chat_usd: 0.5 }, spent_today_usd: 0.1 })
  window.hermesDesktop = { api } as unknown as typeof window.hermesDesktop
})

afterEach(() => vi.clearAllMocks())

async function openReady(onSubmit = vi.fn(async (_value: string) => true)) {
  render(<AuraLocalTalk busy={false} onSubmit={onSubmit} />)
  fireEvent.click(screen.getByRole('button', { name: 'On-device' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Download about 290 MB' }))
  await screen.findByLabelText('Message the on-device model')

  return onSubmit
}

async function say(text: string) {
  fireEvent.change(screen.getByLabelText('Message the on-device model'), { target: { value: text } })
  await act(async () => {
    fireEvent.submit(screen.getByLabelText('Message the on-device model').closest('form')!)
  })
}

it('downloads nothing until the user opts in, and an unsupported browser sends nothing anywhere', async () => {
  support.value = { ok: false, reason: 'This browser doesn’t offer WebGPU, so the on-device model can’t run here.', device: null }
  const onSubmit = vi.fn()
  render(<AuraLocalTalk busy={false} onSubmit={onSubmit} />)
  fireEvent.click(screen.getByRole('button', { name: 'On-device' }))

  expect((await screen.findByRole('alert')).textContent).toContain('Nothing was sent anywhere')
  expect(screen.queryByRole('button', { name: /Download/ })).toBeNull()
  expect(onSubmit).not.toHaveBeenCalled()
  expect(api).not.toHaveBeenCalled()
})

it('keeps a multi-turn conversation with corrections on the device', async () => {
  engine.replies = ['So an app for tailors. Who uses it?', 'Got it, shoemakers. What do they track today?']
  const onSubmit = await openReady()

  await say('An app for tailors')
  await say('Actually shoemakers, not tailors')

  expect(engine.calls[1].map(m => m.role)).toEqual(['system', 'user', 'assistant', 'user'])
  expect(engine.calls[1][3].content).toBe('Actually shoemakers, not tailors')
  expect(screen.getByText('Got it, shoemakers. What do they track today?')).toBeTruthy()
  expect(screen.getAllByText('On device · 12.3 tokens/s')).toHaveLength(2)
  expect(engine.calls[1].every(m => !('detail' in m))).toBe(true)
  expect(onSubmit).not.toHaveBeenCalled()
  expect(api).not.toHaveBeenCalled()
})

it('hands the history and an editable intent to Aura through the normal chat in one message', async () => {
  engine.replies = ['So shoemakers. What do they track?', 'I want an order tracker for shoemakers']
  const onSubmit = await openReady()

  await say('An app for shoemakers')
  fireEvent.click(screen.getByRole('button', { name: 'Hand to Aura' }))

  const intent = await screen.findByLabelText('What you want so far')
  expect((intent as HTMLTextAreaElement).value).toBe('I want an order tracker for shoemakers')
  expect(screen.getByText(/Goes to Anthropic claude-haiku-4-5: \$0.10 of \$2.00 used today, \$0.50 per chat./)).toBeTruthy()
  expect(screen.getByText('Paid model')).toBeTruthy()
  fireEvent.change(intent, { target: { value: 'I want an order tracker for shoemakers in Lagos' } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Send to Aura' }))
  })

  expect(onSubmit).toHaveBeenCalledTimes(1)
  const sent = onSubmit.mock.calls[0][0]
  expect(sent).toContain('What I want so far: I want an order tracker for shoemakers in Lagos')
  expect(sent).toContain('Me: An app for shoemakers\nOn-device model: So shoemakers. What do they track?')
  expect(engine.dispose).toHaveBeenCalled()
  expect(screen.queryByRole('region', { name: 'On-device conversation' })).toBeNull()
})

it('does not hand off when the daily cap is used up', async () => {
  api.mockResolvedValue({ paid_route: { provider: 'anthropic', model: 'claude-haiku-4-5', per_day_usd: 2, per_chat_usd: 0.5 }, spent_today_usd: 2.01 })
  const onSubmit = await openReady()

  await say('An app for shoemakers')
  fireEvent.click(screen.getByRole('button', { name: 'Hand to Aura' }))

  expect(await screen.findByText(/Today’s limit for Anthropic claude-haiku-4-5 is used up/)).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Send to Aura' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Send to Aura' }))
  expect(onSubmit).not.toHaveBeenCalled()
})

it('never runs or shows a tool call the on-device model writes', async () => {
  engine.replies = ['<tool_call>{"name": "send_email", "arguments": {"to": "x@y.z"}}</tool_call>']
  const onSubmit = await openReady()

  await say('What should my first customer get?')

  expect(screen.getByText(/tried to run a tool. It has none, so nothing ran/)).toBeTruthy()
  expect(screen.queryByText(/send_email/)).toBeNull()
  expect(onSubmit).not.toHaveBeenCalled()
})

it('sends tool and live-fact requests to the hand-off instead of letting the small model answer', async () => {
  await openReady()

  await say('can you search for competitors in Lagos')

  expect(engine.calls).toHaveLength(0)
  expect(screen.getByText(/needs Aura’s tools/)).toBeTruthy()
})

it('shows a download failure and sends nothing to Aura', async () => {
  engine.fail = new Error('Failed to fetch')
  const onSubmit = vi.fn()
  render(<AuraLocalTalk busy={false} onSubmit={onSubmit} />)
  fireEvent.click(screen.getByRole('button', { name: 'On-device' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Download about 290 MB' }))

  expect((await screen.findByRole('alert')).textContent).toContain('couldn’t start: Failed to fetch. Nothing was sent to Aura.')
  expect(onSubmit).not.toHaveBeenCalled()
})

it('cancels a download in progress and frees the engine when closed or unmounted', async () => {
  engine.hold = () => {}
  const view = render(<AuraLocalTalk busy={false} onSubmit={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'On-device' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Download about 290 MB' }))

  expect(screen.getByRole('status').textContent).toContain('Fetching param cache[3/6]')
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(engine.cancel).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Download about 290 MB' })).toBeTruthy()

  engine.hold = null
  fireEvent.click(screen.getByRole('button', { name: 'Download about 290 MB' }))
  await screen.findByLabelText('Message the on-device model')
  view.unmount()
  expect(engine.dispose).toHaveBeenCalledTimes(1)
})

it('shows grade, battery and warnings before download, and offline blocks a first download', async () => {
  support.value = { ...support.value, device: { ...device, grade: 'C', vramMb: 128, battery: { level: 0.1, charging: false }, online: false, warnings: ['Battery is at 10% and not charging. Running the model drains it quickly.'] } }
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
  render(<AuraLocalTalk busy={false} onSubmit={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'On-device' }))

  expect((await screen.findByLabelText('This device')).textContent).toBe('Device grade C (about 128 MB for graphics, estimated), battery 10%, offline.')
  expect(screen.getByText('Battery is at 10% and not charging. Running the model drains it quickly.')).toBeTruthy()
  expect(screen.getByRole('alert').textContent).toContain('You’re offline')
  expect((screen.getByRole('button', { name: 'Download about 290 MB' }) as HTMLButtonElement).disabled).toBe(true)
})

it('refuses to hand off while offline and sends nothing', async () => {
  const onSubmit = await openReady()

  await say('An app for shoemakers')
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
  fireEvent.click(screen.getByRole('button', { name: 'Hand to Aura' }))

  expect(await screen.findByText(/You’re offline, so Aura can’t be reached. Nothing was sent./)).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Send to Aura' }) as HTMLButtonElement).disabled).toBe(true)
  expect(api).not.toHaveBeenCalled()
  expect(onSubmit).not.toHaveBeenCalled()
})

it('keeps the on-device conversation across a reload and clears it on request', async () => {
  engine.replies = ['So shoemakers. Who pays?']
  const first = render(<AuraLocalTalk busy={false} onSubmit={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'On-device' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Download about 290 MB' }))
  await screen.findByLabelText('Message the on-device model')
  await say('An app for shoemakers')
  first.unmount()

  render(<AuraLocalTalk busy={false} onSubmit={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'On-device' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Download about 290 MB' }))
  await screen.findByLabelText('Message the on-device model')

  expect(screen.getByText('An app for shoemakers')).toBeTruthy()
  expect(screen.getByText('So shoemakers. Who pays?')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
  expect(screen.queryByText('An app for shoemakers')).toBeNull()
  expect(localStorage.getItem('aura.localTalk.turns.v1')).toBeNull()
})

it('says so when the on-device model returns nothing, instead of showing an empty bubble', async () => {
  engine.replies = ['   ']
  await openReady()

  await say('hmm')

  expect(screen.getByText(/gave an empty reply/)).toBeTruthy()
})

it('says when the model is already on the device', async () => {
  engine.cached = true
  render(<AuraLocalTalk busy={false} onSubmit={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'On-device' }))

  await waitFor(() => expect(screen.getByRole('button', { name: 'Load from this device' })).toBeTruthy())
  expect(screen.getByRole('button', { name: 'Remove download' })).toBeTruthy()
})
