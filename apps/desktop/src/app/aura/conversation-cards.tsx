import { useStore } from '@nanostores/react'
import { ChevronDown } from 'lucide-react'
import { useEffect, useState } from 'react'

import { requestComposerFocus, requestComposerInsert, requestComposerSubmit } from '@/app/chat/composer/focus'
import { chatMessageText } from '@/lib/chat-messages'
import { $busy, $messages } from '@/store/session'

import { AuraCard } from './card'
import { auraFiles } from './files'
import {
  $auraDismissedGoals,
  $auraGoalKey,
  $auraGoals,
  auraGoalProposal,
  auraReplyHints,
  dismissAuraGoal,
  saveAuraGoal
} from './goals'
import { clock, openAuraPanel } from './panel-store'
import { auraSources } from './sources'
import { auraSteps } from './steps'

interface AuraConversationCardsProps {
  resumed: boolean
}

function GoalEditor({ initial, onDone }: { initial: string; onDone: (text: null | string) => void }) {
  const [draft, setDraft] = useState(initial)

  return (
    <form
      className="aura-goal-form"
      onSubmit={event => {
        event.preventDefault()
        onDone(draft.trim())
      }}
    >
      <label>
        Your goal
        <textarea autoFocus maxLength={500} onChange={event => setDraft(event.target.value)} rows={2} value={draft} />
      </label>
      <div className="aura-card-actions">
        <button disabled={!draft.trim()} type="submit">
          Save goal
        </button>
        <button onClick={() => onDone(null)} type="button">
          Cancel
        </button>
      </div>
    </form>
  )
}

function LiveClock({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now() / 1000)

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000)

    return () => window.clearInterval(timer)
  }, [])

  return <time className="aura-strip-time">{clock(now - since)}</time>
}

export function AuraConversationCards({ resumed }: AuraConversationCardsProps) {
  const messages = useStore($messages)
  const busy = useStore($busy)
  const key = useStore($auraGoalKey)
  const goals = useStore($auraGoals)
  const dismissed = useStore($auraDismissedGoals)
  const [editing, setEditing] = useState(false)

  // A conversation, not its first message, is what this panel is about. Nothing is a goal until confirmed.
  if (!messages.some(message => message.role === 'user' && !message.hidden)) {
    return null
  }

  const goal = key ? goals[key] : undefined
  const candidate = auraGoalProposal(messages)
  const proposal = key && !goal && candidate && dismissed[key] !== candidate ? candidate : null
  const sources = auraSources(messages.filter(message => message.role === 'assistant').map(chatMessageText).join('\n'))
  const steps = auraSteps(messages)
  const running = steps.filter(step => step.status === 'Running').length
  const lastReply = [...messages].reverse().find(message => message.role === 'assistant' && chatMessageText(message))
  const hints = auraReplyHints(messages, busy)

  const sendReply = (text: string) => {
    // Sends like a typed reply; if no composer is visible to take it, it is left in the text box instead.
    if (!requestComposerSubmit(text)) {
      requestComposerInsert(text, { mode: 'block' })
      requestComposerFocus()
    }
  }

  const files = new Set(auraFiles(messages).map(file => file.path)).size
  const plural = (n: number, word: string) => `${n} ${n === 1 ? word : `${word}s`}`
  const showPanel = Boolean(goal || resumed || editing)
  const live = steps.findLast(step => step.status === 'Running')

  const finishEdit = (text: null | string) => {
    if (text && key) {
      saveAuraGoal(key, text)
    }

    setEditing(false)
  }

  return (
    <div className="aura-context">
      {proposal && !editing && (
        <div aria-label="Proposed goal" className="aura-goal-proposal" role="group">
          <span className="aura-goal-proposal-label">Save as goal?</span>
          <span className="aura-goal-proposal-text">{proposal}</span>
          <button onClick={() => saveAuraGoal(key!, proposal)} type="button">
            Save
          </button>
          <button onClick={() => setEditing(true)} type="button">
            Edit
          </button>
          <button aria-label="Not now" onClick={() => dismissAuraGoal(key!, proposal)} type="button">
            Not now
          </button>
        </div>
      )}
      {hints.tag && (
        <div aria-label="Quick replies" className="aura-quick-replies" role="group">
          <span className="aura-ai-tag" title="Inferred from Aura’s reply">
            <span aria-hidden="true">AI</span>
            <span className="sr-only">Aura’s reply, inferred:</span> {hints.tag}
          </span>
          {hints.replies.map(reply => (
            <button key={reply} onClick={() => sendReply(reply)} type="button">
              {reply}
            </button>
          ))}
        </div>
      )}
      {showPanel && (
        <details className="aura-context-panel" open={editing || undefined}>
          <summary>
            <span>{resumed ? 'Pick up where you left off' : goal ? 'Goal' : 'This chat'}</span>
            {goal && <span className="aura-context-goal">{goal}</span>}
            <ChevronDown aria-hidden="true" size={16} />
          </summary>
          <div className="aura-context-body">
            {editing ? (
              <GoalEditor initial={goal ?? proposal ?? ''} onDone={finishEdit} />
            ) : (
              <div className="aura-goal-row">
                <p>{goal ?? 'No goal saved. Aura will suggest one once your intent is clear, or you can set it yourself.'}</p>
                {key && (
                  <button onClick={() => setEditing(true)} type="button">
                    {goal ? 'Edit goal' : 'Set a goal'}
                  </button>
                )}
                {goal && key && (
                  <button onClick={() => saveAuraGoal(key, '')} type="button">
                    Clear
                  </button>
                )}
              </div>
            )}
            {resumed && (
              <AuraCard kind="resume" onResume={() => requestComposerFocus()} title="Pick up where you left off">
                {goal && (
                  <p>
                    <strong>Goal:</strong> {goal.slice(0, 160)}
                  </p>
                )}
                <p>
                  <strong>Last step:</strong> {lastReply ? chatMessageText(lastReply).slice(0, 180) : 'No reply yet.'}
                </p>
                <p>
                  <strong>Next step:</strong> Tell Aura what you’d like to continue or change.
                </p>
              </AuraCard>
            )}
          </div>
        </details>
      )}
      {(steps.length > 0 || sources.length > 0 || files > 0 || busy) && (
        <div aria-label="This chat" className="aura-strip" role="group">
          {busy ? (
            <button className="aura-strip-live" onClick={() => openAuraPanel('work')} type="button">
              <span aria-hidden="true" className="aura-live-dot" />
              <span aria-live="polite" className="aura-context-status" role="status">
                {live ? `${live.label}…` : 'Working…'}
              </span>
              {live?.timestamp !== undefined && <LiveClock since={live.timestamp} />}
              <span className="sr-only">You can stop it below.</span>
            </button>
          ) : (
            steps.length > 0 && (
              <button onClick={() => openAuraPanel('work')} type="button">
                {plural(steps.length, 'step')}
                {running ? `, ${running} running` : ''}
              </button>
            )
          )}
          {sources.length > 0 && (
            <button onClick={() => openAuraPanel('sources')} type="button">
              {plural(sources.length, 'source')}
            </button>
          )}
          {files > 0 && (
            <button onClick={() => openAuraPanel('files')} type="button">
              {plural(files, 'file')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
