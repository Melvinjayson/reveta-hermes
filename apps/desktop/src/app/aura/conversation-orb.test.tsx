import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import { AuraConversationOrb, orbMotion } from './conversation-orb'

it('maps voice statuses into distinct and bounded visual states', () => {
  expect(orbMotion('Hearing you')).toBe('listening')
  expect(orbMotion('Listening')).toBe('listening')
  expect(orbMotion('Speaking')).toBe('speaking')
  expect(orbMotion('Thinking')).toBe('thinking')
  expect(orbMotion('Reconnecting')).toBe('reconnecting')
  expect(orbMotion('Muted')).toBe('muted')
  expect(orbMotion('Voice off')).toBe('idle')
})

it('is decorative and does not expose a second audio control', () => {
  const { container, rerender } = render(<AuraConversationOrb status="Speaking" />)
  expect(container.querySelector('[data-motion="speaking"]')).not.toBeNull()
  expect(container.querySelectorAll('button')).toHaveLength(0)
  expect(screen.queryByRole('img')).toBeNull()
  rerender(<AuraConversationOrb status="Listening" />)
  expect(container.querySelector('[data-motion="listening"]')).not.toBeNull()
})
