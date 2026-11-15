import { act, fireEvent, render, screen } from '@testing-library/react'
import { atom } from 'nanostores'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import type { ChatMessage } from '@/lib/chat-messages'

import { AuraVoice, TURN_SETTLE_MS } from './voice-call'

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
    expect(screen.getByRole('button', { name: 'Start voice' }).getAttribute('aria-describedby')).toBe('aura-voice-hint')
  )
  const toggle = screen.getByRole('button', { name: 'Start voice' })
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

it('speaks on the device when server speech fails, and stops it when you cut in', async () => {
  const { ws } = await startCall()
  act(() => ws.emit({ type: 'speech_failed', text: 'Here is the answer.', message: 'quota' }))
  expect(speak).toHaveBeenCalledTimes(1)
  expect(speak.mock.calls[0][0].text).toBe('Here is the answer.')
  expect(screen.getByRole('status').textContent).toBe('Speaking')
  expect(screen.getByRole('alert').textContent).toContain('this device')
  act(() => ws.emit({ type: 'user_speaking' }))
  expect(window.speechSynthesis.cancel).toHaveBeenCalled()
  expect(screen.getByRole('status').textContent).toBe('Hearing you')
})

it('mutes the microphone track and shows it, then ends the call cleanly', async () => {
  await startCall()
  fireEvent.click(screen.getByRole('button', { name: 'Mute microphone' }))
  expect(track.enabled).toBe(false)
  expect(screen.getByRole('status').textContent).toBe('Muted')
  expect(screen.getByRole('button', { name: 'Unmute microphone' }).getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(screen.getByRole('button', { name: 'End voice' }))
  expect(track.stop).toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Start voice' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Mute microphone' })).toBeNull()
})
