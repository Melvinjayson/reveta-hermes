import { useStore } from '@nanostores/react'
import { ChevronDown } from 'lucide-react'
import { useState } from 'react'

import { requestComposerFocus } from '@/app/chat/composer/focus'
import { chatMessageText } from '@/lib/chat-messages'
import { $busy, $messages } from '@/store/session'

import { AuraCard } from './card'
import { AuraFiles } from './files'
import { auraSources } from './sources'
import { AuraSteps } from './step-history'
import { auraSteps } from './steps'

interface GoalCardProps {
  text: string
  onSave: (text: string) => void
}

interface AuraConversationCardsProps {
  resumed: boolean
}

function GoalCard({ text, onSave }: GoalCardProps) {
  const goal = text
  const [draft, setDraft] = useState(text)
  const [editing, setEditing] = useState(false)

  return (
    <AuraCard kind="goal" title="What we’re working toward">
      {editing ? (
        <form
          onSubmit={event => {
            event.preventDefault()

            if (draft.trim()) {
              onSave(draft.trim())
              setEditing(false)
            }
          }}
        >
          <label>
            Your goal
            <textarea autoFocus maxLength={500} onChange={event => setDraft(event.target.value)} value={draft} />
          </label>
          <div className="aura-card-actions">
            <button type="submit">Save goal</button>
            <button onClick={() => setEditing(false)} type="button">
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          <p>{goal}</p>
          <button
            onClick={() => {
              setDraft(goal)
              setEditing(true)
            }}
            type="button"
          >
            Edit goal
          </button>
        </>
      )}
    </AuraCard>
  )
}

export function AuraConversationCards({ resumed }: AuraConversationCardsProps) {
  const [goals, setGoals] = useState<Record<string, string>>({})
  const messages = useStore($messages)
  const busy = useStore($busy)
  const goal = messages.find(message => message.role === 'user' && !message.hidden)

  const text = messages
    .filter(message => message.role === 'assistant')
    .map(chatMessageText)
    .join('\n')

  const sources = auraSources(text)
  const lastReply = [...messages].reverse().find(message => message.role === 'assistant' && chatMessageText(message))

  if (!goal) {
    return null
  }

  const goalText = goals[goal.id] ?? chatMessageText(goal)
  const steps = auraSteps(messages)
  const running = steps.filter(step => step.status === 'Running').length

  return (
    <div className="aura-context">
      <details className="aura-context-panel">
        <summary>
          <span>{resumed ? 'Pick up where you left off' : 'Goal'}</span>
          <span className="aura-context-goal">{goalText}</span>
          <span className="aura-context-counts">
            {steps.length} {steps.length === 1 ? 'step' : 'steps'}, {running} running · {sources.length} {sources.length === 1 ? 'source' : 'sources'}
          </span>
          <ChevronDown aria-hidden="true" size={16} />
        </summary>
        <div className="aura-context-body">
          <GoalCard key={goal.id} onSave={text => setGoals(current => ({ ...current, [goal.id]: text }))} text={goalText} />
          {resumed && (
            <AuraCard kind="resume" onResume={() => requestComposerFocus()} title="Pick up where you left off">
              <p>
                <strong>Goal:</strong> {goalText.slice(0, 160)}
              </p>
              <p>
                <strong>Last step:</strong> {lastReply ? chatMessageText(lastReply).slice(0, 180) : 'No reply yet.'}
              </p>
              <p>
                <strong>Next step:</strong> Tell Aura what you’d like to continue or change.
              </p>
            </AuraCard>
          )}
          {sources.length > 0 && <details className="aura-context-sources">
            <summary>Sources in this conversation</summary>
            {sources.map(([url, label]) => (
              <AuraCard key={url} kind="source" title={label}>
                <p>{new URL(url).hostname} · Date not provided</p>
                <p>Referenced in Aura’s reply. Open the source to check the original.</p>
                <a href={url} rel="noreferrer" target="_blank">
                  {new URL(url).hostname}
                </a>
              </AuraCard>
            ))}
          </details>}
          <AuraSteps steps={steps} />
        </div>
      </details>
      <AuraFiles messages={messages} />
      {busy && (
        <p aria-live="polite" className="aura-context-status" role="status">
          Waiting for Aura’s response. You can stop it below.
        </p>
      )}
    </div>
  )
}
