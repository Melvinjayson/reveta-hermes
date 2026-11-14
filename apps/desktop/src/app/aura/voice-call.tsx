import { useStore } from '@nanostores/react'
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

const MAX_RECONNECTS = 3

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

  const call = useRef<{
    ws: WebSocket
    context: AudioContext
    stream: MediaStream
    processor: ScriptProcessorNode
    playing: Set<AudioBufferSourceNode>
    playAt: number
  } | null>(null)

  const wanted = useRef(false)
  const reconnects = useRef(0)
  const lastSpoken = useRef('')
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

  const teardown = useCallback(() => {
    const current = call.current
    call.current = null

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
          setStatus('Hearing you')

          break

        case 'interrupt':
          stopPlayback()
          setStatus('Hearing you')

          break

        case 'transcript':
          if (message.text.trim()) {
            setHeard(message.text)
            setQueue(previous => [...previous, message.text.trim()])
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
  }, [play, scope.connectionId, scope.profile, settings.in_rate, stop, stopPlayback, teardown])

  const start = () => {
    wanted.current = true
    reconnects.current = 0
    const last = messages.findLast(message => message.role === 'assistant')
    // Never speak a reply that was already on screen when the call started.
    lastSpoken.current = JSON.stringify([messages.filter(message => message.role === 'user').length,
      last ? sanitizeTextForSpeech(chatMessageText(last)) : ''])
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

  // eslint-disable-next-line no-restricted-syntax -- consumed reply key, not an atom mirror
  useEffect(() => {
    if (!active || busy) {
      return
    }

    const last = messages.findLast(message => message.role === 'assistant' && !message.pending)
    const ws = call.current?.ws

    if (!last || !ws || ws.readyState !== WebSocket.OPEN) {
      return
    }

    const text = sanitizeTextForSpeech(chatMessageText(last))
    const replyKey = JSON.stringify([messages.filter(message => message.role === 'user').length, text])

    if (!text.trim() || replyKey === lastSpoken.current) {
      return
    }

    lastSpoken.current = replyKey

    for (const chunk of speechChunks(text)) {
      ws.send(JSON.stringify({ type: 'speak', text: chunk }))
    }
  }, [active, busy, messages, status])

  const label = active ? (busy && status === 'Listening' ? 'Thinking' : status) : 'Voice off'

  return (
    <div className="aura-browser-voice" data-aura-voice={active ? label : 'off'}>
      <button disabled={disabled} onClick={active ? stop : start} type="button">
        {active ? 'End voice' : 'Start voice'}
      </button>
      {active && (
        <button
          onClick={() => {
            stopPlayback()
            call.current?.ws.send(JSON.stringify({ type: 'interrupt' }))
          }}
          type="button"
        >
          Stop speaking
        </button>
      )}
      <small>Live voice: just talk. Speak over Aura to cut in; running tasks keep going.</small>
      <p aria-live="polite" role="status">
        {label}
      </p>
      {active && heard && <p aria-label="What Aura heard">{heard}</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  )
}
