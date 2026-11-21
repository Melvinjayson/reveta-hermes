import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, expect, it, vi } from 'vitest'

import { requestComposerInsert } from '@/app/chat/composer/focus'

import { AuraOnboarding } from './onboarding'

vi.mock('@/app/chat/composer/focus', () => ({ requestComposerInsert: vi.fn() }))

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.open = true }

  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.open = false }
})

function serve(api: unknown) {
  ;(window as unknown as { hermesDesktop?: unknown }).hermesDesktop = { api }
}

afterEach(() => vi.clearAllMocks())

it('walks a new account through three steps and remembers it on the server', async () => {
  const api = vi.fn().mockResolvedValueOnce({ completed: false, storage_durable: false }).mockResolvedValue({ completed: true })
  serve(api)
  render(<AuraOnboarding theme="dark" />)
  expect(await screen.findByRole('heading', { name: 'Meet Aura' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  expect(screen.getByText(/does not keep data across restarts yet/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  fireEvent.click(screen.getByRole('button', { name: 'Build' }))
  expect(requestComposerInsert).toHaveBeenCalledWith('Help me build ')
  await waitFor(() => expect(api).toHaveBeenLastCalledWith({ path: '/api/aura/onboarding', method: 'PUT' }))
  expect(screen.queryByRole('heading', { name: 'Start' })).toBeNull()
})

it('says chats survive restarts only when the server keeps them, and can be skipped', async () => {
  const api = vi.fn().mockResolvedValueOnce({ completed: false, storage_durable: true }).mockResolvedValue({ completed: true })
  serve(api)
  render(<AuraOnboarding theme="light" />)
  fireEvent.click(await screen.findByRole('button', { name: 'Next' }))
  expect(screen.getByText(/They stay when the server restarts/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Skip' }))
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
})

it('shows nothing for an account that already finished', async () => {
  serve(vi.fn().mockResolvedValue({ completed: true, storage_durable: false }))
  const { container } = render(<AuraOnboarding theme="dark" />)
  await waitFor(() => expect(container.innerHTML).toBe(''))
})

it('opens on the primary action rather than Skip', async () => {
  serve(vi.fn().mockResolvedValue({ completed: false, storage_durable: false }))
  render(<AuraOnboarding theme="dark" />)
  const next = await screen.findByRole('button', { name: 'Next' })
  await waitFor(() => expect(document.activeElement).toBe(next))
})
