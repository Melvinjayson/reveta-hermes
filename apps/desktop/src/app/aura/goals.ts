import { computed } from 'nanostores'

import { type ChatMessage, chatMessageText } from '@/lib/chat-messages'
import { Codecs, persistentAtom } from '@/lib/persisted'
import { $activeSessionId, $selectedStoredSessionId } from '@/store/session'

/** Confirmed goals, one per conversation, on this device (the same localStorage choke point as other prefs). */
export const $auraGoals = persistentAtom('aura.goals.v1', {} as Record<string, string>, Codecs.stringRecord)
/** The proposal text the user waved away per conversation, so the same suggestion is not offered again. */
export const $auraDismissedGoals = persistentAtom('aura.goals.dismissed.v1', {} as Record<string, string>, Codecs.stringRecord)

export const $auraGoalKey = computed(
  [$selectedStoredSessionId, $activeSessionId],
  (stored, active) => stored ?? active ?? null
)

// Aura's prompt asks it to offer a goal only after the intent is clear, on one line: "Proposed goal: …".
const PROPOSAL = /^\s*(?:[-*]\s*)?(?:\*\*)?proposed goal:?(?:\*\*)?:?\s*(.+?)\s*$/im

export function auraGoalProposal(messages: ChatMessage[]): null | string {
  const reply = [...messages].reverse().find(message => message.role === 'assistant' && chatMessageText(message))
  const match = reply ? PROPOSAL.exec(chatMessageText(reply)) : null
  const text = match?.[1]?.replace(/\*\*$/, '').trim()

  return text ? text.slice(0, 500) : null
}

export interface AuraReplyHints {
  /** Short label for what Aura's last reply is doing, inferred from its text (shown with an "AI" mark). */
  tag: null | string
  /** One-tap answers to the question Aura ended on; tapping sends that text as your reply. */
  replies: string[]
}

const LEAD_IN =
  /^(?:so,?\s+)?(?:do you want(?: me)? to|would you (?:like|prefer)(?: me)? to|would you rather|should i|shall i|do you prefer|want me to|is it|are you|which (?:one|would you like|do you want)\s*[:,-]?)\s+/i

// "start with the X or the Y": the verb belongs to every option, so the chip is just "X".
const SHARED_VERB =
  /^(?:start|begin|go|focus|work|plan|do|try|use|pick|build|write|draft|look)(?:\s+(?:with|on|at|for|about|into))?\s+/i

const YES_NO = /^(?:so,?\s+)?(?:do|does|did|should|shall|can|could|would|will|is|are|was|want|ready|okay|ok)\b/i

function lastQuestion(text: string): null | string {
  const lines = text.trim().split('\n').filter(line => line.trim())
  const tail = lines.at(-1)?.trim() ?? ''

  if (!tail.endsWith('?')) {
    return null
  }

  const sentences = tail.split(/(?<=[.!?])\s+/)

  return sentences.at(-1)!.replace(/[*_`]/g, '').slice(0, -1).trim()
}

function options(question: string): string[] {
  const body = (question.includes(':') ? question.slice(question.lastIndexOf(':') + 1) : question)
    .trim()
    .replace(LEAD_IN, '')
    .replace(SHARED_VERB, '')

  if (!/\bor\b/i.test(body)) {
    return []
  }

  const parts = body
    .split(/,\s*(?:or\s+)?|\s+or\s+/i)
    .map(part => part.replace(/^(?:the|a|an)\s+/i, '').trim())
    .filter(Boolean)

  const fit = parts.length >= 2 && parts.length <= 4 && parts.every(part => part.length <= 40 && part.split(/\s+/).length <= 6)

  return fit ? parts.map(part => part[0]!.toUpperCase() + part.slice(1)) : []
}

/**
 * Tag and quick replies built from Aura's own last reply: no extra model call. Nothing is shown
 * while Aura is working, after you have answered, or when the goal card already asks the question.
 */
export function auraReplyHints(messages: ChatMessage[], busy: boolean): AuraReplyHints {
  const visible = messages.filter(message => !message.hidden && (message.role === 'user' || message.role === 'assistant'))
  const last = visible.at(-1)
  const text = last?.role === 'assistant' ? chatMessageText(last) : ''

  if (busy || !text) {
    return { replies: [], tag: null }
  }

  if (PROPOSAL.test(text)) {
    return { replies: [], tag: null } // the goal card asks this one
  }

  const question = lastQuestion(text)

  if (!question) {
    return { replies: [], tag: null }
  }

  const choices = options(question)

  return {
    replies: choices.length ? choices : YES_NO.test(question) ? ['Yes', 'Not yet'] : [],
    tag: 'Asking you'
  }
}

export function saveAuraGoal(key: string, text: string) {
  const trimmed = text.trim().slice(0, 500)
  const { [key]: _old, ...rest } = $auraGoals.get()
  $auraGoals.set(trimmed ? { ...rest, [key]: trimmed } : rest)
}

export function dismissAuraGoal(key: string, proposal: string) {
  $auraDismissedGoals.set({ ...$auraDismissedGoals.get(), [key]: proposal })
}
