import { act, fireEvent, render, screen } from '@testing-library/react'
import { atom } from 'nanostores'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import type { ChatMessage } from '@/lib/chat-messages'

import { AuraVoice, isEchoOfAura, TURN_SETTLE_MS } from './voice-call'

const messages = atom<ChatMessage[]>([])
const sockets: FakeSocket[] = []

vi.mock('@/app/chat/composer/scope', () => ({ useComposerScope: () => ({ $messages: messages }) }))
vi.mock('@/lib/sibling-ws-url', () => ({ resolveSiblingWsUrl: async () => 'ws://aura.test/api/audio/voice-call' }))
vi.mock('@/api/canonical-protocol', () => ({ openGatewaySocket: () => new FakeSocket() }))

class FakeSocket {
  static OPEN = 1
  readyState = 1
  binaryType = ''
  sent: string[] = []
  onmessage?: (event: { data: unknown }) => void
  onclose: null | (() => void) = null
  onopen?: () => void
  onerror?: () => void
  constructor() {
    sockets.push(this)
  }
  send(data: string) {
    this.sent.push(data)
  }
  close() {}
  emit(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) })
  }
}

const track = { enabled: true, stop: vi.fn() }
const speak = vi.fn()

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  sockets.length = 0
  messages.set([])
  track.enabled = true
  speak.mockClear()
  vi.stubGlobal('WebSocket', FakeSocket)
  vi.stubGlobal('AudioContext', class {
    sampleRate = 48000
    destination = {}
    currentTime = 0
    resume = async () => undefined
    close = async () => undefined
    createMediaStreamSource = () => ({ connect: vi.fn() })
    createScriptProcessor = () => ({ connect: vi.fn(), disconnect: vi.fn() })
  })
  vi.stubGlobal('navigator', {
    ...navigator,
    mediaDevices: { getUserMedia: async () => ({ getTracks: () => [track], getAudioTracks: () => [track] }) }
  })
  vi.stubGlobal('SpeechSynthesisUtterance', class {
    onend?: () => void
    onerror?: () => void
    constructor(public text: string) {}
  })
  vi.stubGlobal('speechSynthesis', { cancel: vi.fn(), speak })
  window.hermesDesktop = {
    api: async () => ({ available: true, reason: null, in_rate: 16000, out_rate: 24000 })
  } as unknown as typeof window.hermesDesktop
})

afterEach(() => {
  vi.useRealTimers()
})

async function startCall() {
  const onSubmit = vi.fn().mockResolvedValue(true)
  render(<AuraVoice busy={false} disabled={false} onInterrupt={vi.fn()} onSubmit={onSubmit} sessionId="s1" />)
  // The browser voice shows until the server says a live call can start.
  await vi.waitFor(() =>
    expect(screen.getByRole('button', { name: 'Start voice chat' }).getAttribute('aria-describedby')).toBe('aura-voice-hint')
  )
  const toggle = screen.getByRole('button', { name: 'Start voice chat' })
  expect(toggle.getAttribute('aria-pressed')).toBe('false')
  await act(async () => {
    fireEvent.click(toggle)
    await vi.waitFor(() => expect(sockets.length).toBe(1))
  })
  const ws = sockets.at(-1)!
  act(() => ws.emit({ type: 'ready', in_rate: 16000, out_rate: 24000 }))

  return { onSubmit, ws }
}

it('joins phrases split by short pauses into one turn before sending it', async () => {
  const { onSubmit, ws } = await startCall()
  expect(screen.getByRole('status').textContent).toBe('Listening')

  act(() => {
    ws.emit({ type: 'user_speaking' })
    ws.emit({ type: 'user_stopped' })
    ws.emit({ type: 'transcript', text: 'I want to plan' })
  })
  await act(() => vi.advanceTimersByTimeAsync(TURN_SETTLE_MS - 200))
  act(() => {
    ws.emit({ type: 'user_speaking' })
    ws.emit({ type: 'user_stopped' })
  })
  await act(() => vi.advanceTimersByTimeAsync(300))
  act(() => ws.emit({ type: 'transcript', text: 'a launch for next month' }))
  expect(onSubmit).not.toHaveBeenCalled()

  await act(() => vi.advanceTimersByTimeAsync(TURN_SETTLE_MS + 50))
  expect(onSubmit).toHaveBeenCalledTimes(1)
  expect(onSubmit).toHaveBeenCalledWith('I want to plan a launch for next month')
})

it('speaks on the device when server speech fails, and stops it only for real speech', async () => {
  const { ws } = await startCall()
  act(() => ws.emit({ type: 'speech_failed', text: 'Here is the answer.', message: 'quota' }))
  expect(speak).toHaveBeenCalledTimes(1)
  expect(speak.mock.calls[0][0].text).toBe('Here is the answer.')
  expect(screen.getByRole('status').textContent).toBe('Speaking')
  expect(screen.getByRole('alert').textContent).toContain('this device')
  const cancel = vi.mocked(window.speechSynthesis.cancel)
  const before = cancel.mock.calls.length // the turn-based fallback cancels once when it unmounts
  act(() => ws.emit({ type: 'user_speaking' }))
  expect(cancel.mock.calls.length).toBe(before) // could be its own echo
  act(() => ws.emit({ type: 'transcript', text: 'wait, actually change the plan' }))
  expect(cancel.mock.calls.length).toBe(before + 1)
})

it('never sends Aura its own spoken reply back as the user turn', async () => {
  const { onSubmit, ws } = await startCall()
  const reply = 'The deploy is live on Render. Want me to monitor the inspection and help analyse it?'
  act(() => messages.set([
    { id: 'u1', parts: [{ text: 'status?', type: 'text' }], role: 'user' },
    { id: 'a1', parts: [{ text: reply, type: 'text' }], role: 'assistant' }
  ] as ChatMessage[]))
  await vi.waitFor(() => expect(ws.sent.some(sent => sent.includes('"speak"'))).toBe(true))
  act(() => {
    ws.emit({ type: 'user_speaking' })
    ws.emit({ type: 'user_stopped' })
    ws.emit({ type: 'transcript', text: 'want me to monitor the inspection and help analyse it' })
  })
  await act(() => vi.advanceTimersByTimeAsync(TURN_SETTLE_MS + 100))
  expect(onSubmit).not.toHaveBeenCalled()
  act(() => ws.emit({ type: 'transcript', text: 'no, just tell me what broke' }))
  await act(() => vi.advanceTimersByTimeAsync(TURN_SETTLE_MS + 100))
  expect(onSubmit).toHaveBeenCalledWith('no, just tell me what broke')
})

it('starts speaking finished sentences while the reply is still streaming, without repeats', async () => {
  const { ws } = await startCall()
  const speaks = () => ws.sent.filter(sent => sent.includes('"speak"')).map(sent => JSON.parse(sent).text)

  const reply = (text: string, pending: boolean) =>
    act(() => messages.set([
      { id: 'u1', parts: [{ text: 'plan my week', type: 'text' }], role: 'user' },
      { id: 'a1', parts: [{ text, type: 'text' }], pending, role: 'assistant' }
    ] as ChatMessage[]))

  reply('Sure, here is a pl', true)
  expect(speaks()).toEqual([])
  reply('Sure, here is a plan. Monday is for', true)
  expect(speaks()).toEqual(['Sure, here is a plan.'])
  reply('Sure, here is a plan. Monday is for deep work. Tuesday', true)
  reply('Sure, here is a plan. Monday is for deep work. Tuesday is meetings.', false)
  expect(speaks()).toEqual(['Sure, here is a plan.', 'Monday is for deep work.', 'Tuesday is meetings.'])
  reply('Sure, here is a plan. Monday is for deep work. Tuesday is meetings.', false)
  expect(speaks()).toHaveLength(3)
})

it('does not keep speaking a streaming reply after you cut in', async () => {
  const { ws } = await startCall()
  const speaks = () => ws.sent.filter(sent => sent.includes('"speak"')).length

  const reply = (text: string) =>
    act(() => messages.set([
      { id: 'u1', parts: [{ text: 'go', type: 'text' }], role: 'user' },
      { id: 'a1', parts: [{ text, type: 'text' }], pending: true, role: 'assistant' }
    ] as ChatMessage[]))

  reply('First point. Second')
  expect(speaks()).toBe(1)
  act(() => ws.emit({ type: 'interrupt' }))
  reply('First point. Second point. Third point.')
  expect(speaks()).toBe(1)
})

it('echo check needs real overlap and lets short answers through', () => {
  const spoken = ['I can pre-route that for you. Shall I start?']
  expect(isEchoOfAura('I can pre route that for you', spoken)).toBe(true)
  expect(isEchoOfAura('yes start', spoken)).toBe(false)
  expect(isEchoOfAura('please route my calendar invites instead', spoken)).toBe(false)
})

it('mutes the microphone track and shows it, then ends the call cleanly', async () => {
  await startCall()
  fireEvent.click(screen.getByRole('button', { name: 'Mute microphone' }))
  expect(track.enabled).toBe(false)
  expect(screen.getByRole('status').textContent).toBe('Muted')
  expect(screen.getByRole('button', { name: 'Unmute microphone' }).getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(screen.getByRole('button', { name: 'End voice chat' }))
  expect(track.stop).toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Start voice chat' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Mute microphone' })).toBeNull()
})


it('releases queued server audio and detaches socket messages when the call ends', async () => {
  const audioStop = vi.fn()
  vi.stubGlobal('AudioContext', class {
    sampleRate = 48000
    destination = {}
    currentTime = 0
    resume = async () => undefined
    close = async () => undefined
    createMediaStreamSource = () => ({ connect: vi.fn() })
    createScriptProcessor = () => ({ connect: vi.fn(), disconnect: vi.fn() })
    createBuffer = () => ({ duration: 0.1, getChannelData: () => new Float32Array(2) })
    createBufferSource = () => ({ connect: vi.fn(), start: vi.fn(), stop: audioStop, onended: null })
  })
  const { ws } = await startCall()
  act(() => ws.onmessage?.({ data: new Int16Array([0, 100]).buffer }))
  fireEvent.click(screen.getByRole('button', { name: 'End voice chat' }))
  expect(audioStop).toHaveBeenCalledTimes(1)
  expect(ws.onmessage).toBeNull()
  expect(track.stop).toHaveBeenCalled()
})
