import './aura.css'

import { useStore } from '@nanostores/react'
import { Menu } from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import type { WiringActions } from '@/app/contrib/types'
import { useStatusSnapshot } from '@/app/shell/hooks/use-status-snapshot'
import { useMediaQuery } from '@/hooks/use-media-query'
import { sessionTitle } from '@/lib/chat-runtime'
import { Plus, Search, Settings, X } from '@/lib/icons'
import { $activeGatewayProfile } from '@/store/profile'
import { $currentModel, $gatewayState, $sessions } from '@/store/session'
import { useTheme } from '@/themes'

import { AuraConversationCards } from './conversation-cards'
import { AuraContinueLater, AuraReadiness } from './readiness'
import { auraSignOut } from './sign-out'

export function conversationGroup(seconds: number, now = new Date()) {
  const day = new Date(seconds * 1000)
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)

  if (day.toDateString() === now.toDateString()) {
    return 'Today'
  }

  if (day.toDateString() === yesterday.toDateString()) {
    return 'Yesterday'
  }

  return 'Earlier'
}

export function AuraShell({ actions, children }: { actions: WiringActions; children: ReactNode }) {
  const wide = useMediaQuery('(min-width: 900px)')
  const [collapsed, setCollapsed] = useState(false)
  const [open, setOpen] = useState(false)
  const [panel, setPanel] = useState('Conversations')
  const [resumed, setResumed] = useState(false)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const sessions = useStore($sessions)
  const gatewayState = useStore($gatewayState)
  const profile = useStore($activeGatewayProfile)
  const currentModel = useStore($currentModel)
  const { inferenceStatus } = useStatusSnapshot(gatewayState, actions.requestGateway, profile)
  const { mode, resolvedMode, setMode } = useTheme()
  const dialog = useRef<HTMLDialogElement>(null)
  const menu = useRef<HTMLButtonElement>(null)
  const location = useLocation()
  const navigate = useNavigate()
  const [lastConversationRoute, setLastConversationRoute] = useState('/')

  useEffect(() => {
    if (location.pathname.startsWith('/settings')) {
      setPanel('Settings')

      if (wide) {
        setCollapsed(false)
      } else {
        setOpen(true)
      }

      navigate(lastConversationRoute, { replace: true })
    } else if (lastConversationRoute !== location.pathname) {
      setLastConversationRoute(location.pathname)
    }
  }, [lastConversationRoute, location.pathname, navigate, wide])

  useEffect(() => {
    const node = dialog.current

    if (open && node && !node.open) {
      node.showModal()
    }

    if (!open && node?.open) {
      node.close()
    }
  }, [open])

  useEffect(() => {
    const viewport = window.visualViewport

    const update = () =>
      document.documentElement.style.setProperty('--aura-viewport', `${viewport?.height ?? window.innerHeight}px`)

    update()
    viewport?.addEventListener('resize', update)

    return () => viewport?.removeEventListener('resize', update)
  }, [])

  const close = () => {
    setOpen(false)
    menu.current?.focus()
  }

  const newChat = () => {
    actions.onNavigate({ id: 'new-session', action: 'new-session', label: 'New conversation', icon: Plus })
    setResumed(false)
    close()
  }

  const nav = (
    <>
      <div className="aura-nav-title">
        <span>A little room to think.</span>
        <button aria-label="Close menu" onClick={close} type="button">
          <X size={20} />
        </button>
      </div>
      <nav aria-label="Main navigation">
        {['Conversations', 'Search', 'Settings'].map(label => (
          <button
            aria-current={panel === label ? 'page' : undefined}
            key={label}
            onClick={() => setPanel(label)}
            type="button"
          >
            {label === 'Search' ? (
              <Search size={18} />
            ) : label === 'Settings' ? (
              <Settings size={18} />
            ) : (
              <Plus size={18} />
            )}
            {label}
          </button>
        ))}
      </nav>
      {panel === 'Settings' ? (
        <section className="aura-settings">
          <h2>Make yourself at home</h2>
          <label>
            Appearance
            <select onChange={e => setMode(e.target.value as 'light' | 'dark' | 'system')} value={mode}>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
              <option value="system">Follow device</option>
            </select>
          </label>
          <h2>Model connection</h2>
          <p>
            {currentModel !== 'aura-not-connected' && inferenceStatus?.ready
              ? 'Your workspace is ready to reply.'
              : 'Aura can’t reply yet. A model still needs to be connected.'}
          </p>
          <p>
            Your workspace operator connects OpenRouter free models first, then Gemini’s free tier, using environment
            variables. Keys are never entered in chat.
          </p>
          <p>Anthropic is disabled. Enabling paid models requires an enforced spending cap.</p>
          <p>Voice is coming soon.</p>
          <p>Aura by Reveta</p>
        </section>
      ) : (
        <section className="aura-conversations">
          <h2>{panel}</h2>
          {panel === 'Search' && (
            <input
              aria-label="Search conversations"
              onChange={e => setQuery(e.target.value)}
              placeholder="Find a conversation…"
              value={query}
            />
          )}
          <button onClick={newChat} type="button">
            <Plus size={18} />
            New conversation
          </button>
          {['Today', 'Yesterday', 'Earlier'].map(group => (
            <section aria-label={group} key={group}>
              <h3>{group}</h3>
              {sessions
                .filter(s => conversationGroup(s.last_active || s.started_at) === group)
                .filter(s => sessionTitle(s).toLowerCase().includes(query.toLowerCase()))
                .map(s => (
                  <button
                    key={s.id}
                    onClick={() => {
                      actions.onResumeSession(s.id, s)
                      setResumed(true)
                      close()
                    }}
                    type="button"
                  >
                    {sessionTitle(s)}
                  </button>
                ))}
            </section>
          ))}
          {!sessions.length && <p>Your conversations will appear here.</p>}
        </section>
      )}
      <button
        className="aura-signout"
        onClick={() => {
          void auraSignOut().catch(() => setError('Sign out could not finish. Please try again.'))
        }}
        type="button"
      >
        Sign out
      </button>
      {error && <p role="alert">{error}</p>}
    </>
  )

  return (
    <div className="aura-app" data-aura-theme={resolvedMode}>
      <header className="aura-header">
        <button
          aria-expanded={wide ? !collapsed : open}
          aria-label="Open menu"
          onClick={() => {
            if (wide) {
              setCollapsed(!collapsed)
            } else {
              setOpen(true)
            }
          }}
          ref={menu}
          type="button"
        >
          <Menu size={21} />
        </button>
        <a className="aura-wordmark" href="#/">
          <img alt="" src="brand/aura-mark.svg" />
          Aura
        </a>
        <button aria-label="New conversation" onClick={newChat} type="button">
          <Plus size={23} />
        </button>
      </header>
      <div className="aura-workspace">
        <aside aria-label="Conversation navigation" className="aura-rail" data-collapsed={collapsed || undefined}>
          {nav}
        </aside>
        <main aria-label="Conversation" className="aura-chat">
          <AuraReadiness
            value={
              currentModel === 'aura-not-connected' || inferenceStatus?.model === 'aura-not-connected'
                ? false
                : (inferenceStatus?.ready ?? null)
            }
          >
            <AuraConversationCards resumed={resumed} />
            <AuraContinueLater
              value={() => {
                setPanel('Conversations')

                if (wide) {
                  setCollapsed(false)
                } else {
                  setOpen(true)
                }
              }}
            >
              {children}
            </AuraContinueLater>
          </AuraReadiness>
        </main>
      </div>
      <dialog
        aria-label="Aura menu"
        className="aura-sheet"
        onCancel={() => setOpen(false)}
        onClick={e => {
          if (e.target === dialog.current) {
            close()
          }
        }}
        ref={dialog}
      >
        <div>{nav}</div>
      </dialog>
    </div>
  )
}
