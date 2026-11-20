import type { ChatMessagePart } from '@/lib/chat-messages'
import { coerceGatewayText } from '@/lib/chat-runtime'

import type { GatewayEventContext } from './types'

export function handleVoicePlaybackEvent(ctx: GatewayEventContext): boolean {
  const { event, sessionId, payload, deps } = ctx
  const { flushQueuedDeltas, updateSessionState, sessionStateByRuntimeIdRef } = deps

  if (event.type === 'message.voice_played' && sessionId) {
    flushQueuedDeltas(sessionId)

    if (payload?.interrupted === true && typeof payload.turn_id === 'string') {
      updateSessionState(sessionId, state => {
        const anchor = state.messages.findIndex(message => message.id === `user-${payload.turn_id}`)

        if (anchor < 0) { return state }
        const nextUser = state.messages.findIndex((message, at) => at > anchor && message.role === 'user')
        let index = -1

        const messages = state.messages.map((message, at) => {
          if (at <= anchor || (nextUser >= 0 && at >= nextUser) || message.role !== 'assistant' || !message.parts.some(part => part.type === 'text')) { return message }
          index++

          if (index !== payload.message_index) { return message }
          let added = false

          const parts = message.parts.flatMap<ChatMessagePart>(part => {
            if (part.type !== 'text') { return [part] }

            if (added) { return [] }
            added = true

            return [{ ...part, text: coerceGatewayText(payload.text) }]
          })

          return { ...message, parts, interrupted: true }
        })

        return { ...state, messages, voiceInterrupted: state.voiceInterrupted || nextUser < 0 }
      })
    }

    return true
  }

  if (sessionId && sessionStateByRuntimeIdRef.current.get(sessionId)?.voiceInterrupted &&
      (event.type === 'message.delta' || event.type === 'message.interim')) { return true }

  return false
}
