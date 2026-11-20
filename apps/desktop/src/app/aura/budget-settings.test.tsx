import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { AuraBudgetSettings, type AuraBudgetStatus } from './budget-settings'

const base: AuraBudgetStatus = {
  currency: 'USD', limit_usd: 3, paid_enabled: false, spent_usd: 0, reserved_usd: 0, remaining_usd: 3,
  percent_used: 0, state: 'active', updated_at: null, by_model: [], history: []
}

function serve(api: unknown) {
  ;(window as unknown as { hermesDesktop?: unknown }).hermesDesktop = { api }
}

afterEach(() => vi.restoreAllMocks())

it('shows the $3 default, the figures and that the budget buys no credit', async () => {
  serve(vi.fn().mockResolvedValue(base))
  render(<AuraBudgetSettings />)
  expect(await screen.findByLabelText('Budget limit (USD)')).toHaveProperty('value', '3')
  expect(screen.getByText(/doesn’t buy provider credit/)).toBeTruthy()
  expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('0')
  expect(screen.getByText(/^Active · 0% used/)).toBeTruthy()
  expect((screen.getByLabelText('Allow paid models') as HTMLInputElement).checked).toBe(false)
})

it('saves a new limit through the server and shows what it returns', async () => {
  const api = vi.fn().mockResolvedValueOnce(base).mockResolvedValueOnce({ ...base, limit_usd: 10, remaining_usd: 10 })
  serve(api)
  render(<AuraBudgetSettings />)
  const input = await screen.findByLabelText('Budget limit (USD)')
  fireEvent.change(input, { target: { value: '10' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save budget' }))
  await waitFor(() => expect(api).toHaveBeenLastCalledWith({ path: '/api/aura/budget', method: 'PUT', body: { limit_usd: 10 } }))
  expect(await screen.findByText('Budget set to $10.00.')).toBeTruthy()
})

it('rejects a negative amount before sending and explains a reached budget and per-model spend', async () => {
  const reached: AuraBudgetStatus = {
    ...base, paid_enabled: true, limit_usd: 1, spent_usd: 1.2, remaining_usd: 0, percent_used: 120, state: 'reached',
    by_model: [{ model: 'deepseek/deepseek-v4.1-flash-1017', tier: 'default', requests: 4, spent_usd: 1.2 }],
    history: [{ request_id: 'r1', model: 'deepseek/deepseek-v4.1-flash-1017', tier: 'default', reserved_usd: 0.02,
      actual_usd: null, status: 'usage_unknown', created_at: '2026-11-20T17:00:00+00:00' }]
  }

  const api = vi.fn().mockResolvedValue(reached)
  serve(api)
  render(<AuraBudgetSettings />)
  expect(await screen.findByText(/^Reached · 120% used/)).toBeTruthy()
  expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('100')
  expect(screen.getByText('4 requests · $1.20')).toBeTruthy()
  expect(screen.getByText('Cost not reported · full estimate counted · $0.02')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Budget limit (USD)'), { target: { value: '-2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save budget' }))
  expect(await screen.findByText('Enter an amount of $0 or more.')).toBeTruthy()
  expect(api).toHaveBeenCalledTimes(1)
})

it('tells a non-owner plainly', async () => {
  serve(vi.fn().mockRejectedValue(new Error('403 Forbidden')))
  render(<AuraBudgetSettings />)
  expect(await screen.findByText('Only the owner account can see or change the budget.')).toBeTruthy()
  expect(screen.queryByLabelText('Budget limit (USD)')).toBeNull()
})
