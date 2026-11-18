import type { SessionInfo } from '@/types/hermes'

export const HISTORY_GROUPS = ['Today', 'Yesterday', 'Previous 7 days', 'Older'] as const
export type HistoryGroup = (typeof HISTORY_GROUPS)[number]

const DAY_MS = 86_400_000

function startOfDay(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

/** Calendar-day buckets in the viewer's local time; `seconds` is a Unix timestamp. */
export function historyGroup(seconds: number, now = new Date()): HistoryGroup {
  const days = Math.round((startOfDay(now) - startOfDay(new Date(seconds * 1000))) / DAY_MS)

  if (days <= 0) {
    return 'Today'
  }

  if (days === 1) {
    return 'Yesterday'
  }

  return days <= 7 ? 'Previous 7 days' : 'Older'
}

export interface HistoryEntry {
  session: SessionInfo
  title: string
}

/** Newest first within each non-empty group, filtered by a case-insensitive title match. */
export function groupHistory(
  sessions: SessionInfo[],
  titleOf: (session: SessionInfo) => string,
  query = '',
  now = new Date()
): { group: HistoryGroup; entries: HistoryEntry[] }[] {
  const needle = query.trim().toLowerCase()
  const at = (session: SessionInfo) => session.last_active || session.started_at

  const entries = sessions
    .map(session => ({ session, title: titleOf(session) }))
    .filter(entry => entry.title.toLowerCase().includes(needle))
    .sort((a, b) => at(b.session) - at(a.session))

  return HISTORY_GROUPS.map(group => ({
    group,
    entries: entries.filter(entry => historyGroup(at(entry.session), now) === group)
  })).filter(section => section.entries.length > 0)
}
