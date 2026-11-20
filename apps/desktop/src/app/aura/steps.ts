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
  browser_navigate: 'Open a page',
  aura_fetch: 'Fetch a source',
  aura_browser: 'Read a page in the browser',
  aura_file: 'Work with a conversation file',
  aura_computer: 'Run a command in Aura’s workspace',
  aura_complex: 'Anthropic complex workflow',
  memory: 'Update memory',
  session_search: 'Search past chats',
  skills_list: 'Look up skills',
  skill_view: 'Read a skill',
  skill_manage: 'Change a skill',
  delegate_task: 'Hand off to a subagent',
  cronjob_manage: 'Change a scheduled job',
  clarify: 'Ask you a question',
  process_manage: 'Manage a background task',
  browser_exec: 'Use the browser',
  browser_cdp: 'Use the browser',
  browser_dialog: 'Answer a browser dialog',
  vision_analyze: 'Look at an image',
  image_generate: 'Create an image'
}

export interface AuraStep {
  id: string
  label: string
  /** Tool name for the activity icon; absent for non-tool steps. */
  tool?: string
  status: StepStatus
  timestamp?: number
  completedAt?: number
  facts: string[]
  detail?: { url?: string; command?: string; summary?: string }
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

const COST_REFUSAL = "This would cost money, so I didn't run it."

// tools/aura_model_routing.py REASONS: the only other refusal sentences a Refused row may show.
const ROUTING_REFUSALS = new Set([
    'Budget reached. Aura did not send this request.',
  'Model not permitted. Aura only uses the models set up for it.',
  'Model unavailable. No permitted model can take this request right now.',
  'Requested capability unavailable on the permitted models.',
  'The experimental test model is switched off on this deployment.',
  "Paid routing isn't switched on for this deployment.",
  "Aura couldn't check its budget, so it didn't send this paid request.",
  'Paid models are switched off in Settings → Model.',
  "Aura couldn't bound this request's cost, so it didn't send it."
])

/** The backend's own routing reason when it is one of the known sentences; never other text. */
function refusalReason(error: string | undefined): string {
  const text = (error ?? '').trim()

  return ROUTING_REFUSALS.has(text) ? text : COST_REFUSAL
}

/** A conservative projection: arbitrary payloads, commands and URLs may contain
 * credentials. Details exposes only allowlisted outcome facts, never raw text. */
export function auraSteps(messages: ChatMessage[]): AuraStep[] {
  return messages.filter(message => !message.hidden).flatMap<AuraStep>(message => {
    if (message.errorSurface?.code === 'aura_free_only_refused') {
      return [{ id: `${message.id}:cost-refusal`, label: 'Reply request', status: 'Refused' as const,
        timestamp: message.timestamp, completedAt: message.completedAt,
        facts: [refusalReason(message.error)] }]
    }

    if (message.role !== 'assistant') {return []}

    return message.parts.flatMap((part, index) => {
      if (part.type !== 'tool-call') {
        return []
      }

      const result = record(part.result)
      const display = part.toolName.startsWith('aura_') ? record(result.aura_display) : {}

      const detail = {
        url: typeof display.url === 'string' && /^https?:/.test(display.url) ? display.url : undefined,
        command: typeof display.command === 'string' ? display.command : undefined,
        summary: typeof display.summary === 'string' ? display.summary : undefined
      }

      const label = Object.hasOwn(STEP_NAMES, part.toolName)
        ? STEP_NAMES[part.toolName as keyof typeof STEP_NAMES]
        : 'Used a tool'

      const status = statusOf(part)
      const facts = [part.result === undefined ? 'No result received.' : 'A result was received.']

      if (result.status === 'refused' && result.error === "This would cost money, so I didn't run it.") {
        facts.push(result.error, 'Nothing was charged.')
      } else if (result.status === 'refused' && result.aura_policy === true && typeof result.error === 'string') {
        facts.push(result.error.slice(0, 200)) // fixed, server-authored policy text; never tool output
      }

      if (typeof result.exit_code === 'number' && Number.isFinite(result.exit_code)) {
        facts.push(`Exit code: ${result.exit_code}`)
      }

      if (status === 'Result received' || status === 'Unconfirmed') {
        facts.push('Success has not been confirmed.')
      }

      return [{
        id: `${message.id}:${part.toolCallId ?? index}`,
        label, tool: part.toolName, status, timestamp: part.timestamp, completedAt: part.completedAt, facts, detail
      }]
    })
  })
}
