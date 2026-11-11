import { useStore } from '@nanostores/react'

import { sessionFileOwnerScope } from '@/api/client'
import type { ChatMessage } from '@/lib/chat-messages'
import { downloadGatewayFileWithFeedback } from '@/lib/media'
import { $activeSessionId, $selectedStoredSessionId } from '@/store/session'

import { AuraCard } from './card'

export function resultRecord(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') {
    try { return resultRecord(JSON.parse(value)) } catch { return {} }
  }

  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export function auraFiles(messages: ChatMessage[]) {
  return messages.filter(message => !message.hidden).flatMap(message => message.parts.flatMap(part => {
    if (part.type !== 'tool-call' || !['aura_file', 'aura_browser'].includes(part.toolName)) { return [] }
    const result = resultRecord(part.result)
    const file = resultRecord(result.file)

    return !result.error && typeof file.path === 'string' && typeof file.name === 'string' && typeof file.bytes === 'number'
      ? [{ path: file.path, name: file.name, bytes: file.bytes }]
      : []
  }))
}

export function AuraFiles({ messages }: { messages: ChatMessage[] }) {
  const active = useStore($activeSessionId)
  const stored = useStore($selectedStoredSessionId)
  const sessionId = stored ?? active ?? undefined
  const owner = sessionId ? sessionFileOwnerScope(sessionId) ?? undefined : undefined
  const files = [...new Map(auraFiles(messages).map(file => [file.path, file])).values()]

  return files.map(file => (
    <AuraCard key={file.path} kind="file" title={file.name}>
      <p>{file.bytes} bytes · Created in this conversation’s workspace</p>
      <button onClick={() => { void downloadGatewayFileWithFeedback(file.path, { sessionId, owner, suggestedName: file.name }) }} type="button">
        Download {file.name}
      </button>
    </AuraCard>
  ))
}
