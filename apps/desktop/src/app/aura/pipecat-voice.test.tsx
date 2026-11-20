import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { atom } from 'nanostores'
import { beforeEach, expect, it, vi } from 'vitest'

import type { ChatMessage } from '@/lib/chat-messages'
import type { VoiceEvent } from '@/lib/pipecat-voice'

import { AuraPipecatVoice } from './pipecat-voice'

const messages = atom<ChatMessage[]>([])
let emit: (event: VoiceEvent) => void
const send = vi.fn(), flush = vi.fn(), stop = vi.fn()
vi.mock('@/app/chat/composer/scope', () => ({ useComposerScope: () => ({ $messages: messages }) }))
vi.mock('@/lib/pipecat-voice', () => ({ PipecatVoice: class {
  constructor(_route: unknown, _id: unknown, event: typeof emit) { emit = event }
  start = vi.fn().mockResolvedValue(undefined)
  send = send; flush = flush; stop = stop; adopt = vi.fn()
} }))
beforeEach(() => { messages.set([]); vi.clearAllMocks() })

it('keeps partials live and admits one final once with the ordinary conversation identity', async () => {
  const onSubmit = vi.fn().mockResolvedValue(true)
  render(<AuraPipecatVoice busy={false} disabled={false} onInterrupt={vi.fn()} onSubmit={onSubmit} sessionId="chat" />)
  fireEvent.click(screen.getByRole('button', { name: 'Voice' }))
  act(() => emit({ type: 'partial', turn_id: 'a'.repeat(32), text: 'partial words' }))
  expect(screen.getByText('partial words')).toBeTruthy()
  expect(onSubmit).not.toHaveBeenCalled()
  act(() => { for (let i = 0; i < 2; i++) { emit({ type: 'final', turn_id: 'a'.repeat(32), text: 'final words' }) } })
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
  expect(onSubmit).toHaveBeenCalledWith('final words', expect.objectContaining({ submission_id: 'a'.repeat(32), voiceRecordingId: 'a'.repeat(32) }))
  act(() => messages.set([
    { id: `user-${'a'.repeat(32)}`, role: 'user', parts: [{ type: 'text', text: 'final words' }] },
    { id: 'assistant', role: 'assistant', parts: [{ type: 'text', text: 'Same reply.' }] }
  ]))
  await waitFor(() => expect(send).toHaveBeenCalledWith(expect.objectContaining({ type: 'reply', text: 'Same reply.' })))
})

it('flushes on barge-in, preserves tools, records only played words and waits for completion', async () => {
  const onSubmit = vi.fn().mockResolvedValue(true), request = vi.fn().mockResolvedValue({})
  const props = { disabled: false, gateway: { request }, onInterrupt: vi.fn(), onSubmit, sessionId: 'chat' }
  const view = render(<AuraPipecatVoice {...props} busy={false} />)
  fireEvent.click(screen.getByRole('button', { name: 'Voice' }))
  act(() => emit({ type: 'final', turn_id: 'a'.repeat(32), text: 'old request' }))
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
  view.rerender(<AuraPipecatVoice {...props} busy />)
  act(() => emit({ type: 'played', turn_id: 'a'.repeat(32), message_index: 0, text: 'Heard.' }))
  act(() => emit({ type: 'speech_start', turn_id: 'b'.repeat(32), interrupt_turn_id: 'a'.repeat(32) }))
  expect(flush).toHaveBeenCalledWith('a'.repeat(32))
  expect(request).toHaveBeenCalledWith('session.interrupt', { session_id: 'chat', preserve_running_tools: true })
  expect(request).toHaveBeenCalledWith('session.voice.record', expect.objectContaining({ text: 'Heard.', interrupted: true }))
  act(() => emit({ type: 'final', turn_id: 'b'.repeat(32), text: 'changed request' }))
  expect(onSubmit).toHaveBeenCalledTimes(1)
  view.rerender(<AuraPipecatVoice {...props} busy={false} />)
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2))
})

it('leaving a speaking conversation interrupts its owner and never the newly opened chat', async () => {
  const oldRequest = vi.fn().mockResolvedValue({}), newRequest = vi.fn().mockResolvedValue({})
  const onSubmit = vi.fn().mockResolvedValue(true)
  const view = render(<AuraPipecatVoice busy={false} disabled={false} gateway={{ request: oldRequest }} onInterrupt={vi.fn()} onSubmit={onSubmit} sessionId="old-chat" />)
  fireEvent.click(screen.getByRole('button', { name: 'Voice' }))
  act(() => emit({ type: 'final', turn_id: 'a'.repeat(32), text: 'old request' }))
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
  view.rerender(<AuraPipecatVoice busy disabled={false} gateway={{ request: oldRequest }} onInterrupt={vi.fn()} onSubmit={onSubmit} sessionId="old-chat" />)
  act(() => emit({ type: 'played', turn_id: 'a'.repeat(32), message_index: 0, text: 'Heard.' }))
  view.rerender(<AuraPipecatVoice busy disabled={false} gateway={{ request: newRequest }} onInterrupt={vi.fn()} onSubmit={onSubmit} sessionId="new-chat" />)
  expect(oldRequest).toHaveBeenCalledWith('session.interrupt', { session_id: 'old-chat', preserve_running_tools: true })
  expect(oldRequest).toHaveBeenCalledWith('session.voice.record', expect.objectContaining({ session_id: 'old-chat', interrupted: true }))
  expect(newRequest).not.toHaveBeenCalled()
})
