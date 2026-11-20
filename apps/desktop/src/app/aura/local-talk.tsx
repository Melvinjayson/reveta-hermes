import './local-talk.css'

import { useStore } from '@nanostores/react'
import { Cpu, Send, Square, X } from 'lucide-react'
import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'

import { useSessionView } from '@/app/chat/session-view'

import { isLocalModelCached, type LocalEngine, type LocalEngineStart, removeLocalModel, startLocalEngine } from './local-engine'
import {
  forModel,
  handoffBudget,
  handoffMessage,
  INTENT_PROMPT,
  intentFallback,
  loadLocalTurns,
  LOCAL_MODEL,
  LOCAL_SYSTEM_PROMPT,
  type LocalDevice,
  localReplyDetail,
  localTalkEnabled,
  type LocalTurn,
  looksLikeToolCall,
  needsAura,
  probeLocalSupport,
  type ProviderBudget,
  saveLocalTurns,
  TOOL_ATTEMPT_NOTE
} from './local-model'
import { ReplyOriginBadge } from './reply-origin'

type Phase = 'checking' | 'consent' | 'error' | 'idle' | 'loading' | 'ready' | 'thinking' | 'unsupported'

interface Props {
  busy: boolean
  disabled?: boolean
  onSubmit: (value: string) => Promise<boolean> | boolean
}

const providerStatus = () => window.hermesDesktop.api<ProviderBudget>({ path: '/api/aura/provider', method: 'GET' })

const isOffline = () => typeof navigator !== 'undefined' && navigator.onLine === false

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error)).slice(0, 240)

/**
 * Opt-in prototype: talk an idea through with a small model running in this browser (no server call, no
 * per-message bill), then hand the conversation to Aura's server model with one tap. The local model has
 * no tools; Hermes on the server stays the only thing that can act, under the normal caps and approvals.
 */
export function AuraLocalTalk({ busy, disabled, onSubmit }: Props) {
  const [enabled] = useState(() => localTalkEnabled())
  const view = useSessionView()
  const chatProvider = useStore(view.$provider)
  const chatModel = useStore(view.$model)
  const [open, setOpen] = useState(false)
  const [phase, setPhase] = useState<Phase>('idle')
  const [reason, setReason] = useState('')
  const [modelId, setModelId] = useState('')
  const [device, setDevice] = useState<LocalDevice | null>(null)
  const [cached, setCached] = useState(false)
  const [progress, setProgress] = useState({ fraction: 0, text: '' })
  const [turns, setTurns] = useState<LocalTurn[]>(() => (enabled ? loadLocalTurns() : []))
  const [streaming, setStreaming] = useState('')
  const [draft, setDraft] = useState('')
  const [notice, setNotice] = useState('')

  const [handoff, setHandoff] = useState<null | {
    budget: null | ReturnType<typeof handoffBudget>
    intent: string
    preparing: boolean
  }>(null)

  const start = useRef<LocalEngineStart | null>(null)
  const engine = useRef<LocalEngine | null>(null)

  const release = useCallback(() => {
    start.current?.cancel()
    start.current = null
    engine.current?.dispose()
    engine.current = null
  }, [])

  useEffect(() => release, [release])

  useEffect(() => {
    if (enabled) {
      saveLocalTurns(turns)
    }
  }, [enabled, turns])

  const check = async () => {
    setPhase('checking')
    const support = await probeLocalSupport()

    if (!support.ok) {
      setReason(`${support.reason} Nothing was sent anywhere. You can still type or talk to Aura as usual.`)
      setPhase('unsupported')

      return
    }

    setModelId(support.modelId)
    setDevice(support.device)
    setCached(await isLocalModelCached(support.modelId).catch(() => false))
    setPhase('consent')
  }

  const toggle = () => {
    if (open) {
      release()
      setHandoff(null)
      setPhase(phase === 'unsupported' ? phase : 'idle')
      setOpen(false)

      return
    }

    setOpen(true)

    if (phase === 'idle' || phase === 'error') {
      void check()
    }
  }

  const load = () => {
    setPhase('loading')
    setProgress({ fraction: 0, text: cached ? 'Loading from this device…' : 'Starting download…' })
    const next = startLocalEngine(modelId, (fraction, text) => setProgress({ fraction, text }))
    start.current = next
    next.ready.then(
      ready => {
        if (start.current !== next) {
          ready.dispose()

          return
        }

        start.current = null
        engine.current = ready
        setCached(true)
        setPhase('ready')
      },
      error => {
        if (start.current !== next) {
          return
        }

        start.current = null
        setReason(`The on-device model couldn’t start: ${errorText(error)}. Nothing was sent to Aura.`)
        setPhase('error')
      }
    )
  }

  const cancelLoad = () => {
    release()
    setPhase('consent')
  }

  const send = async (event: FormEvent) => {
    event.preventDefault()
    const text = draft.trim()

    if (!text || phase !== 'ready') {
      return
    }

    setDraft('')
    setNotice('')
    const history = [...turns, { role: 'user' as const, content: text }]
    setTurns(history)

    if (needsAura(text)) {
      setNotice('That needs Aura’s tools, live facts or deeper thinking, which the on-device model doesn’t have. Tap Hand to Aura.')

      return
    }

    const current = engine.current

    if (!current) {
      return
    }

    setPhase('thinking')

    try {
      const reply = await current.chat([{ role: 'system', content: LOCAL_SYSTEM_PROMPT }, ...forModel(history.slice(-12))], setStreaming)
      const detail = localReplyDetail(reply)

      if (looksLikeToolCall(reply.text)) {
        setNotice(TOOL_ATTEMPT_NOTE)
        setTurns([...history, { role: 'assistant', content: '(tried to run a tool; nothing ran)', detail }])
      } else if (reply.text.trim()) {
        setTurns([...history, { role: 'assistant', content: reply.text.trim(), detail }])
      } else if (reply.finish !== 'abort') {
        setNotice('The on-device model gave an empty reply. Try rephrasing, or tap Hand to Aura.')
      }
    } catch (error) {
      setNotice(`The on-device model stopped: ${errorText(error)}`)
    } finally {
      setStreaming('')

      if (engine.current === current) {
        setPhase('ready')
      }
    }
  }

  const beginHandoff = async () => {
    setHandoff({ budget: null, intent: '', preparing: true })

    // Offline: say so and send nothing. There is no queue and no silent retry.
    const budget = isOffline()
      ? Promise.resolve({ blocked: true, origin: null, text: 'You’re offline, so Aura can’t be reached. Nothing was sent.' })
      : providerStatus().then(
          status => handoffBudget(status, { provider: chatProvider, model: chatModel }),
          () => handoffBudget(null, { provider: chatProvider, model: chatModel })
        )

    const users = turns.filter(turn => turn.role === 'user').map(turn => turn.content)
    let intent = intentFallback(turns)

    if (engine.current && users.length && phase === 'ready') {
      setPhase('thinking')

      try {
        const summary = await engine.current.chat(
          [
            { role: 'system', content: INTENT_PROMPT },
            { role: 'user', content: users.slice(-8).join('\n') }
          ],
          () => {},
          { maxTokens: 48, temperature: 0 }
        )

        if (summary.text.trim() && !looksLikeToolCall(summary.text)) {
          intent = summary.text.trim().replace(/\s+/g, ' ').slice(0, 300)
        }
      } catch {
        // keep the fallback: the user's own last message
      } finally {
        setPhase('ready')
      }
    }

    setHandoff({ budget: await budget, intent, preparing: false })
  }

  const confirmHandoff = async () => {
    if (!handoff || handoff.preparing || handoff.budget?.blocked) {
      return
    }

    if (isOffline()) {
      setHandoff({ ...handoff, budget: { blocked: true, origin: null, text: 'You’re offline, so Aura can’t be reached. Nothing was sent.' } })

      return
    }

    const accepted = await Promise.resolve(onSubmit(handoffMessage(turns, handoff.intent))).catch(() => false)

    if (!accepted) {
      setNotice('The hand-off wasn’t sent. Try again, or type to Aura below.')

      return
    }

    release()
    setTurns([])
    setHandoff(null)
    setNotice('')
    setPhase('idle')
    setOpen(false)
  }

  const forget = async () => {
    release()
    await removeLocalModel(modelId).catch(() => {})
    setCached(false)
    setPhase('consent')
  }

  const working = phase === 'thinking'

  if (!enabled) {
    return null
  }

  return (
    <div className="aura-local">
      <button aria-expanded={open} aria-label="On-device" aria-pressed={open} className="aura-local-toggle" disabled={disabled} onClick={toggle} type="button">
        <Cpu aria-hidden="true" size={16} />
        <span>On-device</span>
      </button>
      {open && (
        <section aria-label="On-device conversation" className="aura-local-panel">
          <header>
            <strong>Think it through on this device</strong>
            <button aria-label="Close on-device conversation" onClick={toggle} type="button">
              <X size={16} />
            </button>
          </header>
          {phase === 'checking' && <p role="status">Checking whether this browser can run it…</p>}
          {(phase === 'unsupported' || phase === 'error') && <p role="alert">{reason}</p>}
          {phase === 'consent' && (
            <div className="aura-local-consent">
              <p>
                Runs {LOCAL_MODEL.name} ({LOCAL_MODEL.licence}) in this browser.{' '}
                {cached
                  ? 'It’s already downloaded on this device.'
                  : `First use downloads about ${LOCAL_MODEL.downloadMb} MB from Hugging Face and keeps it in this browser.`}
              </p>
              <p>
                What you type here stays on this device and costs nothing per message, but it uses battery, memory and
                storage. It’s text only. Nothing goes to Aura until you tap Hand to Aura.
              </p>
              {device && (
                <p aria-label="This device">
                  Device grade {device.grade} (about {device.vramMb} MB for graphics, estimated)
                  {device.battery ? `, battery ${Math.round(device.battery.level * 100)}%${device.battery.charging ? ' and charging' : ''}` : ''}
                  {device.online ? '' : ', offline'}.
                </p>
              )}
              {device && device.warnings.length > 0 && (
                <ul className="aura-local-warnings">
                  {device.warnings.map(warning => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              )}
              {!cached && isOffline() && <p role="alert">You’re offline. Connect once to download the model; after that it works offline.</p>}
              <div>
                <button disabled={!cached && isOffline()} onClick={load} type="button">
                  {cached ? 'Load from this device' : `Download about ${LOCAL_MODEL.downloadMb} MB`}
                </button>
                {cached && (
                  <button onClick={() => void forget()} type="button">
                    Remove download
                  </button>
                )}
              </div>
            </div>
          )}
          {phase === 'loading' && (
            <div className="aura-local-loading">
              <progress aria-label="On-device model download" max={1} value={progress.fraction} />
              <p role="status">{progress.text}</p>
              <button onClick={cancelLoad} type="button">
                Cancel
              </button>
            </div>
          )}
          {(phase === 'ready' || working) && (
            <>
              <ol aria-label="On-device messages" className="aura-local-turns">
                {turns.map((turn, index) => (
                  <li data-role={turn.role} key={index}>
                    {turn.content}
                    {turn.role === 'assistant' && (
                      <ReplyOriginBadge detail={LOCAL_MODEL.name} note={turn.detail} origin="device" />
                    )}
                  </li>
                ))}
                {streaming && (
                  <li data-role="assistant">
                    {streaming}
                    <ReplyOriginBadge detail={LOCAL_MODEL.name} origin="device" />
                  </li>
                )}
              </ol>
              {notice && <p role="status">{notice}</p>}
              {handoff ? (
                <div className="aura-local-handoff">
                  {handoff.preparing ? (
                    <p role="status">Getting the hand-off ready…</p>
                  ) : (
                    <>
                      <label>
                        What you want so far
                        <textarea onChange={e => setHandoff({ ...handoff, intent: e.target.value })} rows={2} value={handoff.intent} />
                      </label>
                      <p>
                        {handoff.budget?.origin && <ReplyOriginBadge origin={handoff.budget.origin} />} {handoff.budget?.text}
                      </p>
                      {busy && <p>Aura is still replying in the chat. Send when it finishes.</p>}
                      <div>
                        <button disabled={busy || Boolean(handoff.budget?.blocked)} onClick={() => void confirmHandoff()} type="button">
                          Send to Aura
                        </button>
                        <button onClick={() => setHandoff(null)} type="button">
                          Back
                        </button>
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <>
                  <form onSubmit={e => void send(e)}>
                    <input
                      aria-label="Message the on-device model"
                      disabled={working}
                      onChange={e => setDraft(e.target.value)}
                      placeholder="Think out loud…"
                      value={draft}
                    />
                    {working ? (
                      <button aria-label="Stop" onClick={() => engine.current?.stop()} type="button">
                        <Square size={16} />
                      </button>
                    ) : (
                      <button aria-label="Send to on-device model" disabled={!draft.trim()} type="submit">
                        <Send size={16} />
                      </button>
                    )}
                  </form>
                  <div>
                    <button className="aura-local-escalate" disabled={working || turns.length === 0} onClick={() => void beginHandoff()} type="button">
                      Hand to Aura
                    </button>
                    <button disabled={working || turns.length === 0} onClick={() => setTurns([])} type="button">
                      Clear
                    </button>
                  </div>
                </>
              )}
            </>
          )}
        </section>
      )}
    </div>
  )
}
