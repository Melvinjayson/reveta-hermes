import { useStore } from '@nanostores/react'
import { Mic, MicOff, PhoneOff, Square } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { openGatewaySocket } from '@/api/canonical-protocol'
import { useComposerScope } from '@/app/chat/composer/scope'
import type { ChatBarProps } from '@/app/chat/composer/types'
import { chatMessageText } from '@/lib/chat-messages'
import { resolveSiblingWsUrl } from '@/lib/sibling-ws-url'
import { sanitizeTextForSpeech } from '@/lib/speech-text'

import { AuraBrowserVoice } from './browser-voice'

interface Props {
  busy: boolean
  disabled: boolean
  onSubmit: ChatBarProps['onSubmit']
  onInterrupt: ChatBarProps['onCancel']
  sessionId?: string | null
}

interface VoiceSettings {
  available: boolean
  reason: null | string
  backend?: string
  in_rate: number
  out_rate: number
}

type CallMessage =
  | { type: 'bot_idle' | 'bot_speaking' | 'interrupt' | 'user_speaking' | 'user_stopped' }
  | { type: 'error'; message: string }
  | { type: 'ready'; in_rate: number; out_rate: number }
  | { type: 'transcript'; text: string }
  | { type: 'speech_failed'; text: string; message: string }

const MAX_RECONNECTS = 3
/** Silence after the last phrase before your turn goes to Aura (on top of the server's 0.7 s segmenting). */
export const TURN_SETTLE_MS = 1200
const ECHO_WINDOW_MS = 30_000

const words = (text: string) => text.toLowerCase().replace(/[^\p{L}\p{N}\s']/gu, ' ').split(/\s+/).filter(Boolean)
const pairs = (list: string[]) => list.slice(1).map((word, index) => `${list[index]} ${word}`)

/** True when what the mic heard is mostly Aura's own recent speech coming back through the speaker. */
export function isEchoOfAura(heard: string, spoken: string[]): boolean {
  const heardPairs = pairs(words(heard))

  if (heardPairs.length < 2) {
    return false // too short to tell; a real "yes" or "stop" must get through
  }

  const spokenPairs = new Set(spoken.flatMap(text => pairs(words(text))))
  const matched = heardPairs.filter(pair => spokenPairs.has(pair)).length

  return matched / heardPairs.length >= 0.6
}

/** The part of a reply still being written that ends on a finished sentence. */
export function speakableSoFar(text: string): string {
  const ends = [...text.matchAll(/[.!?](?=\s)|\n/g)]
  const end = ends.at(-1)

  return end?.index === undefined ? '' : text.slice(0, end.index + 1)
}

/** Speech in chunks of whole sentences so the first words play while the rest synthesize. */
export function speechChunks(text: string, size = 280): string[] {
  const sentences = text.match(/[^.!?\n]+[.!?]*\s*/g) ?? [text]
  const chunks: string[] = []
  let current = ''

  for (const sentence of sentences) {
    if (current && (current + sentence).length > size) {
      chunks.push(current.trim())
      current = ''
    }

    current += sentence
  }

  if (current.trim()) {
    chunks.push(current.trim())
  }

  return chunks
}

function voiceLabel(active: boolean, muted: boolean, busy: boolean, status: string): string {
  if (!active) {
    return 'Voice off'
  }

  if (muted && (status === 'Listening' || status === 'Hearing you')) {
    return 'Muted'
  }

  return busy && status === 'Listening' ? 'Thinking' : status
}

const hasDeviceVoice = () => typeof window !== 'undefined' && 'speechSynthesis' in window

/** Device-voice fallback: `counter` holds how many device utterances are queued. */
function cancelDeviceSpeech(counter: { current: number }) {
  if (counter.current && hasDeviceVoice()) {
    window.speechSynthesis.cancel()
  }

  counter.current = 0
}

/** Returns false when the device cannot speak `text`; calls onStart before speaking and onIdle once the last queued utterance ends. */
function speakWithDevice(text: string, counter: { current: number }, onStart: () => void, onIdle: () => void): boolean {
  if (!text.trim() || !hasDeviceVoice()) {
    return false
  }

  const utterance = new SpeechSynthesisUtterance(text)
  counter.current++
  onStart()

  utterance.onend = utterance.onerror = () => {
    counter.current = Math.max(0, counter.current - 1)

    if (counter.current === 0) {
      onIdle()
    }
  }

  window.speechSynthesis.speak(utterance)

  return true
}

function toPcm16(input: Float32Array, fromRate: number, toRate: number): ArrayBuffer {
  const ratio = fromRate / toRate
  const out = new Int16Array(Math.floor(input.length / ratio))

  for (let i = 0; i < out.length; i++) {
    const sample = Math.max(-1, Math.min(1, input[Math.floor(i * ratio)] ?? 0))
    out[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
  }

  return out.buffer
}

/** Aura's continuous voice call over Pipecat (`/api/audio/voice-call`), with the browser's
 * turn-based voice as the fallback when the server cannot run a call. Each transcript goes to
 * the normal chat; each finished reply is spoken. Barge-in stops speech only: the chat turn,
 * its tools and its approvals keep running. */
export function AuraVoice(props: Props) {
  const [settings, setSettings] = useState<VoiceSettings | null>(null)

  useEffect(() => {
    const api = window.hermesDesktop?.api

    if (!api) {
      return
    }

    Promise.resolve(api<VoiceSettings>({ path: '/api/aura/voice' }))
      .then(setSettings)
      .catch(() => setSettings(null))
  }, [])

  // The browser's turn-based voice serves until the server says a live call can start.
  if (!settings?.available) {
    return <AuraBrowserVoice {...props} />
  }

  return <AuraVoiceCall {...props} settings={settings} />
}

function AuraVoiceCall({ busy, disabled, onSubmit, sessionId, settings }: Props & { settings: VoiceSettings }) {
  const scope = useComposerScope()
  const messages = useStore(scope.$messages)
  const [active, setActive] = useState(false)
  const [status, setStatus] = useState('Voice off')
  const [heard, setHeard] = useState('')
  const [error, setError] = useState('')
  const [queue, setQueue] = useState<string[]>([])
  const [muted, setMuted] = useState(false)

  const call = useRef<{
    ws: WebSocket
    context: AudioContext
    stream: MediaStream
    processor: ScriptProcessorNode
    playing: Set<AudioBufferSourceNode>
    playAt: number
  } | null>(null)

  const wanted = useRef(false)
  const talking = useRef(false)
  const recentSpeech = useRef<{ at: number; text: string }[]>([])
  const heldTurn = useRef<string[]>([])
  const settle = useRef<ReturnType<typeof setTimeout>>(undefined)
  const deviceSpeaking = useRef(0)
  const deviceNoticeShown = useRef(false)
  const reconnects = useRef(0)
  const spoken = useRef({ closed: true, id: '', text: '', turn: -1 })
  const submitting = useRef(false)
  const owner = useRef(sessionId)

  const stopPlayback = useCallback(() => {
    const current = call.current

    if (!current) {
      return
    }

    for (const node of current.playing) {
      node.onended = null
      node.stop()
    }

    current.playing.clear()
    current.playAt = 0
  }, [])

  // A pause shorter than this joins the next phrase to the same turn instead of sending a fragment.
  const armTurnEnd = useCallback(() => {
    clearTimeout(settle.current)
    settle.current = setTimeout(() => {
      if (talking.current || heldTurn.current.length === 0) {
        return
      }

      const turn = heldTurn.current.join(' ')
      heldTurn.current = []
      setQueue(previous => [...previous, turn])
    }, TURN_SETTLE_MS)
  }, [])

  const stopDeviceSpeech = useCallback(() => cancelDeviceSpeech(deviceSpeaking), [])

  const speakOnDevice = useCallback((text: string) => {
    const onStart = () => setStatus('Speaking')
    const onIdle = () => call.current && setStatus('Listening')

    if (!speakWithDevice(text, deviceSpeaking, onStart, onIdle)) {
      setError('Aura’s reply could not be spoken. It is shown in the chat.')
    }
  }, [])

  const teardown = useCallback(() => {
    const current = call.current
    call.current = null
    clearTimeout(settle.current)
    heldTurn.current = []
    talking.current = false
    cancelDeviceSpeech(deviceSpeaking)

    if (!current) {
      return
    }

    current.ws.onclose = null
    current.ws.close()
    current.processor.disconnect()
    current.stream.getTracks().forEach(track => track.stop())
    void current.context.close()
  }, [])

  const stop = useCallback(() => {
    wanted.current = false
    teardown()
    setActive(false)
    setQueue([])
    setMuted(false)
    setStatus('Voice off')
  }, [teardown])

  const play = useCallback((data: ArrayBuffer) => {
    const current = call.current

    if (!current || data.byteLength < 2) {
      return
    }

    const pcm = new Int16Array(data, 0, data.byteLength >> 1)
    const buffer = current.context.createBuffer(1, pcm.length, settings.out_rate)
    const channel = buffer.getChannelData(0)

    for (let i = 0; i < pcm.length; i++) {
      channel[i] = pcm[i] / 0x8000
    }

    const node = current.context.createBufferSource()
    node.buffer = buffer
    node.connect(current.context.destination)
    const at = Math.max(current.context.currentTime + 0.02, current.playAt)
    node.start(at)
    current.playAt = at + buffer.duration
    current.playing.add(node)
    node.onended = () => current.playing.delete(node)
  }, [settings.out_rate])

  const connect = useCallback(async () => {
    setError('')
    setStatus('Connecting')
    let url: URL

    try {
      url = new URL(await resolveSiblingWsUrl(
        { connectionId: scope.connectionId ?? null, profile: scope.profile ?? null },
        '/api/audio/voice-call'
      ))
    } catch (failure) {
      setError(`Voice call could not start: ${failure instanceof Error ? failure.message : 'no connection'}.`)
      stop()

      return
    }

    const context = new AudioContext()
    let stream: MediaStream

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { autoGainControl: true, channelCount: 1, echoCancellation: true, noiseSuppression: true }
      })
    } catch {
      void context.close()
      setError('Aura needs your microphone. Allow it in the browser and start voice again.')
      stop()

      return
    }

    if (!wanted.current) {
      stream.getTracks().forEach(track => track.stop())
      void context.close()

      return
    }

    await context.resume().catch(() => undefined)
    const ws = openGatewaySocket(url.toString())
    ws.binaryType = 'arraybuffer'
    const source = context.createMediaStreamSource(stream)
    const processor = context.createScriptProcessor(2048, 1, 1)

    processor.onaudioprocess = event => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(toPcm16(event.inputBuffer.getChannelData(0), context.sampleRate, settings.in_rate))
      }
    }

    source.connect(processor)
    processor.connect(context.destination)
    call.current = { ws, context, stream, processor, playing: new Set(), playAt: 0 }

    ws.onmessage = event => {
      if (event.data instanceof ArrayBuffer) {
        play(event.data)

        return
      }

      let message: CallMessage

      try {
        message = JSON.parse(String(event.data)) as CallMessage
      } catch {
        return
      }

      switch (message.type) {
        case 'ready':
          reconnects.current = 0
          setStatus('Listening')

          break

        case 'user_speaking':
          talking.current = true
          clearTimeout(settle.current)
          // Device speech is not echo-cancelled everywhere, so it only stops once a real (non-echo) transcript arrives.
          setStatus(deviceSpeaking.current ? 'Speaking' : 'Hearing you')

          break

        case 'user_stopped':
          talking.current = false
          armTurnEnd()

          break

        case 'interrupt':
          stopPlayback()
          stopDeviceSpeech()
          // You cut in: the rest of the reply that is still streaming is not spoken afterwards.
          spoken.current = { ...spoken.current, closed: true }
          setStatus('Hearing you')

          break

        case 'transcript':
          if (message.text.trim()) {
            const now = Date.now()
            recentSpeech.current = recentSpeech.current.filter(item => now - item.at < ECHO_WINDOW_MS)

            if (isEchoOfAura(message.text, recentSpeech.current.map(item => item.text))) {
              break // Aura hearing itself: never send its own words back as the user's turn
            }

            if (deviceSpeaking.current) {
              stopDeviceSpeech()
            }

            // Pieces of one turn are held until you have finished, then sent to Aura together.
            heldTurn.current.push(message.text.trim())
            setHeard(heldTurn.current.join(' '))

            if (!talking.current) {
              armTurnEnd()
            }
          }

          break

        case 'speech_failed':
          speakOnDevice(message.text)

          if (!deviceNoticeShown.current) {
            deviceNoticeShown.current = true
            setError('Server voice is unavailable right now, so Aura is using this device’s voice.')
          }

          break

        case 'bot_speaking':
          setStatus('Speaking')

          break

        case 'bot_idle':
          setStatus('Listening')

          break

        case 'error':
          setError(message.message)

          break
      }
    }

    ws.onclose = () => {
      teardown()

      if (!wanted.current) {
        return
      }

      if (reconnects.current >= MAX_RECONNECTS) {
        setError('Voice call dropped and could not reconnect. Start voice again, or type below.')
        stop()

        return
      }

      reconnects.current++
      setStatus('Reconnecting')
      window.setTimeout(() => {
        if (wanted.current) {
          void connect()
        }
      }, 800 * reconnects.current)
    }
  }, [armTurnEnd, play, scope.connectionId, scope.profile, settings.in_rate, speakOnDevice, stop, stopDeviceSpeech,
    stopPlayback, teardown])

  const start = () => {
    wanted.current = true
    reconnects.current = 0
    const last = messages.findLast(message => message.role === 'assistant')
    // Never speak a reply that was already on screen when the call started.
    spoken.current = {
      closed: true,
      id: last?.id ?? '',
      text: last ? sanitizeTextForSpeech(chatMessageText(last)) : '',
      turn: messages.filter(message => message.role === 'user').length
    }
    setActive(true)
    void connect()
  }

  // Leaving a real conversation ends the call; its first voice turn adopting an id does not.
  // eslint-disable-next-line no-restricted-syntax -- ownership latch, not an atom mirror
  useEffect(() => {
    if (owner.current && owner.current !== sessionId) {
      stop()
    }

    owner.current = sessionId
  }, [sessionId, stop])

  useEffect(() => () => {
    wanted.current = false
    teardown()
  }, [teardown])

  // Transcripts wait for the running turn rather than cancelling it.
  // eslint-disable-next-line no-restricted-syntax -- in-flight submit latch, not an atom mirror
  useEffect(() => {
    if (!active || busy || submitting.current || queue.length === 0) {
      return
    }

    submitting.current = true
    const text = queue.join(' ')
    setQueue([])
    setStatus('Thinking')
    void Promise.resolve(onSubmit(text))
      .then(accepted => {
        if (!accepted) {
          setError('What you said was not sent. Try typing it below.')
        }
      })
      .catch(() => setError('What you said could not be sent. Try typing it below.'))
      .finally(() => {
        submitting.current = false
      })
  }, [active, busy, onSubmit, queue])

  // Speak each finished sentence while the reply is still being written, instead of waiting for the whole
  // turn to settle (that wait was the gap between text appearing and Aura starting to talk).
  // eslint-disable-next-line no-restricted-syntax -- consumed reply progress, not an atom mirror
  useEffect(() => {
    const ws = call.current?.ws

    if (!active || !ws || ws.readyState !== WebSocket.OPEN) {
      return
    }

    const turn = messages.filter(message => message.role === 'user').length
    const last = messages.findLast(message => message.role === 'assistant')

    if (!last || messages.indexOf(last) < messages.findLastIndex(message => message.role === 'user')) {
      return
    }

    const text = sanitizeTextForSpeech(chatMessageText(last))
    const settled = !last.pending && !busy
    const ready = settled ? text : speakableSoFar(text)
    const progress = spoken.current
    const sameBubble = progress.turn === turn && (progress.id === last.id || ready.startsWith(progress.text))
    const already = sameBubble ? progress.text : ''

    if (sameBubble && progress.closed) {
      return
    }

    if (!ready.startsWith(already)) {
      // The text was rewritten mid-stream (markdown settling); never repeat what was already said.
      spoken.current = { ...progress, closed: settled }

      return
    }

    const fresh = ready.slice(already.length)
    spoken.current = { closed: false, id: last.id, text: ready, turn }

    if (!fresh.trim()) {
      return
    }

    recentSpeech.current.push({ at: Date.now(), text: fresh })

    // The first words of a reply go out alone so audio starts as soon as possible.
    for (const chunk of speechChunks(fresh, already ? 280 : 120)) {
      ws.send(JSON.stringify({ type: 'speak', text: chunk }))
    }
  }, [active, busy, messages, status])

  const toggleMute = () => {
    const next = !muted
    call.current?.stream.getAudioTracks().forEach(track => {
      track.enabled = !next
    })
    setMuted(next)
  }

  const label = voiceLabel(active, muted, busy, status)

  return (
    <div aria-label="Voice chat" className="aura-voice" data-aura-voice={active ? label : 'off'} role="group">
      <button
        aria-describedby="aura-voice-hint"
        aria-label={active ? 'End voice chat' : 'Start voice chat'}
        aria-pressed={active}
        className="aura-voice-toggle"
        disabled={disabled}
        onClick={active ? stop : start}
        title={active ? 'End voice chat' : 'Start voice chat'}
        type="button"
      >
        {active ? <PhoneOff aria-hidden="true" size={18} /> : <Mic aria-hidden="true" size={18} />}
        <span aria-hidden="true" className="aura-voice-dot" />
        <span className="aura-voice-label">{active ? label : 'Voice chat'}</span>
      </button>
      {active && (
        <button
          aria-label={muted ? 'Unmute microphone' : 'Mute microphone'}
          aria-pressed={muted}
          className="aura-voice-icon"
          onClick={toggleMute}
          title={muted ? 'Unmute microphone' : 'Mute microphone'}
          type="button"
        >
          {muted ? <MicOff aria-hidden="true" size={18} /> : <Mic aria-hidden="true" size={18} />}
        </button>
      )}
      {active && status === 'Speaking' && (
        <button
          aria-label="Stop speaking"
          className="aura-voice-icon"
          onClick={() => {
            stopPlayback()
            stopDeviceSpeech()
            spoken.current = { ...spoken.current, closed: true }
            call.current?.ws.send(JSON.stringify({ type: 'interrupt' }))
            setStatus('Interrupted')
          }}
          title="Stop speaking"
          type="button"
        >
          <Square aria-hidden="true" size={16} />
        </button>
      )}
      <span className="sr-only" id="aura-voice-hint">
        Live voice: just talk. Speak over Aura to cut in; running tasks keep going.
      </span>
      <span aria-live="polite" className="sr-only" role="status">
        {label}
      </span>
      {active && heard && (
        <p aria-label="What Aura heard" className="aura-voice-heard">
          {heard}
        </p>
      )}
      {error && (
        <p className="aura-voice-error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
