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

/** The next new chat starts in this project; the server files it and adds the notes when its agent is built. */
export const startAuraProjectChat = (projectId: null | string) =>
  apply(api('/next-chat', 'PUT', { project_id: projectId }))

export const assignAuraProject = (sessionId: string, projectId: null | string) =>
  apply(api('/membership', 'PUT', { session_id: sessionId, project_id: projectId }))

export function projectOf(projects: AuraProject[] | null, sessionId: null | string) {
  return sessionId ? (projects ?? []).find(project => project.session_ids.includes(sessionId)) : undefined
}
