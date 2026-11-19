import { atom } from 'nanostores'

export type AuraPanelTab = 'work' | 'sources' | 'files'

/** Which side-panel tab is open (null = closed). Presentation state for this window only. */
export const $auraPanel = atom<AuraPanelTab | null>(null)

export function openAuraPanel(tab: AuraPanelTab) {
  $auraPanel.set(tab)
}

export function closeAuraPanel() {
  $auraPanel.set(null)
}

export type AuraPreviewKind = 'pdf' | 'image' | 'text' | 'none'

/** How the panel can show a file, from its name alone; unknown types are download-only. */
export function previewKind(name: string): AuraPreviewKind {
  const ext = name.toLowerCase().split('.').pop() ?? ''

  if (ext === 'pdf') {
    return 'pdf'
  }

  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext)) {
    return 'image'
  }

  return ['md', 'txt', 'csv', 'json', 'yaml', 'yml', 'html', 'xml', 'log', 'py', 'js', 'ts', 'tsx', 'css'].includes(ext)
    ? 'text'
    : 'none'
}

/** Seconds as m:ss for live timers. */
export function clock(seconds: number) {
  const whole = Math.max(0, Math.floor(seconds))

  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}
