import { type KeyboardEvent, useEffect, useRef, useState } from 'react'

import { Search, X } from '@/lib/icons'
import type { SessionInfo } from '@/types/hermes'

import { groupHistory } from './history'

interface AuraSearchDialogProps {
  open: boolean
  sessions: SessionInfo[]
  theme: string
  titleOf: (session: SessionInfo) => string
  onClose: () => void
  onOpen: (session: SessionInfo) => void
}

/** True for Cmd+K on Apple keyboards and Ctrl+K elsewhere. */
export function isSearchShortcut(event: { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean }) {
  return event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey) && !event.altKey
}

/** Title search over the conversations already loaded in this browser; no message bodies are searched. */
export function AuraSearchDialog({ open, sessions, theme, titleOf, onClose, onOpen }: AuraSearchDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const results = groupHistory(sessions, titleOf, query)
  const flat = results.flatMap(section => section.entries)

  useEffect(() => {
    const node = dialog.current

    if (open && node && !node.open) {
      setQuery('')
      setActive(0)
      node.showModal()
    }

    if (!open && node?.open) {
      node.close()
    }
  }, [open])

  const choose = (session: SessionInfo | undefined) => {
    if (session) {
      onOpen(session)
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
      choose(flat[active]?.session)
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
          aria-activedescendant={flat[active] ? `aura-search-${flat[active].session.id}` : undefined}
          aria-controls="aura-search-results"
          aria-expanded="true"
          aria-label="Search conversations"
          autoFocus
          onChange={event => {
            setQuery(event.target.value)
            setActive(0)
          }}
          onKeyDown={onKeyDown}
          placeholder="Search conversations"
          role="combobox"
          value={query}
        />
        <button aria-label="Close search" className="aura-icon-button" onClick={onClose} type="button">
          <X size={18} />
        </button>
      </div>
      <div className="aura-search-results" id="aura-search-results" role="listbox">
        {results.map(section => (
          <div aria-label={section.group} className="aura-search-group" key={section.group} role="group">
            <p className="aura-section-label">{section.group}</p>
            {section.entries.map(entry => {
              row += 1
              const index = row

              return (
                <div
                  aria-selected={index === active}
                  className="aura-search-option"
                  id={`aura-search-${entry.session.id}`}
                  key={entry.session.id}
                  onClick={() => choose(entry.session)}
                  onMouseMove={() => setActive(index)}
                  role="option"
                >
                  {entry.title}
                </div>
              )
            })}
          </div>
        ))}
        {!flat.length && (
          <p className="aura-empty-note" role="status">
            {sessions.length ? 'No conversation titles match.' : 'No conversations yet.'}
          </p>
        )}
      </div>
      <p className="aura-search-hint">Searches conversation titles. Enter opens, Esc closes.</p>
    </dialog>
  )
}
