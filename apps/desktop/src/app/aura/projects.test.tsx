import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import type { SessionInfo } from '@/types/hermes'

import { AuraProjectDialog } from './project-dialog'
import { $auraProjects, type AuraProject, startAuraProjectChat } from './projects'

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

it('a new chat in a project is announced to the server before the chat starts', async () => {
  await startAuraProjectChat('p_1')
  expect(api).toHaveBeenCalledWith({ path: '/api/aura/projects/next-chat', method: 'PUT', body: { project_id: 'p_1' } })
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

it('keeps the project dialog open and prevents a duplicate new chat while binding is pending', async () => {
  let finish!: (ok: boolean) => void
  const onNewChat = vi.fn(() => new Promise<boolean>(resolve => { finish = resolve }))
  const onClose = vi.fn()
  render(
    <AuraProjectDialog
      onClose={onClose}
      onNewChat={onNewChat}
      onOpenChat={vi.fn()}
      projectId="p_1"
      sessions={[session('a')]}
      theme="light"
      titleOf={s => s.id}
    />
  )

  fireEvent.click(screen.getByRole('button', { name: 'New chat in this project' }))
  const pending = screen.getByRole('button', { name: 'Preparing chat…' }) as HTMLButtonElement
  expect(pending.disabled).toBe(true)
  fireEvent.click(pending)
  expect(onNewChat).toHaveBeenCalledTimes(1)

  finish(false)
  await waitFor(() => expect(screen.getByRole('button', { name: 'New chat in this project' })).toBeTruthy())
  expect(onClose).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog').hasAttribute('open')).toBe(true)
})
