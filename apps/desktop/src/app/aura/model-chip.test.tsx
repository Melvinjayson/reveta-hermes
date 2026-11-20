import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { AuraModelChip, modelChipLabel } from './model-chip'
import { $auraSettingsRequest } from './settings-request'

function serve(api: unknown) {
  ;(window as unknown as { hermesDesktop?: unknown }).hermesDesktop = api === undefined ? undefined : { api }
}

afterEach(() => {
  serve(undefined)
  $auraSettingsRequest.set(null)
})

it('names the model that answers and opens Settings at Model', async () => {
  const api = vi.fn().mockResolvedValue({ active_model: { provider: 'gemini', model: 'google/gemini-3.8-flash' } })
  serve(api)
  render(<AuraModelChip />)
  const chip = await screen.findByRole('button', { name: 'Model: gemini-3.8-flash. Change in Settings' })
  expect(api).toHaveBeenCalledWith({ path: '/api/aura/provider' })
  fireEvent.click(chip)
  expect($auraSettingsRequest.get()).toBe('Model')
})

it('shows nothing when no model is set or the status request fails', async () => {
  const api = vi.fn().mockRejectedValue(new Error('403'))
  serve(api)
  const { container } = render(<AuraModelChip />)
  await waitFor(() => expect(api).toHaveBeenCalled())
  expect(container.innerHTML).toBe('')
  expect(modelChipLabel(undefined)).toBe('')
  expect(modelChipLabel('openai/gpt-x')).toBe('gpt-x')
})
