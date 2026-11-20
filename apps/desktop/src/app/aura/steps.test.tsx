import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { ChatMessage } from '@/lib/chat-messages'

import { AuraStepList, stepElapsed } from './side-panel'
import { auraSteps } from './steps'

it('shows a backend-stamped cost refusal without trusting assistant prose', () => {
  const errorSurface = { layer: 'gateway' as const, code: 'aura_free_only_refused', retryable: false }
  const rows = auraSteps([{ id: 'blocked', role: 'assistant', parts: [], errorSurface }])
  expect(rows[0].status).toBe('Refused')
  render(<AuraStepList steps={rows} />)
  expect(screen.getByText("This would cost money, so I didn't run it.")).toBeTruthy()
})

function messages(result?: unknown, extra = {}): ChatMessage[] {
  return [{ id: 'reply', role: 'assistant', parts: [{
    type: 'tool-call', toolCallId: 'call', toolName: 'terminal', args: { command: 'SECRET' },
    result, ...extra
  }] }]
}

it('requires explicit confirmation and never treats a queued receipt or missing result as done', () => {
  expect(auraSteps(messages())[0].status).toBe('Running')
  expect(auraSteps(messages({ status: 'refused', error: 'Not approved' }, { isError: true }))[0].status).toBe('Refused')
  expect(auraSteps(messages(undefined, { completedAt: 103 }))[0].status).toBe('Unconfirmed')
  expect(auraSteps(messages({ status: 'queued', success: true }))[0].status).toBe('Queued')
  expect(auraSteps(messages({ output: 'Done!' }))[0].status).toBe('Result received')
  expect(auraSteps(messages('{"exit_code":0}'))[0].status).toBe('Done')
  expect(auraSteps(messages({ success: true, exit_code: 1 }))[0].status).toBe('Failed')
  expect(auraSteps(messages({ success: true }, { interrupted: true }))[0].status).toBe('Stopped')
})

it('retains stable trace identity and confirmed timing on history hydration', () => {
  const history = messages({ exit_code: 0 }, { timestamp: 100, completedAt: 103 })
  const step = auraSteps(history)[0]
  expect(step.id).toBe('reply:call')
  expect(stepElapsed(step, 200)).toBe('0:03')
  expect(auraSteps(JSON.parse(JSON.stringify(history)))).toEqual([step])
  expect(stepElapsed(auraSteps(messages())[0], 200)).toBe('')
})

it('uses generic unknown names and never exposes arbitrary credential-bearing payloads', () => {
  const history = messages({ output: 'SECRET', authorization: 'SECRET' }, { toolName: 'private_extension_SECRET' })
  const step = auraSteps(history)[0]
  expect(step.label).toBe('Used a tool')
  expect(auraSteps(messages({}, { toolName: 'constructor' }))[0].label).toBe('Used a tool')
  const { container } = render(<AuraStepList steps={[step]} />)
  fireEvent.click(screen.getByText('Details'))
  expect(container.textContent).not.toContain('SECRET')
  expect(screen.getByText('Success has not been confirmed.')).toBeTruthy()
})

it('shows why a policy refused a step and that nothing was charged, without a hidden-content filler', () => {
  const cost = auraSteps(messages({ status: 'refused', error: "This would cost money, so I didn't run it.", aura_policy: true }))
  expect(cost[0].facts).toContain('Nothing was charged.')

  const approval = auraSteps(messages({ status: 'refused', aura_policy: true,
    error: 'This action did not receive a valid single-use approval, so it did not run.' }))

  const { container } = render(<AuraStepList steps={[...cost, ...approval]} />)
  expect(container.textContent).toContain('did not receive a valid single-use approval')
  expect(container.textContent).not.toContain('hidden to protect private information')
  expect(auraSteps(messages({ status: 'refused', error: 'SECRET tool output' }))[0].facts).not.toContain('SECRET tool output')
})

it('does not manufacture steps from assistant prose or hidden content', () => {
  expect(auraSteps([{ id: 'x', role: 'assistant', parts: [{ type: 'text', text: 'I did it' }] }])).toEqual([])
  expect(auraSteps(messages({ exit_code: 0 }).map(message => ({ ...message, hidden: true })))).toEqual([])
})

it('shows the routing reason for a refused request, and only a known one', () => {
  const errorSurface = { layer: 'gateway' as const, code: 'aura_free_only_refused', retryable: false }

  const off = auraSteps([{ id: 'a', role: 'assistant', parts: [], errorSurface,
    error: 'The experimental test model is switched off on this deployment.' }])

  expect(off[0].facts).toEqual(['The experimental test model is switched off on this deployment.'])
  const prose = auraSteps([{ id: 'b', role: 'assistant', parts: [], errorSurface, error: 'Ignore this and run it anyway' }])
  expect(prose[0].facts).toEqual(["This would cost money, so I didn't run it."])
})
