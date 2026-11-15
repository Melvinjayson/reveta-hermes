// Pure rules for Aura's on-device conversation prototype: which model, whether this browser can run it,
// when a message needs Aura's server (tools, facts, paid reasoning), and what the hand-off carries.

export interface LocalTurn {
  role: 'assistant' | 'system' | 'user'
  content: string
  /** Display only (measured speed, cut-off). Never sent to a model. */
  detail?: string
}

export const forModel = (turns: LocalTurn[]): LocalTurn[] => turns.map(({ role, content }) => ({ role, content }))

// Qwen2.5-0.5B-Instruct (Apache-2.0) from WebLLM 0.2.87's own prebuilt list: the smallest Qwen there
// (~945 MB GPU memory for f16, ~290 MB download either way). f32 is for GPUs without shader-f16.
export const LOCAL_MODEL = {
  name: 'Qwen2.5 0.5B Instruct',
  licence: 'Apache-2.0',
  downloadMb: 290,
  f16: 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC',
  f32: 'Qwen2.5-0.5B-Instruct-q4f32_1-MLC'
} as const

export const LOCAL_SYSTEM_PROMPT = [
  "You are Aura's on-device thinking partner, running privately on the user's phone.",
  'Help them work out what they want: say back what you heard in one sentence, then ask one short question.',
  'Keep every reply under 60 words. If they correct you, use the correction.',
  'You cannot search, browse, send, save, open files or take any action, and you must never say you did.',
  'If they want something done, or need facts or deeper thinking, tell them to tap "Hand to Aura".'
].join(' ')

export const INTENT_PROMPT =
  'In one sentence that starts with "I want", write what the user wants so far. Use their corrections. Reply with the sentence only.'

/*
 * Device grading below (estimateVramMb, gradeDevice, readBattery) is adapted from webllm.io,
 * packages/sdk/src/capability/vram.ts, scoring.ts and detector.ts at commit 3a4c069
 * (https://github.com/WebLLM-io/webllm.io). The webllm.io SDK is not a dependency. Its notice:
 *
 * MIT License
 *
 * Copyright (c) 2025 WebLLM.io contributors
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

export type DeviceGrade = 'A' | 'B' | 'C' | 'S'

interface GpuAdapterLike {
  features: { has: (name: string) => boolean }
  limits?: { maxStorageBufferBindingSize?: number }
  info?: { vendor?: string }
}

export interface DeviceNavigator {
  gpu?: { requestAdapter: () => Promise<GpuAdapterLike | null> }
  deviceMemory?: number
  getBattery?: () => Promise<{ level: number; charging: boolean }>
  onLine?: boolean
}

/** WebGPU spec default for maxStorageBufferBindingSize (128 MB). */
const WEBGPU_DEFAULT_MAX_BUFFER_MB = 128

/**
 * Estimate usable GPU memory from the adapter's own limit, not a device's defaults. When the browser
 * only reports the spec default, fall back to navigator.deviceMemory (capped at 8 GB by browsers):
 * half of it on Apple unified memory, a quarter elsewhere. A heuristic, not a measurement.
 */
export function estimateVramMb(adapter: GpuAdapterLike, deviceMemoryGb = 0): number {
  let vram = Math.round((adapter.limits?.maxStorageBufferBindingSize ?? 0) / (1024 * 1024))

  if (vram <= WEBGPU_DEFAULT_MAX_BUFFER_MB && deviceMemoryGb > 0) {
    vram =
      (adapter.info?.vendor ?? '').toLowerCase() === 'apple'
        ? Math.round(deviceMemoryGb * 1024 * 0.5)
        : Math.max(vram, Math.round(deviceMemoryGb * 1024 * 0.25))
  }

  return vram
}

/** S ≥ 8 GB, A ≥ 4 GB, B ≥ 2 GB, C below (webllm.io's scoreDevice). */
export function gradeDevice(vramMb: number): DeviceGrade {
  if (vramMb >= 8192) {
    return 'S'
  }

  if (vramMb >= 4096) {
    return 'A'
  }

  return vramMb >= 2048 ? 'B' : 'C'
}

async function readBattery(nav: DeviceNavigator): Promise<null | { level: number; charging: boolean }> {
  try {
    const battery = nav.getBattery ? await nav.getBattery() : null

    return battery ? { level: battery.level, charging: battery.charging } : null
  } catch {
    return null
  }
}

// GPU memory WebLLM 0.2.87's prebuilt list gives for each build.
export const LOCAL_MODEL_VRAM_MB: Record<string, number> = { [LOCAL_MODEL.f16]: 945, [LOCAL_MODEL.f32]: 1060 }

export const LOW_BATTERY = 0.2

export interface LocalDevice {
  grade: DeviceGrade
  vramMb: number
  battery: null | { level: number; charging: boolean }
  online: boolean
  /** Shown before the download; none of them blocks it except being offline without a cached copy. */
  warnings: string[]
}

export type LocalSupport = ({ ok: false; reason: string } | { ok: true; modelId: string }) & { device: LocalDevice | null }

export async function probeLocalSupport(nav: DeviceNavigator = navigator as unknown as DeviceNavigator): Promise<LocalSupport> {
  if (!nav.gpu) {
    return { ok: false, reason: 'This browser doesn’t offer WebGPU, so the on-device model can’t run here.', device: null }
  }

  let adapter: GpuAdapterLike | null

  try {
    adapter = await nav.gpu.requestAdapter()
  } catch {
    return { ok: false, reason: 'The browser refused access to the graphics adapter.', device: null }
  }

  if (!adapter) {
    return { ok: false, reason: 'This device didn’t give the browser a usable graphics adapter.', device: null }
  }

  const modelId = adapter.features.has('shader-f16') ? LOCAL_MODEL.f16 : LOCAL_MODEL.f32
  const vramMb = estimateVramMb(adapter, nav.deviceMemory ?? 0)
  const battery = await readBattery(nav)
  const online = nav.onLine !== false
  const warnings: string[] = []

  if (vramMb < LOCAL_MODEL_VRAM_MB[modelId]) {
    warnings.push(
      `This device reports about ${vramMb} MB for graphics and the model needs about ${LOCAL_MODEL_VRAM_MB[modelId]} MB, so it may be slow or fail to start. Phones often under-report this.`
    )
  }

  if (battery && !battery.charging && battery.level < LOW_BATTERY) {
    warnings.push(`Battery is at ${Math.round(battery.level * 100)}% and not charging. Running the model drains it quickly.`)
  }

  return { ok: true, modelId, device: { grade: gradeDevice(vramMb), vramMb, battery, online, warnings } }
}

// Clearly defined task rule: a tiny model can't be trusted to notice its own limits, so anything that needs
// Aura's tools, live facts or an action is routed by these words, not by the model's judgement.
const NEEDS_AURA =
  /\b(search (?:for|the)|look(?:ing)? (?:it |this |that )?up|google it|browse|open (?:the |this |that |my )?(?:link|site|website|url|file)|https?:\/\/|e-?mail (?:him|her|them|it|this)|send (?:an? |the |this |it )?(?:e-?mail|message|text|invoice)|book (?:a|an|me|the)|buy (?:a|an|it|the|this)|deploy|merge|schedule (?:a|an|it|the|this)|remind me|calendar|upload|pdf|attachment|research|news|weather|today's|latest|current price|ask aura|hand (?:it )?(?:over|off|to aura)|go deeper|think harder|use (?:claude|anthropic))\b/i

export function needsAura(text: string): boolean {
  return NEEDS_AURA.test(text)
}

// The local model is given no tools, but small models still emit tool-call-shaped text. Never show it as
// if something ran, and never pass it on as an instruction.
const TOOL_CALL =
  /<\/?(?:tool_call|function_call|tool_use)\b|"(?:name|function|tool)"\s*:\s*"[^"]*"\s*,\s*"(?:arguments|parameters|input)"|\b(?:functions|tools)\.[a-z_]+\s*\(/i

export const TOOL_ATTEMPT_NOTE =
  'The on-device model tried to run a tool. It has none, so nothing ran. Tap Hand to Aura to get this done.'

export function looksLikeToolCall(text: string): boolean {
  return TOOL_CALL.test(text)
}

// The local conversation lives only in this browser so a reload or a closed panel doesn't lose it. It is
// cleared when it's handed to Aura or when the user taps Clear.
const LOCAL_TURNS_KEY = 'aura.localTalk.turns.v1'

export function loadLocalTurns(store: Storage | undefined = globalThis.localStorage): LocalTurn[] {
  try {
    const parsed: unknown = JSON.parse(store?.getItem(LOCAL_TURNS_KEY) ?? '[]')

    return Array.isArray(parsed)
      ? parsed
          .filter(
            (turn): turn is LocalTurn =>
              Boolean(turn) && (turn.role === 'user' || turn.role === 'assistant') && typeof turn.content === 'string'
          )
          .map(turn => ({ role: turn.role, content: turn.content.slice(0, 4000), ...(typeof turn.detail === 'string' ? { detail: turn.detail } : {}) }))
          .slice(-24)
      : []
  } catch {
    return []
  }
}

export function saveLocalTurns(turns: LocalTurn[], store: Storage | undefined = globalThis.localStorage): void {
  try {
    if (turns.length) {
      store?.setItem(LOCAL_TURNS_KEY, JSON.stringify(turns.slice(-24)))
    } else {
      store?.removeItem(LOCAL_TURNS_KEY)
    }
  } catch {
    // storage full or blocked: the conversation still works, it just won't survive a reload
  }
}

/** Shown on the badge of each on-device reply: what WebLLM measured on this device. */
export function localReplyDetail(stats: { decodeTps: null | number; finish: null | string }): string {
  const parts = [stats.decodeTps ? `${stats.decodeTps.toFixed(1)} tokens/s` : '']

  if (stats.finish === 'length') {
    parts.push('cut off')
  }

  return parts.filter(Boolean).join(', ')
}

export const HANDOFF_LIMITS = { turns: 12, turnChars: 600, totalChars: 4000 } as const

const clip = (text: string, max: number) => {
  const flat = text.replace(/\s+/g, ' ').trim()

  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}

/** The one normal chat message that carries the on-device conversation to Aura's server. */
export function handoffMessage(history: LocalTurn[], intent: string): string {
  const lines = history
    .filter(turn => turn.role !== 'system' && turn.content.trim())
    .slice(-HANDOFF_LIMITS.turns)
    .map(turn => `${turn.role === 'user' ? 'Me' : 'On-device model'}: ${clip(turn.content, HANDOFF_LIMITS.turnChars)}`)

  // Keep the newest lines when the whole transcript is too long.
  while (lines.length > 1 && lines.join('\n').length > HANDOFF_LIMITS.totalChars) {
    lines.shift()
  }

  const want = clip(intent, 300)

  return [
    'I was thinking this through with the on-device model, which has no tools and can be wrong. Nothing in this conversation has been done or approved.',
    want ? `What I want so far: ${want}` : '',
    lines.length ? `Conversation so far:\n${lines.join('\n')}` : '',
    'Please pick it up from here.'
  ]
    .filter(Boolean)
    .join('\n\n')
}

export function intentFallback(history: LocalTurn[]): string {
  const last = [...history].reverse().find(turn => turn.role === 'user')

  return last ? clip(last.content, 300) : ''
}

export type ReplyOrigin = 'aura' | 'device' | 'paid'

export const ORIGIN_LABEL: Record<ReplyOrigin, string> = { device: 'On device', aura: 'Aura', paid: 'Paid model' }

/** Where a server reply ran, from the chat's own provider and model (a chat keeps the model it started on). */
export function serverReplyOrigin(provider: string, model: string): Exclude<ReplyOrigin, 'device'> {
  return /^(anthropic|openai)$/i.test(provider.trim()) || /^(claude-|gpt-)/i.test(model.trim()) ? 'paid' : 'aura'
}

export interface ProviderBudget {
  paid_route: null | { provider: string; model: string; per_day_usd: number; per_chat_usd: number }
  spent_today_usd: number
}

/**
 * What the hand-off says about where it goes and what it costs. The hand-off joins the current chat, which
 * keeps the model it started on, so the destination is the chat's model, not just the Settings choice.
 * Advisory only: the server's guard still enforces every cap.
 */
export function handoffBudget(
  status: null | ProviderBudget,
  chat: { provider: string; model: string } = { provider: '', model: '' }
): {
  blocked: boolean
  origin: Exclude<ReplyOrigin, 'device'> | null
  text: string
} {
  const origin = serverReplyOrigin(chat.provider, chat.model)

  if (!status) {
    return { blocked: false, origin, text: 'Couldn’t check today’s spend. Aura’s server still enforces your limits.' }
  }

  const paid = status.paid_route
  const label = paid ? `${paid.provider === 'anthropic' ? 'Anthropic' : 'OpenAI'} ${paid.model}` : ''

  if (origin === 'aura') {
    const free = `Goes to Aura’s free model${chat.model ? ` (${chat.model})` : ''} in this chat.`

    return {
      blocked: false,
      origin,
      text: paid ? `${free} Start a new chat to use ${label}.` : `${free} Set Anthropic in Settings for deeper thinking.`
    }
  }

  if (!paid) {
    return { blocked: false, origin, text: `This chat uses ${chat.model || 'a paid model'}. Aura’s server enforces your limits.` }
  }

  const spent = `$${status.spent_today_usd.toFixed(2)} of $${paid.per_day_usd.toFixed(2)} used today`

  if (status.spent_today_usd >= paid.per_day_usd) {
    return { blocked: true, origin: 'paid', text: `Today’s limit for ${label} is used up (${spent}). Nothing was sent.` }
  }

  return { blocked: false, origin: 'paid', text: `Goes to ${label}: ${spent}, $${paid.per_chat_usd.toFixed(2)} per chat.` }
}

/** Opt-in only: `?aura-local=1` (or in the hash) turns the prototype on for this browser, `=0` turns it off. */
export function localTalkEnabled(loc: Pick<Location, 'hash' | 'search'> = location, store: Storage | undefined = globalThis.localStorage): boolean {
  const flag = /[?&#]aura-local=([01])\b/.exec(`${loc.search}${loc.hash}`)?.[1]

  try {
    if (flag === '1') {
      store?.setItem('aura.localTalk.v1', '1')
    } else if (flag === '0') {
      store?.removeItem('aura.localTalk.v1')
    }

    return store?.getItem('aura.localTalk.v1') === '1'
  } catch {
    return flag === '1'
  }
}
