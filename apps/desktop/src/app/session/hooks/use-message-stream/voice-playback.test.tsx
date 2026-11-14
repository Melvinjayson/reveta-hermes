import { act, cleanup } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'

import { renderMessageStream } from './test-harness'
afterEach(cleanup)
it('truncates unheard text while a started tool still lands exactly once', () => {
  const stream = renderMessageStream('chat')
  stream.states.set('chat', { ...stream.state('chat'), messages: [
    { id: `user-${'a'.repeat(32)}`, role: 'user', parts: [{ type: 'text', text: 'old request' }] }
  ] })

  const emit = (type: Parameters<typeof stream.handleEvent>[0]['type'], payload: Record<string, unknown>) =>
    act(() => stream.handleEvent({ type, session_id: 'chat', payload }))

  emit('message.start', {})
  emit('message.delta', { text: 'Heard. Never heard.' })
  emit('tool.start', { name: 'terminal', tool_id: 'once', args: { command: 'test' } })
  emit('message.voice_played', { turn_id: 'a'.repeat(32), message_index: 0, text: 'Heard.', interrupted: true })
  emit('message.delta', { text: 'More old output.' })
  emit('tool.complete', { name: 'terminal', tool_id: 'once', result: 'actual result' })
  emit('tool.complete', { name: 'terminal', tool_id: 'once', result: 'actual result' })
  emit('message.complete', { text: 'Heard. Never heard.', status: 'interrupted' })
  const parts = stream.state('chat').messages.flatMap(message => message.parts)
  expect(parts.filter(part => part.type === 'text').map(part => part.text)).toEqual(['old request', 'Heard.'])
  expect(parts.filter(part => part.type === 'tool-call')).toEqual([
    expect.objectContaining({ toolCallId: 'once', result: 'actual result' })
  ])
  expect(stream.state('chat').busy).toBe(false)
})
it('a late interrupted receipt cannot truncate or freeze a newer user turn', () => {
  const stream = renderMessageStream('chat')
  stream.states.set('chat', { ...stream.state('chat'), messages: [
    { id: `user-${'a'.repeat(32)}`, role: 'user', parts: [{ type: 'text', text: 'old' }] },
    { id: 'new-user', role: 'user', parts: [{ type: 'text', text: 'new' }] },
    { id: 'new-assistant', role: 'assistant', parts: [{ type: 'text', text: 'New reply.' }] }
  ] })
  act(() => stream.handleEvent({ type: 'message.voice_played', session_id: 'chat', payload: {
    turn_id: 'a'.repeat(32), message_index: 0, text: '', interrupted: true
  } }))
  expect(stream.state('chat').voiceInterrupted).toBeFalsy()
  expect(stream.text('chat')).toBe('New reply.')
})
