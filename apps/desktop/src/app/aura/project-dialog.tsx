import { useStore } from '@nanostores/react'
import { type FormEvent, useEffect, useRef, useState } from 'react'

import { X } from '@/lib/icons'
import type { SessionInfo } from '@/types/hermes'

import {
  $auraProjectError,
  $auraProjects,
  assignAuraProject,
  createAuraProject,
  deleteAuraProject,
  updateAuraProject
} from './projects'

interface AuraProjectDialogProps {
  /** A project id, 'new' to create one, or null when closed. */
  projectId: null | string
  sessions: SessionInfo[]
  theme: string
  titleOf: (session: SessionInfo) => string
  onClose: () => void
  onOpenChat: (session: SessionInfo) => void
  onNewChat: (projectId: string) => Promise<boolean>
}

export function AuraProjectDialog({ projectId, sessions, theme, titleOf, onClose, onOpenChat, onNewChat }: AuraProjectDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const projects = useStore($auraProjects)
  const error = useStore($auraProjectError)
  const project = projectId && projectId !== 'new' ? projects?.find(p => p.id === projectId) : undefined
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const node = dialog.current

    if (projectId && node && !node.open) {
      node.showModal()
    }

    if (!projectId && node?.open) {
      node.close()
    }

    setConfirmDelete(false)
  }, [projectId])

  useEffect(() => {
    setName(project?.name ?? '')
    setDescription(project?.description ?? '')
  }, [project?.id, project?.name, project?.description])

  const byId = new Map(sessions.map(session => [session.id, session]))
  const members = (project?.session_ids ?? []).map(id => byId.get(id)).filter((s): s is SessionInfo => Boolean(s))
  const elsewhere = new Set((projects ?? []).flatMap(p => p.session_ids))
  const candidates = sessions.filter(session => !elsewhere.has(session.id))

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)

    const ok = project
      ? await updateAuraProject(project.id, { name, description })
      : await createAuraProject(name, description)

    setBusy(false)

    if (ok && !project) {
      onClose()
    }
  }

  return (
    <dialog
      aria-labelledby="aura-project-title"
      className="aura-dialog aura-project-dialog"
      data-aura-theme={theme}
      onCancel={event => {
        event.preventDefault()
        onClose()
      }}
      onClick={event => event.target === dialog.current && onClose()}
      ref={dialog}
    >
      <header className="aura-dialog-header">
        <h2 id="aura-project-title">{project ? project.name : 'New project'}</h2>
        <button aria-label="Close project" className="aura-icon-button" onClick={onClose} type="button">
          <X size={18} />
        </button>
      </header>
      <div className="aura-project-body">
        <form className="aura-project-form" onSubmit={save}>
          <label className="aura-field">
            <span>Name</span>
            <input maxLength={80} onChange={event => setName(event.target.value)} required value={name} />
          </label>
          <label className="aura-field">
            <span>Notes</span>
            <textarea
              maxLength={2000}
              onChange={event => setDescription(event.target.value)}
              placeholder="What this project is about"
              rows={3}
              value={description}
            />
          </label>
          <button className="aura-button aura-button-primary" disabled={busy || !name.trim()} type="submit">
            {project ? 'Save' : 'Create project'}
          </button>
        </form>
        {error && <p role="alert">{error}</p>}
        {project && (
          <>
            <section aria-labelledby="aura-project-chats">
              <div className="aura-project-row">
                <h3 id="aura-project-chats">Chats</h3>
                <button
                  className="aura-button aura-button-secondary"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true)
                    try {
                      await onNewChat(project.id)
                    } finally {
                      setBusy(false)
                    }
                  }}
                  type="button"
                >
                  {busy ? 'Preparing chat…' : 'New chat in this project'}
                </button>
              </div>
              {members.length ? (
                <ul className="aura-project-chats">
                  {members.map(session => (
                    <li key={session.id}>
                      <button className="aura-conversation-open" onClick={() => onOpenChat(session)} type="button">
                        {titleOf(session)}
                      </button>
                      <button
                        aria-label={`Remove ${titleOf(session)} from project`}
                        className="aura-icon-button"
                        onClick={() => void assignAuraProject(session.id, null)}
                        type="button"
                      >
                        <X size={16} />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="aura-empty-note">No chats in this project yet.</p>
              )}
              {candidates.length > 0 && (
                <label className="aura-field">
                  <span>Add a chat</span>
                  <select
                    onChange={event => event.target.value && void assignAuraProject(event.target.value, project.id)}
                    value=""
                  >
                    <option value="">Choose a chat…</option>
                    {candidates.map(session => (
                      <option key={session.id} value={session.id}>
                        {titleOf(session)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </section>
            <section className="aura-project-danger">
              {confirmDelete ? (
                <div aria-label={`Delete ${project.name}?`} role="group">
                  <p>Delete “{project.name}”? Its chats stay in your history.</p>
                  <button
                    className="aura-button aura-button-danger"
                    onClick={async () => {
                      if (await deleteAuraProject(project.id)) {
                        onClose()
                      }
                    }}
                    type="button"
                  >
                    Delete project
                  </button>
                  <button autoFocus className="aura-button aura-button-secondary" onClick={() => setConfirmDelete(false)} type="button">
                    Cancel
                  </button>
                </div>
              ) : (
                <button className="aura-button aura-button-secondary" onClick={() => setConfirmDelete(true)} type="button">
                  Delete project…
                </button>
              )}
            </section>
          </>
        )}
      </div>
    </dialog>
  )
}
