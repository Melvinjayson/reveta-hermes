import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from 'react'

import { searchSessions } from '@/api/sessions'
import { Search, X } from '@/lib/icons'
import type { SessionInfo, SessionSearchResult } from '@/types/hermes'

import { groupHistory } from './history'

interface AuraSearchDialogProps {
  open: boolean
  sessions: SessionInfo[]
  theme: string
  titleOf: (session: SessionInfo) => string
  onClose: () => void
  onOpen: (id: string, session?: SessionInfo) => void
  /** Injected for tests; defaults to the server's full-text message search. */
  search?: (query: string) => Promise<{ results: SessionSearchResult[] }>
}

/** True for Cmd+K on Apple keyboards and Ctrl+K elsewhere. */
export function isSearchShortcut(event: { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean }) {
  return event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey) && !event.altKey
}

/** The server marks matches with >>> and <<< (SQLite FTS snippet); render them as <mark>. */
export function highlightSnippet(snippet: string): ReactNode[] {
  return snippet.split(/(>>>.*?<<<)/g).filter(Boolean).map((part, index) =>
    part.startsWith('>>>') && part.endsWith('<<<') ? <mark key={index}>{part.slice(3, -3)}</mark> : part
  )
}

const MESSAGE_SEARCH_MIN = 2
const MESSAGE_SEARCH_DELAY_MS = 250

interface Option {
  id: string
  session?: SessionInfo
  label: ReactNode
  detail?: ReactNode
}

/** Titles of loaded conversations, plus the server's full-text search inside message text. */
export function AuraSearchDialog({ open, sessions, theme, titleOf, onClose, onOpen, search = searchSessions }: AuraSearchDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const request = useRef(0)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [hits, setHits] = useState<SessionSearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [failed, setFailed] = useState(false)
  const byId = new Map(sessions.map(session => [session.id, session]))
  const titles = groupHistory(sessions, titleOf, query)

  useEffect(() => {
    const node = dialog.current

    if (open && node && !node.open) {
      setQuery('')
      setActive(0)
      setHits([])
      node.showModal()
    }

    if (!open && node?.open) {
      node.close()
    }
  }, [open])

  useEffect(() => {
    const text = query.trim()
    const token = ++request.current

    if (text.length < MESSAGE_SEARCH_MIN) {
      setHits([])
      setSearching(false)

      return
    }

    setSearching(true)

    const timer = window.setTimeout(() => {
      search(text)
        .then(response => {
          if (token === request.current) {
            setHits(response.results ?? [])
            setFailed(false)
          }
        })
        .catch(() => token === request.current && setFailed(true))
        .finally(() => token === request.current && setSearching(false))
    }, MESSAGE_SEARCH_DELAY_MS)

    return () => window.clearTimeout(timer)
  }, [query, search])

  const sections: { label: string; options: Option[] }[] = [
    ...titles.map(section => ({
      label: section.group,
      options: section.entries.map(entry => ({ id: entry.session.id, session: entry.session, label: entry.title }))
    })),
    {
      label: 'In messages',
      options: hits.map(hit => {
        const session = byId.get(hit.session_id)

        return {
          id: hit.session_id,
          session,
          label: session ? titleOf(session) : 'Conversation',
          detail: highlightSnippet(hit.snippet)
        }
      })
    }
  ].filter(section => section.options.length > 0)

  const flat = sections.flatMap(section => section.options)

  const choose = (option: Option | undefined) => {
    if (option) {
      onOpen(option.id, option.session)
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive(index => Math.min(flat.length - 1, index + 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive(index => Math.max(0, index - 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      choose(flat[active])
    }
  }

  let row = -1

  return (
    <dialog
      aria-label="Search conversations"
      className="aura-dialog aura-search"
      data-aura-theme={theme}
      onCancel={event => {
        event.preventDefault()
        onClose()
      }}
      onClick={event => event.target === dialog.current && onClose()}
      ref={dialog}
    >
      <div className="aura-search-field">
        <Search aria-hidden="true" size={18} />
        <input
          aria-activedescendant={flat[active] ? `aura-search-option-${active}` : undefined}
          aria-controls="aura-search-results"
          aria-expanded="true"
          aria-label="Search conversations"
          autoFocus
          onChange={event => {
            setQuery(event.target.value)
            setActive(0)
          }}
          onKeyDown={onKeyDown}
          placeholder="Search titles and messages"
          role="combobox"
          value={query}
        />
        <button aria-label="Close search" className="aura-icon-button" onClick={onClose} type="button">
          <X size={18} />
        </button>
      </div>
      <div className="aura-search-results" id="aura-search-results" role="listbox">
        {sections.map(section => (
          <div aria-label={section.label} className="aura-search-group" key={section.label} role="group">
            <p className="aura-section-label">{section.label}</p>
            {section.options.map(option => {
              row += 1
              const index = row

              return (
                <div
                  aria-selected={index === active}
                  className="aura-search-option"
                  data-has-detail={option.detail ? '' : undefined}
                  id={`aura-search-option-${index}`}
                  key={`${section.label}:${option.id}:${index}`}
                  onClick={() => choose(option)}
                  onMouseMove={() => setActive(index)}
                  role="option"
                >
                  <span className="aura-search-title">{option.label}</span>
                  {option.detail && <span className="aura-search-snippet">{option.detail}</span>}
                </div>
              )
            })}
          </div>
        ))}
        {searching && <p className="aura-empty-note" role="status">Searching messages…</p>}
        {failed && !searching && (
          <p className="aura-empty-note" role="alert">
            Message search is unavailable right now. Title matches still work.
          </p>
        )}
        {!flat.length && !searching && !failed && (
          <p className="aura-empty-note" role="status">
            {!sessions.length ? 'No conversations yet.' : query.trim() ? 'Nothing matches.' : 'Type to search.'}
          </p>
        )}
      </div>
      <p className="aura-search-hint">Searches titles and message text. Enter opens, Esc closes.</p>
    </dialog>
  )
}
