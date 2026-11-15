import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import { AuraConversationRow } from './conversation-row'

it('deletes only after an explicit confirm, and Cancel deletes nothing', async () => {
  const onDelete = vi.fn().mockResolvedValue(undefined)
  const onOpen = vi.fn()
  render(<AuraConversationRow onDelete={onDelete} onOpen={onOpen} title="Synthetic launch plan" />)

  fireEvent.click(screen.getByRole('button', { name: 'Delete conversation: Synthetic launch plan' }))
  expect(onDelete).not.toHaveBeenCalled()
  expect(onOpen).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(onDelete).not.toHaveBeenCalled()

  fireEvent.click(screen.getByRole('button', { name: 'Delete conversation: Synthetic launch plan' }))
  expect(screen.getByRole('group', { name: 'Delete Synthetic launch plan?' }).textContent).toContain('can’t be undone')
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
  await waitFor(() => expect(onDelete).toHaveBeenCalledOnce())
})

it('opens the conversation from its title', () => {
  const onOpen = vi.fn()
  render(<AuraConversationRow onDelete={vi.fn()} onOpen={onOpen} title="Synthetic chat" />)
  fireEvent.click(screen.getByRole('button', { name: 'Synthetic chat' }))
  expect(onOpen).toHaveBeenCalledOnce()
})
