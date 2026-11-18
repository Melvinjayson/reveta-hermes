import type { ChatMessage } from '@/lib/chat-messages'

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
