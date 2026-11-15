import './local-talk.css'

import { useStore } from '@nanostores/react'
import { useState } from 'react'

import { useSessionView } from '@/app/chat/session-view'

import { localTalkEnabled, ORIGIN_LABEL, type ReplyOrigin, serverReplyOrigin } from './local-model'

export function ReplyOriginBadge({ origin, detail, note }: { origin: ReplyOrigin; detail?: string; note?: string }) {
  return (
    <span className="aura-origin" data-origin={origin} title={detail ? `${ORIGIN_LABEL[origin]}: ${detail}` : ORIGIN_LABEL[origin]}>
      {ORIGIN_LABEL[origin]}
      {note ? ` · ${note}` : ''}
    </span>
  )
}

/** On each server reply while the on-device prototype is switched on: Aura's free model or a paid one. */
export function AuraServerReplyOrigin() {
  const [enabled] = useState(() => localTalkEnabled())
  const view = useSessionView()
  const provider = useStore(view.$provider)
  const model = useStore(view.$model)

  if (!enabled) {
    return null
  }

  return <ReplyOriginBadge detail={model || undefined} origin={serverReplyOrigin(provider, model)} />
}
