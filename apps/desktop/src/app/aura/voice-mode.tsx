import { useEffect, useState } from 'react'

import type { ChatBarProps } from '@/app/chat/composer/types'
import type { HermesGateway } from '@/hermes'

import { AuraPipecatVoice } from './pipecat-voice'
import { AuraVoice } from './voice-call'

interface Props {
  busy: boolean
  disabled: boolean
  onSubmit: ChatBarProps['onSubmit']
  onInterrupt: ChatBarProps['onCancel']
  gateway?: Pick<HermesGateway, 'request'> | null
  sessionId?: string | null
}

interface VoiceMode {
  full_duplex: boolean
}

/** The live voice is the default. Full-duplex Pipecat voice is shown only when the server says
 * `aura.voice.full_duplex` is on and its speech runtime is installed; any failure keeps the default. */
export function AuraVoiceMode(props: Props) {
  const [fullDuplex, setFullDuplex] = useState(false)

  useEffect(() => {
    const api = window.hermesDesktop?.api

    if (!api) {
      return
    }

    let live = true

    Promise.resolve(api<VoiceMode>({ path: '/api/aura/voice/mode' }))
      .then(mode => live && setFullDuplex(mode?.full_duplex === true))
      .catch(() => live && setFullDuplex(false))

    return () => {
      live = false
    }
  }, [])

  return fullDuplex ? <AuraPipecatVoice {...props} /> : <AuraVoice {...props} />
}
