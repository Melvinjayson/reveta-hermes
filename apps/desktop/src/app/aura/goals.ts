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

export function saveAuraGoal(key: string, text: string) {
  const trimmed = text.trim().slice(0, 500)
  const { [key]: _old, ...rest } = $auraGoals.get()
  $auraGoals.set(trimmed ? { ...rest, [key]: trimmed } : rest)
}

export function dismissAuraGoal(key: string, proposal: string) {
  $auraDismissedGoals.set({ ...$auraDismissedGoals.get(), [key]: proposal })
}
