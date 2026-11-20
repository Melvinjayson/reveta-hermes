import { type FormEvent, useEffect, useState } from 'react'

interface ModelOption {
  provider: string
  label: string
  model: string
  input_per_million_usd: number
  output_per_million_usd: number
}

export interface AuraProviderStatus {
  paid_route: null | { provider: string; model: string; per_day_usd: number; per_chat_usd: number }
  active_model: { provider?: string; model?: string }
  spent_today_usd: number
  keys: Record<string, boolean>
  gemini_key: boolean
  options: ModelOption[]
}

const providerApi = <T,>(method: 'GET' | 'PUT', body?: unknown) =>
  window.hermesDesktop.api<T>({ path: '/api/aura/provider', method, ...(body ? { body } : {}) })

function errorText(error: unknown) {
  const text = error instanceof Error ? error.message : String(error)

  return text.replace(/^.*?"detail":\s*"([^"]+)".*$/s, '$1')
}

/** Owner-set chat model, API key and USD caps; keys are write-only from here. */
export function AuraModelSettings({ onSaved }: { onSaved?: () => void }) {
  const [status, setStatus] = useState<AuraProviderStatus | null>(null)
  const [provider, setProvider] = useState('openai')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [perDay, setPerDay] = useState('2')
  const [perChat, setPerChat] = useState('0.5')
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)

  const show = (next: AuraProviderStatus) => {
    setStatus(next)

    if (next.paid_route) {
      setProvider(next.paid_route.provider)
      setModel(next.paid_route.model)
      setPerDay(String(next.paid_route.per_day_usd))
      setPerChat(String(next.paid_route.per_chat_usd))
    }
  }

  useEffect(() => {
    providerApi<AuraProviderStatus>('GET')
      .then(show)
      .catch(error => setMessage(`Couldn’t load model settings: ${errorText(error)}`))
  }, [])

  const models = status?.options.filter(o => o.provider === provider) ?? []
  const chosen = models.find(o => o.model === model) ?? models[0]
  const label = provider === 'anthropic' ? 'Anthropic' : 'OpenAI'
  const hasKey = Boolean(status?.keys[provider])

  const save = async (body: Record<string, unknown>, done: string) => {
    setSaving(true)
    setMessage('')

    try {
      show(await providerApi<AuraProviderStatus>('PUT', body))
      setApiKey('')
      setMessage(done)
      onSaved?.()
    } catch (error) {
      setMessage(errorText(error))
    } finally {
      setSaving(false)
    }
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()

    if (!chosen) {
      return
    }

    void save(
      {
        provider,
        model: chosen.model,
        api_key: apiKey,
        per_day_usd: Number(perDay),
        per_chat_usd: Number(perChat)
      },
      `Aura now replies with ${chosen.model}. New messages use it straight away.`
    )
  }

  return (
    <form className="aura-model-settings" onSubmit={submit}>
      <h2>Model</h2>
      <p aria-live="polite">
        {status?.paid_route
          ? `Replying with ${status.paid_route.model}. $${status.spent_today_usd.toFixed(2)} of $${status.paid_route.per_day_usd.toFixed(2)} used today.`
          : 'Replying with Google Gemini’s free tier. It has a low per-minute limit.'}
      </p>
      <label>
        Provider
        <select
          onChange={e => {
            setProvider(e.target.value)
            setModel('')
          }}
          value={provider}
        >
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
        </select>
      </label>
      <label>
        Model
        <select onChange={e => setModel(e.target.value)} value={chosen?.model ?? ''}>
          {models.map(o => (
            <option key={o.model} value={o.model}>
              {o.model} (${o.input_per_million_usd} in / ${o.output_per_million_usd} out per million tokens)
            </option>
          ))}
        </select>
      </label>
      <label>
        {label} API key
        <input
          autoComplete="off"
          onChange={e => setApiKey(e.target.value)}
          placeholder={hasKey ? 'Saved. Paste a new key to replace it.' : 'Paste your key'}
          type="password"
          value={apiKey}
        />
      </label>
      <label>
        Daily limit (USD)
        <input inputMode="decimal" min="0.01" onChange={e => setPerDay(e.target.value)} step="0.01" type="number" value={perDay} />
      </label>
      <label>
        Limit per chat (USD)
        <input inputMode="decimal" min="0.01" onChange={e => setPerChat(e.target.value)} step="0.01" type="number" value={perChat} />
      </label>
      <button disabled={saving || !chosen || (!hasKey && !apiKey.trim())} type="submit">
        {saving ? 'Saving…' : `Use ${label}`}
      </button>
      {status?.paid_route && (
        <button
          disabled={saving}
          onClick={() => void save({ provider: 'gemini' }, 'Back on Gemini’s free tier.')}
          type="button"
        >
          Switch back to free Gemini
        </button>
      )}
      {message && <p role="status">{message}</p>}
      <p>Your key is sent to your Aura server and is not displayed again here. Retention across server restarts requires durable secret storage; a successful save does not verify that durability. Aura stops replying when a configured limit is reached.</p>
    </form>
  )
}
