import { useEffect, useRef, useState } from 'react'

import { requestComposerInsert } from '@/app/chat/composer/focus'

import { AURA_STARTERS } from './empty'

interface OnboardingStatus {
  completed: boolean
  storage_durable: boolean
}

const STEPS = ['Meet Aura', 'You stay in control', 'Start'] as const

const onboardingApi = <T,>(method: 'GET' | 'PUT') =>
  window.hermesDesktop.api<T>({ path: '/api/aura/onboarding', method })

/** First-run welcome: what Aura does, how approvals and data work, and a first prompt. Skippable;
 *  finishing or skipping is stored on the server for this account, so it shows once. */
export function AuraOnboarding({ theme }: { theme: string }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [status, setStatus] = useState<OnboardingStatus | null>(null)
  const [step, setStep] = useState(0)

  useEffect(() => {
    const api = window.hermesDesktop?.api

    if (!api) {
      return
    }

    let live = true
    Promise.resolve(onboardingApi<OnboardingStatus>('GET'))
      .then(next => live && setStatus(next))
      .catch(() => live && setStatus(null))

    return () => {
      live = false
    }
  }, [])

  const open = Boolean(status && !status.completed)

  useEffect(() => {
    const node = dialog.current

    if (open && node && !node.open) {
      node.showModal()
      // Start on the primary action, not on Skip, which is first in DOM order.
      node.querySelector<HTMLButtonElement>('.aura-onboarding-next')?.focus()
    }
  }, [open])

  const finish = (prompt?: string) => {
    dialog.current?.close()
    setStatus(current => (current ? { ...current, completed: true } : current))
    void Promise.resolve(onboardingApi('PUT')).catch(() => undefined)

    if (prompt) {
      requestComposerInsert(prompt)
    }
  }

  if (!open || !status) {
    return null
  }

  const last = step === STEPS.length - 1

  return (
    <dialog
      aria-labelledby="aura-onboarding-title"
      className="aura-dialog aura-onboarding"
      data-aura-theme={theme}
      onCancel={event => {
        event.preventDefault()
        finish()
      }}
      ref={dialog}
    >
      <div className="aura-onboarding-body">
        <img alt="" className="aura-onboarding-mark" src="brand/aura-mark.svg" />
        <p aria-live="polite" className="aura-onboarding-progress">
          Step {step + 1} of {STEPS.length}
        </p>
        <h2 id="aura-onboarding-title">{STEPS[step]}</h2>
        {step === 0 && (
          <>
            <p>Talk or type a rough idea. Aura turns it into a plan, a cited brief or finished work.</p>
            <ul>
              <li>
                <strong>Chat and research</strong> with numbered sources you can open.
              </li>
              <li>
                <strong>Voice chat</strong>: speak naturally and interrupt whenever you like.
              </li>
              <li>
                <strong>Projects</strong> keep related chats and notes together.
              </li>
            </ul>
          </>
        )}
        {step === 1 && (
          <>
            <p>
              Before Aura runs a command, acts in a browser or uses a paid model, it asks you first. Choose{' '}
              <strong>Approve</strong> to run it once or <strong>Change</strong> to stop it.
            </p>
            <p>
              Your chats are kept on this Aura server.
              {status.storage_durable
                ? ' They stay when the server restarts.'
                : ' This server does not keep data across restarts yet, so chats and settings can be cleared when it restarts.'}
            </p>
            <p>Your microphone is used only while voice chat is on, and only after you allow it.</p>
          </>
        )}
        {last && (
          <>
            <p>Pick a way to begin, or close this and type your own.</p>
            <div className="aura-onboarding-starters">
              {AURA_STARTERS.map(({ icon: Icon, label, prompt }) => (
                <button key={label} onClick={() => finish(prompt)} type="button">
                  <Icon aria-hidden="true" size={18} />
                  {label}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
      <footer className="aura-onboarding-actions">
        <button className="aura-onboarding-skip" onClick={() => finish()} type="button">
          {last ? 'Close' : 'Skip'}
        </button>
        <span className="aura-onboarding-nav">
          {step > 0 && (
            <button onClick={() => setStep(step - 1)} type="button">
              Back
            </button>
          )}
          {!last && (
            <button className="aura-onboarding-next" onClick={() => setStep(step + 1)} type="button">
              Next
            </button>
          )}
        </span>
      </footer>
    </dialog>
  )
}
