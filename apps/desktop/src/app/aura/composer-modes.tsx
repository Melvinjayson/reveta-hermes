import type { ComponentProps } from 'react'

import { AuraLocalTalk } from './local-talk'
import { AuraVoiceMode } from './voice-mode'

/** Voice chat and On-device share one labelled toolbar row so a phone composer stays two rows tall. */
export function AuraComposerModes(props: ComponentProps<typeof AuraVoiceMode>) {
  return (
    <div aria-label="Conversation options" className="aura-composer-modes" role="group">
      <AuraVoiceMode {...props} />
      <AuraLocalTalk busy={props.busy} disabled={props.disabled} onSubmit={props.onSubmit} />
    </div>
  )
}
