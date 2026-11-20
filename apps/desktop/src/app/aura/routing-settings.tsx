export interface AuraRoutingTier {
  tier: string
  label: string
  model: string
  paid: boolean
  state: 'available' | 'disabled'
  reason: string | null
}

export interface AuraRoutingStatus {
  enabled: boolean
  tiers: AuraRoutingTier[]
  test_route: { label: string; model: string | null; state: 'available' | 'disabled'; experimental: boolean }
}

interface Props {
  activeModel?: string
  routing?: AuraRoutingStatus
  saving: boolean
  onUseTest: () => void
}

/** Configured routing tiers and the experimental test route, with what can actually run.
 *  A disabled tier is a plain row, never a control: it cannot be chosen until it can execute. */
export function AuraRoutingSettings({ activeModel, routing, saving, onUseTest }: Props) {
  if (!routing) {
    return null
  }

  const test = routing.test_route
  const testActive = Boolean(test.model) && activeModel === test.model

  return (
    <section aria-labelledby="aura-routing-title" className="aura-routing">
      <h3 id="aura-routing-title">Model routing</h3>
      <ul>
        {routing.tiers.map(tier => (
          <li data-state={tier.state} key={tier.tier}>
            <span className="aura-routing-name">
              {tier.label} · <code>{tier.model}</code>
            </span>
            <span className="aura-routing-state">{tier.state === 'available' ? 'Available' : `Off — ${tier.reason}`}</span>
          </li>
        ))}
        {test.model && (
          <li data-state={test.state}>
            <span className="aura-routing-name">
              {test.label} · <code>{test.model}</code> <span className="aura-routing-tag">Experimental</span>
            </span>
            <span className="aura-routing-state">
              {testActive
                ? 'In use. Synthetic test prompts only; free, rate-limited trial service.'
                : test.state === 'available'
                  ? 'Free, rate-limited trial service. Synthetic test prompts only.'
                  : 'Off on this deployment.'}
            </span>
            {test.state === 'available' && !testActive && (
              <button disabled={saving} onClick={onUseTest} type="button">
                Use the test model
              </button>
            )}
          </li>
        )}
      </ul>
    </section>
  )
}
