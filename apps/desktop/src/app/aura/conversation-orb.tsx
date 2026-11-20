/**
 * Aura's original procedural conversation orb.
 * Visual-only: the gateway remains the source of voice and session state.
 * No microphone access, animation loop, model calls, or external assets here.
 */
export type OrbMotion = 'idle' | 'listening' | 'thinking' | 'speaking' | 'reconnecting' | 'muted'

export function orbMotion(status: string): OrbMotion {
  const value = status.toLowerCase()

  if (value.includes('muted')) return 'muted'
  if (value.includes('reconnect') || value.includes('connect')) return 'reconnecting'
  if (value.includes('speak') || value.includes('playback')) return 'speaking'
  if (value.includes('think') || value.includes('process')) return 'thinking'
  if (value.includes('listen') || value.includes('hearing')) return 'listening'

  return 'idle'
}

export function AuraConversationOrb({ status }: { status: string }) {
  return (
    <div aria-hidden="true" className="aura-voice-orb aura-kinetic-orb" data-motion={orbMotion(status)}>
      <span className="aura-orb-glow" />
      <span className="aura-orb-shell">
        <span className="aura-orb-current aura-orb-current-one" />
        <span className="aura-orb-current aura-orb-current-two" />
        <span className="aura-orb-specular" />
      </span>
      <img alt="" className="aura-orb-emblem" src="brand/aura-mark.svg" />
    </div>
  )
}
