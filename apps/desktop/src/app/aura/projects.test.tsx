import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import type { SessionInfo } from '@/types/hermes'

import { AuraProjectDialog } from './project-dialog'
import { $auraProjects, type AuraProject, pendingTarget } from './projects'

const project = (over: Partial<AuraProject> = {}): AuraProject => ({
  id: 'p_1', slug: 'launch', name: 'Launch', description: '', created_at: 1, session_ids: ['a'], ...over
})

const session = (id: string) => ({ id, last_active: 1, started_at: 1 }) as SessionInfo
const api = vi.fn()

beforeEach(() => {
  api.mockReset()
  api.mockImplementation(async ({ method, body }: { method: string; body?: { project_id: null | string } }) => ({
    projects: [project(method === 'PUT' && body?.project_id === null ? { session_ids: [] } : {})]
  }))
  ;(window as unknown as { hermesDesktop: unknown }).hermesDesktop = { api }

  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute('open', '')
  }

  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute('open')
  }

  $auraProjects.set([project()])
})

it('files a new chat only once a different chat id exists', () => {
  expect(pendingTarget({ projectId: 'p_1', from: 'old' }, 'old')).toBeNull()
  expect(pendingTarget({ projectId: 'p_1', from: 'old' }, null)).toBeNull()
  expect(pendingTarget({ projectId: 'p_1', from: 'old' }, 'new')).toBe('p_1')
  expect(pendingTarget(null, 'new')).toBeNull()
})

it('lists project chats, removes one, and deletes only after a confirm that keeps chats', async () => {
  const titles: Record<string, string> = { a: 'Pricing page', b: 'Budget' }
  const onClose = vi.fn()
  render(
    <AuraProjectDialog
      onClose={onClose}
      onNewChat={vi.fn()}
      onOpenChat={vi.fn()}
      projectId="p_1"
      sessions={[session('a'), session('b')]}
      theme="light"
      titleOf={s => titles[s.id]}
    />
  )

  expect(screen.getByRole('button', { name: 'Pricing page' })).toBeTruthy()
  expect(screen.getByRole('option', { name: 'Budget' })).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: 'Remove Pricing page from project' }))
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith({
      path: '/api/aura/projects/membership', method: 'PUT', body: { session_id: 'a', project_id: null }
    })
  )

  fireEvent.click(screen.getByRole('button', { name: 'Delete project…' }))
  expect(screen.getByRole('group', { name: 'Delete Launch?' }).textContent).toContain('chats stay in your history')
  expect(api).not.toHaveBeenCalledWith(expect.objectContaining({ method: 'DELETE' }))
  fireEvent.click(screen.getByRole('button', { name: 'Delete project' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith({ path: '/api/aura/projects/p_1', method: 'DELETE' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
})
