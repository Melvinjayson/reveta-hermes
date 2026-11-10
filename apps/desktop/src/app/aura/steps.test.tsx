import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { ChatMessage } from '@/lib/chat-messages'

import { AuraSteps } from './step-history'
import { auraSteps, stepDuration } from './steps'

function messages(result?: unknown, extra = {}): ChatMessage[] {
  return [{ id: 'reply', role: 'assistant', parts: [{
    type: 'tool-call', toolCallId: 'call', toolName: 'terminal', args: { command: 'SECRET' },
    result, ...extra
  }] }]
}

it('requires explicit confirmation and never treats a queued receipt or missing result as done', () => {
  expect(auraSteps(messages())[0].status).toBe('Running')
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
  expect(stepDuration(step, 200)).toBe('3s')
  expect(auraSteps(JSON.parse(JSON.stringify(history)))).toEqual([step])
  expect(stepDuration(auraSteps(messages())[0], 200)).toBe('Timing unavailable')
})

it('uses generic unknown names and never exposes arbitrary credential-bearing payloads', () => {
  const history = messages({ output: 'SECRET', authorization: 'SECRET' }, { toolName: 'private_extension_SECRET' })
  const step = auraSteps(history)[0]
  expect(step.label).toBe('Used a tool')
  expect(auraSteps(messages({}, { toolName: 'constructor' }))[0].label).toBe('Used a tool')
  const { container } = render(<AuraSteps steps={[step]} />)
  fireEvent.click(screen.getByText('1 step'))
  fireEvent.click(screen.getByText('Details'))
  expect(container.textContent).not.toContain('SECRET')
  expect(screen.getByText('Success has not been confirmed.')).toBeTruthy()
})

it('does not manufacture steps from assistant prose or hidden content', () => {
  expect(auraSteps([{ id: 'x', role: 'assistant', parts: [{ type: 'text', text: 'I did it' }] }])).toEqual([])
  expect(auraSteps(messages({ exit_code: 0 }).map(message => ({ ...message, hidden: true })))).toEqual([])
})
