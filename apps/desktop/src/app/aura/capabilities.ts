import { atom } from 'nanostores'

export interface AuraCapability {
  id: string
  label: string
  description: string
  enabled: boolean
  available: boolean
  blocked: null | string
  requires_env: string[]
  /** Another capability this one needs switched on (Full browser needs Commands). */
  requires?: null | string
}

export interface AuraCapabilityStatus {
  applies_to: string
  mode: null | string
  modes: Record<string, string[]>
  capabilities: AuraCapability[]
}

export const AURA_MODES = ['Focused', 'Research', 'Agent'] as const

export const AURA_MODE_HINTS: Record<(typeof AURA_MODES)[number], string> = {
  Focused: 'Conversation, sources and files',
  Research: 'Adds past chats, memory and web search',
  Agent: 'Everything that is set up'
}

/** Last status the server returned; null until loaded. */
export const $auraCapabilities = atom<AuraCapabilityStatus | null>(null)
export const $auraCapabilityError = atom('')
/** The composer's + menu opens the tools dialog that AuraShell mounts. */
export const $auraToolsOpen = atom(false)

function api<T>(method: 'GET' | 'PUT', body?: unknown) {
  return window.hermesDesktop.api<T>({ path: '/api/aura/capabilities', method, ...(body ? { body } : {}) })
}

function message(error: unknown) {
  const text = error instanceof Error ? error.message : String(error)

  return text.replace(/^.*?"detail":\s*"([^"]+)".*$/s, '$1')
}

async function apply(request: Promise<AuraCapabilityStatus>) {
  try {
    $auraCapabilities.set(await request)
    $auraCapabilityError.set('')
  } catch (error) {
    $auraCapabilityError.set(message(error))
  }
}

export const loadAuraCapabilities = () => apply(api<AuraCapabilityStatus>('GET'))

export const setAuraMode = (mode: string) => apply(api<AuraCapabilityStatus>('PUT', { mode }))

/** Switching one on also switches on what it needs; switching a dependency off also switches off its dependants. */
export function toggleAuraCapability(status: AuraCapabilityStatus, id: string, on: boolean) {
  const next = new Set(status.capabilities.filter(c => (c.id === id ? on : c.enabled)).map(c => c.id))

  for (const capability of status.capabilities) {
    if (capability.requires && next.has(capability.id)) {
      if (on && capability.id === id) {
        next.add(capability.requires)
      } else if (!next.has(capability.requires)) {
        next.delete(capability.id)
      }
    }
  }

  const enabled = status.capabilities.filter(c => next.has(c.id)).map(c => c.id)

  return apply(api<AuraCapabilityStatus>('PUT', { enabled }))
}
