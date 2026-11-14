import { randomUuid } from '@hermes/shared'

import processorUrl from './pipecat-pcm-processor.ts?worker&url'
import { resolveSiblingWsUrl, type SiblingWsRoute } from './sibling-ws-url'

export interface VoiceEvent {
  type: string; interrupted?: boolean; turn_id?: string; interrupt_turn_id?: string; text?: string
  packet_id?: string; message_index?: number; pcm?: string; seq?: number; epoch?: string
}
/** No audio survives this object's lifetime. A reconnect replays only final/control frames. */
export class PipecatVoice {
  private socket: WebSocket | null = null
  private context: AudioContext | null = null
  private mic: MediaStream | null = null
  private input: AudioWorkletNode | null = null
  private sources = new Set<AudioBufferSourceNode>()
  private nextAudio = 0
  private epoch = ''
  private seq = 0
  private packets = new Set<string>()
  private cancelled = new Set<string>()
  private stopped = false
  private retry: ReturnType<typeof setTimeout> | null = null
  private clientId = randomUuid().replaceAll('-', '')
  private speechEnd = new Map<string, number>()
  private firstAudio = new Set<string>()
  constructor(private route: SiblingWsRoute, private conversationId: string | null | undefined,
    private event: (event: VoiceEvent) => void, private fail: (message: string) => void) {}

  async start(): Promise<void> {
    this.context = new AudioContext()
    await this.context.resume()
    this.mic = await navigator.mediaDevices.getUserMedia({ audio: {
      echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1
    } })
    await this.context.audioWorklet.addModule(processorUrl)

    if (this.stopped) { this.stop();

 return }

    const source = this.context.createMediaStreamSource(this.mic)
    this.input = new AudioWorkletNode(this.context, 'aura-pipecat-input')

    this.input.port.onmessage = ({ data }: MessageEvent<ArrayBuffer>) => {
      if (this.socket?.readyState !== WebSocket.OPEN || this.socket.bufferedAmount > 128000) { return }
      const bytes = new Uint8Array(data)
      this.send({ type: 'audio', pcm: btoa(String.fromCharCode(...bytes)) })
    }

    source.connect(this.input)
    this.input.connect(this.context.destination)
    await this.connect()
  }

  private async connect(): Promise<void> {
    const url = await resolveSiblingWsUrl(this.route, '/api/audio/pipecat')

    if (this.stopped) { return }
    const socket = new WebSocket(url)
    this.socket = socket
    socket.onopen = () => this.send({ type: 'hello', conversation_id: this.conversationId,
      client_id: this.clientId, after_seq: this.seq })

    socket.onmessage = ({ data }) => {
      if (this.socket !== socket || this.stopped) { return }
      const event = JSON.parse(String(data)) as VoiceEvent

      if (event.epoch && event.epoch !== this.epoch) { this.epoch = event.epoch; this.seq = 0 }

      if (event.seq && event.seq <= this.seq) { return }

      if (event.seq) { this.seq = event.seq }

      if (event.type === 'unavailable' || event.type === 'error') {
        this.stop(); this.fail('Continuous voice unavailable. Turn-based voice is available below.');

 return
      }

      if (event.type === 'speech_end' && event.turn_id) { this.speechEnd.set(event.turn_id, performance.now()) }

      if (event.type === 'speech_start') {
        const start = performance.now()
        this.flush(event.interrupt_turn_id)
        console.info('[aura-voice] barge-in-stop', { turn_id: event.turn_id, ms: performance.now() - start })
      }

      if (event.type === 'audio') { this.play(event) }
      this.event(event)
    }

    socket.onclose = event => {
      if (this.stopped || this.socket !== socket) { return }
      this.flush()
      this.event({ type: 'disconnected' })

      if (event.code === 4401 || event.code === 4403) { this.stop(); this.fail('Voice sign-in expired.');

 return }

      this.retry = setTimeout(() => { void this.connect().catch(() => { this.stop(); this.fail('Voice reconnect failed.') }) }, 500)
    }
  }

  send(frame: object): void { if (this.socket?.readyState === WebSocket.OPEN) { this.socket.send(JSON.stringify(frame)) } }
  adopt(id: string): void { this.conversationId = id; this.send({ type: 'adopt', conversation_id: id }) }
  flush(turnId?: string): void {
    if (turnId) { this.cancelled.add(turnId) }

    for (const source of this.sources) { source.onended = null; source.stop() }
    this.sources.clear()
    this.nextAudio = 0
  }
  private play(event: VoiceEvent): void {
    const context = this.context

    if (!context || !event.pcm || !event.packet_id || !event.turn_id ||
        this.cancelled.has(event.turn_id) || this.packets.has(event.packet_id)) { return }

    this.packets.add(event.packet_id)
    const bytes = Uint8Array.from(atob(event.pcm), char => char.charCodeAt(0))
    const pcm = new DataView(bytes.buffer)
    const buffer = context.createBuffer(1, bytes.length / 2, 16000)
    const samples = buffer.getChannelData(0)

    for (let i = 0; i < samples.length; i++) { samples[i] = pcm.getInt16(i * 2, true) / 32768 }
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(context.destination)
    this.sources.add(source)
    const at = Math.max(context.currentTime + 0.02, this.nextAudio)
    this.nextAudio = at + buffer.duration

    source.onended = () => {
      this.sources.delete(source)
      this.send({ type: 'ack', packet_id: event.packet_id })

      if (!this.sources.size) { this.event({ type: 'listening' }) }
    }

    source.start(at)

    if (!this.firstAudio.has(event.turn_id)) {
      this.firstAudio.add(event.turn_id)
      const ended = this.speechEnd.get(event.turn_id)

      if (ended !== undefined) { console.info('[aura-voice] speech-end-first-audio', {
        turn_id: event.turn_id, ms: performance.now() - ended + (at - context.currentTime) * 1000 }) }
    }
  }
  stop(): void {
    this.stopped = true

    if (this.retry) { clearTimeout(this.retry) }
    this.flush()
    this.send({ type: 'close' })
    this.socket?.close()
    this.input?.disconnect()
    this.input?.port.close()

    for (const track of this.mic?.getTracks() ?? []) { track.stop() }
    void this.context?.close()
  }
}
