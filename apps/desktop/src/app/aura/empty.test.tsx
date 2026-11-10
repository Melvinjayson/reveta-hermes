import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import { requestComposerInsert } from '@/app/chat/composer/focus'

import { AuraEmpty } from './empty'
import { AuraReadiness } from './readiness'

vi.mock('@/app/chat/composer/focus', () => ({ requestComposerInsert: vi.fn() }))
vi.mock('@/store/session', async () => {
  const { atom } = await import('nanostores')

  return { $gatewayState: atom('open') }
})

it('explains missing model readiness and lets a suggestion populate the real composer action', () => {
  const { rerender } = render(
    <AuraReadiness value={false}>
      <AuraEmpty />
    </AuraReadiness>
  )

  expect(screen.getByRole('status').textContent).toContain('Aura can’t reply yet')
  fireEvent.click(screen.getByRole('button', { name: /Plan my next step/ }))
  expect(requestComposerInsert).toHaveBeenCalledWith('Plan my next step')
  rerender(
    <AuraReadiness value={true}>
      <AuraEmpty />
    </AuraReadiness>
  )
  expect(screen.queryByText(/Aura can’t reply yet/)).toBeNull()
})
