import { useStore } from '@nanostores/react'
import { useEffect, useRef, useState } from 'react'

import { useComposerScope } from '@/app/chat/composer/scope'
import type { ChatBarProps } from '@/app/chat/composer/types'
import type { HermesGateway } from '@/hermes'
import { chatMessageText } from '@/lib/chat-messages'
import { PipecatVoice, type VoiceEvent } from '@/lib/pipecat-voice'
import { sanitizeTextForSpeech } from '@/lib/speech-text'

import { AuraConversationOrb } from './conversation-orb'
import { AuraVoice } from './voice-call'

interface Props {
  busy: boolean; disabled: boolean; onSubmit: ChatBarProps['onSubmit']; onInterrupt: ChatBarProps['onCancel']
  gateway?: Pick<HermesGateway, 'request'> | null; sessionId?: string | null
}

/** One continuous mic; every final uses the same composer's ordinary admission. */
export function AuraPipecatVoice(props: Props) {
  const scope = useComposerScope()
  const messages = useStore(scope.$messages)
  const [active, setActive] = useState(false)
  const [status, setStatus] = useState('Voice off')
  const [partial, setPartial] = useState('')
  const [fallback, setFallback] = useState(false)
  const [pending, setPending] = useState<VoiceEvent[]>([])
  const current = useRef(props)
  current.current = props
  const voice = useRef<PipecatVoice | null>(null)
  const seen = useRef(new Set<string>())
  const submitting = useRef(false)
  const reply = useRef<{ turn: string; offsets: Map<number, number>; done: Set<number> } | null>(null)
  const receipts = useRef(new Map<string, VoiceEvent>())

  const owner = useRef({ sessionId: props.sessionId, gateway: props.gateway, busy: props.busy,
    connectionId: scope.connectionId ?? null, profile: scope.profile ?? null })

  const acceptedSession = useRef(props.sessionId)

  const record = (event: VoiceEvent) => {
    const { gateway } = owner.current
    const sessionId = acceptedSession.current

    if (!gateway || !sessionId || !event.turn_id) { return }
    void gateway.request('session.voice.record', { session_id: sessionId, turn_id: event.turn_id,
      message_index: event.message_index ?? 0, text: event.text ?? '', interrupted: Boolean(event.type === 'interrupted' || event.interrupted)
    }).catch(() => {
      if (owner.current.gateway === gateway && acceptedSession.current === sessionId) { setStatus('Playback receipt pending') }
    })
  }

  const interrupt = (busy = current.current.busy) => {
    const { gateway } = owner.current
    const sessionId = acceptedSession.current

    if (busy && gateway && sessionId) {
      void gateway.request('session.interrupt', { session_id: sessionId, preserve_running_tools: true })
        .catch(() => {
          if (owner.current.gateway === gateway && acceptedSession.current === sessionId) {
            setStatus('Safe interruption unavailable'); setPending([])
          }
        })
    }

    const turn = reply.current?.turn

    if (turn) {
      voice.current?.flush(turn)
      voice.current?.send({ type: 'interrupt', turn_id: turn })

      for (const event of receipts.current.values()) {
        if (event.turn_id === turn) { record({ ...event, type: 'interrupted' }) }
      }

      if (![...receipts.current.values()].some(event => event.turn_id === turn)) {
        record({ type: 'interrupted', turn_id: turn, text: '', message_index: 0 })
      }
    }

    reply.current = null
  }

  const stop = (busy?: boolean) => {
    interrupt(busy)
    voice.current?.stop()
    voice.current = null
    setActive(false)
    setPending([])
    setStatus('Voice off')
  }

  // eslint-disable-next-line no-restricted-syntax -- conversation ownership, not an atom mirror
  useEffect(() => {
    const previous = owner.current

    const changed = Boolean(previous.sessionId && previous.sessionId !== props.sessionId) ||
      previous.connectionId !== (scope.connectionId ?? null) || previous.profile !== (scope.profile ?? null)

    if (changed) { stop(previous.busy) }
    owner.current = { sessionId: props.sessionId, gateway: props.gateway, busy: props.busy,
      connectionId: scope.connectionId ?? null, profile: scope.profile ?? null }

    if (props.sessionId || changed) { acceptedSession.current = props.sessionId }

    if (props.sessionId) { voice.current?.adopt(props.sessionId) }
  }, [props.sessionId, props.gateway, props.busy, scope.connectionId, scope.profile])
  useEffect(() => () => { voice.current?.stop() }, [])

  const start = async () => {
    setActive(true)
    setStatus('Listening')

    const client = new PipecatVoice(scope, props.sessionId, event => {
      if (voice.current !== client) { return }

      if (event.type === 'partial') { setPartial(event.text ?? '') }

      if (event.type === 'speech_start' || event.type === 'disconnected') {
        interrupt(); setStatus('Interrupted'); setPartial('')
      }

      if (event.type === 'final' && event.turn_id && !seen.current.has(event.turn_id)) {
        seen.current.add(event.turn_id); setPartial(event.text ?? ''); setPending(old => [...old, event])
      }

      if (event.type === 'played') {
        receipts.current.set(`${event.turn_id}:${event.message_index}`, event); record(event)
      }

      if (event.type === 'audio') { setStatus('Speaking') }

      if (event.type === 'listening' || event.type === 'ready') { setStatus('Listening') }
    }, () => {
      if (voice.current !== client) { return }
      interrupt(); setActive(false); setFallback(true)
    })

    voice.current = client

    try { await client.start() } catch {
      client.stop()

      if (voice.current === client) { setActive(false); setFallback(true) }
    }
  }

  // eslint-disable-next-line no-restricted-syntax -- single-flight final admission, not an atom mirror
  useEffect(() => {
    const final = pending[0]

    if (!active || props.busy || !final?.turn_id || submitting.current) { return }
    submitting.current = true
    const turn = final.turn_id
    reply.current = { turn, offsets: new Map(), done: new Set() }
    setStatus('Thinking')
    void Promise.resolve(current.current.onSubmit(final.text ?? '', { submission_id: turn, voiceRecordingId: turn,
      onAccepted: identity => { acceptedSession.current = identity.runtimeSessionId; voice.current?.adopt(identity.runtimeSessionId) }
    })).then(ok => {
      if (!ok) { reply.current = null; setStatus('Transcript was refused; use chat to continue') }
      setPending(old => old.filter(event => event.turn_id !== turn))
    }).catch(() => { reply.current = null; setPending([]); setStatus('Transcript could not be sent') })
      .finally(() => { submitting.current = false })
  }, [active, pending, props.busy])


  useEffect(() => {
    const stream = reply.current

    if (!active || !stream) { return }
    const anchor = messages.findIndex(message => message.id === `user-${stream.turn}`)

    if (anchor < 0) { return }
    const tail = messages.slice(anchor + 1)
    const nextUser = tail.findIndex(message => message.role === 'user')

    const assistants = (nextUser < 0 ? tail : tail.slice(0, nextUser)).filter(message =>
      message.role === 'assistant' && chatMessageText(message).trim())

    assistants.forEach((message, index) => {
      if (stream.done.has(index) || message.interrupted) { return }
      const text = sanitizeTextForSpeech(chatMessageText(message))
      const offset = stream.offsets.get(index) ?? 0
      const done = Boolean(message.interim || (!props.busy && !message.pending))

      if (text.length > offset || done) {
        voice.current?.send({ type: 'reply', turn_id: stream.turn, message_index: index, text: text.slice(offset), done })
        stream.offsets.set(index, text.length)

        if (done) { stream.done.add(index) }
      }
    })
  }, [active, messages, props.busy])

  // The speech edge is down or refused: the default live voice takes over, unchanged.
  if (fallback) { return <AuraVoice {...props} /> }

  return (
    <div aria-label="Continuous voice" className="aura-voice" data-aura-voice={active ? status : 'off'} role="group">
      {active && (
        <div className="aura-voice-stage">
          <img alt="" className="aura-voice-brand" src="brand/aura-mark.svg" />
          <span className="aura-voice-kicker">Aura · Continuous conversation</span>
          <h2>{status === 'Speaking' ? 'Aura is speaking' : status === 'Thinking' ? 'One moment…' : 'Go ahead, I’m listening'}</h2>
          <AuraConversationOrb status={status} />
          <p className="aura-voice-caption">Talk naturally. You can interrupt at any time.</p>
        </div>
      )}
      <button
        aria-label={active ? 'End voice chat' : 'Start voice chat'}
        aria-pressed={active}
        className="aura-voice-toggle"
        disabled={props.disabled && !active}
        onClick={() => { if (active) { stop() } else { void start() } }}
        type="button"
      >
        {active ? 'End conversation' : 'Voice chat'}
      </button>
      <span aria-live="polite" className="sr-only" role="status">{status}</span>
      {active && partial && <p aria-label="Live transcript" className="aura-voice-heard">{partial}</p>}
    </div>
  )
}
