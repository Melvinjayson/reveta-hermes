import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { requestComposerInsert } from '@/app/chat/composer/focus'

import { AuraDictation } from './dictation'

vi.mock('@/app/chat/composer/focus', () => ({ requestComposerFocus: vi.fn(), requestComposerInsert: vi.fn() }))
vi.mock('@/store/session', async () => {
  const { atom } = await import('nanostores')

  return { $gatewayState: atom('open') }
})

type Handler = (event: { resultIndex: number; results: { isFinal: boolean; 0: { transcript: string } }[] }) => void

let instance: { onresult: Handler | null; started: boolean } | null = null

class FakeRecognition {
  continuous = false
  interimResults = true
  lang = ''
  onresult: Handler | null = null
  onend: (() => void) | null = null
  onerror = null
  started = false
  constructor() {
    instance = this
  }
  start() {
    this.started = true
  }
  stop() {
    this.onend?.()
  }
  abort() {}
}

afterEach(() => {
  delete (window as { SpeechRecognition?: unknown }).SpeechRecognition
  instance = null
})

it('is hidden when the browser has no speech recognition', () => {
  const { container } = render(<AuraDictation disabled={false} />)
  expect(container.innerHTML).toBe('')
})

it('types final speech into the draft and never sends', () => {
  ;(window as { SpeechRecognition?: unknown }).SpeechRecognition = FakeRecognition
  render(<AuraDictation disabled={false} />)

  fireEvent.click(screen.getByRole('button', { name: 'Dictate' }))
  expect(instance?.started).toBe(true)
  instance?.onresult?.({ resultIndex: 0, results: [{ isFinal: false, 0: { transcript: 'draft' } }] })
  instance?.onresult?.({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: ' plan the launch ' } }] })
  expect(requestComposerInsert).toHaveBeenCalledExactlyOnceWith('plan the launch ')

  fireEvent.click(screen.getByRole('button', { name: 'Stop dictation' }))
  expect(screen.getByRole('button', { name: 'Dictate' })).toBeTruthy()
})
