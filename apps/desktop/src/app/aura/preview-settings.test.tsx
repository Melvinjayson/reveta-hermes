import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import { AuraPreviewSection } from './settings-sections'

const api = vi.fn()

beforeEach(() => {
  api.mockReset()
  ;(window as unknown as { hermesDesktop: unknown }).hermesDesktop = { api }
})

it('lets the owner switch run evidence on through the preview route', async () => {
  api.mockImplementation(async ({ method, body }: { method?: string; body?: Record<string, boolean> }) =>
    method === 'PUT'
      ? { companion: false, handoff: false, venus_evidence: Boolean(body?.venus_evidence) }
      : { companion: false, handoff: false, venus_evidence: false }
  )
  render(<AuraPreviewSection />)

  const evidence = await screen.findByRole('switch', { name: 'Run evidence (Venus) enabled' })
  expect((evidence as HTMLInputElement).checked).toBe(false)
  // Handoff needs the companion first.
  expect((screen.getByRole('switch', { name: 'Send tasks to your browser enabled' }) as HTMLInputElement).disabled).toBe(true)
  fireEvent.click(evidence)
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith({ path: '/api/aura/preview', method: 'PUT', body: { venus_evidence: true } })
  )
  await waitFor(() => expect((evidence as HTMLInputElement).checked).toBe(true))
})

it('shows the refusal to anyone but the owner and offers no switches', async () => {
  api.mockRejectedValue(new Error('403: {"detail": "Only the owner account can change this."}'))
  render(<AuraPreviewSection />)

  expect((await screen.findByRole('alert')).textContent).toBe('Only the owner account can change this.')
  expect(screen.queryByRole('switch')).toBeNull()
})
