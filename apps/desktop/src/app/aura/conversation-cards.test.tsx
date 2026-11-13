import { act, fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import type { ChatMessage } from '@/lib/chat-messages'
import { $messages } from '@/store/session'

import { AuraConversationCards } from './conversation-cards'

vi.mock('@/lib/chat-messages', () => ({
  chatMessageText: (message: ChatMessage) => message.parts.map(part => (part.type === 'text' ? part.text : '')).join('')
}))
vi.mock('@/app/chat/composer/focus', () => ({ requestComposerFocus: vi.fn() }))
vi.mock('@/store/session', async () => {
  const { atom } = await import('nanostores')

  return { $busy: atom(false), $messages: atom<ChatMessage[]>([]), $activeSessionId: atom(null), $selectedStoredSessionId: atom(null) }
})

it('keeps a goal annotation across navigation without rewriting stored messages', () => {
  const messages: ChatMessage[] = [
    { id: 'synthetic-user', role: 'user', parts: [{ type: 'text', text: 'Original synthetic goal' }] }
  ]

  $messages.set(messages)
  const { rerender } = render(<AuraConversationCards resumed={false} />)
  fireEvent.click(screen.getByRole('button', { name: 'Edit goal' }))
  fireEvent.change(screen.getByLabelText('Your goal'), { target: { value: 'A clearer goal' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save goal' }))
  expect($messages.get()).toBe(messages)
  act(() => $messages.set([]))
  act(() => $messages.set(messages))
  rerender(<AuraConversationCards resumed />)
  expect(screen.getByRole('region', { name: /resume:/ }).textContent).toContain('A clearer goal')
})
