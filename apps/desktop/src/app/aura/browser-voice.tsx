import { useStore } from '@nanostores/react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { useComposerScope } from '@/app/chat/composer/scope'
import type { ChatBarProps } from '@/app/chat/composer/types'
import { chatMessageText } from '@/lib/chat-messages'
import { sanitizeTextForSpeech } from '@/lib/speech-text'

interface RecognitionResult {
  isFinal: boolean
  0: { transcript: string }
}
interface Recognition {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: { results: ArrayLike<RecognitionResult>; resultIndex: number }) => void) | null
  onend: (() => void) | null
  onerror: ((event: { error: string }) => void) | null
  start: () => void
  abort: () => void
}
interface VoiceWindow {
  SpeechRecognition?: new () => Recognition
  webkitSpeechRecognition?: new () => Recognition
}
interface Props {
  busy: boolean
  disabled: boolean
  onSubmit: ChatBarProps['onSubmit']
  onInterrupt: ChatBarProps['onCancel']
  sessionId?: string | null
}

/** Browser fallback: text and voice share onSubmit and the persisted transcript.
 * Full duplex is deliberately not claimed: recognition pauses during playback. */
export function AuraBrowserVoice({ busy, disabled, onSubmit, onInterrupt, sessionId }: Props) {
  const { $messages } = useComposerScope()
  const messages = useStore($messages)
  const [active, setActive] = useState(false)
  const [status, setStatus] = useState('Voice off')
  const [transcript, setTranscript] = useState('')
  const [pending, setPending] = useState('')
  const [error, setError] = useState('')
  const recognition = useRef<Recognition | null>(null)
  const enabled = useRef(false)
  const speaking = useRef(false)
  const lastSpoken = useRef('')
  const speechEpoch = useRef(0)
  const submitting = useRef(false)
  const owner = useRef(sessionId)
  const callbacks = useRef({ busy, onSubmit, onInterrupt })
  callbacks.current = { busy, onSubmit, onInterrupt }
  const ctor = (window as VoiceWindow).SpeechRecognition ?? (window as VoiceWindow).webkitSpeechRecognition
  const supported = Boolean(ctor && window.speechSynthesis && window.SpeechSynthesisUtterance)

  const stop = useCallback(() => {
    enabled.current = false
    speaking.current = false
    speechEpoch.current++
    recognition.current?.abort()
    window.speechSynthesis?.cancel()
    setActive(false)
    setPending('')
    setStatus('Voice off')
  }, [])

  // Re-home only when leaving a real conversation, not when its first voice turn adopts an id.
  useEffect(() => {
    if (owner.current && owner.current !== sessionId) { stop() }
    owner.current = sessionId
  }, [sessionId, stop])

  useEffect(() => () => {
    enabled.current = false
    speechEpoch.current++
    recognition.current?.abort()
    window.speechSynthesis?.cancel()
  }, [])

  const listen = useCallback(() => {
    if (!enabled.current || !recognition.current) { return }

    try {
      recognition.current.start()
      setStatus('Listening')
    } catch {
      setError('Microphone could not start. Stop voice and try again.')
      stop()
    }
  }, [stop])

  const start = () => {
    if (!ctor) { return }
    setError('')
    const last = messages.findLast(message => message.role === 'assistant')
    lastSpoken.current = JSON.stringify([messages.filter(message => message.role === 'user').length,
      last ? sanitizeTextForSpeech(chatMessageText(last)) : ''])
    const mic = new ctor()
    mic.continuous = true
    mic.interimResults = true
    mic.lang = navigator.language || 'en-US'
    const finals = new Set<number>()

    mic.onresult = event => {
      // A stopped/replaced recognizer can still deliver a queued browser event.
      if (!enabled.current || speaking.current || recognition.current !== mic) { return }
      let final = ''
      let interim = ''

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]

        if (result.isFinal) {
          if (!finals.has(i)) { final += result[0].transcript; finals.add(i) }
        } else { interim += result[0].transcript }
      }

      setTranscript(final || interim)

      if (final.trim()) {
        window.speechSynthesis.cancel()
        setPending(previous => [previous, final.trim()].filter(Boolean).join(' '))

        if (callbacks.current.busy) { void callbacks.current.onInterrupt() }
      }
    }

    mic.onerror = event => {
      if (event.error === 'aborted' && (speaking.current || !enabled.current)) { return }

      if (event.error === 'no-speech') { return }
      setError(`Voice unavailable: ${event.error}. You can still type.`)
      stop()
    }

    mic.onend = () => {
      if (recognition.current !== mic) { return }
      // Result indexes restart at zero for each recognition run. Equal words in
      // a later run are a new utterance, not a replay of an earlier final.
      finals.clear()

      if (enabled.current && !speaking.current) { listen() }
    }

    recognition.current = mic
    enabled.current = true
    setActive(true)
    listen()
  }

  useEffect(() => {
    if (!active || !pending || busy || submitting.current) { return }
    submitting.current = true
    const text = pending
    setStatus('Thinking')
    void Promise.resolve(callbacks.current.onSubmit(text)).then(accepted => {
      if (accepted) { setPending(current => current === text ? '' : current.slice(text.length).trim()) }
      else { setError('Voice transcript was not sent. Try typing it below.'); setPending('') }
    }).catch(() => {
      setError('Voice transcript could not be sent. Try typing it below.')
      setPending('')
    }).finally(() => { submitting.current = false })
  }, [active, busy, pending])

  useEffect(() => {
    if (!active || busy || pending) { return }
    const last = messages.findLast(message => message.role === 'assistant' && !message.pending)

    if (!last) { return }
    const text = sanitizeTextForSpeech(chatMessageText(last))
    // History hydration can replace a live message id after playback stops.
    // Scope content deduplication to the user-turn count so a later request
    // with the same answer still gets spoken.
    const replyKey = JSON.stringify([messages.filter(message => message.role === 'user').length, text])

    if (!text.trim() || replyKey === lastSpoken.current) { return }
    lastSpoken.current = replyKey
    const epoch = ++speechEpoch.current
    speaking.current = true
    recognition.current?.abort()
    setStatus('Speaking')
    const utterance = new SpeechSynthesisUtterance(text)

    utterance.onend = () => {
      if (speechEpoch.current !== epoch) { return }
      speaking.current = false
      listen()
    }

    utterance.onerror = () => {
      if (speechEpoch.current !== epoch) { return }
      speaking.current = false

      if (enabled.current) { setError('Spoken reply was interrupted. Tap Interrupt to listen.'); setStatus('Playback stopped') }
    }

    window.speechSynthesis.speak(utterance)
  }, [active, busy, listen, messages, pending])

  return (
    <div className="aura-browser-voice" data-aura-voice={active ? busy ? 'Thinking' : status : 'off'}>
      <button disabled={disabled || !supported} onClick={active ? stop : start} type="button">
        {active ? 'Stop voice' : 'Start voice'}
      </button>
      {active && <button onClick={() => {
        const wasSpeaking = speaking.current
        speechEpoch.current++
        speaking.current = false
        window.speechSynthesis.cancel()

        if (busy) { void onInterrupt() }

        if (wasSpeaking) { listen() }
      }} type="button">Interrupt and listen</button>}
      <small>Browser voice · turn-based. Full duplex unavailable. Tap Interrupt to barge in.</small>
      {!supported && <p>Speech recognition unavailable in this browser. You can still type.</p>}
      <p aria-live="polite" role="status">{active ? busy ? 'Thinking' : status : 'Voice off'}</p>
      {transcript && <p aria-label="Live transcript">{transcript}</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  )
}
