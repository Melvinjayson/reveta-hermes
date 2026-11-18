import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import { $auraCapabilities } from './capabilities'
import { AuraConnectorsSection, AuraJobsSection, AuraMemorySection } from './settings-sections'

const api = vi.fn()

beforeEach(() => {
  api.mockReset()
  ;(window as unknown as { hermesDesktop: unknown }).hermesDesktop = { api }
  $auraCapabilities.set({ applies_to: 'new conversations', mode: null, modes: {}, capabilities: [] })
})

it('clears a memory note only after an explicit confirm', async () => {
  api.mockImplementation(async ({ path }: { path: string }) =>
    path === '/api/aura/memory'
      ? { memory: { text: 'Prefers short answers.', truncated: false }, user: { text: '', truncated: false } }
      : { ok: true }
  )
  render(<AuraMemorySection />)

  expect(await screen.findByText('Prefers short answers.')).toBeTruthy()
  expect(screen.getByText('Nothing saved yet.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Clear…' }))
  expect(api).not.toHaveBeenCalledWith(expect.objectContaining({ path: '/api/memory/reset' }))
  fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith({ path: '/api/memory/reset', method: 'POST', body: { target: 'memory' } })
  )
})

it('lists connectors and marks Composio blocked when its key is not set up', async () => {
  api.mockResolvedValue({ servers: [{ name: 'docs', transport: 'http', url: 'https://mcp.example.test/sse', enabled: true, source: 'config' }] })
  render(<AuraConnectorsSection />)

  expect(await screen.findByText('docs')).toBeTruthy()
  expect(screen.getByText(/needs a Composio API key/)).toBeTruthy()
  fireEvent.click(screen.getByRole('switch', { name: 'docs enabled' }))
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith({ path: '/api/mcp/servers/docs/enabled', method: 'PUT', body: { enabled: false } })
  )
})

it('pauses, runs and deletes a scheduled job through the cron routes; delete needs a confirm', async () => {
  api.mockImplementation(async ({ path }: { path: string }) =>
    path === '/api/cron/jobs' ? [{ id: 'j1', name: 'Morning brief', state: 'scheduled', schedule_display: 'every day 08:00' }] : { ok: true }
  )
  render(<AuraJobsSection />)

  expect(await screen.findByText('Morning brief')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
  fireEvent.click(screen.getByRole('button', { name: 'Run now' }))
  fireEvent.click(screen.getByRole('button', { name: 'Delete…' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith({ path: '/api/cron/jobs/j1/pause', method: 'POST' }))
  expect(api).toHaveBeenCalledWith({ path: '/api/cron/jobs/j1/trigger', method: 'POST' })
  expect(api).not.toHaveBeenCalledWith(expect.objectContaining({ method: 'DELETE' }))
  fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith({ path: '/api/cron/jobs/j1', method: 'DELETE' }))
})
