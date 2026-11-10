import type { ToolTitleKey } from '@/i18n'
import type { ChatMessage } from '@/lib/chat-messages'

export type StepStatus = 'Queued' | 'Running' | 'Failed' | 'Done' | 'Stopped' | 'Result received' | 'Unconfirmed' | 'Refused'

// Keys are checked against the existing runtime presentation registry. Unknown
// extensions stay generic rather than exposing their internal identifiers.
const STEP_NAMES = {
  terminal: 'Run a command in Aura’s workspace',
  execute_code: 'Run a calculation',
  read_file: 'Read a file',
  write_file: 'Write a file',
  patch: 'Change a file',
  web_search: 'Search the web',
  web_extract: 'Read a page',
  browser_navigate: 'Open a page'
} satisfies Partial<Record<ToolTitleKey, string>>

export interface AuraStep {
  id: string
  label: string
  status: StepStatus
  timestamp?: number
  completedAt?: number
  facts: string[]
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') {
    try {
      return record(JSON.parse(value))
    } catch {
      return {}
    }
  }

  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function statusOf(part: { result?: unknown; isError?: boolean; interrupted?: boolean; completedAt?: number }): StepStatus {
  const result = record(part.result)

  if (result.status === 'refused') {
    return 'Refused'
  }

  if (part.interrupted || result.status === 'cancelled' || result.status === 'stopped') {
    return 'Stopped'
  }

  if (
    part.isError || result.error || result.success === false || result.ok === false ||
    (typeof result.exit_code === 'number' && result.exit_code !== 0) || result.status === 'failed'
  ) {
    return 'Failed'
  }

  if (result.status === 'queued') {
    return 'Queued'
  }

  if (result.status === 'running' || result.status === 'pending') {
    return 'Running'
  }

  if (part.result === undefined) {
    return part.completedAt === undefined ? 'Running' : 'Unconfirmed'
  }

  if (
    result.success === true || result.ok === true || result.exit_code === 0 ||
    result.status === 'completed' || result.status === 'success'
  ) {
    return 'Done'
  }

  return 'Result received'
}

/** A conservative projection: arbitrary payloads, commands and URLs may contain
 * credentials. Details exposes only allowlisted outcome facts, never raw text. */
export function auraSteps(messages: ChatMessage[]): AuraStep[] {
  return messages.filter(message => message.role === 'assistant' && !message.hidden).flatMap(message =>
    message.parts.flatMap((part, index) => {
      if (part.type !== 'tool-call') {
        return []
      }

      const result = record(part.result)

      const label = Object.hasOwn(STEP_NAMES, part.toolName)
        ? STEP_NAMES[part.toolName as keyof typeof STEP_NAMES]
        : 'Used a tool'

      const status = statusOf(part)
      const facts = [part.result === undefined ? 'No result received.' : 'A result was received.']

      if (typeof result.exit_code === 'number' && Number.isFinite(result.exit_code)) {
        facts.push(`Exit code: ${result.exit_code}`)
      }

      if (status === 'Result received' || status === 'Unconfirmed') {
        facts.push('Success has not been confirmed.')
      }

      return [{
        id: `${message.id}:${part.toolCallId ?? index}`,
        label, status, timestamp: part.timestamp, completedAt: part.completedAt, facts
      }]
    })
  )
}

export function stepDuration(step: AuraStep, now: number): string {
  if (step.timestamp === undefined) {
    return 'Timing unavailable'
  }

  const end = step.completedAt ?? (step.status === 'Running' ? now : undefined)

  if (end === undefined) {
    return 'Timing unavailable'
  }

  return `${Math.max(0, Math.floor(end - step.timestamp))}s`
}
