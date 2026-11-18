import { atom } from 'nanostores'

export interface AuraProject {
  id: string
  slug: string
  name: string
  description: string
  created_at: number
  session_ids: string[]
}

interface ProjectsPayload {
  projects: AuraProject[]
}

/** Server truth for the profile's Aura projects; null until loaded. */
export const $auraProjects = atom<AuraProject[] | null>(null)
export const $auraProjectError = atom('')
/** A project chosen for the next new chat, and the chat that was open when it was chosen.
 * Assigned once a DIFFERENT chat has a stored id, so the previous chat is never filed by mistake. */
export const $auraPendingProject = atom<null | { projectId: string; from: null | string }>(null)

export function pendingTarget(pending: null | { projectId: string; from: null | string }, activeId: null | string) {
  return pending && activeId && activeId !== pending.from ? pending.projectId : null
}

type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE' | 'PUT'

function api(path: string, method: Method = 'GET', body?: unknown) {
  return window.hermesDesktop.api<ProjectsPayload>({ path: `/api/aura/projects${path}`, method, ...(body ? { body } : {}) })
}

function message(error: unknown) {
  const text = error instanceof Error ? error.message : String(error)

  return text.replace(/^.*?"detail":\s*"([^"]+)".*$/s, '$1')
}

let generation = 0

/** A slower, older response never overwrites a newer one. */
async function apply(request: Promise<ProjectsPayload>): Promise<boolean> {
  const token = ++generation

  try {
    const payload = await request

    if (token === generation) {
      $auraProjects.set(payload.projects)
      $auraProjectError.set('')
    }

    return true
  } catch (error) {
    if (token === generation) {
      $auraProjectError.set(message(error))
    }

    return false
  }
}

export const loadAuraProjects = () => apply(api(''))

export const createAuraProject = (name: string, description = '') => apply(api('', 'POST', { name, description }))

export const updateAuraProject = (id: string, fields: { name?: string; description?: string }) =>
  apply(api(`/${encodeURIComponent(id)}`, 'PATCH', fields))

export const deleteAuraProject = (id: string) => apply(api(`/${encodeURIComponent(id)}`, 'DELETE'))

export const assignAuraProject = (sessionId: string, projectId: null | string) =>
  apply(api('/membership', 'PUT', { session_id: sessionId, project_id: projectId }))

export function projectOf(projects: AuraProject[] | null, sessionId: null | string) {
  return sessionId ? (projects ?? []).find(project => project.session_ids.includes(sessionId)) : undefined
}
