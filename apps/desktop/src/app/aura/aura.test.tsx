import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AuraCard } from './card'
import { auraCopy } from './copy'
import { auraSources } from './sources'

describe('Aura product boundaries', () => {
  it('requires an explicit callback before approval can be submitted', () => {
    const approve = vi.fn()
    const change = vi.fn()

    const { rerender } = render(
      <AuraCard kind="approval" title="Write the draft">
        Review the proposed action.
      </AuraCard>
    )

    expect((screen.getByRole('button', { name: 'Approve' }) as HTMLButtonElement).disabled).toBe(true)
    rerender(
      <AuraCard kind="approval" onApprove={approve} onChange={change} title="Write the draft">
        Review the proposed action.
      </AuraCard>
    )
    fireEvent.click(screen.getByRole('button', { name: 'Change' }))
    expect(approve).not.toHaveBeenCalled()
    expect(change).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(approve).toHaveBeenCalledOnce()
  })
  it('rebrands copy without changing translation keys or CLI commands', () => {
    const source = {
      HermesKey: 'Hermes by Nous Research',
      command: 'hermes webapp',
      title: (name: string) => `Hermes: ${name}`
    }

    const result = auraCopy(source)
    expect(result.HermesKey).toBe('Aura by Reveta')
    expect(result.command).toBe('hermes webapp')
    expect(result.title('A synthetic task')).toBe('Aura: A synthetic task')
    expect(source.HermesKey).toBe('Hermes by Nous Research')
    expect(auraCopy(source)).toBe(result)
  })
})

describe('Aura card states', () => {
  it('only offers resume when a real resume handler is available', () => {
    const resume = vi.fn()

    const { rerender } = render(
      <AuraCard kind="resume" title="A synthetic conversation">
        Ready to continue.
      </AuraCard>
    )

    expect(screen.queryByRole('button', { name: 'Resume conversation' })).toBeNull()
    rerender(
      <AuraCard kind="resume" onResume={resume} title="A synthetic conversation">
        Ready to continue.
      </AuraCard>
    )
    fireEvent.click(screen.getByRole('button', { name: 'Resume conversation' }))
    expect(resume).toHaveBeenCalledOnce()
  })
})

it('keeps code identifiers and translated lists intact', () => {
  expect(auraCopy(['Hermes', 'HermesGateway', 'hermes webapp'])).toEqual(['Aura', 'HermesGateway', 'hermes webapp'])
})

it('deduplicates source chips and refuses executable link schemes', () => {
  expect(
    auraSources(
      '[Source](https://example.test) [Source](https://example.test) [Unsafe](javascript:alert) [Broken](https://%)'
    )
  ).toEqual([['https://example.test', 'Source']])
})
