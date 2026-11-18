import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { AuraVoiceMode } from './voice-mode'

vi.mock('./voice-call', () => ({ AuraVoice: () => <p>default live voice</p> }))
vi.mock('./pipecat-voice', () => ({ AuraPipecatVoice: () => <p>full duplex voice</p> }))

const props = { busy: false, disabled: false, onInterrupt: vi.fn(), onSubmit: vi.fn() }

function serve(api: unknown) {
  ;(window as unknown as { hermesDesktop?: unknown }).hermesDesktop = api === undefined ? undefined : { api }
}

afterEach(() => serve(undefined))

it('shows the default live voice when the server says full duplex is off', async () => {
  const api = vi.fn().mockResolvedValue({ full_duplex: false, enabled: false, runtime: false })
  serve(api)
  render(<AuraVoiceMode {...props} />)
  await waitFor(() => expect(api).toHaveBeenCalledWith({ path: '/api/aura/voice/mode' }))
  expect(screen.getByText('default live voice')).toBeTruthy()
  expect(screen.queryByText('full duplex voice')).toBeNull()
})

it('keeps the default live voice when the mode request fails or no server is attached', async () => {
  serve(vi.fn().mockRejectedValue(new Error('404')))
  const view = render(<AuraVoiceMode {...props} />)
  await waitFor(() => expect(screen.getByText('default live voice')).toBeTruthy())
  view.unmount()
  serve(undefined)
  render(<AuraVoiceMode {...props} />)
  expect(screen.getByText('default live voice')).toBeTruthy()
})

it('switches to full duplex only when the server reports it on', async () => {
  serve(vi.fn().mockResolvedValue({ full_duplex: true, enabled: true, runtime: true }))
  render(<AuraVoiceMode {...props} />)
  await waitFor(() => expect(screen.getByText('full duplex voice')).toBeTruthy())
  expect(screen.queryByText('default live voice')).toBeNull()
})
