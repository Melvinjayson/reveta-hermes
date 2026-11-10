import type { ReactNode } from 'react'

export interface AuraCardProps {
  kind: 'goal' | 'source' | 'progress' | 'approval' | 'resume'
  title: string
  children: ReactNode
  onApprove?: () => void
  onChange?: () => void
  onResume?: () => void
}

/** Presentation only. Approval callbacks must come from the pending runtime request. */
export function AuraCard({ children, kind, onApprove, onChange, onResume, title }: AuraCardProps) {
  return (
    <section aria-label={`${kind}: ${title}`} className="aura-card" data-aura-card={kind}>
      <p className="aura-eyebrow">{kind === 'approval' ? 'Your approval is needed' : kind}</p>
      <h2>{title}</h2>
      <div>{children}</div>
      {kind === 'approval' && (
        <div className="aura-card-actions">
          <button disabled={!onApprove} onClick={onApprove} type="button">
            Approve
          </button>
          <button disabled={!onChange} onClick={onChange} type="button">
            Change
          </button>
        </div>
      )}
      {kind === 'resume' && onResume && (
        <button onClick={onResume} type="button">
          Resume conversation
        </button>
      )}
    </section>
  )
}
