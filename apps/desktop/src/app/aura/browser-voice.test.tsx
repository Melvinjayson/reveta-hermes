import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { atom } from 'nanostores'
import { beforeEach, expect, it, vi } from 'vitest'

import type { ChatMessage } from '@/lib/chat-messages'

import { AuraBrowserVoice } from './browser-voice'

vi.mock('@/app/chat/composer/scope', () => ({ useComposerScope: () => ({ $messages: messages }) }))

const messages = atom<ChatMessage[]>([])
const microphones: FakeRecognition[] = []

class FakeRecognition {
  onresult?: (event: { resultIndex: number; results: object[] }) => void
  onend?: () => void
  start = vi.fn()
  abort = vi.fn()
  constructor() { microphones.push(this) }
  result(text: string, isFinal = true, index = 0) {
    this.onresult?.({ resultIndex: index, results: Array.from({ length: index + 1 }, () => ({ isFinal, 0: { transcript: text } })) })
  }
}

beforeEach(() => {
  microphones.length = 0
  messages.set([])
  vi.stubGlobal('SpeechRecognition', FakeRecognition)
  vi.stubGlobal('SpeechSynthesisUtterance', class {})
  vi.stubGlobal('speechSynthesis', { cancel: vi.fn(), speak: vi.fn() })
})

function mount() {
  const onSubmit = vi.fn().mockResolvedValue(true)
  render(<AuraBrowserVoice busy={false} disabled={false} onInterrupt={vi.fn()} onSubmit={onSubmit} sessionId="same-text-thread" />)
  fireEvent.click(screen.getByRole('button', { name: 'Start voice' }))

  return { onSubmit, mic: microphones[0] }
}

it('shows partials without sending them and submits a replayed final only once', async () => {
  const { onSubmit, mic } = mount()
  act(() => mic.result('change the request', false))
  expect(screen.getByLabelText('Live transcript').textContent).toBe('change the request')
  expect(onSubmit).not.toHaveBeenCalled()
  act(() => mic.result('change the request'))
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
  act(() => mic.result('change the request'))
  expect(onSubmit).toHaveBeenCalledTimes(1)
  expect(onSubmit).toHaveBeenCalledWith('change the request')
})

it('accepts equal words at a new result index and after recognition restarts', async () => {
  const { onSubmit, mic } = mount()
  act(() => mic.result('again'))
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
  act(() => mic.result('again', true, 1))
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2))
  act(() => { mic.onend?.(); mic.result('again') })
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(3))
})

it('ignores queued results after stopping or replacing the microphone', async () => {
  const { onSubmit, mic } = mount()
  fireEvent.click(screen.getByRole('button', { name: 'Stop voice' }))
  act(() => mic.result('late stopped result'))
  fireEvent.click(screen.getByRole('button', { name: 'Start voice' }))
  act(() => mic.result('late replaced result'))
  expect(onSubmit).not.toHaveBeenCalled()
  act(() => microphones[1].result('current result'))
  await waitFor(() => expect(onSubmit).toHaveBeenCalledExactlyOnceWith('current result'))
})

it('ignores a queued final from recognition aborted for playback', async () => {
  const { onSubmit, mic } = mount()
  act(() => messages.set([{ id: 'reply', role: 'assistant', parts: [{ type: 'text', text: 'Spoken reply.' }] }]))
  await waitFor(() => expect(window.speechSynthesis.speak).toHaveBeenCalledTimes(1))
  act(() => { mic.onend?.(); mic.result('queued before playback') })
  expect(onSubmit).not.toHaveBeenCalled()
})

it('does not replay a stopped reply when history replaces its live message id', async () => {
  mount()
  const reply: ChatMessage = { id: 'live-reply', role: 'assistant', parts: [{ type: 'text', text: 'Spoken reply.' }] }
  act(() => messages.set([reply]))
  await waitFor(() => expect(window.speechSynthesis.speak).toHaveBeenCalledTimes(1))
  fireEvent.click(screen.getByRole('button', { name: 'Interrupt and listen' }))
  act(() => messages.set([{ ...reply, id: 'hydrated-reply' }]))
  expect(window.speechSynthesis.speak).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('status').textContent).toBe('Listening')
  act(() => messages.set([
    { id: 'new-user', role: 'user', parts: [{ type: 'text', text: 'Say it again' }] },
    { ...reply, id: 'new-reply' }
  ]))
  await waitFor(() => expect(window.speechSynthesis.speak).toHaveBeenCalledTimes(2))
})
