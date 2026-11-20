import { type FormEvent, useEffect, useState } from 'react'

export interface AuraBudgetRow {
  request_id: string
  model: string
  tier: string
  reserved_usd: number
  actual_usd: number | null
  status: 'reserved' | 'reconciled' | 'usage_unknown' | 'released'
  created_at: string
}

export interface AuraBudgetStatus {
  currency: 'USD'
  limit_usd: number
  paid_enabled: boolean
  spent_usd: number
  reserved_usd: number
  remaining_usd: number
  percent_used: number
  state: 'active' | 'approaching' | 'reached'
  updated_at: string | null
  by_model: { model: string; tier: string; requests: number; spent_usd: number }[]
  history: AuraBudgetRow[]
}

const STATE_LABEL: Record<AuraBudgetStatus['state'], string> = {
  active: 'Active',
  approaching: 'Approaching limit',
  reached: 'Reached'
}

const ROW_STATUS: Record<AuraBudgetRow['status'], string> = {
  reserved: 'In progress',
  reconciled: 'Settled',
  usage_unknown: 'Cost not reported · full estimate counted',
  released: 'Not charged'
}

const budgetApi = <T,>(method: 'GET' | 'PUT', body?: unknown) =>
  window.hermesDesktop.api<T>({ path: '/api/aura/budget', method, ...(body ? { body } : {}) })

export const usd = (value: number) => `$${value < 0.01 && value > 0 ? value.toFixed(4) : value.toFixed(2)}`

function errorText(error: unknown) {
  const text = error instanceof Error ? error.message : String(error)

  if (/\b403\b|only the owner/i.test(text)) {
    return 'Only the owner account can see or change the budget.'
  }

  return text.replace(/^.*?"detail":\s*"([^"]+)".*$/s, '$1')
}

/** Settings → Model → Spending budget. The server holds the limit and the ledger; this only shows them. */
export function AuraBudgetSettings() {
  const [status, setStatus] = useState<AuraBudgetStatus | null>(null)
  const [limit, setLimit] = useState('')
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)

  const show = (next: AuraBudgetStatus) => {
    setStatus(next)
    setLimit(String(next.limit_usd))
  }

  useEffect(() => {
    budgetApi<AuraBudgetStatus>('GET')
      .then(show)
      .catch(error => setMessage(errorText(error)))
  }, [])

  const save = async (body: { limit_usd?: number; paid_enabled?: boolean }, done: string) => {
    setSaving(true)
    setMessage('')

    try {
      show(await budgetApi<AuraBudgetStatus>('PUT', body))
      setMessage(done)
    } catch (error) {
      setMessage(errorText(error))
    } finally {
      setSaving(false)
    }
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const value = Number(limit)

    if (!Number.isFinite(value) || value < 0) {
      setMessage('Enter an amount of $0 or more.')

      return
    }

    void save({ limit_usd: value }, `Budget set to ${usd(value)}.`)
  }

  const used = status ? Math.min(status.percent_used, 100) : 0

  return (
    <form aria-labelledby="aura-budget-title" className="aura-budget" noValidate onSubmit={submit}>
      <h3 id="aura-budget-title">Spending budget</h3>
      <p className="aura-budget-note">
        The most Aura may spend on paid models in total. It doesn’t buy provider credit: your provider bills its own account.
      </p>
      {status && (
        <>
          <div className="aura-budget-figures">
            <p>
              <span>Spent</span>
              <strong>{usd(status.spent_usd)}</strong>
            </p>
            <p>
              <span>Reserved now</span>
              <strong>{usd(status.reserved_usd)}</strong>
            </p>
            <p>
              <span>Remaining</span>
              <strong>{usd(status.remaining_usd)}</strong>
            </p>
          </div>
          <div
            aria-label={`${status.percent_used}% of the budget used`}
            aria-valuemax={100}
            aria-valuemin={0}
            aria-valuenow={used}
            className="aura-budget-meter"
            data-state={status.state}
            role="progressbar"
          >
            <span style={{ width: `${used}%` }} />
          </div>
          <p className="aura-budget-state" data-state={status.state}>
            {STATE_LABEL[status.state]} · {status.percent_used}% used
            {status.updated_at ? ` · updated ${new Date(status.updated_at).toLocaleString()}` : ''}
          </p>
          <label className="aura-budget-switch">
            <span>Allow paid models</span>
            <input
              checked={status.paid_enabled}
              className="aura-switch"
              disabled={saving}
              onChange={e =>
                void save(
                  { paid_enabled: e.target.checked },
                  e.target.checked ? 'Paid models may now run within the budget.' : 'Paid models are off.'
                )
              }
              role="switch"
              type="checkbox"
            />
          </label>
          <label>
            Budget limit (USD)
            <input
              inputMode="decimal"
              max="1000"
              min="0"
              onChange={e => setLimit(e.target.value)}
              step="0.01"
              type="number"
              value={limit}
            />
          </label>
          <button disabled={saving} type="submit">
            {saving ? 'Saving…' : 'Save budget'}
          </button>
          {status.by_model.length > 0 && (
            <section aria-label="Spending by model">
              <h4>By model</h4>
              <ul className="aura-budget-list">
                {status.by_model.map(row => (
                  <li key={`${row.model}:${row.tier}`}>
                    <code>{row.model}</code>
                    <span>
                      {row.requests} requests · {usd(row.spent_usd)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {status.history.length > 0 && (
            <section aria-label="Recent paid requests">
              <h4>Recent requests</h4>
              <ul className="aura-budget-list">
                {status.history.map(row => (
                  <li key={row.request_id}>
                    <code>{row.model}</code>
                    <span>
                      {ROW_STATUS[row.status]} · {usd(row.actual_usd ?? row.reserved_usd)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
      {message && <p role="status">{message}</p>}
    </form>
  )
}
