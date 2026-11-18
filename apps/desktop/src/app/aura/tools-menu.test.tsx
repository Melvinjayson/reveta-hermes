import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import { $auraCapabilities, $auraToolsOpen, type AuraCapabilityStatus } from './capabilities'
import { AuraToolsDialog } from './tools-menu'

const status = (enabled: string[]): AuraCapabilityStatus => ({
  applies_to: 'new conversations',
  mode: null,
  modes: {},
  capabilities: [
    { id: 'memory', label: 'Memory', description: 'Notes.', enabled: enabled.includes('memory'), available: true, blocked: null, requires_env: [] },
    { id: 'web', label: 'Web search', description: 'Search.', enabled: false, available: false, blocked: 'Needs a service key or package that is not set up.', requires_env: ['TAVILY_API_KEY'] }
  ]
})

const api = vi.fn()

beforeEach(() => {
  api.mockReset()
  api.mockImplementation(async ({ method, body }: { method: string; body?: { enabled: string[] } }) =>
    method === 'PUT' ? status(body?.enabled ?? []) : status([])
  )
  ;(window as unknown as { hermesDesktop: unknown }).hermesDesktop = { api }

  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute('open', '')
  }

  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute('open')
  }

  $auraCapabilities.set(null)
})

it('switches a capability on for new chats and keeps key-less ones off with the reason', async () => {
  render(<AuraToolsDialog theme="light" />)
  $auraToolsOpen.set(true)

  const memory = await screen.findByRole('switch', { name: /Memory/ })
  const web = screen.getByRole('switch', { name: /Web search/ })
  expect((web as HTMLInputElement).disabled).toBe(true)
  expect(screen.getByText(/Not set up/)).toBeTruthy()
  expect(screen.getByText(/Changes apply to new chats/)).toBeTruthy()

  fireEvent.click(memory)
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith({ path: '/api/aura/capabilities', method: 'PUT', body: { enabled: ['memory'] } })
  )
  await waitFor(() => expect((screen.getByRole('switch', { name: /Memory/ }) as HTMLInputElement).checked).toBe(true))
})
