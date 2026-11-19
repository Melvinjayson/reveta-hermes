import { useAuiState } from '@assistant-ui/react'

import { messageContentText } from '@/components/assistant-ui/thread/content'

import { auraSources } from './sources'

export function sourceHost(url: string) {
  return new URL(url).hostname.replace(/^www\./, '')
}

/** Numbered chips for the links a reply cites, in citation order. */
export function AuraMessageSources() {
  const content = useAuiState(state => state.message.content)

  const sources = auraSources(messageContentText(content))

  if (!sources.length) {
    return null
  }

  return (
    <nav aria-label="Sources for this reply" className="aura-sources">
      {sources.map(([url, label], index) => (
        <a aria-label={`Source ${index + 1}: ${label}`} href={url} key={url} rel="noreferrer" target="_blank">
          <span aria-hidden="true" className="aura-source-number">
            {index + 1}
          </span>
          <span className="aura-source-label">{label}</span>
          <span className="aura-source-host">{sourceHost(url)}</span>
        </a>
      ))}
    </nav>
  )
}
