import { Mic, Square } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { requestComposerFocus, requestComposerInsert } from '@/app/chat/composer/focus'

interface Recognition {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: { results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>; resultIndex: number }) => void) | null
  onend: (() => void) | null
  onerror: ((event: { error: string }) => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

type RecognitionCtor = new () => Recognition

function recognitionCtor(): RecognitionCtor | undefined {
  const host = window as Window & { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }

  return host.SpeechRecognition ?? host.webkitSpeechRecognition
}

/** Composer dictation: speech becomes draft text; nothing is sent until the user presses Send.
 * Separate from Voice chat, which holds a spoken conversation. Hidden without browser support. */
export function AuraDictation({ disabled }: { disabled: boolean }) {
  const [listening, setListening] = useState(false)
  const [error, setError] = useState('')
  const recognition = useRef<Recognition | null>(null)
  const Ctor = recognitionCtor()

  useEffect(() => () => recognition.current?.abort(), [])

  if (!Ctor) {
    return null
  }

  const stop = () => {
    recognition.current?.stop()
    setListening(false)
  }

  const start = () => {
    setError('')
    const next = new Ctor()
    next.continuous = true
    next.interimResults = false
    next.lang = navigator.language || 'en-US'

    next.onresult = event => {
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index]

        if (result.isFinal && result[0].transcript.trim()) {
          requestComposerInsert(`${result[0].transcript.trim()} `)
        }
      }
    }

    next.onerror = event => {
      setError(event.error === 'not-allowed' ? 'Microphone access was blocked.' : 'Dictation stopped.')
      setListening(false)
    }

    next.onend = () => {
      setListening(false)
      requestComposerFocus()
    }

    recognition.current = next
    next.start()
    setListening(true)
  }

  return (
    <span className="aura-dictation">
      <button
        aria-label={listening ? 'Stop dictation' : 'Dictate'}
        aria-pressed={listening}
        className="aura-icon-button aura-dictation-button"
        data-listening={listening || undefined}
        disabled={disabled}
        onClick={listening ? stop : start}
        type="button"
      >
        {listening ? <Square aria-hidden="true" size={14} /> : <Mic aria-hidden="true" size={18} />}
      </button>
      <span aria-live="polite" className="sr-only">
        {listening ? 'Listening for dictation' : error}
      </span>
    </span>
  )
}
