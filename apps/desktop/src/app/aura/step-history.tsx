import { ChevronDown, ListChecks } from 'lucide-react'
import { useEffect, useState } from 'react'

import { AuraCard } from './card'
import { type AuraStep, stepDuration } from './steps'

interface AuraStepsProps {
  steps: AuraStep[]
}

export function AuraSteps({ steps }: AuraStepsProps) {
  const running = steps.some(step => step.status === 'Running')
  const [now, setNow] = useState(() => Date.now() / 1000)

  useEffect(() => {
    if (!running) {
      return
    }

    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000)

    return () => window.clearInterval(timer)
  }, [running])

  if (!steps.length) {
    return null
  }

  return (
    <AuraCard kind="progress" title="Steps in this conversation">
      <p className="sr-only" role="status">
        {steps.length} steps. {steps.filter(step => step.status === 'Running').length} running.
        {steps.filter(step => step.status === 'Failed').length} failed.
      </p>
      <details className="aura-steps">
        <summary>
          {steps.length} {steps.length === 1 ? 'step' : 'steps'}
          <ChevronDown aria-hidden="true" size={16} />
        </summary>
        <ol>
          {steps.map(step => (
            <li data-aura-step={step.status} key={step.id}>
              <div className="aura-step-heading">
                <ListChecks aria-hidden="true" size={18} />
                <span>{step.label}</span>
                <span className="aura-step-status">{step.status}</span>
              </div>
              <small>{stepDuration(step, now)}</small>
              {step.status === 'Refused' && step.facts.includes("This would cost money, so I didn't run it.") && (
                <p>This would cost money, so I didn't run it.</p>
              )}
              <details>
                <summary>Details</summary>
                <p>Inputs and result content are hidden to protect private information.</p>
                {step.facts.filter(fact => fact !== "This would cost money, so I didn't run it.").map(fact => <p key={fact}>{fact}</p>)}
              </details>
            </li>
          ))}
        </ol>
      </details>
    </AuraCard>
  )
}
