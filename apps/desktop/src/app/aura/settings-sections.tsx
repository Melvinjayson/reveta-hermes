import { useStore } from '@nanostores/react'
import { type ReactNode, useCallback, useEffect, useState } from 'react'

import { $auraCapabilities, $auraToolsOpen, loadAuraCapabilities } from './capabilities'

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE'

function call<T>(path: string, method: Method = 'GET', body?: unknown) {
  return window.hermesDesktop.api<T>({ path, method, ...(body ? { body } : {}) })
}

function errorText(error: unknown) {
  const text = error instanceof Error ? error.message : String(error)

  return text.replace(/^.*?"detail":\s*"([^"]+)".*$/s, '$1')
}

/** Load-on-mount with honest loading / error states and a reload for after mutations. */
function useResource<T>(path: string) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')

  const reload = useCallback(() => {
    setError('')

    return call<T>(path)
      .then(setData)
      .catch(err => setError(errorText(err)))
  }, [path])

  useEffect(() => {
    void reload()
  }, [reload])

  return { data, error, reload, setError }
}

/** Whether the matching capability is switched on for new chats, with a link to Tools. */
function CapabilityNote({ id, children }: { id: string; children: ReactNode }) {
  const status = useStore($auraCapabilities)
  const capability = status?.capabilities.find(c => c.id === id)

  useEffect(() => {
    if (!status) {
      void loadAuraCapabilities()
    }
  }, [status])

  return (
    <p className="aura-capability-note">
      {children}{' '}
      {capability ? (
        capability.enabled ? (
          <strong>On for new chats.</strong>
        ) : capability.available ? (
          <>
            <strong>Off.</strong>{' '}
            <button className="aura-link-button" onClick={() => $auraToolsOpen.set(true)} type="button">
              Turn on in Tools
            </button>
          </>
        ) : (
          <strong>Not set up on this server.</strong>
        )
      ) : null}
    </p>
  )
}

/** Warns that a restart can erase this only when the server says its storage is not durable. */
function StorageNote() {
  const { data } = useResource<{ storage_durable: boolean }>('/api/aura/onboarding')

  return data && !data.storage_durable ? (
    <p className="aura-muted">
      This server doesn’t keep data across restarts yet, so a restart or redeploy can erase this.
    </p>
  ) : null
}

function Confirm({ label, prompt, onConfirm }: { label: string; prompt: string; onConfirm: () => Promise<unknown> }) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)

  if (!asking) {
    return (
      <button className="aura-button aura-button-secondary" onClick={() => setAsking(true)} type="button">
        {label}
      </button>
    )
  }

  return (
    <span aria-label={prompt} className="aura-confirm" role="group">
      <span>{prompt}</span>
      <button
        className="aura-button aura-button-danger"
        disabled={busy}
        onClick={async () => {
          setBusy(true)
          await onConfirm()
          setBusy(false)
          setAsking(false)
        }}
        type="button"
      >
        {busy ? 'Working…' : 'Confirm'}
      </button>
      <button autoFocus className="aura-button aura-button-secondary" onClick={() => setAsking(false)} type="button">
        Cancel
      </button>
    </span>
  )
}

interface MemoryNotes {
  memory: { text: string; truncated: boolean }
  user: { text: string; truncated: boolean }
}

export function AuraMemorySection() {
  const { data, error, reload, setError } = useResource<MemoryNotes>('/api/aura/memory')

  const reset = (target: 'memory' | 'user') =>
    call('/api/memory/reset', 'POST', { target })
      .then(reload)
      .catch(err => setError(errorText(err)))

  return (
    <section aria-labelledby="aura-settings-memory">
      <h3 id="aura-settings-memory">Memory</h3>
      <CapabilityNote id="memory">Aura keeps short notes about your work and you, and reads them in new chats.</CapabilityNote>
      {error && <p role="alert">{error}</p>}
      {!data && !error && <p role="status">Loading memory…</p>}
      {data &&
        (
          [
            ['memory', 'Notes about your work'],
            ['user', 'About you']
          ] as const
        ).map(([key, title]) => (
          <div className="aura-settings-block" key={key}>
            <h4>{title}</h4>
            {data[key].text ? (
              <pre className="aura-memory-text">{data[key].text}</pre>
            ) : (
              <p className="aura-empty-note">Nothing saved yet.</p>
            )}
            {data[key].truncated && <p className="aura-muted">Showing the first part only.</p>}
            {data[key].text && (
              <Confirm label="Clear…" onConfirm={() => reset(key)} prompt={`Clear “${title}”? This can’t be undone.`} />
            )}
          </div>
        ))}
      <StorageNote />
    </section>
  )
}

interface Skill {
  name: string
  description?: string
  category?: string
  enabled: boolean
  provenance?: string
}

export function AuraSkillsSection() {
  const { data, error, reload, setError } = useResource<Skill[]>('/api/skills')
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<null | string>(null)
  const [content, setContent] = useState('')

  useEffect(() => {
    setContent('')

    if (open) {
      call<{ content?: string }>(`/api/skills/content?name=${encodeURIComponent(open)}`)
        .then(result => setContent(result.content ?? ''))
        .catch(err => setContent(`Couldn’t load this skill: ${errorText(err)}`))
    }
  }, [open])

  const needle = query.trim().toLowerCase()

  const shown = (data ?? []).filter(
    skill => !needle || skill.name.toLowerCase().includes(needle) || (skill.description ?? '').toLowerCase().includes(needle)
  )

  const toggle = (skill: Skill) =>
    call('/api/skills/toggle', 'PUT', { name: skill.name, enabled: !skill.enabled })
      .then(reload)
      .catch(err => setError(errorText(err)))

  return (
    <section aria-labelledby="aura-settings-skills">
      <h3 id="aura-settings-skills">Skills</h3>
      <CapabilityNote id="skills">Skills are step-by-step guides Aura can follow.</CapabilityNote>
      {error && <p role="alert">{error}</p>}
      {!data && !error && <p role="status">Loading skills…</p>}
      {data && (
        <>
          <input aria-label="Search skills" onChange={event => setQuery(event.target.value)} placeholder="Search skills" value={query} />
          <p className="aura-muted">
            {shown.length} of {data.length} skills
          </p>
          <ul className="aura-settings-list">
            {shown.slice(0, 200).map(skill => (
              <li key={skill.name}>
                <div className="aura-settings-item">
                  <button className="aura-settings-item-main" onClick={() => setOpen(open === skill.name ? null : skill.name)} type="button">
                    <span className="aura-tool-name">{skill.name}</span>
                    {skill.description && <span className="aura-muted">{skill.description}</span>}
                  </button>
                  <input
                    aria-label={`${skill.name} enabled`}
                    checked={skill.enabled}
                    className="aura-switch"
                    onChange={() => void toggle(skill)}
                    role="switch"
                    type="checkbox"
                  />
                </div>
                {open === skill.name && <pre className="aura-memory-text">{content || 'Loading…'}</pre>}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

interface CronJob {
  id: string
  name?: string
  schedule_display?: string
  state?: string
  enabled?: boolean
  next_run_at?: null | string
  last_run_at?: null | string
}

function when(value?: null | string) {
  if (!value) {
    return '—'
  }

  const date = new Date(value)

  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export function AuraJobsSection() {
  const { data, error, reload, setError } = useResource<CronJob[] | { jobs: CronJob[] }>('/api/cron/jobs')
  const jobs = Array.isArray(data) ? data : (data?.jobs ?? [])

  const act = (job: CronJob, path: string, method: Method = 'POST') =>
    call(`/api/cron/jobs/${encodeURIComponent(job.id)}${path}`, method)
      .then(reload)
      .catch(err => setError(errorText(err)))

  return (
    <section aria-labelledby="aura-settings-jobs">
      <h3 id="aura-settings-jobs">Scheduled jobs</h3>
      <CapabilityNote id="cronjob">Ask Aura in a chat to schedule something; jobs then appear here.</CapabilityNote>
      <p className="aura-muted">
        Jobs run while you are away, so any step that would need your approval is refused rather than run.
      </p>
      {error && <p role="alert">{error}</p>}
      {!data && !error && <p role="status">Loading jobs…</p>}
      {data && !jobs.length && <p className="aura-empty-note">No scheduled jobs.</p>}
      <ul className="aura-settings-list">
        {jobs.map(job => {
          const paused = job.state === 'paused'

          return (
            <li data-aura-job={job.state} key={job.id}>
              <div className="aura-settings-item">
                <div className="aura-settings-item-main">
                  <span className="aura-tool-name">{job.name || job.id}</span>
                  <span className="aura-muted">
                    {job.schedule_display || 'No schedule'} · {job.state ?? 'unknown'} · next {when(job.next_run_at)}
                  </span>
                </div>
              </div>
              <div className="aura-settings-actions">
                <button className="aura-button aura-button-secondary" onClick={() => void act(job, paused ? '/resume' : '/pause')} type="button">
                  {paused ? 'Resume' : 'Pause'}
                </button>
                <button className="aura-button aura-button-secondary" onClick={() => void act(job, '/trigger')} type="button">
                  Run now
                </button>
                <Confirm label="Delete…" onConfirm={() => act(job, '', 'DELETE')} prompt={`Delete “${job.name || job.id}”?`} />
              </div>
            </li>
          )
        })}
      </ul>
      <StorageNote />
    </section>
  )
}

interface McpServer {
  name: string
  transport: string
  url?: null | string
  enabled: boolean
  source: string
}

export function AuraConnectorsSection() {
  const { data, error, reload, setError } = useResource<{ servers: McpServer[] }>('/api/mcp/servers')
  const servers = data?.servers ?? []
  const composio = servers.some(server => server.name === 'composio')

  const toggle = (server: McpServer) =>
    call(`/api/mcp/servers/${encodeURIComponent(server.name)}/enabled`, 'PUT', { enabled: !server.enabled })
      .then(reload)
      .catch(err => setError(errorText(err)))

  return (
    <section aria-labelledby="aura-settings-connectors">
      <h3 id="aura-settings-connectors">Connectors</h3>
      <p className="aura-capability-note">
        Connectors give Aura tools from other services (MCP servers). Changes apply to new chats; actions that send,
        submit, buy or delete still ask first.
      </p>
      {error && <p role="alert">{error}</p>}
      {!data && !error && <p role="status">Loading connectors…</p>}
      <ul className="aura-settings-list">
        {servers.map(server => (
          <li key={server.name}>
            <div className="aura-settings-item">
              <div className="aura-settings-item-main">
                <span className="aura-tool-name">{server.name}</span>
                <span className="aura-muted">
                  {server.transport}
                  {server.url ? ` · ${new URL(server.url).host}` : ''}
                  {server.source === 'plugin' ? ' · provided by a plugin' : ''}
                </span>
              </div>
              <input
                aria-label={`${server.name} enabled`}
                checked={server.enabled}
                className="aura-switch"
                disabled={server.source === 'plugin'}
                onChange={() => void toggle(server)}
                role="switch"
                type="checkbox"
              />
            </div>
          </li>
        ))}
      </ul>
      {data && !composio && (
        <div className="aura-settings-block" data-aura-blocked="composio">
          <h4>Composio Connect</h4>
          <p className="aura-tool-blocked">
            Not set up. It needs a Composio API key added to the server’s environment by the owner. Aura never asks for
            keys in a chat.
          </p>
        </div>
      )}
      {data && !servers.length && <p className="aura-empty-note">No connectors are configured.</p>}
    </section>
  )
}

interface PreviewStatus {
  companion: boolean
  handoff: boolean
  venus_evidence: boolean
  restart_required?: boolean
}

const PREVIEW_SWITCHES: { key: keyof Omit<PreviewStatus, 'restart_required'>; label: string; note: string }[] = [
  {
    key: 'venus_evidence',
    label: 'Run evidence (Venus)',
    note: 'Records counts, durations and outcomes for each run, never what was said. Type /venus-value in a chat to add your time comparison.'
  },
  {
    key: 'companion',
    label: 'Browser companion',
    note: 'Lets the Aura Companion extension connect to this account. Planning uses your paid model and its limits from Model.'
  },
  {
    key: 'handoff',
    label: 'Send tasks to your browser',
    note: 'Adds a Your browser card to chats. Needs the companion on. Steps that send, submit, buy or delete still ask here first.'
  }
]

/** Owner-only preview switches (`/api/aura/preview`). Anyone else sees why they can't change them. */
export function AuraPreviewSection() {
  const { data, error, setError } = useResource<PreviewStatus>('/api/aura/preview')
  const [status, setStatus] = useState<PreviewStatus | null>(null)
  const current = status ?? data

  const flip = (key: keyof Omit<PreviewStatus, 'restart_required'>) =>
    call<PreviewStatus>('/api/aura/preview', 'PUT', { [key]: !current?.[key] })
      .then(setStatus)
      .catch(err => setError(errorText(err)))

  return (
    <section aria-labelledby="aura-settings-preview">
      <h3 id="aura-settings-preview">Preview</h3>
      <p className="aura-capability-note">
        Early features for the owner account only. They stay off for everyone else, and they reset if the server&apos;s
        disk is wiped (Render free does this after a quiet spell): switch them on again here.
      </p>
      {error && <p role="alert">{error}</p>}
      {!current && !error && <p role="status">Loading preview features…</p>}
      {current && (
        <ul className="aura-settings-list">
          {PREVIEW_SWITCHES.map(item => (
            <li key={item.key}>
              <div className="aura-settings-item">
                <div className="aura-settings-item-main">
                  <span className="aura-tool-name">{item.label}</span>
                  <span className="aura-muted">{item.note}</span>
                </div>
                <input
                  aria-label={`${item.label} enabled`}
                  checked={current[item.key]}
                  className="aura-switch"
                  disabled={item.key === 'handoff' && !current.companion && !current.handoff}
                  onChange={() => void flip(item.key)}
                  role="switch"
                  type="checkbox"
                />
              </div>
            </li>
          ))}
        </ul>
      )}
      {current?.restart_required && (
        <p className="aura-muted" role="status">
          Run evidence is off for new settings; the running server keeps recording until it restarts.
        </p>
      )}
    </section>
  )
}

interface VoiceMode {
  full_duplex: boolean
  enabled: boolean
  runtime: boolean
}

/** Owner switch for full-duplex voice. Off by default; the browser voice stays the fallback. */
export function AuraVoiceModeSetting() {
  const { data, error, setError } = useResource<VoiceMode>('/api/aura/voice/mode')
  const [mode, setMode] = useState<VoiceMode | null>(null)
  const current = mode ?? data

  const toggle = () =>
    current &&
    call<VoiceMode>('/api/aura/voice/mode', 'PUT', { full_duplex: !current.enabled })
      .then(setMode)
      .catch(err => setError(errorText(err)))

  return (
    <div className="aura-settings-item">
      <div className="aura-settings-item-main">
        <span className="aura-tool-name">Full-duplex voice</span>
        <span className="aura-muted">
          Talk and interrupt at any time, with speech handled on the server. Applies the next time you start Voice chat.
        </span>
        {current?.enabled && !current.runtime && (
          <span className="aura-muted" role="status">
            This server can’t run it (its speech runtime isn’t available), so Aura keeps the browser voice.
          </span>
        )}
        {error && <span role="alert">{error}</span>}
      </div>
      <input
        aria-label="Full-duplex voice"
        checked={Boolean(current?.enabled)}
        className="aura-switch"
        disabled={!current}
        onChange={() => void toggle()}
        role="switch"
        type="checkbox"
      />
    </div>
  )
}
