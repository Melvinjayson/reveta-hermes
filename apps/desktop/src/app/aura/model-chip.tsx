import { ChevronDown, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'

import type { AuraProviderStatus } from './model-settings'
import { $auraSettingsRequest } from './settings-request'

/** "provider/name-v2" → "name-v2": the chip shows what answers, not the route. */
export function modelChipLabel(model: string | undefined): string {
  return (model ?? '').split('/').pop()?.trim() ?? ''
}

/** Shows the model that answers this chat; choosing another happens in Settings → Model. */
export function AuraModelChip() {
  const [model, setModel] = useState('')

  useEffect(() => {
    const api = window.hermesDesktop?.api

    if (!api) {
      return
    }

    let live = true

    Promise.resolve(api<AuraProviderStatus>({ path: '/api/aura/provider' }))
      .then(status => live && setModel(modelChipLabel(status?.active_model?.model)))
      .catch(() => live && setModel(''))

    return () => {
      live = false
    }
  }, [])

  if (!model) {
    return null
  }

  return (
    <button
      aria-label={`Model: ${model}. Change in Settings`}
      className="aura-model-chip"
      onClick={() => $auraSettingsRequest.set('Model')}
      type="button"
    >
      <Sparkles aria-hidden="true" size={14} />
      <span>{model}</span>
      <ChevronDown aria-hidden="true" size={14} />
    </button>
  )
}
