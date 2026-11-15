import { useStore } from '@nanostores/react'
import { ChevronDown } from 'lucide-react'
import { useState } from 'react'

import { requestComposerFocus } from '@/app/chat/composer/focus'
import { type ChatMessage, chatMessageText } from '@/lib/chat-messages'
import { $busy, $messages } from '@/store/session'

import { AuraCard } from './card'
import { AuraFiles } from './files'
import { $auraDismissedGoals, $auraGoalKey, $auraGoals, auraGoalProposal, dismissAuraGoal, saveAuraGoal } from './goals'
import { auraSources } from './sources'
import { AuraSteps } from './step-history'
import { type AuraStep, auraSteps } from './steps'

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

function GoalProposal({ goalKey, proposal, onEdit }: { goalKey: string; proposal: string; onEdit: () => void }) {
  return (
    <div aria-label="Proposed goal" className="aura-goal-proposal" role="group">
      <span className="aura-goal-proposal-label">Save as goal?</span>
      <span className="aura-goal-proposal-text">{proposal}</span>
      <button onClick={() => saveAuraGoal(goalKey, proposal)} type="button">
        Save
      </button>
      <button onClick={onEdit} type="button">
        Edit
      </button>
      <button aria-label="Not now" onClick={() => dismissAuraGoal(goalKey, proposal)} type="button">
        Not now
      </button>
    </div>
  )
}

function GoalRow({ goal, goalKey, onEdit }: { goal?: string; goalKey: null | string; onEdit: () => void }) {
  return (
    <div className="aura-goal-row">
      <p>{goal ?? 'No goal saved. Aura will suggest one once your intent is clear, or you can set it yourself.'}</p>
      {goalKey && (
        <button onClick={onEdit} type="button">
          {goal ? 'Edit goal' : 'Set a goal'}
        </button>
      )}
      {goal && goalKey && (
        <button onClick={() => saveAuraGoal(goalKey, '')} type="button">
          Clear
        </button>
      )}
    </div>
  )
}

function ResumeCard({ goal, messages }: { goal?: string; messages: ChatMessage[] }) {
  const lastReply = [...messages].reverse().find(message => message.role === 'assistant' && chatMessageText(message))

  return (
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
  )
}

function SourceList({ sources }: { sources: ReturnType<typeof auraSources> }) {
  return (
    <details className="aura-context-sources">
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
  )
}

function contextCounts(steps: AuraStep[], sourceCount: number) {
  const running = steps.filter(step => step.status === 'Running').length

  return [
    steps.length > 0 && `${steps.length} ${steps.length === 1 ? 'step' : 'steps'}${running ? `, ${running} running` : ''}`,
    sourceCount > 0 && `${sourceCount} ${sourceCount === 1 ? 'source' : 'sources'}`
  ].filter(Boolean)
}

function BusyStatus({ steps }: { steps: AuraStep[] }) {
  return (
    <p aria-live="polite" className="aura-context-status" role="status">
      {steps.findLast(step => step.status === 'Running')?.label.concat('…') ?? 'Waiting for Aura’s response.'} You can
      stop it below.
    </p>
  )
}

function panelTitle(resumed: boolean, goal?: string) {
  if (resumed) {
    return 'Pick up where you left off'
  }

  return goal ? 'Goal' : 'This chat'
}

function visibleProposal(messages: ChatMessage[], key: null | string, goal: string | undefined, dismissed: Record<string, string>) {
  const candidate = auraGoalProposal(messages)

  return key && !goal && candidate && dismissed[key] !== candidate ? candidate : null
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
  const proposal = visibleProposal(messages, key, goal, dismissed)
  const sources = auraSources(messages.filter(message => message.role === 'assistant').map(chatMessageText).join('\n'))
  const steps = auraSteps(messages)
  const counts = contextCounts(steps, sources.length)
  const showPanel = Boolean(goal || steps.length || sources.length || resumed || editing)
  const edit = () => setEditing(true)

  const finishEdit = (text: null | string) => {
    if (text && key) {
      saveAuraGoal(key, text)
    }

    setEditing(false)
  }

  return (
    <div className="aura-context">
      {proposal && key && !editing && <GoalProposal goalKey={key} onEdit={edit} proposal={proposal} />}
      {showPanel && (
        <details className="aura-context-panel" open={editing || undefined}>
          <summary>
            <span>{panelTitle(resumed, goal)}</span>
            {goal && <span className="aura-context-goal">{goal}</span>}
            {counts.length > 0 && <span className="aura-context-counts">{counts.join(' · ')}</span>}
            <ChevronDown aria-hidden="true" size={16} />
          </summary>
          <div className="aura-context-body">
            {editing ? (
              <GoalEditor initial={goal ?? proposal ?? ''} onDone={finishEdit} />
            ) : (
              <GoalRow goal={goal} goalKey={key} onEdit={edit} />
            )}
            {resumed && <ResumeCard goal={goal} messages={messages} />}
            {sources.length > 0 && <SourceList sources={sources} />}
            <AuraSteps steps={steps} />
          </div>
        </details>
      )}
      <AuraFiles messages={messages} />
      {busy && <BusyStatus steps={steps} />}
    </div>
  )
}
