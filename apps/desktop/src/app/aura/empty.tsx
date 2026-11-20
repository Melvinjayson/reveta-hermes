import { useStore } from '@nanostores/react'
import { Code, Lightbulb, type LucideIcon, Pencil } from 'lucide-react'
import { useContext } from 'react'

import { requestComposerInsert } from '@/app/chat/composer/focus'
import { $gatewayState } from '@/store/session'

import { AuraReadiness } from './readiness'

interface Starter {
  icon: LucideIcon
  label: string
  prompt: string
}

/** Each starter types an opening into the draft; nothing is sent until the user does. */
export const AURA_STARTERS: Starter[] = [
  { icon: Pencil, label: 'Create', prompt: 'Help me create ' },
  { icon: Code, label: 'Build', prompt: 'Help me build ' },
  { icon: Lightbulb, label: 'Explore', prompt: 'Help me explore ' }
]

export function AuraEmpty() {
  const ready = useContext(AuraReadiness)
  const gateway = useStore($gatewayState)

  return (
    <section className="aura-empty">
      <div className="aura-empty-head">
        <div aria-hidden="true" className="aura-empty-mark">
          <img alt="" src="brand/aura-mark.svg" />
        </div>
        <h1>
          Hi, I’m <span className="aura-empty-name">Aura.</span>
        </h1>
        <p className="aura-greeting">How can I help you today?</p>
      </div>
      <div aria-hidden="true" className="aura-empty-composer-slot" />
      <div className="aura-empty-foot">
      <div aria-label="Conversation starters" className="aura-suggestions">
        {AURA_STARTERS.map(({ icon: Icon, label, prompt }) => (
          <button key={label} onClick={() => requestComposerInsert(prompt)} type="button">
            <Icon aria-hidden="true" size={18} />
            {label}
          </button>
        ))}
      </div>
      {gateway !== 'open' ? (
        <p role="status">Connecting to your workspace…</p>
      ) : (
        ready === false && (
          <p className="aura-notice" role="status">
            Aura can’t reply yet. A model still needs to be connected.
          </p>
        )
      )}
      </div>
    </section>
  )
}
