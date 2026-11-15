import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import { requestComposerInsert, requestComposerSubmit } from '@/app/chat/composer/focus'
import type { ChatMessage } from '@/lib/chat-messages'
import { $activeSessionId, $busy, $messages } from '@/store/session'

import { AuraConversationCards } from './conversation-cards'
import { $auraDismissedGoals, $auraGoals, auraReplyHints } from './goals'

vi.mock('@/lib/chat-messages', () => ({
  chatMessageText: (message: ChatMessage) => message.parts.map(part => (part.type === 'text' ? part.text : '')).join('')
}))
vi.mock('@/app/chat/composer/focus', () => ({
  requestComposerFocus: vi.fn(),
  requestComposerInsert: vi.fn(),
  requestComposerSubmit: vi.fn(() => true)
}))
vi.mock('@/store/session', async () => {
  const { atom } = await import('nanostores')

  return {
    $busy: atom(false),
    $messages: atom<ChatMessage[]>([]),
    $activeSessionId: atom<null | string>(null),
    $selectedStoredSessionId: atom<null | string>(null)
  }
})

const user = (id: string, text: string): ChatMessage => ({ id, role: 'user', parts: [{ type: 'text', text }] })
const aura = (id: string, text: string): ChatMessage => ({ id, role: 'assistant', parts: [{ type: 'text', text }] })

beforeEach(() => {
  localStorage.clear()
  $auraGoals.set({})
  $auraDismissedGoals.set({})
  $activeSessionId.set('chat-1')
})

it('never turns the first message into a goal', () => {
  $messages.set([user('u1', 'hey, what can you do?')])
  const { container } = render(<AuraConversationCards resumed={false} />)
  expect(container.querySelector('.aura-context-panel')).toBeNull()
  expect(container.querySelector('.aura-goal-proposal')).toBeNull()
  expect(container.textContent).not.toContain('hey, what can you do?')
  expect($auraGoals.get()).toEqual({})
})

it('offers a goal only after Aura proposes one, and saves it on confirm', () => {
  const messages = [
    user('u1', 'I want to sell my art'),
    aura('a1', 'Got it.\n\nProposed goal: Launch an online shop for my art by March\n\nShall I save that?')
  ]

  $messages.set(messages)
  const { container } = render(<AuraConversationCards resumed={false} />)
  expect(screen.getByRole('group', { name: 'Proposed goal' }).textContent).toContain('Launch an online shop for my art by March')
  expect($auraGoals.get()).toEqual({})
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect($auraGoals.get()).toEqual({ 'chat-1': 'Launch an online shop for my art by March' })
  expect(container.querySelector('.aura-goal-proposal')).toBeNull()
  expect(container.querySelector('.aura-context-goal')?.textContent).toBe('Launch an online shop for my art by March')
  expect(container.querySelector('details.aura-context-panel')!.hasAttribute('open')).toBe(false)
  expect($messages.get()).toBe(messages)
})

it('does not offer a dismissed proposal again', () => {
  $messages.set([user('u1', 'help'), aura('a1', 'Proposed goal: Draft a pitch deck')])
  const { container, rerender } = render(<AuraConversationCards resumed={false} />)
  fireEvent.click(screen.getByRole('button', { name: 'Not now' }))
  rerender(<AuraConversationCards resumed={false} />)
  expect(container.querySelector('.aura-goal-proposal')).toBeNull()
  expect($auraGoals.get()).toEqual({})
})

it('keeps an edited goal per conversation across navigation', () => {
  $messages.set([user('u1', 'start'), aura('a1', 'Proposed goal: Original')])
  const { rerender } = render(<AuraConversationCards resumed={false} />)
  fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
  fireEvent.change(screen.getByLabelText('Your goal'), { target: { value: 'A clearer goal' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save goal' }))
  act(() => $activeSessionId.set('chat-2'))
  expect(screen.queryByText('A clearer goal')).toBeNull()
  act(() => $activeSessionId.set('chat-1'))
  rerender(<AuraConversationCards resumed />)
  expect(screen.getByRole('region', { name: /resume:/ }).textContent).toContain('A clearer goal')
  expect(JSON.parse(localStorage.getItem('aura.goals.v1') ?? '{}')).toEqual({ 'chat-1': 'A clearer goal' })
})

it('builds quick replies from the options in Aura’s own closing question', () => {
  const hints = (text: string, busy = false) => auraReplyHints([user('u1', 'idea'), aura('a1', text)], busy)

  expect(hints('Nice idea. Do you want to start with the landing page, the pricing or the waitlist?')).toEqual({
    replies: ['Landing page', 'Pricing', 'Waitlist'],
    tag: 'Asking you'
  })
  expect(hints('Should I draft the outline now?')).toEqual({ replies: ['Yes', 'Not yet'], tag: 'Asking you' })
  expect(hints('What does a good first week look like for you?')).toEqual({ replies: [], tag: 'Asking you' })
  expect(hints('Here is the plan. It has three steps.')).toEqual({ replies: [], tag: null })
  expect(hints('Proposed goal: Ship the beta by Friday\n\nSave it?')).toEqual({ replies: [], tag: null })
  expect(hints('Should I draft the outline now?', true)).toEqual({ replies: [], tag: null })
  expect(auraReplyHints([aura('a1', 'Should I go on?'), user('u2', 'wait')], false)).toEqual({ replies: [], tag: null })
})

it('sends a tapped quick reply as your message, or leaves it in the text box when it cannot', () => {
  $busy.set(false)
  $messages.set([user('u1', 'I want a podcast'), aura('a1', 'Fun. Would you like to plan the format or the first episode?')])
  const { container } = render(<AuraConversationCards resumed={false} />)
  expect(container.querySelector('.aura-ai-tag')?.textContent).toContain('Asking you')
  fireEvent.click(screen.getByRole('button', { name: 'First episode' }))
  expect(requestComposerSubmit).toHaveBeenCalledWith('First episode')
  expect(requestComposerInsert).not.toHaveBeenCalled()

  vi.mocked(requestComposerSubmit).mockReturnValueOnce(false)
  fireEvent.click(screen.getByRole('button', { name: 'Format' }))
  expect(requestComposerInsert).toHaveBeenCalledWith('Format', { mode: 'block' })
})
