import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import { AuraRoutingSettings, type AuraRoutingStatus } from './routing-settings'

const reason = "Paid models stay off until Aura's budget authorization is in place."

function routing(testState: 'available' | 'disabled'): AuraRoutingStatus {
  return {
    enabled: false,
    tiers: [
      { tier: 'default', label: 'Routine', model: 'deepseek/deepseek-v4.1-flash-1017', paid: true, state: 'disabled', reason },
      { tier: 'reasoning', label: 'Reasoning', model: 'moonshotai/kimi-k3.1-pro', paid: true, state: 'disabled', reason }
    ],
    test_route: { label: 'Test', model: 'nvidia/nemotron-3-ultra-550b-a55b:free', state: testState, experimental: true }
  }
}

it('lists disabled paid tiers as plain rows with their reason, never as choices', () => {
  render(<AuraRoutingSettings onUseTest={vi.fn()} routing={routing('disabled')} saving={false} />)
  expect(screen.getAllByText(`Off — ${reason}`)).toHaveLength(2)
  expect(screen.getByText('deepseek/deepseek-v4.1-flash-1017')).toBeTruthy()
  expect(screen.queryByRole('button')).toBeNull()
  expect(screen.getByText('Off on this deployment.')).toBeTruthy()
})

it('offers the experimental test model only when the deployment switched it on', () => {
  const onUseTest = vi.fn()
  const { rerender } = render(<AuraRoutingSettings onUseTest={onUseTest} routing={routing('available')} saving={false} />)
  expect(screen.getByText('Experimental')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Use the test model' }))
  expect(onUseTest).toHaveBeenCalledOnce()
  rerender(<AuraRoutingSettings activeModel="nvidia/nemotron-3-ultra-550b-a55b:free" onUseTest={onUseTest}
    routing={routing('available')} saving={false} />)
  expect(screen.queryByRole('button')).toBeNull()
  expect(screen.getByText(/^In use\./)).toBeTruthy()
})

it('renders nothing when the deployment configures no routing', () => {
  const empty: AuraRoutingStatus = { enabled: false, tiers: [],
    test_route: { label: 'Test', model: null, state: 'disabled', experimental: true } }

  const { container } = render(<AuraRoutingSettings onUseTest={vi.fn()} routing={empty} saving={false} />)
  expect(container.innerHTML).toBe('')
})
