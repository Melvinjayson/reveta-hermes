import { expect, it } from 'vitest'

import type { SessionInfo } from '@/types/hermes'

import { groupHistory, historyGroup } from './history'
import { isSearchShortcut } from './search-dialog'

const now = new Date(2026, 10, 18, 9, 30)
const at = (days: number, hour = 12) => new Date(2026, 10, 18 - days, hour).getTime() / 1000

it('buckets by local calendar day: Today, Yesterday, Previous 7 days, Older', () => {
  expect(historyGroup(at(0, 0), now)).toBe('Today')
  expect(historyGroup(at(1, 23), now)).toBe('Yesterday')
  expect(historyGroup(at(2), now)).toBe('Previous 7 days')
  expect(historyGroup(at(7), now)).toBe('Previous 7 days')
  expect(historyGroup(at(8), now)).toBe('Older')
})

it('drops empty groups, sorts newest first and filters titles case-insensitively', () => {
  const session = (id: string, days: number) => ({ id, last_active: at(days), started_at: at(days) }) as SessionInfo
  const sessions = [session('old', 30), session('a', 0), session('b', 0), session('c', 3)]
  const titles: Record<string, string> = { old: 'Launch retro', a: 'Morning notes', b: 'Launch plan', c: 'Budget' }
  const titleOf = (s: SessionInfo) => titles[s.id]

  const all = groupHistory(sessions, titleOf, '', now)
  expect(all.map(section => section.group)).toEqual(['Today', 'Previous 7 days', 'Older'])

  const launch = groupHistory(sessions, titleOf, 'LAUNCH', now)
  expect(launch.flatMap(section => section.entries.map(entry => entry.title))).toEqual(['Launch plan', 'Launch retro'])
})

it('opens search on Cmd+K or Ctrl+K only', () => {
  const key = (over: Partial<KeyboardEvent>) => ({ key: 'k', metaKey: false, ctrlKey: false, altKey: false, ...over })
  expect(isSearchShortcut(key({ metaKey: true }))).toBe(true)
  expect(isSearchShortcut(key({ ctrlKey: true, key: 'K' }))).toBe(true)
  expect(isSearchShortcut(key({}))).toBe(false)
  expect(isSearchShortcut(key({ ctrlKey: true, altKey: true }))).toBe(false)
})
