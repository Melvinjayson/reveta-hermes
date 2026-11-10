import { useStore } from '@nanostores/react'
import { useState } from 'react'

import { requestComposerFocus } from '@/app/chat/composer/focus'
import { chatMessageText } from '@/lib/chat-messages'
import { $busy, $messages } from '@/store/session'

import { AuraCard } from './card'
import { auraSources } from './sources'

function GoalCard({ text, onSave }: { text: string; onSave: (text: string) => void }) {
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

export function AuraConversationCards({ resumed }: { resumed: boolean }) {
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

  return (
    <div className="aura-context">
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
      <details>
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
      </details>
      {busy && (
        <div aria-live="polite" role="status">
          <AuraCard kind="progress" title="Finding your next step">
            <ol>
              <li>Message received</li>
              <li aria-current="step">Preparing your response…</li>
            </ol>
            <p>You can stop the response below.</p>
          </AuraCard>
        </div>
      )}
    </div>
  )
}
