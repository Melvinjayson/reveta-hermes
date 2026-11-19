import { useState } from 'react'

import { Trash2 } from '@/lib/icons'

interface AuraConversationRowProps {
  title: string
  /** The conversation open in the main pane. */
  current?: boolean
  onOpen: () => void
  /** The app's canonical delete (owner-resolved, idempotent, restores the row on failure). */
  onDelete: () => Promise<void> | void
}

/** One conversation in Aura's list: open it, or delete it after an inline confirm (no dialog inside the sheet). */
export function AuraConversationRow({ current = false, title, onOpen, onDelete }: AuraConversationRowProps) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  if (confirming) {
    return (
      <div aria-label={`Delete ${title}?`} className="aura-conversation-row aura-conversation-confirm" role="group">
        <span>Delete “{title}”? This can’t be undone.</span>
        <button
          className="aura-danger"
          disabled={busy}
          onClick={async () => {
            setBusy(true)

            try {
              await onDelete()
            } finally {
              setBusy(false)
              setConfirming(false)
            }
          }}
          type="button"
        >
          {busy ? 'Deleting…' : 'Delete'}
        </button>
        <button autoFocus disabled={busy} onClick={() => setConfirming(false)} type="button">
          Cancel
        </button>
      </div>
    )
  }

  return (
    <div className="aura-conversation-row" data-current={current || undefined}>
      <button aria-current={current ? 'page' : undefined} className="aura-conversation-open" onClick={onOpen} type="button">
        {title}
      </button>
      <button
        aria-label={`Delete conversation: ${title}`}
        className="aura-conversation-delete"
        onClick={() => setConfirming(true)}
        type="button"
      >
        <Trash2 aria-hidden="true" size={16} />
      </button>
    </div>
  )
}
