import { useStore } from '@nanostores/react'
import { useContext } from 'react'

import { requestComposerInsert } from '@/app/chat/composer/focus'
import { $gatewayState } from '@/store/session'

import { AuraReadiness } from './readiness'

export function AuraEmpty() {
  const ready = useContext(AuraReadiness)
  const gateway = useStore($gatewayState)

  return (
    <section className="aura-empty">
      <div aria-hidden="true" className="aura-empty-mark">
        <img alt="" src="brand/aura-mark.svg" />
      </div>
      <p className="aura-eyebrow">A little clarity starts here</p>
      <h1>
        What are you
        <br />
        working on?
      </h1>
      <p>Think out loud. Decide with clarity.</p>
      <div aria-label="Conversation starters" className="aura-suggestions">
        {['Shape a new idea', 'Research a decision', 'Plan my next step'].map(text => (
          <button key={text} onClick={() => requestComposerInsert(text)} type="button">
            {text}
            <span aria-hidden="true">↗</span>
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
    </section>
  )
}
