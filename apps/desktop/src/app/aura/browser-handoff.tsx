import { useStore } from '@nanostores/react'
import { useCallback, useEffect, useState } from 'react'

import { requestComposerInsert } from '@/app/chat/composer/focus'

import { $auraGoalKey } from './goals'

const BASE = '/api/aura/companion/handoff'
const POLL_MS = 3000

interface PendingStep {
  approval_id: string
  step: number
  action: string
  label: string
  host: string
}

export interface BrowserHandoff {
  id: string
  instruction: string
  state: 'pending' | 'started' | 'done' | 'failed' | 'cancelled'
  ok: boolean | null
  summary: string
  approvals: PendingStep[]
}

type Method = 'GET' | 'POST'

function call<T>(path: string, method: Method = 'GET', body?: unknown) {
  return window.hermesDesktop.api<T>({ path, method, ...(body ? { body } : {}) })
}

const live = (handoff: BrowserHandoff | null) => handoff?.state === 'pending' || handoff?.state === 'started'

/** Result text the browser sent back. It is page content: shown and quoted as such, never sent on its own. */
export function handoffResultMessage(handoff: BrowserHandoff) {
  return `From my browser (web page content, not checked by Aura):\n> ${handoff.summary.replace(/\n/g, ' ')}`
}

/**
 * Chat-to-browser handoff (Aura Companion). Hidden unless the owner switched it on and this account may use
 * the companion. Steps that send, submit, buy or delete are approved here, in the signed-in chat.
 */
export function AuraBrowserHandoff() {
  const sessionId = useStore($auraGoalKey)
  const [enabled, setEnabled] = useState(false)
  const [handoff, setHandoff] = useState<BrowserHandoff | null>(null)
  const [draft, setDraft] = useState('')
  const [dismissed, setDismissed] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true

    Promise.resolve(call<{ enabled: boolean }>(`${BASE}/status`))
      .then(status => active && setEnabled(status?.enabled === true))
      .catch(() => active && setEnabled(false))

    return () => {
      active = false
    }
  }, [])

  const reload = useCallback(async () => {
    if (!sessionId) {
      return setHandoff(null)
    }

    try {
      const data = await call<{ handoff: BrowserHandoff | null }>(`${BASE}?session_id=${encodeURIComponent(sessionId)}`)
      setHandoff(data?.handoff ?? null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [sessionId])

  useEffect(() => {
    if (enabled) {
      void reload()
    }
  }, [enabled, reload])

  useEffect(() => {
    if (!enabled || !live(handoff)) {
      return
    }

    const timer = window.setInterval(() => void reload(), POLL_MS)

    return () => window.clearInterval(timer)
  }, [enabled, handoff, reload])

  const act = (path: string, body: unknown) =>
    call(path, 'POST', body)
      .then(() => {
        setError('')

        return reload()
      })
      .catch(err => setError(err instanceof Error ? err.message : String(err)))

  if (!enabled || !sessionId) {
    return null
  }

  const finished = handoff && !live(handoff) && handoff.state !== 'cancelled' && dismissed !== handoff.id

  return (
    <section aria-label="Browser handoff" className="aura-card" data-aura-card="browser-handoff">
      <p className="aura-eyebrow">Your browser</p>
      {live(handoff) && handoff ? (
        <>
          <h2>{handoff.state === 'pending' ? 'Waiting for your browser' : 'Your browser is working on it'}</h2>
          <p>{handoff.instruction}</p>
          {handoff.state === 'pending' && <p className="aura-muted">Open the Aura Companion side panel to start it.</p>}
          {handoff.approvals.map(step => (
            <div className="aura-card-actions" data-aura-handoff-approval={step.approval_id} key={step.approval_id}>
              <p>
                Step {step.step + 1} on {step.host || 'the page'} would {step.action} “{step.label || 'an element'}”.
              </p>
              <button onClick={() => void act(`${BASE}/approve`, { approval_id: step.approval_id, approve: true })} type="button">
                Approve
              </button>
              <button onClick={() => void act(`${BASE}/approve`, { approval_id: step.approval_id, approve: false })} type="button">
                Deny
              </button>
            </div>
          ))}
          <button className="aura-button aura-button-secondary" onClick={() => void act(`${BASE}/cancel`, { id: handoff.id })} type="button">
            Stop
          </button>
        </>
      ) : finished && handoff ? (
        <>
          <h2>{handoff.ok ? 'Your browser finished' : 'Your browser stopped'}</h2>
          <p className="aura-muted">From the web page, not checked by Aura:</p>
          <blockquote>{handoff.summary || 'No details.'}</blockquote>
          <div className="aura-card-actions">
            <button onClick={() => requestComposerInsert(handoffResultMessage(handoff))} type="button">
              Add to message
            </button>
            <button onClick={() => setDismissed(handoff.id)} type="button">
              Dismiss
            </button>
          </div>
        </>
      ) : (
        <form
          onSubmit={event => {
            event.preventDefault()
            const instruction = draft.trim()

            if (instruction.length >= 3) {
              void act(BASE, { session_id: sessionId, instruction }).then(() => setDraft(''))
            }
          }}
        >
          <label htmlFor="aura-handoff-task">Send a task to your browser</label>
          <textarea
            id="aura-handoff-task"
            maxLength={500}
            onChange={event => setDraft(event.target.value)}
            placeholder="e.g. Find the pricing page and note the Pro plan"
            rows={2}
            value={draft}
          />
          <button disabled={draft.trim().length < 3} type="submit">
            Send to browser
          </button>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  )
}
