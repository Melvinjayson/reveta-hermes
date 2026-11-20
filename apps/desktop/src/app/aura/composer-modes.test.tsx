import { render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { AuraComposerModes } from './composer-modes'

vi.mock('./voice-mode', () => ({
  AuraVoiceMode: ({ sessionId }: { sessionId?: string | null }) => <button type="button">Voice chat {sessionId}</button>
}))

const props = { busy: false, disabled: false, onInterrupt: vi.fn(), onSubmit: vi.fn(), sessionId: 's-1' }

afterEach(() => window.localStorage.removeItem('aura.localTalk.v1'))

it('keeps Voice chat and the opted-in On-device toggle together in one labelled group', () => {
  window.localStorage.setItem('aura.localTalk.v1', '1')
  render(<AuraComposerModes {...props} />)
  const group = screen.getByRole('group', { name: 'Conversation options' })
  expect(within(group).getByRole('button', { name: 'Voice chat s-1' })).toBeTruthy()
  expect(within(group).getByRole('button', { name: 'On-device' })).toBeTruthy()
})

it('shows only Voice chat until On-device is opted in', () => {
  render(<AuraComposerModes {...props} />)
  const group = screen.getByRole('group', { name: 'Conversation options' })
  expect(within(group).getAllByRole('button')).toHaveLength(1)
  expect(screen.queryByRole('button', { name: 'On-device' })).toBeNull()
})
