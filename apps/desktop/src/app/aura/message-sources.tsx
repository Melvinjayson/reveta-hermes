import { useAuiState } from '@assistant-ui/react'

import { messageContentText } from '@/components/assistant-ui/thread/content'

import { auraSources } from './sources'

export function AuraMessageSources() {
  const content = useAuiState(state => state.message.content)

  const sources = auraSources(messageContentText(content))

  if (!sources.length) {
    return null
  }

  return (
    <nav aria-label="Sources for this reply" className="aura-sources">
      {sources.map(([url, label]) => (
        <a href={url} key={url} rel="noreferrer" target="_blank">
          {label} ↗
        </a>
      ))}
    </nav>
  )
}
