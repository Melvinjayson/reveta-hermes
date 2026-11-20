import './tokens.css'
import './aura.css'
import './shell.css'
import './home.css'
import './thread.css'
import './look.css'
import './panel.css'

import { useStore } from '@nanostores/react'
import { Menu, PanelRight, SquarePen } from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { COMPOSER_AREAS } from '@/app/chat/composer/contrib'
import type { WiringActions } from '@/app/contrib/types'
import { useStatusSnapshot } from '@/app/shell/hooks/use-status-snapshot'
import { Contribute } from '@/contrib/react/contribute'
import { useMediaQuery } from '@/hooks/use-media-query'
import { sessionTitle } from '@/lib/chat-runtime'
import { FolderOpen, PanelLeftIcon, Plus, Search, Settings, X } from '@/lib/icons'
import { $activeGatewayProfile } from '@/store/profile'
import { $currentModel, $gatewayState, $selectedStoredSessionId, $sessions } from '@/store/session'
import { useTheme } from '@/themes'
import type { SessionInfo } from '@/types/hermes'

import { AuraBrowserHandoff } from './browser-handoff'
import { AuraConversationCards } from './conversation-cards'
import { AuraConversationRow } from './conversation-row'
import { AuraDictation } from './dictation'
import { groupHistory } from './history'
import { AuraModelChip } from './model-chip'
import { $auraPanel, closeAuraPanel, openAuraPanel } from './panel-store'
import { AuraProjectDialog } from './project-dialog'
import { $auraProjects, type AuraProject, loadAuraProjects, startAuraProjectChat } from './projects'
import { AuraContinueLater, AuraReadiness } from './readiness'
import { AuraSearchDialog, isSearchShortcut } from './search-dialog'
import { AuraSettingsDialog } from './settings-dialog'
import { $auraSettingsRequest } from './settings-request'
import { AuraSidePanel } from './side-panel'
import { auraSignOut } from './sign-out'
import { AuraToolsDialog } from './tools-menu'

interface AuraShellProps {
  actions: WiringActions
  children: ReactNode
}

interface AuraNavProps {
  activeId: null | string
  projects: AuraProject[] | null
  sessions: SessionInfo[]
  onProject: (id: string) => void
  onClose?: () => void
  onCollapse?: () => void
  onDelete: (session: SessionInfo) => Promise<void> | void
  onNewChat: () => void
  onOpen: (session: SessionInfo) => void
  onSearch: () => void
  onSettings: () => void
}

/** The same navigation in the desktop sidebar and the phone drawer. */
function AuraNav({ activeId, projects, sessions, onProject, onClose, onCollapse, onDelete, onNewChat, onOpen, onSearch, onSettings }: AuraNavProps) {
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
        <section aria-label="Projects" className="aura-projects">
          <div className="aura-projects-head">
            <h3 className="aura-section-label">Projects</h3>
            <button aria-label="New project" className="aura-icon-button" onClick={() => onProject('new')} type="button">
              <Plus size={16} />
            </button>
          </div>
          {(projects ?? []).map(project => (
            <button className="aura-project-item" key={project.id} onClick={() => onProject(project.id)} type="button">
              <FolderOpen aria-hidden="true" size={16} />
              <span>{project.name}</span>
              <span className="aura-muted">{project.session_ids.length || ''}</span>
            </button>
          ))}
          {projects && !projects.length && <p className="aura-empty-note">Group related chats into a project.</p>}
        </section>
        {history.length > 0 && <h3 className="aura-section-label aura-recent-label">Recent</h3>}
        {history.map(section => (
          <section aria-label={section.group} key={section.group}>
            <h4 className="aura-section-label aura-history-group">{section.group}</h4>
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
  const roomy = useMediaQuery('(min-width: 1200px)')
  const panel = useStore($auraPanel)
  const [collapsed, setCollapsed] = useState(false)
  const [drawer, setDrawer] = useState(false)
  const [searching, setSearching] = useState(false)
  const [settings, setSettings] = useState(false)
  const settingsRequest = useStore($auraSettingsRequest)
  const [resumed, setResumed] = useState(false)
  const [error, setError] = useState('')
  const [project, setProject] = useState<null | string>(null)
  const projects = useStore($auraProjects)
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
    void loadAuraProjects()
  }, [])

  // A chat filed into a project by the server (first reply) shows up in the sidebar count.
  useEffect(() => {
    if (activeId) {
      void loadAuraProjects()
    }
  }, [activeId])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isSearchShortcut(event)) {
        // Capture phase: the shared app binds this chord too; inside Aura it opens Aura's search.
        event.preventDefault()
        event.stopImmediatePropagation()
        setDrawer(false)
        setSearching(true)
      }
    }

    window.addEventListener('keydown', onKey, true)

    return () => window.removeEventListener('keydown', onKey, true)
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
    projects,
    sessions,
    onProject: (id: string) => {
      setDrawer(false)
      setProject(id)
    },
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
            <div className="aura-header-actions">
              <button
                aria-expanded={Boolean(panel)}
                aria-label={panel ? 'Close side panel' : 'Open side panel'}
                className="aura-icon-button"
                onClick={() => (panel ? closeAuraPanel() : openAuraPanel('work'))}
                type="button"
              >
                <PanelRight size={19} />
              </button>
              <button aria-label="New chat" className="aura-icon-button aura-header-new" onClick={newChat} type="button">
                <SquarePen size={19} />
              </button>
            </div>
          </header>
          <AuraReadiness
            value={
              currentModel === 'aura-not-connected' || inferenceStatus?.model === 'aura-not-connected'
                ? false
                : (inferenceStatus?.ready ?? null)
            }
          >
            <AuraConversationCards resumed={resumed} />
            <AuraBrowserHandoff />
            <AuraContinueLater value={showHistory}>{children}</AuraContinueLater>
          </AuraReadiness>
        </main>
        {roomy && <AuraSidePanel theme={resolvedMode} wide />}
      </div>
      {!roomy && <AuraSidePanel theme={resolvedMode} wide={false} />}
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
      <Contribute area={COMPOSER_AREAS.leading} id="aura:model">
        <AuraModelChip />
      </Contribute>
      <Contribute area={COMPOSER_AREAS.actions} id="aura:dictation">
        <AuraDictation />
      </Contribute>
      <AuraToolsDialog theme={resolvedMode} />
      <AuraProjectDialog
        onClose={() => setProject(null)}
        onNewChat={async id => {
          // Do not open an unscoped chat if project context could not be saved.
          if (!(await startAuraProjectChat(id))) return false
          setProject(null)
          newChat()
          return true
        }}
        onOpenChat={session => {
          setProject(null)
          openSession(session)
        }}
        projectId={project}
        sessions={sessions}
        theme={resolvedMode}
        titleOf={sessionTitle}
      />
      <AuraSettingsDialog
        mode={mode as 'light' | 'dark' | 'system'}
        onClose={() => {
          setSettings(false)
          $auraSettingsRequest.set(null)
        }}
        onMode={setMode}
        onSignOut={() => {
          setError('')
          void auraSignOut().catch(() => setError('Sign out could not finish. Please try again.'))
        }}
        open={settings || settingsRequest !== null}
        signOutError={error}
        theme={resolvedMode}
      />
    </div>
  )
}
