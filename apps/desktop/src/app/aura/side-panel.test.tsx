import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it } from 'vitest'

import { $backgroundStatusBySession } from '@/store/composer-status'
import { $activeSessionId, $messages } from '@/store/session'
import { $subagentsBySession, type SubagentProgress } from '@/store/subagents'

import { $auraPanel, clock, previewKind } from './panel-store'
import { AuraSidePanel } from './side-panel'

const agent = (over: Partial<SubagentProgress>): SubagentProgress => ({
  id: 'sub-1', parentId: null, goal: 'Compare three vendors', status: 'running', taskCount: 1, taskIndex: 0,
  startedAt: 0, updatedAt: 0, filesRead: [], filesWritten: [], stream: [], ...over
})

beforeEach(() => {
  $activeSessionId.set('run-1')
  $messages.set([])
  $subagentsBySession.set({})
  $backgroundStatusBySession.set({})
})

it('previews PDFs, images and text, and leaves other files download-only', () => {
  expect(['a.pdf', 'b.PNG', 'brief.md', 'data.csv', 'deck.pptx'].map(previewKind)).toEqual(['pdf', 'image', 'text', 'text', 'none'])
  expect(clock(75)).toBe('1:15')
})

it('shows subagents and background tasks of the open chat, and an honest empty state otherwise', () => {
  $auraPanel.set('work')
  const { rerender } = render(<AuraSidePanel theme="light" wide />)
  expect(screen.getByText(/Nothing has run in this chat yet/)).toBeTruthy()

  $subagentsBySession.set({ 'run-1': [agent({ currentTool: 'web_extract' })], other: [agent({ id: 'x', goal: 'Not this chat' })] })
  $backgroundStatusBySession.set({ 'run-1': [{ id: 'p1', type: 'background', title: 'npm run build', state: 'running', output: 'compiled 12 files' }] } as never)
  rerender(<AuraSidePanel theme="light" wide />)

  expect(screen.getByText('Compare three vendors')).toBeTruthy()
  expect(screen.queryByText('Not this chat')).toBeNull()
  expect(screen.getByText(/Working · web_extract/)).toBeTruthy()
  expect(screen.getByText('npm run build')).toBeTruthy()
  expect(screen.getByText('compiled 12 files')).toBeTruthy()
})
