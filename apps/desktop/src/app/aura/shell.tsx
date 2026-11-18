import './tokens.css'
import './aura.css'
import './shell.css'
import './home.css'
import './thread.css'

import { useStore } from '@nanostores/react'
import { Menu, SquarePen } from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import type { WiringActions } from '@/app/contrib/types'
import { useStatusSnapshot } from '@/app/shell/hooks/use-status-snapshot'
import { useMediaQuery } from '@/hooks/use-media-query'
import { sessionTitle } from '@/lib/chat-runtime'
import { PanelLeftIcon, Plus, Search, Settings, X } from '@/lib/icons'
import { $activeGatewayProfile } from '@/store/profile'
import { $currentModel, $gatewayState, $selectedStoredSessionId, $sessions } from '@/store/session'
import { useTheme } from '@/themes'
import type { SessionInfo } from '@/types/hermes'

import { AuraConversationCards } from './conversation-cards'
import { AuraConversationRow } from './conversation-row'
import { groupHistory } from './history'
import { AuraContinueLater, AuraReadiness } from './readiness'
import { AuraSearchDialog, isSearchShortcut } from './search-dialog'
import { AuraSettingsDialog } from './settings-dialog'
import { auraSignOut } from './sign-out'
import { AuraToolsDialog } from './tools-menu'

interface AuraShellProps {
  actions: WiringActions
  children: ReactNode
}

interface AuraNavProps {
  activeId: null | string
  sessions: SessionInfo[]
  onClose?: () => void
  onCollapse?: () => void
  onDelete: (session: SessionInfo) => Promise<void> | void
  onNewChat: () => void
  onOpen: (session: SessionInfo) => void
  onSearch: () => void
  onSettings: () => void
}

/** The same navigation in the desktop sidebar and the phone drawer. */
function AuraNav({ activeId, sessions, onClose, onCollapse, onDelete, onNewChat, onOpen, onSearch, onSettings }: AuraNavProps) {
  const history = groupHistory(sessions, sessionTitle)

  return (
    <div className="aura-nav">
      <div className="aura-nav-top">
        <a className="aura-wordmark" href="#/">
          <img alt="" src="brand/aura-mark.svg" />
          Aura
        </a>
        {onCollapse && (
          <button aria-label="Collapse sidebar" className="aura-icon-button" onClick={onCollapse} type="button">
            <PanelLeftIcon size={18} />
          </button>
        )}
        {onClose && (
          <button aria-label="Close menu" className="aura-icon-button" onClick={onClose} type="button">
            <X size={18} />
          </button>
        )}
      </div>
      <nav aria-label="Main navigation" className="aura-nav-actions">
        <button className="aura-nav-item" onClick={onNewChat} type="button">
          <Plus size={18} />
          <span>New chat</span>
        </button>
        <button className="aura-nav-item" onClick={onSearch} type="button">
          <Search size={18} />
          <span>Search</span>
          <kbd aria-hidden="true">⌘K</kbd>
        </button>
      </nav>
      <div aria-label="Conversation history" className="aura-conversations" role="region">
        {history.map(section => (
          <section aria-label={section.group} key={section.group}>
            <h3 className="aura-section-label">{section.group}</h3>
            {section.entries.map(({ session, title }) => (
              <AuraConversationRow
                current={session.id === activeId}
                key={session.id}
                onDelete={() => onDelete(session)}
                onOpen={() => onOpen(session)}
                title={title}
              />
            ))}
          </section>
        ))}
        {!history.length && <p className="aura-empty-note">Your conversations will appear here.</p>}
      </div>
      <div className="aura-nav-footer">
        <button className="aura-nav-item" onClick={onSettings} type="button">
          <Settings size={18} />
          <span>Settings</span>
        </button>
      </div>
    </div>
  )
}

export function AuraShell({ actions, children }: AuraShellProps) {
  const wide = useMediaQuery('(min-width: 900px)')
  const [collapsed, setCollapsed] = useState(false)
  const [drawer, setDrawer] = useState(false)
  const [searching, setSearching] = useState(false)
  const [settings, setSettings] = useState(false)
  const [resumed, setResumed] = useState(false)
  const [error, setError] = useState('')
  const sessions = useStore($sessions)
  const activeId = useStore($selectedStoredSessionId)
  const gatewayState = useStore($gatewayState)
  const profile = useStore($activeGatewayProfile)
  const currentModel = useStore($currentModel)
  const { inferenceStatus } = useStatusSnapshot(gatewayState, actions.requestGateway, profile)
  const { mode, resolvedMode, setMode } = useTheme()
  const sheet = useRef<HTMLDialogElement>(null)
  const menu = useRef<HTMLButtonElement>(null)
  const location = useLocation()
  const navigate = useNavigate()
  const [lastConversationRoute, setLastConversationRoute] = useState('/')
  const activeTitle = sessions.find(session => session.id === activeId)

  useEffect(() => {
    // The shared /settings route opens Aura's own settings over the current chat.
    if (location.pathname.startsWith('/settings')) {
      setSettings(true)
      navigate(lastConversationRoute, { replace: true })
    } else if (lastConversationRoute !== location.pathname) {
      setLastConversationRoute(location.pathname)
    }
  }, [lastConversationRoute, location.pathname, navigate])

  useEffect(() => {
    const node = sheet.current

    if (drawer && node && !node.open) {
      node.showModal()
    }

    if (!drawer && node?.open) {
      node.close()
    }
  }, [drawer])

  useEffect(() => {
    if (wide) {
      setDrawer(false)
    }
  }, [wide])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isSearchShortcut(event)) {
        event.preventDefault()
        setDrawer(false)
        setSearching(true)
      }
    }

    window.addEventListener('keydown', onKey)

    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    const viewport = window.visualViewport

    const update = () =>
      document.documentElement.style.setProperty('--aura-viewport', `${viewport?.height ?? window.innerHeight}px`)

    update()
    viewport?.addEventListener('resize', update)

    return () => viewport?.removeEventListener('resize', update)
  }, [])

  const closeDrawer = () => {
    setDrawer(false)
    menu.current?.focus()
  }

  const newChat = () => {
    actions.onNavigate({ id: 'new-session', action: 'new-session', label: 'New chat', icon: Plus })
    setResumed(false)
    setDrawer(false)
  }

  const resumeById = (id: string, session?: SessionInfo) => {
    actions.onResumeSession(id, session)
    setResumed(true)
    setDrawer(false)
    setSearching(false)
  }

  const openSession = (session: SessionInfo) => resumeById(session.id, session)

  const showHistory = () => (wide ? setCollapsed(false) : setDrawer(true))

  const navProps = {
    activeId,
    sessions,
    onDelete: (session: SessionInfo) => actions.onDeleteSession(session.id),
    onNewChat: newChat,
    onOpen: openSession,
    onSearch: () => {
      setDrawer(false)
      setSearching(true)
    },
    onSettings: () => {
      setDrawer(false)
      setSettings(true)
    }
  }

  return (
    <div className="aura-app" data-aura-collapsed={(wide && collapsed) || undefined} data-aura-theme={resolvedMode}>
      <div className="aura-workspace">
        <aside aria-label="Conversation navigation" className="aura-rail" data-collapsed={collapsed || undefined}>
          <AuraNav {...navProps} onCollapse={() => setCollapsed(true)} />
        </aside>
        <main aria-label="Conversation" className="aura-chat">
          <header className="aura-header">
            <button
              aria-expanded={wide ? !collapsed : drawer}
              aria-label="Open menu"
              className="aura-icon-button aura-menu-button"
              onClick={() => (wide ? setCollapsed(!collapsed) : setDrawer(true))}
              ref={menu}
              type="button"
            >
              {wide ? <PanelLeftIcon size={18} /> : <Menu size={20} />}
            </button>
            <a className="aura-wordmark aura-header-mark" href="#/">
              <img alt="" src="brand/aura-mark.svg" />
              Aura
            </a>
            <p className="aura-header-title">{activeTitle ? sessionTitle(activeTitle) : ''}</p>
            <button aria-label="New chat" className="aura-icon-button aura-header-new" onClick={newChat} type="button">
              <SquarePen size={19} />
            </button>
          </header>
          <AuraReadiness
            value={
              currentModel === 'aura-not-connected' || inferenceStatus?.model === 'aura-not-connected'
                ? false
                : (inferenceStatus?.ready ?? null)
            }
          >
            <AuraConversationCards resumed={resumed} />
            <AuraContinueLater value={showHistory}>{children}</AuraContinueLater>
          </AuraReadiness>
        </main>
      </div>
      <dialog
        aria-label="Aura menu"
        className="aura-sheet aura-drawer"
        onCancel={event => {
          event.preventDefault()
          closeDrawer()
        }}
        onClick={event => event.target === sheet.current && closeDrawer()}
        ref={sheet}
      >
        <AuraNav {...navProps} onClose={closeDrawer} />
      </dialog>
      <AuraSearchDialog
        onClose={() => setSearching(false)}
        onOpen={resumeById}
        open={searching}
        sessions={sessions}
        theme={resolvedMode}
        titleOf={sessionTitle}
      />
      <AuraToolsDialog theme={resolvedMode} />
      <AuraSettingsDialog
        mode={mode as 'light' | 'dark' | 'system'}
        onClose={() => setSettings(false)}
        onMode={setMode}
        onSignOut={() => {
          setError('')
          void auraSignOut().catch(() => setError('Sign out could not finish. Please try again.'))
        }}
        open={settings}
        signOutError={error}
        theme={resolvedMode}
      />
    </div>
  )
}
