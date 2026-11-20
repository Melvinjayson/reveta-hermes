import { useStore } from '@nanostores/react'
import { useContext } from 'react'

import { requestComposerInsert } from '@/app/chat/composer/focus'
import { $gatewayState } from '@/store/session'

import { AuraReadiness } from './readiness'

export const AURA_STARTERS = ['Shape a new idea', 'Research a decision', 'Plan my next step', 'Summarise a document']

export function auraGreeting(hour: number) {
  if (hour < 5 || hour >= 18) {
    return 'Good evening'
  }

  return hour < 12 ? 'Good morning' : 'Good afternoon'
}

export function AuraEmpty() {
  const ready = useContext(AuraReadiness)
  const gateway = useStore($gatewayState)

  return (
    <section className="aura-empty">
      <div className="aura-empty-head">
        <div aria-hidden="true" className="aura-empty-mark">
          <img alt="" src="brand/aura-mark.svg" />
        </div>
        <p className="aura-greeting">{auraGreeting(new Date().getHours())}</p>
        <h1>What are you working on?</h1>
      </div>
      <div aria-hidden="true" className="aura-empty-composer-slot" />
      <div className="aura-empty-foot">
      <div aria-label="Conversation starters" className="aura-suggestions">
        {AURA_STARTERS.map(text => (
          <button key={text} onClick={() => requestComposerInsert(text)} type="button">
            {text}
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
