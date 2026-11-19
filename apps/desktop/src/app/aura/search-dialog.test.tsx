import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import type { SessionInfo, SessionSearchResult } from '@/types/hermes'

import { AuraSearchDialog, highlightSnippet } from './search-dialog'

vi.mock('@/api/sessions', () => ({ searchSessions: vi.fn() }))

const session = (id: string) => ({ id, last_active: Date.now() / 1000, started_at: Date.now() / 1000 }) as SessionInfo
const titles: Record<string, string> = { a: 'Launch plan', b: 'Budget review' }
const hit = (id: string, snippet: string) => ({ session_id: id, snippet }) as SessionSearchResult

beforeEach(() => {
  vi.useFakeTimers()

  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute('open', '')
  }

  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute('open')
  }
})

it('marks the server snippet matches', () => {
  render(<p>{highlightSnippet('...the >>>pricing<<< page and >>>pricing<<< table')}</p>)
  expect(screen.getAllByText('pricing').every(node => node.tagName === 'MARK')).toBe(true)
})

it('finds text inside messages, opens the hit, and ignores a stale reply', async () => {
  const replies: Record<string, (value: { results: SessionSearchResult[] }) => void> = {}
  const search = vi.fn((query: string) => new Promise<{ results: SessionSearchResult[] }>(resolve => (replies[query] = resolve)))
  const onOpen = vi.fn()

  render(
    <AuraSearchDialog
      onClose={vi.fn()}
      onOpen={onOpen}
      open
      search={search}
      sessions={[session('a'), session('b')]}
      theme="light"
      titleOf={s => titles[s.id]}
    />
  )
  const input = screen.getByRole('combobox', { name: 'Search conversations' })

  fireEvent.change(input, { target: { value: 'pri' } })
  await act(() => vi.advanceTimersByTimeAsync(300))
  fireEvent.change(input, { target: { value: 'pricing' } })
  await act(() => vi.advanceTimersByTimeAsync(300))
  expect(search).toHaveBeenCalledWith('pricing')

  await act(async () => replies.pricing({ results: [hit('b', 'the >>>pricing<<< table')] }))
  await act(async () => replies.pri({ results: [hit('a', 'stale >>>pri<<<')] }))

  const group = screen.getByRole('group', { name: 'In messages' })
  expect(group.textContent).toContain('Budget review')
  expect(group.textContent).not.toContain('stale')

  fireEvent.keyDown(input, { key: 'Enter' })
  expect(onOpen).toHaveBeenCalledWith('b', expect.objectContaining({ id: 'b' }))
})
